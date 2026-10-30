# Feature Specification: Enron Mail Browser

**Feature Branch**: `001-enron-mail-browser`

**Created**: 2026-10-29

**Status**: Draft

**Input**: User description: "make a curses utility to explore the email dataset like a email client but it only works for the enron email dataset."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Browse mailboxes and read email (Priority: P1)

A researcher opens the browser in their terminal and sees the Enron corpus laid out like a familiar
email client. One pane lists the 150 mailboxes, and selecting a mailbox shows its folders, such as
inbox, sent and deleted_items. Selecting a folder lists its emails, newest first, with date, sender
and subject. Opening an email shows its headers and full body, which they can scroll. They move
between panes and emails entirely with the keyboard and can quit at any time.

**Why this priority**: this is the core of an email client and is valuable on its own. It
replaces opening raw files in a text editor with a fast, structured way to read the corpus as the
original users saw it.

**Independent Test**: launch the browser on an ingested corpus, choose `lay-k`, then `inbox`, then
any email, and confirm the headers and body match the original message file.

**Acceptance Scenarios**:

1. **Given** an ingested corpus, **When** the user launches the browser, **Then** the mailbox list
   appears with all 150 mailboxes and the number of emails in each.
2. **Given** a mailbox is selected, **When** the user opens it, **Then** its folders are listed
   with message counts, nested folders such as `inbox/hist_vols` included.
3. **Given** a folder is open, **When** the user moves through the message list, **Then** each row
   shows date, sender and subject, sorted newest first, and the list scrolls through folders of
   any size.
4. **Given** a message is highlighted, **When** the user opens it, **Then** the reader shows From,
   To, Cc, Date and Subject plus the full body, scrollable line by line and page by page.
5. **Given** any view, **When** the user presses the quit key, **Then** the browser exits and the
   terminal is restored to its previous state.

---

### User Story 2 - Search and filter (Priority: P2)

The researcher wants every email mentioning "Raptor" in the months before the bankruptcy. From
anywhere in the browser, they open a search prompt and enter text, optionally narrowing by
sender, recipient or date range. The results appear as a message list across all mailboxes,
with each email listed once, and they can open, read and step through the results just like a
folder. Within an open folder, they can also filter the visible list without leaving it.

**Why this priority**: the corpus has 255k distinct emails, and browsing alone cannot find
specific topics. Search turns the browser into a research tool.

**Independent Test**: search for "raptor", confirm the result count matches the existing
`jevron emails --search raptor` count, and open a result.

**Acceptance Scenarios**:

1. **Given** any view, **When** the user searches for text, **Then** emails whose subject or body
   contains it, ignoring case, are listed with each distinct email appearing once, and the total
   count is shown.
2. **Given** a search, **When** the user adds a sender, recipient or date-range filter, **Then**
   only matching emails remain.
3. **Given** a results list, **When** the user opens an email, reads it and returns, **Then** they
   are back at the same position in the results.
4. **Given** a search with no matches, **When** it completes, **Then** the browser says so and
   keeps the previous view available.

---

### User Story 3 - Follow conversations and people (Priority: P3)

While reading an email, the researcher wants context. With a single key they can see the other
emails in the same conversation (same subject, ignoring Re:/Fw: prefixes) in date order, all
other emails from the same sender, and which mailboxes and folders held copies of this email.

**Why this priority**: Enron research usually means following a thread or a person. This needs
the reading experience of Stories 1 and 2 to exist first.

**Independent Test**: open a known reply email, jump to its conversation, and confirm the
original message and later replies are listed in date order.

**Acceptance Scenarios**:

1. **Given** an open email, **When** the user asks for its conversation, **Then** emails with the
   same normalized subject are listed in date order, with the current email highlighted.
2. **Given** an open email, **When** the user asks for more from this sender, **Then** that
   sender's emails are listed, newest first.
3. **Given** an open email, **When** the user views its copies, **Then** every mailbox and folder
   that contained the email is listed.
4. **Given** any of these lists, **When** the user goes back, **Then** they return to the email
   they came from.

---

### User Story 4 - See existing Jev labels (Priority: P4)

The researcher has already labeled emails with `jevron label`. When they open the browser with
one or more results files, each labeled email shows its answers in the reader: choice and
confidence, score and confidence, or yes-probability, along with the model version that produced
them. They can filter a message list to emails where a given answer passes a threshold, for
example `special_purpose_entities` ≥ 0.8.

**Why this priority**: this connects the browser to the project's purpose. Labels become far more
useful when the email behind them can be read immediately. It depends on labels already existing,
so it comes last.

**Independent Test**: label a handful of emails, open the browser with that results file, and
confirm the labeled emails show their answers while unlabeled emails show none.

**Acceptance Scenarios**:

1. **Given** a results file is loaded, **When** the user opens a labeled email, **Then** each
   question's answer and the model version are shown alongside the email.
2. **Given** a results file is loaded, **When** the user filters by a question and threshold,
   **Then** only emails meeting it are listed, highest value first.
3. **Given** no results file is loaded, **When** the user opens any email, **Then** no label area
   is shown, and nothing else changes.
4. **Given** the browser is running, **When** the user does anything, **Then** no request is ever
   sent to Jev.

---

### Edge Cases

- **Corpus not ingested**: the browser exits with a clear message saying to run `jevron ingest`
  first. It does not show a stack trace.
- **Very long bodies**, up to about 2 million characters: the email opens without noticeable
  delay, and scrolling stays responsive.
- **Long lines**: they wrap to the terminal width without losing text.
- **Undecodable header or body bytes**, such as garbled Japanese names: replacement characters
  appear as they do in the corpus, and the display never crashes or corrupts the screen.
- **Implausible dates** (1979, 2044): the date shows as stored and the email sorts by it. It is not
  hidden.
- **Missing sender, subject or date**: shown as a visible placeholder, such as "(no subject)".
- **Terminal resized while running**: the layout redraws to fit.
- **Very small terminal** (below 80×24): the browser shows a message asking for a larger window
  instead of drawing a broken layout.
- **Empty folders and empty results**: they show an explicit empty state.
- **Results file problems**: if a results file references unknown email IDs, contains failed
  entries or mixes model versions, the browser still loads it. It ignores unknown IDs, shows
  failures as failures, and shows the model version per email.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The browser MUST work only with the ingested Enron corpus, the output of
  `jevron ingest`. It is not a general mail reader.
- **FR-002**: The browser MUST run in a terminal and MUST be usable entirely from the keyboard.
- **FR-003**: The browser MUST present a mailbox list, then a folder list for the chosen
  mailbox, then a message list for the chosen folder, then a message reader.
- **FR-004**: Folder views MUST reflect the original mailbox layout. An email stored in several
  folders or mailboxes MUST appear in each one.
- **FR-005**: Search results MUST list each distinct email once, matching the corpus's existing
  deduplication.
- **FR-006**: Message lists MUST show date, sender and subject, sorted newest first by default.
  The user MUST be able to reverse the order.
- **FR-007**: The reader MUST show From, To, Cc, Date and Subject plus the full, unmodified body,
  with no reply-trimming or truncation. It MUST be scrollable by line and by page.
- **FR-008**: The reader MUST offer a toggle to view the original message file exactly as it is
  on disk.
- **FR-009**: Users MUST be able to search subject and body text, ignoring case, and narrow
  results by sender, recipient (To/Cc/Bcc), and date range, matching the semantics of the
  existing `jevron emails` filters.
- **FR-010**: Users MUST be able to filter the currently displayed message list by text without
  leaving it.
- **FR-011**: From an open email, users MUST be able to list its conversation (same subject
  ignoring Re:/Fw:/Fwd: prefixes, in date order), the sender's other emails, and all mailboxes
  and folders holding copies.
- **FR-012**: Users MUST be able to go back to the previous view, restoring the selection and
  scroll position.
- **FR-013**: The browser MUST show each email's message ID and copy it to the clipboard on
  request, so the email can be used with other `jevron` commands. If no clipboard is available,
  the ID MUST be shown so it can be copied by hand.
- **FR-014**: The browser MUST accept zero or more Jev results files at launch. For each labeled
  email it MUST show every answer and the model version that produced it.
- **FR-015**: With results loaded, users MUST be able to list emails where a chosen question's
  value meets a threshold, or equals a chosen label for choice questions.
- **FR-016**: The browser MUST NOT call the Jev API or any other network service.
- **FR-017**: The browser MUST NOT modify the corpus, the extracted message files or results
  files. It is read-only.
- **FR-018**: A help screen listing every key binding MUST be available from any view.
- **FR-019**: The browser MUST be launchable as a `jevron` subcommand and MUST respect the
  existing `--data-dir` option.

### Key Entities

- **Mailbox**: one of the 150 Enron employees' mail stores, such as `lay-k`. It has a name, its
  folders and an email count.
- **Folder**: a named folder within a mailbox, possibly nested (`inbox/hist_vols`). It contains
  the emails stored there on disk.
- **Email**: one distinct message, with its message ID, date, sender, recipients (To/Cc/Bcc),
  subject, body, and the list of mailbox/folder locations holding copies of it.
- **Conversation**: the emails sharing a subject once Re:/Fw:/Fwd: prefixes are removed, ordered
  by date.
- **Label result**: for one email, the answers to a question set from one labeling run, with the
  model version and any error.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: On the full corpus, the mailbox list appears within 5 seconds of launch.
- **SC-002**: Opening any folder or email, including the largest folder and the longest body,
  shows content within 1 second.
- **SC-003**: A text search across all 255k distinct emails returns results within 3 seconds.
- **SC-004**: A user unfamiliar with the browser can find and open a specific email, given its
  sender and a subject keyword, in under 1 minute, using only the on-screen help.
- **SC-005**: Every email in the corpus opens and displays without crashing or corrupting the
  terminal, including emails with undecodable characters, implausible dates or missing headers.
- **SC-006**: Search result counts match `jevron emails` for the same filters in 100% of compared
  cases.
- **SC-007**: The browser is fully usable in an 80×24 terminal.

## Assumptions

- **Primary user**: one person exploring the corpus on their own machine, comfortable in a
  terminal. Mouse support is not required.
- **Read-only scope**: composing, replying, deleting, moving, flagging and marking emails as read
  are out of scope. The corpus is a historical record and stays unmodified (constitution
  Principle II).
- **Attachments**: the corpus does not include attachment contents, so attachments are out of
  scope beyond showing any attachment references that appear in the email text.
- **Conversations**: subject matching is good enough for threading. The corpus's headers carry
  no reliable reply-to chains, and threading quality may be refined later.
- **Folder data**: the corpus is ingested with `jevron ingest` before use. If folder views need
  per-copy location data that the current output does not keep, extending ingest to keep it is
  part of this feature.
- **No Jev calls**: running Jev from inside the browser is out of scope for this version.
  Labeling stays a deliberate, separate step with `jevron label` (constitution Principle IV).
- **Terminal environment**: a standard color terminal on macOS or Linux. Windows terminals are
  not a target.
