# Implementation Plan: Enron Mail Browser

**Branch**: `001-enron-mail-browser` | **Date**: 2026-10-29 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `specs/001-enron-mail-browser/spec.md`

## Summary

Add a `jevron browse` subcommand: a read-only, keyboard-driven terminal mail client for the
ingested Enron corpus. It navigates mailboxes → folders → messages → reader, and adds:

- search with the same semantics as `jevron emails`
- conversation, sender and copies views
- optional read-only display and filtering of existing Jev label results

It is built on the standard-library `curses` module over a curses-free core (data access, query
parsing, view stack, text cleaning) so that most behavior is unit-tested offline.

`jevron ingest` is extended to write `data/locations.parquet` (one row per original file), so
folder views show the original mailbox layout. Measurements show the whole corpus fits in
memory: launch takes about 1.6 s and a full-text search about 0.3 s. No search index is needed.

## Technical Context

**Language/Version**: Python 3.14 (project standard, managed by uv)

**Primary Dependencies**: standard-library `curses` (ncurses 6.0 bundled), plus existing pandas
and pyarrow. No new runtime dependencies.

**Storage**:

- reads `data/emails.parquet` (existing)
- reads `data/locations.parquet` (new, written by `jevron ingest`)
- optionally reads `jevron label` JSONL results files
- never writes

**Testing**: pytest (existing, offline). The core is unit-tested. Rendering is tested against a
fake window (research R10).

**Target Platform**: macOS and Linux color terminals, at least 80×24

**Project Type**: CLI and terminal UI inside the existing single `jevron` package

**Performance Goals**:

- launch to mailbox list ≤ 5 s
- folder or email open ≤ 1 s
- search ≤ 3 s

Measured: about 1.6 s load, 0.31 s body search, 0.19 s worst-case wrap.

**Constraints**:

- read-only
- no network
- terminal always restored on exit or error
- display-only cleaning of control characters (4,256 bodies contain them)

**Scale/Scope**:

- 255,170 distinct emails
- 517,401 file locations
- 150 mailboxes and 3,311 folders; the largest folder has 11,896 emails
- the longest body has 2,011,422 characters
- about 650 MB of memory
- 5 screen types: mailboxes, folders, messages, reader, help

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Gate | Status |
| --- | --- | --- |
| I. Playground First | Runs locally with no servers. No new runtime dependencies (stdlib curses). Smallest UI model (view stack, not panes or widgets) | ✅ Pass |
| II. Reproducible From the Source Tarball | New `locations.parquet` is derived deterministically by `jevron ingest` and stored under git-ignored `data/`. The browser never writes. The maildir stays read-only | ✅ Pass |
| III. Faithful to the Source Data | Folder views reflect every on-disk copy (adds `locations.parquet` instead of approximating). The reader shows the full unmodified body and a raw file view. Cleaning is display-only. Implausible dates are shown, not hidden. Ingest and query changes get fixture tests | ✅ Pass |
| IV. Deliberate, Traceable Jev Usage | The browser makes no Jev calls (FR-016). It shows the model version with every label. The tests use no API key | ✅ Pass |
| V. Respect the People in the Corpus | No new outputs leave `data/`. Labels are shown as answers with confidence and model, not as conclusions | ✅ Pass |
| Workflow: tests offline < 10 s; README updated with CLI changes | Planned: core and render tests on the existing fixture; README "Browsing" section and ingest note | ✅ Pass (tracked in tasks) |

**Post-implementation check (T040, 2026-10-29)**: passing.
- `pyproject.toml` runtime dependencies are unchanged, since the browser uses stdlib `curses`.
- `jevron.browse` writes no files.
- No TypeSafe client is constructed (`test_browser_never_calls_jev`).
- `locations.parquet` is derived by `jevron ingest` under the git-ignored `data/`.
- The README has a "Browsing the corpus" section.
- The suite passes offline in about 1.2 s.

**Post-design re-check (after Phase 1)**: still passing. The design adds one data file and one
subcommand, with no dependencies and no network use. Nothing needs to go in Complexity
Tracking.

## Project Structure

### Documentation (this feature)

```text
specs/001-enron-mail-browser/
├── plan.md              # This file
├── research.md          # Phase 0: decisions and measurements
├── data-model.md        # Phase 1: stored and in-memory model, view state
├── quickstart.md        # Phase 1: validation guide
├── contracts/
│   ├── browse-cli.md    # `jevron browse` arguments, exit behavior, ingest change
│   └── keybindings.md   # screen layout, keys, query and label-filter syntax
├── checklists/
│   └── requirements.md  # spec quality checklist
└── tasks.md             # Phase 2 (/speckit-tasks)
```

### Source Code (repository root)

```text
src/jevron/
├── corpus.py            # CHANGED: dedupe() also returns per-file locations; build() writes
│                        #          locations.parquet; load_locations()
├── label.py             # CHANGED: read_records() (raw per-email records) shared with browse
├── cli.py               # CHANGED: `browse` subcommand; ingest skip logic checks both outputs
└── browse/
    ├── __init__.py
    ├── data.py          # Corpus indexes: mailboxes, folders, folder_messages, threads,
    │                    #   by_sender, copies, search(Query); LabelStore
    ├── query.py         # parse search prompt -> Query; parse label filter -> LabelFilter
    ├── views.py         # ViewStack, ListView, ReaderView, HelpView, key-binding table,
    │                    #   actions (curses-free)
    ├── text.py          # clean(), display width, wrap(), truncate to columns
    └── app.py           # curses layer: setup/teardown, safe drawing, prompt line,
                         #   resize, key dispatch, clipboard

tests/
├── test_jevron.py       # CHANGED: ingest writes locations; parity with n_copies/mailboxes
└── test_browse.py       # NEW: query parsing, search parity with filter_emails, navigation
                         #   and back-restore, threads, copies, labels, text cleaning,
                         #   rendering into a fake window
```

**Structure Decision**: a single project. The browser is a `jevron.browse` subpackage inside
the existing `src/jevron` package and is exposed as a `jevron` subcommand (FR-019).

Everything except `app.py` is importable and testable without a terminal. `app.py` stays thin
and covers drawing and input only.

## Implementation Notes

- **Search parity (SC-006)**: `data.search` calls `corpus.filter_emails` with the parsed
  `Query`. It must not reimplement the matching.
- **Folder message lists**: join `locations[(user, folder)]` to `emails` by `message_id`. The
  per-folder ID arrays are precomputed at load with a single groupby (3,311 groups), so opening
  a folder is a lookup.
- **Reader text**: `text.clean` runs, then `text.wrap` at the current width. The result is
  cached on the `ReaderView` and invalidated on resize or `r`.
- **Safe drawing**: all writes go through `app.put(win, y, x, text, attr)`, which clips text to
  the window's width and height, skips the bottom-right cell, and swallows `curses.error`.
- **Clipboard**: `pbcopy`, then `wl-copy`, then `xclip`, found with `shutil.which`. Failures
  fall back to showing the ID.
- **Terminal safety**:
  - `curses.wrapper(main)`.
  - `locale.setlocale(LC_ALL, "")` is called first.
  - A check that stdout is a TTY happens before curses starts.
  - Resizes are handled by `KEY_RESIZE`, followed by `curses.update_lines_cols()` and a
    re-layout.
- **Migration**: if `locations.parquet` is missing, exit with the `jevron ingest --force`
  message (contract). `ingest` without `--force` rebuilds when either file is missing.
- **Delivery order**: the user stories are delivered as independently testable slices: P1 core
  browsing, P2 search, P3 conversations, sender and copies, and P4 labels.

## Complexity Tracking

No constitution violations to justify.
