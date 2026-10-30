"""Extract, parse, deduplicate and filter the CMU Enron maildir."""

import email
import email.policy
import email.utils
import os
import re
import tarfile
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import pandas as pd

DEFAULT_TARBALL = Path.home() / "Downloads" / "enron_mail_20150507.tar.gz"
DEDUP_KEY = ["from", "date", "subject", "body"]


def maildir(data_dir: Path) -> Path:
    return data_dir / "raw" / "maildir"


def emails_path(data_dir: Path) -> Path:
    return data_dir / "emails.parquet"


def locations_path(data_dir: Path) -> Path:
    return data_dir / "locations.parquet"


def extract(tarball: Path, data_dir: Path) -> Path:
    """Unpack the tarball unless the maildir is already there."""
    root = maildir(data_dir)
    if not root.exists():
        with tarfile.open(tarball, "r:gz") as tf:
            tf.extractall(root.parent, filter="data")
    return root


def header(msg, name):
    """Header as str. Some Enron headers hold raw, undeclared 8-bit bytes (Windows-1252),
    which compat32 would otherwise return as lossy Header objects."""
    for key, value in msg.raw_items():
        if key.lower() == name.lower():
            return value.encode("ascii", "surrogateescape").decode("cp1252", errors="replace")
    return None


def split_addrs(value):
    if not value:
        return []
    return [a.lower() for _, a in email.utils.getaddresses([value]) if a]


def parse_message(path: Path, root: Path) -> dict:
    with open(path, "rb") as f:
        msg = email.message_from_binary_file(f, policy=email.policy.compat32)
    try:
        date = pd.Timestamp(email.utils.parsedate_to_datetime(header(msg, "Date")))
        date = date.tz_localize("UTC") if date.tzinfo is None else date.tz_convert("UTC")
    except Exception:
        date = pd.NaT
    body = msg.get_payload(decode=True) if not msg.is_multipart() else b""
    rel = path.relative_to(root).parts
    return {
        "message_id": header(msg, "Message-ID"),
        "date": date,
        "from": (split_addrs(header(msg, "From")) or [None])[0],
        "to": split_addrs(header(msg, "To")),
        "cc": split_addrs(header(msg, "Cc")),
        "bcc": split_addrs(header(msg, "Bcc")),
        "subject": header(msg, "Subject") or "",
        "x_from": header(msg, "X-From"),
        "user": rel[0],
        "folder": "/".join(rel[1:-1]),
        "body": (body or b"").decode("cp1252", errors="replace"),
        "path": str(path),
    }


def parse_mailbox(user_dir: Path, root: Path) -> list[dict]:
    return [parse_message(p, root) for p in user_dir.rglob("*") if p.is_file()]


def parse_all(root: Path, workers: int | None = None, progress: Callable[[int, int], None] | None = None) -> pd.DataFrame:
    """Parse every message, one mailbox per worker process."""
    users = sorted(p for p in root.iterdir() if p.is_dir())
    rows = []
    with ProcessPoolExecutor(max_workers=workers or os.cpu_count()) as pool:
        futures = [pool.submit(parse_mailbox, u, root) for u in users]
        for done, future in enumerate(as_completed(futures), 1):
            rows.extend(future.result())
            if progress:
                progress(done, len(users))
    return pd.DataFrame(rows)


def dedupe(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Collapse copies of the same email across folders and mailboxes.

    Keeps the first copy (by mailbox, folder, path) and records how many copies
    there were and which mailboxes held them. Also returns every file's location,
    keyed by the message_id of the email it was collapsed into.
    """
    df = df.sort_values(["user", "folder", "path"], ignore_index=True)
    key = pd.util.hash_pandas_object(df[DEDUP_KEY].astype(str), index=False)
    groups = df.groupby(key, sort=False)
    first = df.loc[groups.head(1).index].copy()
    first["n_copies"] = groups.size().loc[key[first.index]].to_numpy()
    mailboxes = groups["user"].unique().map(sorted)
    first["mailboxes"] = mailboxes.loc[key[first.index]].to_numpy()
    kept_id = pd.Series(first["message_id"].to_numpy(), index=key[first.index].to_numpy())
    locations = pd.DataFrame({
        "message_id": kept_id.loc[key.to_numpy()].to_numpy(),
        "user": df["user"],
        "folder": df["folder"],
        "path": df["path"],
    })
    return first.sort_values("date", ignore_index=True), locations


def build(tarball: Path, data_dir: Path, workers: int | None = None, progress=None) -> tuple[pd.DataFrame, pd.DataFrame]:
    root = extract(tarball, data_dir)
    emails, locations = dedupe(parse_all(root, workers, progress))
    emails.to_parquet(emails_path(data_dir))
    locations.to_parquet(locations_path(data_dir), index=False)
    return emails, locations


def load(data_dir: Path, columns: list[str] | None = None) -> pd.DataFrame:
    path = emails_path(data_dir)
    if not path.exists():
        raise FileNotFoundError(f"{path} not found; run `jevron ingest` first")
    return pd.read_parquet(path, columns=columns)


def load_locations(data_dir: Path) -> pd.DataFrame:
    path = locations_path(data_dir)
    if not path.exists():
        raise FileNotFoundError(f"{path} not found; run `jevron ingest --force` to rebuild with folder locations")
    return pd.read_parquet(path)


def filter_emails(
    df: pd.DataFrame,
    *,
    ids: list[str] | None = None,
    user: str | None = None,
    folder: str | None = None,
    sender: str | None = None,
    recipient: str | None = None,
    since: str | None = None,
    until: str | None = None,
    search: str | None = None,
    sample: int | None = None,
    seed: int = 0,
    limit: int | None = None,
) -> pd.DataFrame:
    """Select emails. String filters are case-insensitive substrings, except
    `user` and `folder`, which match a mailbox name or top-level folder exactly."""
    mask = pd.Series(True, index=df.index)
    if ids:
        mask &= df["message_id"].isin({normalize_id(i) for i in ids})
    if user:
        mask &= df["user"] == user
    if folder:
        mask &= df["folder"].str.split("/").str[0] == folder
    if sender:
        mask &= df["from"].fillna("").str.contains(sender, case=False, regex=False)
    if recipient:
        needle = recipient.lower()
        to_all = df["to"].map(list) + df["cc"].map(list) + df["bcc"].map(list)
        mask &= to_all.map(lambda addrs: any(needle in a for a in addrs))
    if since:
        mask &= df["date"] >= pd.Timestamp(since, tz="UTC")
    if until:
        mask &= df["date"] < pd.Timestamp(until, tz="UTC")
    if search:
        mask &= df["subject"].str.contains(search, case=False, regex=False) | df["body"].str.contains(
            search, case=False, regex=False
        )
    out = df[mask]
    if sample is not None:
        out = out.sample(n=min(sample, len(out)), random_state=seed)
    if limit is not None:
        out = out.head(limit)
    return out


def normalize_id(message_id: str) -> str:
    message_id = message_id.strip()
    return message_id if message_id.startswith("<") else f"<{message_id}>"


QUOTED_REPLY = re.compile(r"^\s*-{2,}\s*Original Message\s*-{2,}.*", re.IGNORECASE | re.MULTILINE | re.DOTALL)


def strip_quoted(body: str) -> str:
    """Drop the quoted reply chain ("-----Original Message-----" onwards and `>` lines).
    Forwarded messages are kept, since they are usually the point of a forward."""
    body = QUOTED_REPLY.sub("", body)
    return "\n".join(line for line in body.splitlines() if not line.lstrip().startswith(">")).strip()


def to_state(row, max_chars: int | None = 4000, quoted: bool = False) -> str:
    """The text Jev sees for one email: key headers plus the (trimmed) body."""
    body = row["body"] if quoted else strip_quoted(row["body"])
    if max_chars is not None and len(body) > max_chars:
        body = body[:max_chars] + "\n[truncated]"
    recipients = ", ".join(list(row["to"]) + list(row["cc"]))
    date = "" if pd.isna(row["date"]) else row["date"].strftime("%Y-%m-%d %H:%M UTC")
    return f"From: {row['from']}\nTo: {recipients}\nDate: {date}\nSubject: {row['subject']}\n\n{body}"
