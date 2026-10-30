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

Download the CMU release (May 7, 2015, about 423 MB compressed). The notebook looks for it in `~/Downloads/`; change `TARBALL` in the notebook if you save it elsewhere.

```bash
curl -L -o ~/Downloads/enron_mail_20150507.tar.gz https://www.cs.cmu.edu/~enron/enron_mail_20150507.tar.gz
```

The archive unpacks to `maildir/<user>/<folder>/<n>.`. It holds about 517k messages from about 150 Enron employees, mostly senior management. Many messages appear in more than one folder or mailbox, so the notebook deduplicates them.

Extracted data and the parsed parquet cache live in `data/`, which is git-ignored.

## Exploratory analysis

[`enron_analysis.ipynb`](enron_analysis.ipynb) extracts the archive and parses every message into a DataFrame, cached as `data/enron_emails.parquet`. It then looks at:

- email volume over time, annotated with key events in Enron's collapse
- send-time patterns by day of week and hour of day
- top senders, recipients and domains
- mailbox and folder sizes
- the sender → recipient communication network
- body length, recipient counts and common subject terms, plus a full-text `search()` helper

The first full parse takes a few minutes. Set `MAX_FILES` in the notebook to work on a sample.

## Asking Jev about emails

Each email becomes the state, and each property you care about becomes one typed question:

```python
from typesafe_sdk import Choice, Noul, Score, TypeSafeClient

email = emails.iloc[0]
state = f"From: {email['from']}\nSubject: {email['subject']}\n\n{email['body']}"

with TypeSafeClient(model="jev-latest") as client:
    response = client.system_one(
        state=state,
        questions={
            "topic": Choice(
                instructions="What is this email mainly about?",
                criteria={
                    "trading": "Energy trading, deals, positions or pricing",
                    "legal_regulatory": "Legal, regulatory or compliance matters",
                    "personnel": "Hiring, HR, org changes",
                    "personal": "Non-business, personal correspondence",
                    "other": "Anything else",
                },
            ),
            "urgency": Score(
                instructions="How urgent is this email for the recipient?",
                criteria=["not urgent", "somewhat urgent", "very urgent"],
            ),
            "spe": Noul(
                instructions="The email discusses special purpose entities or off-balance-sheet partnerships (e.g. LJM, Raptor, Chewco).",
            ),
        },
    )

topic = response.answers["topic"]
print(topic.choice, topic.confidence)
```

Some practical notes:

- Ask one specific question per property and combine the answers in your own code.
- Pin a model version, such as `jev-1.13.0`, once you've tuned confidence thresholds, so they don't drift when `jev-latest` changes.
- Deduplicate before labeling. About half of the raw files are duplicates.
- The corpus contains real people's personal information. Labeling it sends email text to TypeSafe's API.

## References

### Enron email dataset

- William W. Cohen, *Enron Email Dataset*, Carnegie Mellon University. <https://www.cs.cmu.edu/~enron/>
- Bryan Klimt and Yiming Yang, "The Enron Corpus: A New Dataset for Email Classification Research," *Machine Learning: ECML 2004*, LNCS 3201, pp. 217–226, Springer, 2004. <https://doi.org/10.1007/978-3-540-30115-8_22>
- Federal Energy Regulatory Commission, Docket No. PA02-2-000, *Fact-Finding Investigation of Potential Manipulation of Electric and Natural Gas Prices*, 2002–2004. The emails were first made public through this investigation.

### Jev / TypeSafe AI

- TypeSafe AI. <https://typesafe.ai>
- Jev documentation: [overview](https://docs.typesafe.ai/), [quickstart](https://docs.typesafe.ai/introduction/quickstart), [System One concepts](https://docs.typesafe.ai/concepts/system-one), [primitives (Choice, Score, Noul)](https://docs.typesafe.ai/primitives), [confidence](https://docs.typesafe.ai/confidence), [models](https://docs.typesafe.ai/models), [API reference](https://docs.typesafe.ai/api)
