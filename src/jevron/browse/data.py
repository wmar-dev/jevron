"""Corpus indexes and label store backing the browser (no curses)."""

import re
from pathlib import Path

import pandas as pd

from jevron import corpus, label
from jevron.browse.query import LabelFilter, Query

REPLY_PREFIX = re.compile(r"^\s*(re|fw|fwd)\s*:\s*", re.IGNORECASE)


def thread_key(subject: str | None) -> str:
    """Subject with Re:/Fw:/Fwd: prefixes stripped, lowercased and whitespace-collapsed."""
    s = subject if isinstance(subject, str) else ""
    while (stripped := REPLY_PREFIX.sub("", s, count=1)) != s:
        s = stripped
    return " ".join(s.lower().split())


def thread_keys(subjects: pd.Series) -> pd.Series:
    """Vectorized thread_key() for a whole column."""
    s = subjects.fillna("").str.lower().str.replace(r"^(\s*(re|fw|fwd)\s*:\s*)+", "", regex=True)
    return s.str.replace(r"\s+", " ", regex=True).str.strip()


class Corpus:
    """The ingested corpus plus the lookups the browser needs, built once at load."""

    def __init__(self, emails: pd.DataFrame, locations: pd.DataFrame):
        # Global order: newest first, missing dates last. `rank` sorts any subset the same way.
        emails = emails.sort_values("date", ascending=False, na_position="last", ignore_index=True)
        emails["rank"] = range(len(emails))
        emails["thread_key"] = thread_keys(emails["subject"])
        self.df = emails  # flat frame, for corpus.filter_emails
        self.emails = emails.set_index("message_id", drop=False)

        locations = locations.join(self.emails["rank"], on="message_id").sort_values(
            ["user", "folder", "rank"], ignore_index=True)
        self.locations = locations
        counts = locations.groupby(["user", "folder"], sort=True).size()
        self._mailboxes = [(u, int(n)) for u, n in locations.groupby("user", sort=True).size().items()]
        self._folders: dict[str, list[tuple[str, int]]] = {}
        for (user, folder), n in counts.items():
            self._folders.setdefault(user, []).append((folder, int(n)))
        self._folder_ids = {k: list(g) for k, g in locations.groupby(["user", "folder"])["message_id"]}
        # Threads, senders and copies are looked up on demand: each is one vectorized
        # comparison (milliseconds), versus seconds to pre-build ~150k groups at launch.

    @classmethod
    def load(cls, data_dir: Path) -> "Corpus":
        return cls(corpus.load(data_dir), corpus.load_locations(data_dir))

    def email(self, message_id: str) -> pd.Series:
        return self.emails.loc[message_id]

    def mailboxes(self) -> list[tuple[str, int]]:
        """(mailbox, number of message files) sorted by name."""
        return self._mailboxes

    def folders(self, user: str) -> list[tuple[str, int]]:
        """(folder, number of message files) for one mailbox, nested folders included."""
        return self._folders.get(user, [])

    def folder_messages(self, user: str, folder: str) -> list[str]:
        """Message ids of every file in the folder, newest first, missing dates last."""
        return self._folder_ids.get((user, folder), [])

    def copies(self, message_id: str) -> list[tuple[str, str]]:
        """(mailbox, folder) of every file holding this email."""
        rows = self.locations[self.locations["message_id"] == message_id]
        return list(zip(rows["user"], rows["folder"]))

    def thread(self, message_id: str) -> list[str]:
        """The email's conversation (same normalized subject), oldest first, missing dates last."""
        key = self.emails.at[message_id, "thread_key"]
        if not key:
            return [message_id]
        hits = self.df[self.df["thread_key"] == key]
        return list(hits.sort_values("date", na_position="last", kind="stable")["message_id"])

    def by_sender(self, sender: str | None) -> list[str]:
        """All emails from `sender`, newest first."""
        return list(self.df.loc[self.df["from"] == sender, "message_id"]) if sender else []

    def search(self, q: Query) -> list[str]:
        """Same matching as `jevron emails` (corpus.filter_emails), newest first."""
        hits = corpus.filter_emails(self.df, search=q.text, sender=q.sender, recipient=q.recipient,
                                    since=q.since, until=q.until, user=q.user, folder=q.folder)
        return list(hits.sort_values("rank")["message_id"])


class LabelStore:
    """Existing `jevron label` results, read-only. Never talks to Jev."""

    def __init__(self, records: dict[str, list[tuple[str, dict]]], flat: pd.DataFrame,
                 questions: dict[str, str], unknown: int):
        self.records = records
        self.flat = flat
        self.questions = questions
        self.unknown = unknown

    @classmethod
    def load(cls, paths: list[Path], known_ids) -> "LabelStore":
        known = set(known_ids)
        records: dict[str, list[tuple[str, dict]]] = {}
        rows, questions, unknown = [], {}, 0
        for path in paths:
            try:
                file_records = label.read_records(path)
            except (OSError, ValueError, KeyError) as e:
                raise ValueError(f"cannot read labels from {path}: {e}") from None
            for message_id, record in file_records.items():
                if message_id not in known:
                    unknown += 1
                    continue
                records.setdefault(message_id, []).append((Path(path).name, record))
                answers = record.get("answers", {})
                rows.append({"message_id": message_id, **label.flatten(answers)})
                for name, answer in answers.items():
                    questions[name] = answer["type"]
                    if answer["type"] in ("choice", "score"):
                        questions[f"{name}_confidence"] = "number"
        flat = pd.DataFrame(rows, columns=["message_id"] if not rows else None)
        flat = flat.groupby("message_id").last() if rows else flat.set_index("message_id")
        return cls(records, flat, questions, unknown)

    def has(self, message_id: str) -> bool:
        return message_id in self.records

    def for_email(self, message_id: str) -> list[tuple[str, dict]]:
        return self.records.get(message_id, [])

    def filter(self, f: LabelFilter) -> list[str]:
        """Message ids passing the filter, highest value first."""
        col = self.flat[f.question].dropna()
        if f.op == "=":
            hits = col[col == f.value]
            if f"{f.question}_confidence" in self.flat:
                return list(self.flat.loc[hits.index, f"{f.question}_confidence"].sort_values(ascending=False).index)
            return list(hits.index)
        hits = col[col >= f.value] if f.op == ">=" else col[col <= f.value]
        return list(hits.sort_values(ascending=False).index)
