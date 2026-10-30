<!--
Sync Impact Report
- Version change: template (unversioned) → 1.0.0
- Principles defined (all new):
  I. Playground First
  II. Reproducible From the Source Tarball
  III. Faithful to the Source Data
  IV. Deliberate, Traceable Jev Usage
  V. Respect the People in the Corpus
- Added sections: Technology & Data Constraints; Development Workflow; Governance
- Removed sections: none
- Templates:
  ✅ .specify/templates/plan-template.md: Constitution Check is filled per feature from this
     file; no change needed
  ✅ .specify/templates/spec-template.md: no mandatory sections added or removed; no change
     needed
  ✅ .specify/templates/tasks-template.md: tests note updated, since Principle III and the
     Development Workflow require offline tests for changes under src/jevron/
  ✅ README.md: consistent with these principles (data/ git-ignored, dry-run, model pinning,
     privacy note); no change needed
  n/a .specify/templates/commands/: directory does not exist
- Deferred TODOs: none
-->

# jevron Constitution

jevron is a playground for exploring the Enron email corpus with Jev, TypeSafe AI's System One
model: a notebook for exploratory analysis and a small `jevron` CLI for browsing the corpus and
labeling emails with typed Jev questions.

## Core Principles

### I. Playground First

jevron exists to explore and experiment, not to run production systems.

- Work MUST stay runnable on one laptop: a notebook, the `jevron` CLI and local files. Servers,
  databases, queues and cloud infrastructure are out of scope unless an amendment allows them.
- New runtime dependencies MUST earn their place. Prefer the standard library, pandas and the
  TypeSafe SDK. Note the reason for any addition in the commit message.
- Prefer the smallest change that answers the question at hand. Do not build abstractions for
  hypothetical future experiments.

Rationale: the value is in fast iteration on questions about the data and about Jev. Weight
added to the project slows that down.

### II. Reproducible From the Source Tarball

Every derived artifact MUST be rebuildable from the CMU tarball (`enron_mail_20150507.tar.gz`)
and the code in this repository.

- Raw data, extracted mail, parquet files and label results live under `data/` and MUST NOT be
  committed. `.gitignore` enforces this.
- The extracted maildir is read-only input. Code MUST NOT modify or delete files under
  `data/raw/`.
- Corpus-building steps (`jevron ingest`, the notebook's parse step) MUST be deterministic for a
  given tarball. The same input yields the same distinct emails and the same IDs.

Rationale: the dataset is large and public, and the repository's job is the method, not a copy
of the data.

### III. Faithful to the Source Data

Parsing and cleaning MUST NOT silently lose or distort information.

- Text decoding MUST be explicit. Undeclared 8-bit bytes are decoded as Windows-1252, and any
  remaining undecodable bytes become visible replacement characters. Text is never dropped.
- Transformations that change what is analyzed or sent to Jev, such as deduplication, trimming
  quoted replies, truncating bodies or excluding implausible dates, MUST be documented in the
  README or code docstrings. Where practical, they MUST be reversible or inspectable, for example
  with `n_copies`, `mailboxes`, `jevron show --raw` or `--quoted`.
- Known data-quality limits, such as unrecoverable Japanese headers or bogus timestamps, MUST be
  stated, not hidden.
- Changes to parsing, deduplication, filtering or state construction MUST include a test that
  pins the behavior on a small synthetic fixture.

Rationale: conclusions drawn from the corpus, by people or by Jev, are only as good as the
fidelity of the text they were drawn from.

### IV. Deliberate, Traceable Jev Usage

Calls to the Jev API cost money, send data to a third party and produce results that later
analysis depends on.

- Bulk labeling MUST support a dry run that reports how many emails would be sent and roughly
  how many input tokens, without calling Jev. Run it before any large job.
- Every stored result MUST record the model version that produced it and the message ID it
  belongs to. Results MUST be written as they are produced, so that an interrupted run resumes
  without re-sending finished emails.
- Runs whose results will be compared or kept MUST pin a versioned model, such as
  `jev-1.14.0`, not an alias like `jev-latest`.
- Questions MUST live in version-controlled question files (`questions/*.toml`) when results are
  kept, so that each label can be traced to the exact wording that produced it.
- Tests MUST NOT call the real API. They use a mock transport and MUST pass with no
  `TYPESAFE_API_KEY` set.

Rationale: labels are data. Without the model version and the question wording, they cannot be
interpreted, compared or reproduced.

### V. Respect the People in the Corpus

The Enron emails are real correspondence from real people, including private and personal
messages.

- Jev outputs about emails or people are signals for a human to review, not findings. Question
  files and write-ups MUST NOT present them as established facts about individuals.
- Derived datasets that contain email bodies or that profile named individuals MUST NOT be
  published outside this repository's git-ignored `data/` directory without a deliberate
  decision recorded in the commit or write-up that publishes them.
- Users MUST be told, as the README does, that labeling sends email text to TypeSafe's API.

Rationale: the corpus being public does not remove the people in it. A playground should not
become a tool for profiling them.

## Technology & Data Constraints

- Language and tooling: Python 3.14, managed with `uv` (`uv sync`, `uv run`). Tests use
  `pytest`, scoped to `tests/`.
- Core libraries: pandas and pyarrow for data, `typesafe-sdk` for Jev, matplotlib for
  notebook charts.
- Code layout: the library and CLI live in `src/jevron/`, exposed as the `jevron` console
  script. Exploratory work lives in notebooks at the repository root. Question sets live in
  `questions/`.
- Data layout: the tarball is read from `~/Downloads/` by default, or wherever `--tarball`
  points. The extracted maildir goes to `data/raw/maildir/`, the distinct emails to
  `data/emails.parquet`, and label results to JSONL files under `data/`.
- Secrets: the TypeSafe API key comes from `TYPESAFE_API_KEY` or an untracked `.env` file. It
  MUST NOT be committed.

## Development Workflow

- `uv run pytest` MUST pass before committing changes under `src/jevron/` or `tests/`. The suite
  MUST stay fast, under 10 seconds, and offline.
- The README MUST be updated in the same change when CLI commands, flags, data paths or defaults
  change.
- Notebooks MAY be committed with outputs, so that results are viewable on GitHub. Re-run them
  top to bottom before committing, so that the outputs match the code.
- Small changes MAY go directly to `main`. Larger features MAY use the Spec Kit flow (specify,
  plan, tasks), whose plans check against this constitution.
- Commit messages say what changed and why. Data-quality discoveries, such as an encoding issue,
  are worth recording there.

## Governance

- This constitution takes precedence over other conventions in the repository. When code or
  documentation conflicts with it, fix whichever is wrong, or amend the constitution.
- Amendments are made by editing this file. Each amendment updates the Sync Impact Report at
  the top and applies matching changes to the Spec Kit templates and the README.
- Versioning follows semantic versioning:
  - MAJOR for removing or redefining a principle
  - MINOR for adding a principle or section, or materially expanding guidance
  - PATCH for clarifications and wording
- Compliance: Spec Kit plans MUST pass the Constitution Check gate against these principles.
  Ad-hoc changes are checked at commit time against the Development Workflow rules above.

**Version**: 1.0.0 | **Ratified**: 2026-10-29 | **Last Amended**: 2026-10-29
