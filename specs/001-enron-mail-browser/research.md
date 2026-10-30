# Research: Enron Mail Browser

All measurements were taken on the full corpus (255,170 distinct emails, 517,401 files) on the
development laptop (10 cores, macOS), using the project's Python 3.14 environment.

## R1. Terminal UI library

- **Decision**: Python's standard-library `curses` module.
- **Rationale**:
  - The user asked for a curses utility, and the constitution (Principle I) prefers the
    standard library over new dependencies.
  - `import curses` works in the project's Python build, which bundles ncurses 6.0.
  - The UI is a stack of lists plus a text pager, which needs no widget toolkit.
- **Alternatives considered**:
  - **Textual**: richer widgets and a built-in test pilot, but a large dependency tree for a
    list-and-pager UI.
  - **urwid**: mature, but also an extra dependency, and its widget model is heavier than
    needed.
  - **prompt_toolkit**: already installed transitively through ipykernel, but it is not a
    declared dependency, and its full-screen apps are more complex than curses for this case.

## R2. Layout for an 80×24 terminal

- **Decision**: one full-screen view at a time, kept on a stack: Mailboxes → Folders → Messages
  → Reader. Search, conversation, sender, copies and label-filter results push another Messages
  view. A top line shows the path through the stack, and a bottom status line shows counts and
  key hints.
- **Rationale**:
  - Three side-by-side panes leave about 25 columns each at 80×24, too narrow for sender and
    subject.
  - A stack gives back-navigation (FR-012) almost for free, and it follows the mutt/less model
    that terminal users already know.
- **Alternatives considered**:
  - **Three-pane layout**: unreadable at 80 columns. Could become an optional wide-terminal mode
    later.
  - **Split list and reader**: halves the reading space. Rejected for v1.

## R3. Loading strategy and performance

- **Decision**: load `data/emails.parquet` in full at launch, bodies included, then build
  in-memory indexes. Do not add a separate search index.
- **Measurements**:

  | Operation | Time | Memory |
  |---|---|---|
  | Metadata columns load | 0.52 s | 179 MB |
  | Body column load | 1.07 s | 477 MB |
  | Case-insensitive substring search over all bodies | 0.31 s | — |
  | Subject search | 0.02 s | — |
  | Reading one original message file (for raw view) | 3 ms | — |

- **Rationale**:
  - Launch takes about 1.6 s plus index building, inside SC-001's 5 seconds.
  - Search takes about 0.3 s, inside SC-003's 3 seconds.
  - Reusing `corpus.filter_emails` for search guarantees result parity with `jevron emails`
    (SC-006).
  - About 650 MB of memory is acceptable for a single-user laptop tool.
- **Alternatives considered**:
  - **Lazy body loading**: saves about 1 s at launch, but adds a loading state to the first
    search or read. Not needed at these numbers.
  - **SQLite FTS index**: faster for repeated queries, but adds a build step and a second copy
    of the data. Not justified by 0.3 s searches (Principle I).

## R4. Per-folder copies (FR-004)

- **Finding**: `data/emails.parquet` is deduplicated. Each distinct email keeps only its first
  copy's `folder` and `path`, plus a `mailboxes` list. Folder views cannot be rebuilt from it:
  for example, an email in both `lay-k/inbox` and `lay-k/all_documents` lists only one of those
  folders.
- **Decision**: extend `jevron ingest` to also write `data/locations.parquet`. It has one row
  per original message file (517,401 rows), with columns `message_id`, `user`, `folder` and
  `path`. `message_id` is the ID of the distinct email that the file was deduplicated into.
- **Rationale**:
  - It records every copy's location, keeping ingest faithful to the source (Principle III), at
    a small cost of about 517k short rows.
  - Deduplication already computes the grouping key, so this costs almost nothing extra at
    ingest time.
- **Migration**: a corpus ingested before this change has no `locations.parquet`. The browser
  detects this and tells the user to run `jevron ingest --force` (about 76 s). `ingest` without
  `--force` also rebuilds when either output file is missing.
- **Alternatives considered**:
  - **Re-scanning the maildir at browser launch**: costs about 76 s per launch.
  - **Storing a list of locations per email in `emails.parquet`**: the nested column is awkward
    to query by folder, and it changes an existing file's schema that `export` and the notebook
    read.

## R5. Text rendering safety (SC-005)

- **Findings**:
  - 4,256 bodies contain C0 control characters (form feeds, escape sequences and similar).
    Written raw to the terminal, these can corrupt the display.
  - The longest body has 2,011,422 characters and 26,152 lines. Splitting it into lines takes
    2 ms, and fully word-wrapping it to 78 columns takes 0.19 s.
- **Decisions**:
  - Before drawing, every string is cleaned: tabs are expanded, other control characters (except
    newline) become a visible `�` or `^X` marker, and lone surrogates are replaced. Cleaning is
    for display only, and the stored data is unchanged (Principle III).
  - Wrapping is done eagerly when an email is opened and cached per terminal width. It is redone
    on resize. At 0.19 s for the worst case, it fits within SC-002's 1-second budget.
  - All drawing goes through one safe-write helper. It clips text to the window, never writes to
    the bottom-right cell (which raises a curses error), and suppresses `curses.error`.
  - Display width uses `unicodedata.east_asian_width` so that wide characters (CJK) occupy two
    columns, without adding a dependency.
  - `locale.setlocale(LC_ALL, "")` is called before `curses.initscr` so that Unicode renders.
- **Alternatives considered**:
  - **The `wcwidth` package**: more accurate for emoji and combining marks, but the corpus is
    from 1998–2002 and almost entirely Latin text, so it is not worth a dependency.

## R6. Conversations (FR-011)

- **Decision**: at load time, compute a `thread_key` for each email: the subject, lowercased,
  with leading `re:`, `fw:` and `fwd:` prefixes removed repeatedly (allowing `RE :` and `Fw:`
  spacing variants), and with whitespace collapsed. Group message IDs by `thread_key`. An
  empty `thread_key` (no subject) has no conversation, and only the email itself is shown.
- **Rationale**: Enron headers have no usable `In-Reply-To` or `References`. Subject matching
  is the documented assumption in the spec.
- **Alternatives considered**:
  - **Subject plus participant overlap**: better precision but more complex. Deferred.
  - **Quoted-text matching**: expensive and fragile.

## R7. Clipboard (FR-013)

- **Decision**: try `pbcopy` (macOS), then `wl-copy` (Wayland), then `xclip -selection
  clipboard` (X11), using the first one found on `PATH`. If none is available, show the
  message ID in the status line so it can be copied by hand.
- **Rationale**: no dependency, and it covers the target platforms. `pbcopy` is present on the
  development machine.
- **Alternatives considered**:
  - **OSC 52 terminal escape**: works over SSH, but support varies by terminal and is silently
    ignored when unsupported. A possible later addition.

## R8. Search query syntax (FR-009)

- **Decision**: a single prompt line. Free text is the subject/body search, and optional tokens
  set filters: `from:ADDR`, `to:ADDR`, `since:YYYY-MM-DD`, `until:YYYY-MM-DD`, `user:MAILBOX`
  and `folder:NAME`. Double quotes group phrases. Tokens map one-to-one onto
  `corpus.filter_emails` arguments.
- **Rationale**:
  - One prompt is faster than a form in a terminal, and the prefixes match the familiar Gmail
    and mutt style.
  - Mapping straight onto `filter_emails` keeps semantics identical to `jevron emails`.
- **Alternatives considered**:
  - **A multi-field search form**: more keystrokes and more UI code.

## R9. Jev labels (FR-014, FR-015)

- **Decision**: `jevron browse --labels FILE` can be given more than once. Each JSONL results
  file is read into a map from message ID to label records (source file, model, answers,
  error). If an email appears more than once in a file, its latest record wins, as in
  `label.read_results`. Unknown message IDs are counted and ignored. For threshold filters, the
  flattened columns from `label.flatten` are reused. The filter prompt takes `NAME>=VALUE`,
  `NAME<=VALUE`, or `NAME=LABEL` for choice questions.
- **Rationale**: reuses the existing results format and helpers. The browser only reads and
  never calls Jev (FR-016, Principle IV).

## R10. Testing approach

- **Decision**:
  - The browser is split into a curses-free core: data access, query parsing, the view stack and
    navigation, and text cleaning and wrapping.
  - A thin curses layer draws the views and maps keys to core actions.
  - Core logic gets ordinary pytest unit tests on the synthetic maildir fixture already in
    `tests/test_jevron.py`.
  - Drawing is tested against a fake window object that records writes and enforces bounds.
    This catches out-of-bounds writes and confirms that control characters never reach the
    screen.
  - The tests do not start a real terminal.
- **Rationale**: keeps the suite offline and fast, within the constitution's 10-second budget,
  and covers the risky parts (navigation state, parity with `jevron emails`, rendering safety).
- **Alternatives considered**:
  - **Driving a real terminal through a pty with a terminal emulator library such as pyte**:
    higher fidelity, but adds a dev dependency and slower tests. Manual quickstart checks cover
    real-terminal behavior instead.
