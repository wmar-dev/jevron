import shutil

import pytest

from jevron import corpus

DATE = b"Mon, 14 May 2001 16:39:00 -0700 (PDT)"


def write_email(root, user, folder, n, *, sender="a@enron.com", subject="Hi", body="Hello", x_from=b"A", date=DATE):
    path = root / user / folder / f"{n}."
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        b"Message-ID: <%d.%s.%s@x>\r\n" % (n, user.encode(), folder.encode())
        + (b"Date: " + date + b"\r\n" if date else b"")
        + b"From: " + sender.encode() + b"\r\n"
        + b"To: b@enron.com, C@AOL.com\r\n"
        + b"Subject: " + subject.encode() + b"\r\n"
        + b"X-From: " + x_from + b"\r\n\r\n"
        + body.encode()
    )


@pytest.fixture(scope="session")
def ingested(tmp_path_factory):
    """A tiny maildir covering duplicates, nested folders, a missing date,
    control characters and a reply thread, ingested once per test session."""
    base = tmp_path_factory.mktemp("corpus")
    root = corpus.maildir(base)
    write_email(root, "lay-k", "inbox", 1, x_from=b"Fran\xe7ois")
    write_email(root, "skilling-j", "inbox", 1, x_from=b"Fran\xe7ois")  # same email in another mailbox ...
    write_email(root, "lay-k", "all_documents", 1, x_from=b"Fran\xe7ois")  # ... and another folder
    write_email(root, "lay-k", "sent", 2, subject="Raptor", body="About Raptor\n-----Original Message-----\nold",
                date=b"Tue, 1 May 2001 09:00:00 -0700 (PDT)")
    write_email(root, "lay-k", "inbox/hist_vols", 3, subject="Vols", body="curves", date=None)
    write_email(root, "lay-k", "inbox", 4, subject="Glitch", body="before\x1b[2J\x0cafter",
                date=b"Wed, 2 May 2001 09:00:00 -0700 (PDT)")
    write_email(root, "skilling-j", "inbox", 5, sender="j.skilling@enron.com", subject="RE: Raptor", body="Thanks",
                date=b"Thu, 3 May 2001 09:00:00 -0700 (PDT)")
    emails, locations = corpus.dedupe(corpus.parse_all(root, workers=1))
    emails.to_parquet(corpus.emails_path(base))
    locations.to_parquet(corpus.locations_path(base), index=False)
    return base


@pytest.fixture
def data_dir(ingested, tmp_path):
    """A per-test copy of the ingested parquet files (the raw maildir is shared, read-only)."""
    for path in (corpus.emails_path(ingested), corpus.locations_path(ingested)):
        shutil.copy(path, tmp_path / path.name)
    return tmp_path


class FakeWindow:
    """Stands in for a curses window: records writes and fails on out-of-bounds ones."""

    def __init__(self, h=24, w=80):
        self.h, self.w = h, w
        self.writes = []

    def getmaxyx(self):
        return self.h, self.w

    def addstr(self, y, x, text, attr=0):
        assert 0 <= y < self.h and 0 <= x < self.w, (y, x)
        assert x + len(text) <= self.w, (y, x, text)
        assert not (y == self.h - 1 and x + len(text) == self.w), "wrote bottom-right cell"
        self.writes.append((y, x, text))

    addnstr = insstr = addstr

    def erase(self):
        self.writes.clear()

    def text(self):
        return "\n".join(t for _, _, t in self.writes)
