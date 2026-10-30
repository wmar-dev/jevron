# Quickstart: validating the Enron Mail Browser

## Prerequisites

- The CMU tarball is at `~/Downloads/enron_mail_20150507.tar.gz`.
- `uv sync` has been run.
- A terminal of at least 80×24.

## 1. Rebuild the corpus with folder locations

```bash
uv run jevron ingest --force
```

**Expected**:

- The run takes about 1–2 minutes.
- It reports 255,170 distinct emails and 517,401 file locations.
- `data/locations.parquet` exists.

## 2. Automated tests (offline, < 10 s)

```bash
uv run pytest
```

**Expected**: all tests pass, including the browser core tests (navigation, query parsing,
search parity, text cleaning, safe rendering against a fake window).

## 3. Manual scenarios

Run `uv run jevron browse` unless a step says otherwise.

| # | Steps | Expected | Covers |
| --- | --- | --- | --- |
| 1 | Launch | Mailbox list with 150 mailboxes and counts within 5 s | US1, SC-001 |
| 2 | Open `lay-k`, then `inbox`, then the top email | Folder counts shown. Message list newest first. Reader shows headers and body | US1, FR-003, FR-006, FR-007 |
| 3 | In the reader, press `r` | Original file shown exactly, with all headers. Press `r` again to return | FR-008 |
| 4 | Open the folder with the most emails (11,896) and press `G` | Jumps to the oldest email instantly | SC-002 |
| 5 | Search `/raptor` | Count equals `uv run jevron emails --search raptor --limit 100000 --format ids \| wc -l` | US2, SC-006 |
| 6 | Search `/raptor since:2001-06-01 from:enron.com` | Results narrow. Open one, go back, and the cursor is unchanged | FR-009, FR-012 |
| 7 | In any message list, press `f` and type `meeting` | List filters in place. An empty filter restores it | FR-010 |
| 8 | Open an email whose subject starts with `RE:` and press `t` | Conversation list in date order, with the current email highlighted | US3, FR-011 |
| 9 | In the reader, press `s`, then `c` | Sender's emails, then every mailbox and folder copy. `Enter` on a copy opens that folder at the email | US3 |
| 10 | In the reader, press `y` | Status shows `copied <id>`, and `pbpaste` prints it | FR-013 |
| 11 | Find the longest email: `/` search for a phrase from it, or open the largest body via `uv run jevron emails --search …` | Opens within 1 s and scrolls smoothly | SC-002, edge case |
| 12 | Open an email with a garbled header (search `/enronsato`) | Replacement characters shown. Terminal intact | SC-005 |
| 13 | Resize the terminal below 80×24, then back | Size message, then a normal redraw | Edge case, SC-007 |
| 14 | Press `?` from the reader | Help lists every binding in the keybindings contract | FR-018 |
| 15 | Move `data/locations.parquet` away and launch | Exits with the `jevron ingest --force` message. Terminal normal | Contract |

## 4. Labels (P4)

```bash
# Requires TYPESAFE_API_KEY, or use any existing results file
uv run jevron label -q questions/investigation.toml --search raptor --limit 20 --out data/raptor.jsonl
uv run jevron browse --labels data/raptor.jsonl
```

**Expected**:

- Labeled emails show a `*` in lists, and a Labels block with the model version in the reader.
- `L special_purpose_entities>=0.8` lists matching emails, highest first.
- Unlabeled emails show no label block.
- No network traffic occurs while browsing.

## Performance

Measured 2026-10-29 on the full corpus (10-core macOS laptop):

```bash
PYTHONPATH=tests uv run python -c "…"   # times Corpus.load, the largest folder, the longest email, and searches
```

| Check | Measured | Target |
| --- | --- | --- |
| `Corpus.load` (launch to mailbox list, excluding interpreter start) | 1.85 s | ≤ 5 s (SC-001) |
| Open and draw the largest folder (`dasovich-j/all_documents`, 11,896) and jump to the end | 0.04 s | ≤ 1 s (SC-002) |
| Open and draw the longest email (2,011,422 characters) | 0.41 s | ≤ 1 s (SC-002) |
| Search `raptor` (409 hits) | 0.27 s | ≤ 3 s (SC-003) |
| Search `raptor since:2001-06-01 from:enron.com` (129 hits) | 0.30 s | ≤ 3 s (SC-003) |
| Search `to:aol.com` (6,703 hits) | 0.70 s | ≤ 3 s (SC-003) |
| Conversation, sender and copies lookups | 44, 2 and 4 ms | ≤ 1 s (SC-002) |

The first implementation pre-built thread, sender and copy indexes at launch, and the load took
4.25 s. Switching those to on-demand vectorized lookups brought it to 1.85 s.

## Results

Run 2026-10-29. "pty" means the step was driven with real keystrokes against `jevron browse` in a
pseudo-terminal (TERM=xterm-256color, 80×24), checking the drawn output and the exit code.
"automated" means it is covered by `tests/test_browse.py` or a script on the full corpus.

| # | Result | How verified |
| --- | --- | --- |
| 1 | PASS | pty: mailbox list drawn. Load is 1.85 s |
| 2 | PASS | pty: folder list, message list and reader headers drawn |
| 3 | PASS | pty: `r` shows the raw file (`X-Folder:` header), and `r` returns |
| 4 | PASS | automated: largest folder plus `G` in 0.04 s |
| 5 | PASS | pty: `search: raptor (409)`, which equals `jevron emails --search raptor` (409) |
| 6 | PASS | automated: filter parity tests, and cursor restored on back |
| 7 | PASS | automated: `f` filter and clear |
| 8 | PASS | pty: `t` opens `conversation: …`. Automated: date order and highlight |
| 9 | PASS | automated: `s` sender list, and `c` copies then `Enter` opens the folder at the email |
| 10 | PASS | pty: `y`, then `pbpaste` returns the message ID |
| 11 | PASS | automated: longest email renders in 0.41 s |
| 12 | PASS | automated: `from:enronsato` (6 emails) renders `¿m ²¡`. All 4,256 control-character emails render into a bounds-checked fake window without error |
| 13 | PASS | pty: resize to 60×20 shows the "Enlarge the terminal" message, and resizing back redraws |
| 14 | PASS | pty: `?` shows the help screen. Automated: every binding is listed |
| 15 | PASS | CLI: missing `locations.parquet` prints the `jevron ingest --force` message, exit 1 |
| §4 labels | PASS | pty with a hand-written results file (no API call): `L spe>=0.5` gives `labels: spe>=0.5 (1)`, and the reader shows `Labels (model jev-1.14.0 …)` and `spe: 0.92` |

**Not verified**:
- A human session at a larger terminal size. pty runs used 80×24 only, and the automated draw
  tests also use 200×50.
- Visual appearance (colors and highlighting) as a person would see it.
- Labels produced by a real `jevron label` run, since no API key was available.
