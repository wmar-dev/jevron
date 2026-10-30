# jevron

Exploring the [Enron email corpus](https://www.cs.cmu.edu/~enron/) with **Jev**, TypeSafe AI's "System One" model.

Jev doesn't generate text. You give it a *state* (here, an email) and a set of typed questions, and it returns structured answers: a **Choice** from options you define, a **Score** on a rubric, or a **Noul** (the probability that a statement is true). Here that means labeling emails, for example classifying topic, rating urgency or flagging mentions of particular deals, with the results stored as DataFrame columns.

## Setup

Requires Python 3.14 and [uv](https://docs.astral.sh/uv/).

```bash
uv sync                    # install dependencies (incl. the Jev SDK, typesafe-sdk) into .venv
export TYPESAFE_API_KEY=…  # create a key at https://console.typesafe.ai/keys
```

## Dataset

Download the CMU release (May 7, 2015, about 423 MB compressed). The notebook and `jevron ingest` look for it in `~/Downloads/`. If you save it elsewhere, change `TARBALL` in the notebook or pass `--tarball` to `jevron ingest`.

```bash
curl -L -o ~/Downloads/enron_mail_20150507.tar.gz https://www.cs.cmu.edu/~enron/enron_mail_20150507.tar.gz
```

The archive unpacks to `maildir/<user>/<folder>/<n>.`. It holds about 517k messages from about 150 Enron employees, mostly senior management. Many messages appear in more than one folder or mailbox. Both the notebook and `jevron ingest` deduplicate them, leaving 255,170 distinct emails.

Extracted data, parquet files and label results live in `data/`, which is git-ignored.

## Exploratory analysis

[`enron_analysis.ipynb`](enron_analysis.ipynb) extracts the archive and parses every message into a DataFrame, cached as `data/enron_emails.parquet`. It then looks at:

- email volume over time, annotated with key events in Enron's collapse
- send-time patterns by day of week and hour of day
- top senders, recipients and domains
- mailbox and folder sizes
- the sender → recipient communication network
- body length, recipient counts and common subject terms, plus a full-text `search()` helper

The first full parse takes a few minutes. Set `MAX_FILES` in the notebook to work on a sample.

## Labeling emails with the `jevron` CLI

`uv sync` installs a `jevron` command (run it as `uv run jevron …`, or activate `.venv`).

```bash
uv run jevron ingest                 # tarball -> data/emails.parquet (255k distinct emails, ~1-2 min)
uv run jevron stats                  # corpus summary
uv run jevron emails --user lay-k --search raptor     # browse; --format ids|jsonl for scripting
uv run jevron show '<12188219.1075842087604.JavaMail.evans@thyme>'   # the exact text Jev will see
```

Questions live in TOML files, one table per question. See [`questions/triage.toml`](questions/triage.toml) and [`questions/investigation.toml`](questions/investigation.toml):

```toml
[topic]
type = "choice"
instructions = "What is this email mainly about?"
criteria = { trading = "Energy trading or deals", personal = "Personal correspondence", other = "Anything else" }

[urgency]
type = "score"
instructions = "How urgent is this email for its recipients?"
criteria = ["Not urgent", "Somewhat urgent", "Very urgent"]

[spe]
type = "noul"
instructions = "The email discusses special purpose entities such as LJM or Raptor."
```

Try questions on a few emails, then label in bulk:

```bash
# print answers for 5 random emails (or add --noul NAME=STATEMENT for a quick yes/no question)
uv run jevron ask -q questions/triage.toml --sample 5

# preview size, then label; results append to the JSONL file, and re-running skips finished emails and retries failed ones
uv run jevron label -q questions/investigation.toml --since 2001-06-01 --out data/investigation.jsonl --dry-run
uv run jevron label -q questions/investigation.toml --since 2001-06-01 --out data/investigation.jsonl

# one row per email: metadata plus a column per question (and <name>_confidence for choice/score)
uv run jevron export data/investigation.jsonl --out data/investigation.parquet
```

All selection commands share the same filters: `--user`, `--folder`, `--from`, `--to`, `--since`, `--until`, `--search`, `--id`/`--ids-file`, `--sample`, `--limit`. Run `uv run jevron <command> --help` for details.

Each email is sent to Jev as its From/To/Date/Subject headers plus the body. Quoted reply chains (`-----Original Message-----` onwards and `>` lines) are dropped, and the body is truncated at `--max-chars` (default 4000).

Some practical notes:

- Ask one specific question per property and combine the answers in your own code.
- Pin a model version with `--model`, such as `jev-1.14.0`, once you've tuned confidence thresholds, so they don't drift when `jev-latest` changes. `jevron models` lists what's available.
- The corpus contains real people's personal information. Labeling it sends email text to TypeSafe's API.

Run the tests with `uv run pytest`. They use a mock Jev API, so no key is needed.

## References

### Enron email dataset

- William W. Cohen, *Enron Email Dataset*, Carnegie Mellon University. <https://www.cs.cmu.edu/~enron/>
- Bryan Klimt and Yiming Yang, "The Enron Corpus: A New Dataset for Email Classification Research," *Machine Learning: ECML 2004*, LNCS 3201, pp. 217–226, Springer, 2004. <https://doi.org/10.1007/978-3-540-30115-8_22>
- Federal Energy Regulatory Commission, Docket No. PA02-2-000, *Fact-Finding Investigation of Potential Manipulation of Electric and Natural Gas Prices*, 2002–2004. The emails were first made public through this investigation.

### Jev / TypeSafe AI

- TypeSafe AI. <https://typesafe.ai>
- Jev documentation: [overview](https://docs.typesafe.ai/), [quickstart](https://docs.typesafe.ai/introduction/quickstart), [System One concepts](https://docs.typesafe.ai/concepts/system-one), [primitives (Choice, Score, Noul)](https://docs.typesafe.ai/primitives), [confidence](https://docs.typesafe.ai/confidence), [models](https://docs.typesafe.ai/models), [API reference](https://docs.typesafe.ai/api)
