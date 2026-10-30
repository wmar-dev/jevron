# Contract: key bindings and screen layout

The help screen (`?`) is generated from this same binding table (FR-018).

## Screen layout (any size ≥ 80×24)

```text
┌ line 1: breadcrumb, e.g. "lay-k › inbox (1,234)" or "search: raptor since:2001-06-01 (355)" ┐
│ lines 2..H-1: the active view (list rows or reader text)                                      │
└ line H: status line (selected position "37/1,234", messages such as "copied <id>", key hints) ┘
```

Message list row: `YYYY-MM-DD  sender (truncated)  subject (fills the rest)`. A `*` marks
emails that have labels, when labels are loaded.

The reader shows header lines (`From`, `To`, `Cc`, `Date`, `Subject`, `Message-ID`, plus
`Copies: N in mailbox/folder, …`), then a blank line, then the body. With labels loaded, a
`Labels (model jev-x.y.z, file):` block with one line per question follows the headers.

## Global keys (every view)

| Key | Action |
| --- | --- |
| `?` | Help |
| `/` | Search prompt (query syntax below) |
| `L` | Label filter prompt (only when `--labels` is given) |
| `q`, `Esc`, `←`, `h` | Back to the previous view, quitting from the first view |
| `Q` | Quit immediately |
| `Ctrl-L` | Redraw |

## List views (mailboxes, folders, messages)

| Key | Action |
| --- | --- |
| `↓`/`j`, `↑`/`k` | Move by one row |
| `PgDn`/`Space`/`Ctrl-F`, `PgUp`/`b`/`Ctrl-B` | Move by one page |
| `g`/`Home`, `G`/`End` | First or last item |
| `Enter`, `→`, `l` | Open the selected item |
| `f` | Filter the visible list by text, case-insensitive, matching any shown column. An empty filter clears it |
| `o` | Reverse the sort order (message lists) |

## Reader

| Key | Action |
| --- | --- |
| `↓`/`j`, `↑`/`k` | Scroll by one line |
| `Space`/`PgDn`, `b`/`PgUp` | Scroll by one page |
| `g`, `G` | Top or bottom of the email |
| `n`, `p` | Next or previous email in the list it was opened from |
| `r` | Toggle the raw original file view |
| `t` | Conversation: emails with the same normalized subject |
| `s` | More emails from this sender |
| `c` | Copies: every mailbox and folder holding this email. `Enter` on a row opens that folder with the email highlighted |
| `y` | Copy the message ID to the clipboard, or show it if no clipboard is available |

## Prompts

A prompt opens on the status line. `Enter` submits, `Esc` cancels, and `Backspace` edits. The
up and down arrows recall earlier queries from this session.

### Search query syntax (`/`)

```text
[free text]  [from:ADDR]  [to:ADDR]  [since:YYYY-MM-DD]  [until:YYYY-MM-DD]  [user:MAILBOX]  [folder:NAME]
```

- Free text is matched as a substring of the subject or body, ignoring case. Words and quoted
  phrases are joined into a single substring, as with `jevron emails --search`.
- The tokens have exactly the semantics of the matching `jevron emails` options, which is what
  makes counts identical (SC-006).
- An invalid date shows `invalid date: …` on the status line and runs no search.
- No matches shows `no emails match` and keeps the current view.

### Label filter syntax (`L`)

```text
QUESTION>=NUMBER     e.g. special_purpose_entities>=0.8
QUESTION<=NUMBER     e.g. urgency<=0.5
QUESTION=LABEL       e.g. topic=trading   (choice questions)
```

Results are sorted by the question's value, highest first. `QUESTION_confidence` columns are
also accepted.
