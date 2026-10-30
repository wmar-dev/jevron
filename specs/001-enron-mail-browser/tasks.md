---

description: "Task list for the Enron Mail Browser (jevron browse)"
---

# Tasks: Enron Mail Browser

**Input**: Design documents from `specs/001-enron-mail-browser/`: [plan.md](plan.md), [spec.md](spec.md),
[research.md](research.md), [data-model.md](data-model.md), [contracts/](contracts/),
[quickstart.md](quickstart.md)

**Tests**: included. Constitution Principles III and IV and the Development Workflow require
offline tests for changes to parsing, filtering, state construction and anything near Jev under
`src/jevron/`. The whole suite MUST stay under 10 s with no API key.

**Organization**: tasks are grouped by user story (US1–US4 from spec.md) so that each story is
an independently testable increment.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: can run in parallel (different files, no dependency on an incomplete task)
- **[Story]**: the user story a task belongs to (US1–US4)
- Paths are relative to the repository root

## Conventions for every task

- Match the existing code style in `src/jevron/` (plain functions, short docstrings, no
  framework).
- Only `src/jevron/browse/app.py` may import `curses`. Every other browse module MUST be
  importable without a terminal.
- All screen writes go through `app.put()` (T010). No direct `addstr` elsewhere.
- Run `uv run pytest` after each task. It must pass.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: package skeleton and shared test fixtures

- [X] T001 Create the `src/jevron/browse/` package with `__init__.py` (docstring: "Read-only
  terminal browser for the ingested Enron corpus.") and empty modules `data.py`, `query.py`,
  `views.py`, `text.py` and `app.py`, each with a one-line module docstring matching plan.md
  § Project Structure
- [X] T002 Move the `write_email` helper and the `data_dir` fixture from `tests/test_jevron.py`
  into a new `tests/conftest.py`, so both test modules can use them. Extend the fixture:
  - add an email whose `Date` header is missing
  - add an email whose body contains `\x1b[2J` and `\x0c` control characters
  - add a reply email (`Subject: RE: Raptor`) from a different sender in `skilling-j/inbox`
  - put the duplicate "Hi" email in both `lay-k/inbox` and `lay-k/all_documents`

  Update the assertions in `tests/test_jevron.py` that depend on fixture counts.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: per-file locations from ingest, text safety, the core view stack, and the curses
shell with the `browse` subcommand. All user stories depend on this phase.

**⚠️ CRITICAL**: no user story work can begin until this phase is complete.

- [X] T003 In `src/jevron/corpus.py`:
  - Change `dedupe(df)` to return `(emails, locations)`. `locations` has one row per input
    file, with columns `message_id` (the kept email's ID for that file's dedup key), `user`,
    `folder` and `path`.
  - Add `locations_path(data_dir)` returning `data_dir / "locations.parquet"`.
  - Make `build()` write both files and return `(emails, locations)`.
  - Add `load_locations(data_dir)`. If the file is missing, it raises `FileNotFoundError` with
    the exact message in contracts/browse-cli.md.

  Update every caller (`cli.cmd_ingest`, tests).
- [X] T004 Add tests to `tests/test_jevron.py`:
  - `locations` has one row per fixture file.
  - Every `locations.message_id` exists in `emails`.
  - For each email, the count of its location rows equals `n_copies`, and the set of `user`
    values equals `mailboxes`.
  - The duplicate "Hi" email appears under both `lay-k/inbox` and `lay-k/all_documents`.
- [X] T005 Update `cmd_ingest` in `src/jevron/cli.py`:
  - Skip only when both `emails.parquet` and `locations.parquet` exist and `--force` is not
    given.
  - Print `Wrote N distinct emails to …/emails.parquet and M file locations to
    …/locations.parquet`.
- [X] T006 [P] Implement `src/jevron/browse/text.py`, curses-free (research R5):
  - `clean(s)`: expand tabs to 4 spaces, keep `\n`, replace every other C0 control and DEL
    with `^X` notation, and replace lone surrogates with `�`.
  - `width(s)`: display columns, counting East Asian Wide and Fullwidth characters as 2, via
    `unicodedata.east_asian_width`.
  - `fit(s, cols)`: truncate to at most `cols` display columns, adding `…` when cut, and pad
    with spaces to exactly `cols`.
  - `wrap(text, cols)`: list of display lines. Clean, then `splitlines()`, then
    `textwrap.wrap(line, cols, replace_whitespace=False, drop_whitespace=False)`, keeping empty
    lines.
- [X] T007 [P] Add text tests to `tests/test_browse.py`:
  - `clean` removes `\x1b` and `\x0c` and keeps `\n`.
  - `width("佐藤")` is 4.
  - `fit` truncates with `…` and pads to an exact width, including wide characters.
  - `wrap` of a 2,000,000-character single line at 78 columns finishes in under 1 s.
- [X] T008 Implement `src/jevron/browse/data.py` class `Corpus`, loading only:
  - `Corpus.load(data_dir)` reads `corpus.load(data_dir)` (all columns) and
    `corpus.load_locations(data_dir)`. It keeps `emails` indexed by `message_id` and
    `locations`, and builds nothing else yet. Missing files propagate `FileNotFoundError` with
    the contract messages.
  - Add `Corpus.email(message_id)` returning the row.
- [X] T009 Implement the core view state in `src/jevron/browse/views.py` (data-model.md § View
  state), with no curses imports:
  - `ListView(kind, title, items, render_row)` with `cursor`, `top`, `filter_text`,
    `visible`, `sort_desc`, and the methods `move(delta)`, `page(direction, height)`,
    `home()`, `end()`, `set_filter(text)`, `toggle_sort()`, `selected()`, and
    `scroll_into_view(height)`. These preserve the invariants in data-model.md.
  - `ViewStack` with `push`, `pop` (returns False when empty) and `top`.
  - A `BINDINGS` table of `(keys, contexts, description, action_name)` entries, covering every
    key in contracts/keybindings.md. The table is the single source for both dispatch and help.
- [X] T010 Implement the curses shell in `src/jevron/browse/app.py`:
  - `run(data_dir, label_files)` checks `sys.stdout.isatty()`, failing with the contract
    error, then calls `locale.setlocale(locale.LC_ALL, "")` and `curses.wrapper(main)`.
  - `put(win, y, x, text, attr=0)` writes `text.fit`-clipped text, never writes the
    bottom-right cell, and ignores `curses.error`.
  - `layout(stdscr)` gives the breadcrumb on line 0, the body on lines 1..H-2, and the status
    on line H-1.
  - Below 80×24, draw only a centered "Enlarge the terminal to at least 80×24" message.
  - Handle `KEY_RESIZE` with `curses.update_lines_cols()` and a redraw.
  - A key loop looks up the active view's context in `views.BINDINGS` and calls the named
    action.
  - `curs_set(0)`, `keypad(True)`, and colors only if `has_colors()`.
- [X] T011 Add a `FakeWindow` class to `tests/conftest.py`. It has a fixed `(h, w)`. `addstr`,
  `addnstr` and `insstr` record `(y, x, text)` and raise `AssertionError` when out of bounds or
  on the bottom-right cell. `getmaxyx` returns `(h, w)`.

  Add tests in `tests/test_browse.py` showing that `app.put` never trips `FakeWindow` for
  oversized text, wide characters, negative widths or the bottom-right corner, and that cleaned
  control characters never appear in recorded text.
- [X] T012 Add a `browse` subcommand to `src/jevron/cli.py` with `--labels FILE` (repeatable,
  `type=Path`, `action="append"`) and `func=cmd_browse`. `cmd_browse` imports
  `jevron.browse.app` lazily and calls `app.run(args.data_dir, args.labels or [])`. Errors
  follow contracts/browse-cli.md, with exit code 1 and an `error: …` message on stderr. Add a
  CLI test for the "needs an interactive terminal" error when stdout is not a TTY.

**Checkpoint**: `jevron ingest --force` writes both files, `jevron browse` starts and quits
cleanly with an empty screen, and the tests pass.

---

## Phase 3: User Story 1 - Browse mailboxes and read email (Priority: P1) 🎯 MVP

**Goal**: navigate mailboxes → folders → messages → reader with the keyboard, using the original
folder layout and the full email text.

**Independent Test**: launch `jevron browse` and open `lay-k` › `inbox` › any email. The headers
and body match the original file, and `r` shows the raw file (quickstart steps 1–4 and 14).

### Tests for User Story 1

- [X] T013 [P] [US1] Tests in `tests/test_browse.py` for the `Corpus` indexes on the fixture:
  - `mailboxes()` gives `(user, file_count)` sorted by name, with counts equal to the location
    rows.
  - `folders(user)` includes nested folders, with counts.
  - `folder_messages("lay-k", "all_documents")` contains the duplicate "Hi" email (FR-004),
    newest first, with the missing-date email last.
- [X] T014 [P] [US1] Tests in `tests/test_browse.py` for navigation without curses, using
  `ViewStack` and `ListView`:
  - Open a mailbox, then a folder, then an email, then go back three times. The cursor and
    `top` are restored at each level (FR-012).
  - `toggle_sort` reverses the order (FR-006).
  - `move` and `page` clamp at the ends.
  - Opening an empty folder gives `selected()` of None and no exception.
- [X] T015 [P] [US1] Tests in `tests/test_browse.py` for `ReaderView`:
  - Header lines include From/To/Cc/Date/Subject/Message-ID and a `Copies:` line.
  - The body is the full, untrimmed `body`, with control characters cleaned.
  - `r` loads `Path(path).read_bytes().decode("cp1252", "replace")`.
  - `n` and `p` move through the originating list.
  - Rendering the reader and a message list into `FakeWindow(24, 80)` raises nothing.

### Implementation for User Story 1

- [X] T016 [US1] Add these indexes to `Corpus` in `src/jevron/browse/data.py`, all built once
  in `load()` with groupby (plan.md § Implementation Notes):
  - `mailboxes()`
  - `folders(user)`
  - `folder_messages(user, folder)`, returning message IDs sorted by date descending with NaT
    last
  - `copies(message_id)`, returning the location rows sorted by user and folder
- [X] T017 [US1] In `src/jevron/browse/views.py`, add row renderers:
  - mailbox: `name  count`
  - folder: `folder  count`
  - message: `YYYY-MM-DD  sender  subject`, with `(no date)`, `(no sender)` and
    `(no subject)` placeholders, using `text.fit` for the column widths in
    contracts/keybindings.md
- [X] T018 [US1] In `src/jevron/browse/views.py`, add `ReaderView(corpus, message_id, context)`:
  - Header lines as in contracts/keybindings.md.
  - `lines(cols)` returns cached `text.wrap` output of the headers plus the body. The cache key
    is `(cols, raw)`.
  - `scroll(delta, height)`, `top()` and `bottom(height)`.
  - `toggle_raw()`.
  - `next()` and `prev()` return the adjacent message ID from `context`, the `ListView` it was
    opened from.
- [X] T019 [US1] Add `HelpView` in `src/jevron/browse/views.py`, generated from `BINDINGS` and
  grouped by context (FR-018).
- [X] T020 [US1] Implement drawing and the US1 actions in `src/jevron/browse/app.py`:
  - Draw a `ListView`, highlighting the cursor with `A_REVERSE`, and draw `ReaderView` and
    `HelpView` scrolled.
  - Breadcrumb from the stack titles, for example `lay-k › inbox (1,234)`.
  - Status shows the position `37/1,234` and key hints.
  - Actions: open, back, quit, the movement and paging keys, `o` sort, `r` raw, `n`/`p`, `?`
    help, and `Ctrl-L` redraw.
  - The first view is the mailbox list.
- [X] T021 [US1] Implement `y` in `src/jevron/browse/app.py`:
  - Copy the message ID through the first of `pbcopy`, `wl-copy`, or `xclip -selection
    clipboard` found by `shutil.which`, with `subprocess.run(input=…, timeout=2)`.
  - The status shows `copied <id>`. If no tool exists or the copy fails, it shows `message id:
    <id>` (FR-013).
  - Add a test in `tests/test_browse.py` that monkeypatches `shutil.which` to return None and
    checks the fallback text.

**Checkpoint**: US1 is fully usable and is the MVP. Run quickstart steps 1–4, 10 and 12–15.

---

## Phase 4: User Story 2 - Search and filter (Priority: P2)

**Goal**: corpus-wide search with `jevron emails` semantics, plus an in-view filter.

**Independent Test**: `/raptor` result count equals `jevron emails --search raptor` (quickstart
steps 5–7).

### Tests for User Story 2

- [X] T022 [P] [US2] Tests in `tests/test_browse.py` for `query.parse_query`:
  - Free text and quoted phrases join into one `text`.
  - `from:`, `to:`, `since:`, `until:`, `user:` and `folder:` map to `Query` fields.
  - An invalid date raises `ValueError("invalid date: …")`.
  - An unknown `key:` stays in the text, so `re: q3` searches the literal `re: q3`.
- [X] T023 [P] [US2] Tests in `tests/test_browse.py` for search parity: for several queries,
  `Corpus.search(parse_query(q))` returns the same message ID set as `corpus.filter_emails` with
  the equivalent keyword arguments (SC-006). Also test that `ListView.set_filter("raptor")`
  keeps only matching rows and that `set_filter("")` restores them all (FR-010).

### Implementation for User Story 2

- [X] T024 [US2] Implement `Query` (a dataclass) and `parse_query(s)` in
  `src/jevron/browse/query.py` per contracts/keybindings.md, using `shlex.split` with a fallback
  for unbalanced quotes.
- [X] T025 [US2] Implement `Corpus.search(query)` in `src/jevron/browse/data.py` by calling
  `corpus.filter_emails(self.emails.reset_index(), text→search, sender, recipient, since, until,
  user, folder)`. It returns message IDs sorted by date descending. It must not reimplement
  matching.
- [X] T026 [US2] Implement the status-line prompt in `src/jevron/browse/app.py`:
  - `prompt(label)` supports editing, `Backspace`, `Esc` to cancel, and up/down for session
    history.
  - `/` parses the query and pushes a message `ListView` titled `search: <query> (N)`.
  - `invalid date: …` and `no emails match` appear on the status line without changing view.
- [X] T027 [US2] Bind `f` in `src/jevron/browse/app.py` to prompt `filter:` and call
  `ListView.set_filter`. The breadcrumb shows `[filter: text]` while it is active.

**Checkpoint**: US1 and US2 both work independently.

---

## Phase 5: User Story 3 - Follow conversations and people (Priority: P3)

**Goal**: from the reader, open the conversation, the sender's other emails, and every copy's
location.

**Independent Test**: on an `RE:` email, `t` lists the thread in date order with the current
email highlighted. `s` and `c` work. `Enter` on a copy opens that folder at the email
(quickstart steps 8–9).

### Tests for User Story 3

- [X] T028 [P] [US3] Tests in `tests/test_browse.py`:
  - `thread_key` normalizes `RE: Raptor`, `Re:  re: raptor`, `FW: Raptor` and `Fwd:Raptor` all
    to `raptor`, and leaves an empty subject empty.
  - `Corpus.thread(id)` is date-ascending and includes the original and the reply.
  - `Corpus.by_sender(addr)` is date-descending.
  - Opening a copy row produces a message `ListView` whose cursor is on that email.

### Implementation for User Story 3

- [X] T029 [US3] In `src/jevron/browse/data.py`:
  - Add `thread_key(subject)`, using a regex that repeatedly strips `^(re|fw|fwd)\s*:\s*`
    case-insensitively, then lowercases and collapses whitespace.
  - Add a `thread_key` column at load.
  - Add `thread(message_id)` (date-ascending IDs; only the email itself for an empty key) and
    `by_sender(addr)` (date-descending), both from precomputed groupby dicts.
- [X] T030 [US3] Bind `t`, `s` and `c` for the reader in `src/jevron/browse/app.py`:
  - `t` and `s` push message `ListView`s titled `conversation: <subject>` and `from: <addr>`,
    with the cursor on the current email for `t`.
  - `c` pushes a copies `ListView` of `user/folder` rows. Its `Enter` pushes that folder's
    message list with the cursor on the email.

**Checkpoint**: US1–US3 work.

---

## Phase 6: User Story 4 - See existing Jev labels (Priority: P4)

**Goal**: show and filter existing `jevron label` results, read-only, with no Jev calls.

**Independent Test**: `jevron browse --labels data/raptor.jsonl`. Labeled emails show `*` and a
Labels block with the model version, and `L spe>=0.8` filters (quickstart § 4).

### Tests for User Story 4

- [X] T031 [P] [US4] Tests in `tests/test_jevron.py` for `label.read_records(path)`: it returns
  `{message_id: record}` with the latest record per ID, keeps failed records with their
  `error`, and raises `ValueError` naming the file and line on invalid JSON.
- [X] T032 [P] [US4] Tests in `tests/test_browse.py`:
  - `LabelStore` merges two files.
  - It counts unknown IDs.
  - `flat` has the flattened columns.
  - `parse_label_filter` accepts `q>=0.8`, `q<=0.5` and `topic=trading`, and rejects unknown
    questions and type mismatches with a `ValueError` message.
  - `LabelStore.filter(f)` sorts by value descending.
  - The reader shows a `Labels (model …, file):` block for a labeled email and none for an
    unlabeled one.
- [X] T033 [P] [US4] Add a test in `tests/test_browse.py` that monkeypatches
  `typesafe_sdk.TypeSafeClient` and `typesafe_sdk.AsyncTypeSafeClient` to raise, then exercises
  loading labels, rendering the reader and filtering, so that no Jev client is ever constructed
  (FR-016).

### Implementation for User Story 4

- [X] T034 [US4] Add `read_records(path) -> dict[str, dict]` to `src/jevron/label.py`. The
  latest line per `message_id` wins. On invalid JSON it raises `ValueError(f"{path}:{lineno}:
  {err}")`. Refactor `read_results` to use it, keeping its behavior.
- [X] T035 [US4] In `src/jevron/browse/data.py`, implement `LabelStore.load(paths,
  known_ids)` (data-model.md § LabelStore):
  - `records` maps a message ID to a list of `(source, record)` pairs.
  - `flat` is a DataFrame built with `label.flatten`.
  - `unknown_ids` is a count.
  - `questions` maps each name to its kind.
  - `filter(LabelFilter)` returns message IDs.

  In `src/jevron/browse/query.py`, implement `LabelFilter` and `parse_label_filter(s, questions)`.
- [X] T036 [US4] Wire labels into `src/jevron/browse/app.py` and `views.py`:
  - `app.run` loads `LabelStore` when `label_files` is given. A failure exits with
    `error: cannot read labels from FILE: <reason>`.
  - Message rows get a `*` marker for labeled emails.
  - `ReaderView` gets a Labels block per source, with one line per answer using
    `label.format_answer`, or the error.
  - The `L` prompt pushes a filtered `ListView` titled `labels: <filter> (N)`.
  - The status line notes `N label records for unknown emails ignored` when nonzero.

**Checkpoint**: all four stories work independently.

---

## Phase 7: Polish & Cross-Cutting Concerns

- [X] T037 [P] Update `README.md`:
  - Add a "Browsing the corpus" section with `jevron browse`, `--labels`, a key-binding summary
    table, and the search syntax.
  - Note that `jevron ingest` now also writes `data/locations.parquet`, and that older corpora
    need `jevron ingest --force`.
- [X] T038 [P] Add a performance check (manual, not part of pytest) in
  `specs/001-enron-mail-browser/quickstart.md` § Performance. On the full corpus, run `uv run
  python -c` timing for `Corpus.load`, the largest `folder_messages`, `ReaderView.lines(78)` for
  the longest email, and `Corpus.search(parse_query("raptor"))`. Record the results against
  SC-001 (≤5 s), SC-002 (≤1 s) and SC-003 (≤3 s).
- [X] T039 Run `uv run jevron ingest --force` on the full corpus, then `uv run pytest` (must
  pass in under 10 s), then quickstart § 3 manual scenarios 1–15 in a real terminal at 80×24
  and at a larger size. Record pass or fail per step in
  `specs/001-enron-mail-browser/quickstart.md` § Results.
- [X] T040 Review the constitution check in `specs/001-enron-mail-browser/plan.md` against the
  delivered code: no new runtime dependencies in `pyproject.toml`, no writes under `data/` from
  `browse`, no Jev client use, and the README updated. Note the outcome under
  § Constitution Check.

---

## Dependencies & Execution Order

### Phase dependencies

- **Setup (T001–T002)** has no dependencies.
- **Foundational (T003–T012)** depends on Setup, and blocks every user story.
  - T003 must come before T004 and T005.
  - T006 and T007 are independent of T003–T005.
  - T008 needs T003.
  - T009 is independent.
  - T010 needs T006 and T009.
  - T011 needs T010.
  - T012 needs T010.
- **US1 (T013–T021)** depends on Foundational.
- **US2 (T022–T027)** depends on Foundational. It reuses US1's message `ListView` and drawing
  (T017, T020), so in practice it follows US1.
- **US3 (T028–T030)** depends on US1 (it needs the reader, T018, and folder lists, T016).
- **US4 (T031–T036)** depends on US1 (reader and rows). It is independent of US2 and US3.
- **Polish (T037–T040)** follows the desired stories.

### Within each story

Write the tests first (they fail), then data or query code, then views, then app wiring.

## Parallel Opportunities

- **Phase 2**:
  - T006, T007 (text) run alongside T003–T005 (ingest).
  - T009 (views core) runs alongside both.
- **US1**: T013, T014 and T015 (tests in separate test functions) can be written together.
  Then T016 (data.py) and T017–T019 (views.py) can proceed in parallel.
- **US2**: T022 and T023 together. T024 (query.py) alongside T025 (data.py).
- **US4**: T031, T032 and T033 together. T034 (label.py) alongside T035 (data.py, query.py).
- **Polish**: T037 and T038 together.

### Example: User Story 1 in parallel

```text
Together: T013 corpus-index tests, T014 navigation tests, T015 reader tests  (tests/test_browse.py)
Then together: T016 Corpus indexes (data.py) | T017+T018+T019 rows, reader, help (views.py)
Then: T020 drawing and actions (app.py), then T021 clipboard (app.py)
```

## Implementation Strategy

### MVP first (User Story 1 only)

1. Phase 1 Setup, then Phase 2 Foundational. Run `jevron ingest --force`.
2. Phase 3 (US1). Stop and validate with quickstart steps 1–4, 10 and 12–15.
3. US1 alone is a usable read-only mail client for the corpus.

### Incremental delivery

1. US1, the MVP: browse and read.
2. US2: search and filter, with parity against `jevron emails`.
3. US3: conversations, sender and copies.
4. US4: Jev labels overlay, read-only.
5. Polish: README, performance record, full quickstart run, constitution re-check.

Each story ends at a checkpoint with passing tests and can be committed on its own.
