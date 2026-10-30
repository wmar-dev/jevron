# Data Model: Enron Mail Browser

## Stored data (written by `jevron ingest`)

### emails.parquet (existing, unchanged schema)

One row per distinct email (255,170 rows).

| Field | Type | Notes |
| --- | --- | --- |
| `message_id` | str | Unique. The primary key, including the angle brackets |
| `date` | timestamp (UTC) or NaT | Implausible dates are kept as stored |
| `from` | str or None | Lowercased address |
| `to`, `cc`, `bcc` | list[str] | Lowercased addresses |
| `subject` | str | Possibly empty |
| `x_from` | str or None | Lotus/Exchange display name |
| `body` | str | Decoded as Windows-1252, unmodified |
| `user`, `folder`, `path` | str | Location of the first copy |
| `n_copies` | int | Number of files on disk that hold this email |
| `mailboxes` | list[str] | Mailboxes that hold a copy, sorted |

### locations.parquet (new)

One row per original message file (517,401 rows). This is what makes folder views faithful to
the original layout (FR-004).

| Field | Type | Notes |
| --- | --- | --- |
| `message_id` | str | Foreign key to the distinct email in `emails.parquet` that this file was deduplicated into |
| `user` | str | Mailbox, such as `lay-k` |
| `folder` | str | Folder path within the mailbox, such as `inbox` or `inbox/hist_vols` |
| `path` | str | Path of the original file |

**Validation:**

- Every `message_id` exists in `emails.parquet`.
- For each email, `count(locations) == n_copies` and `set(user) == set(mailboxes)`.

## In-memory model (browser)

### Corpus

Loaded once at launch from the two files above.

- **emails**: the emails table indexed by `message_id`, plus a derived `thread_key` column (see
  Conversation below).
- **mailboxes**: an ordered list of `(user, file_count)`, where `file_count` is the number of
  location rows for that user. That is the number of message files the mailbox held, so it
  equals the sum of its folder counts.
- **folders[user]**: an ordered list of `(folder, file_count)`, including nested folders.
- **folder_messages(user, folder)**: the distinct message IDs in that folder, sorted by date
  descending, with NaT last.
- **threads**: a map from `thread_key` to message IDs sorted by date ascending.
- **by_sender**: a map from `from` to message IDs sorted by date descending.
- **copies(message_id)**: the location rows for that email.
- **search(query)**: the result of `corpus.filter_emails` with the parsed query arguments,
  sorted by date descending.

### Conversation

- `thread_key = normalize(subject)`, where normalizing means: lowercase the subject, repeatedly
  strip a leading `re`, `fw` or `fwd` prefix (optional spaces, then a colon), and collapse
  whitespace.
- An email with an empty `thread_key` has no conversation, so only the email itself is listed.

### LabelStore (optional; only when `--labels` is given)

- **records**: `message_id → [LabelRecord]`, with one record per results file that labeled the
  email. Within a file, the latest record wins.
- **LabelRecord**:
  - `source`: the file name
  - `model`: str or None
  - `answers`: `{question: answer dict}`, in the same shape as `jevron label` output
  - `error`: str or None
- **flat**: a DataFrame of `message_id` plus the flattened question columns, built with
  `label.flatten`, for threshold filters.
- **unknown_ids**: the number of records whose message ID is not in the corpus. It is reported
  in the status line and otherwise ignored.

### Query (parsed search prompt)

- **Fields**: `text`, `sender`, `recipient`, `since`, `until`, `user`, `folder`. Each is
  optional. These map one-to-one to `corpus.filter_emails` arguments.
- **Validation**: dates must parse. An unknown `key:` token is treated as free text, so
  searching for `"re: q3"` still works.

### LabelFilter (parsed label-filter prompt)

- **Fields**: `question`, `op` (one of `>=`, `<=`, `=`), `value` (float, or str for `=`).
- **Validation**:
  - The question must exist in the loaded labels.
  - `>=` and `<=` require a numeric question (score or noul, or a `_confidence` column).
  - `=` requires a choice question.

## View state (curses-free core)

### ViewStack

A list of views, with the top one active.

- **Push**: opening a mailbox, folder or email; running a search, conversation, sender, copies
  or label filter; opening help.
- **Pop**: back. Popping the last view quits.
- **Restoring**: a popped-to view keeps its cursor, scroll and filter state (FR-012).

### ListView

Used for mailboxes, folders and messages.

| Field | Meaning |
| --- | --- |
| `kind` | `mailboxes`, `folders` or `messages` |
| `title` | Breadcrumb text |
| `items` | Rows to show |
| `cursor` | Index of the highlighted item |
| `top` | First visible index |
| `filter_text` | In-view text filter (FR-010) |
| `visible` | Items after filtering |
| `sort_desc` | Messages only; toggled by `o` (FR-006) |

**Invariants**:

- `0 ≤ cursor < len(visible)`, or `cursor = 0` when the list is empty.
- `top ≤ cursor < top + page_height`.

### ReaderView

| Field | Meaning |
| --- | --- |
| `message_id` | The email being read |
| `raw` | Toggles the original file view (FR-008) |
| `scroll` | First visible line |
| `wrapped` | Cached cleaned and wrapped lines for the current width and raw mode |
| `context` | The list view it was opened from, used for next/previous message |

### HelpView

A static key-binding list, generated from the same binding table that dispatches keys, so the
help can't drift from the real bindings (FR-018).

## State transitions

```text
Mailboxes --Enter--> Folders(user) --Enter--> Messages(user/folder) --Enter--> Reader(id)
   any view --/ query--> Messages(search results)
   any view --L filter--> Messages(label-filtered)            [only with --labels]
   Reader --t--> Messages(conversation)   --s--> Messages(sender)   --c--> Copies list
   Copies list --Enter--> Messages(user/folder) with that email highlighted
   any view --?--> Help
   any view --q/Esc/Left--> previous view (quit when the stack is empty)
   any view --Q--> quit
```
