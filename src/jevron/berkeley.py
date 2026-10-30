"""Load the UC Berkeley hand-labeled Enron subset and link it to the corpus.

The archive (`enron_with_categories.tar.gz`, from https://bailando.berkeley.edu/enron_email.html)
holds about 1,700 emails, each as `<genre>/<id>.txt` plus `<genre>/<id>.cats`. Every
`.cats` line is `group,category,count`, where `count` is how many annotators assigned
that category. `categories.txt` names the categories, for example 4.11 = worry / anxiety.
"""

import re
import tarfile
from pathlib import Path

import pandas as pd

from jevron import corpus

DEFAULT_TARBALL = Path.home() / "Downloads" / "enron_with_categories.tar.gz"
GROUPS = {1: "coarse genre", 2: "included/forwarded", 3: "topic", 4: "emotional tone"}


def labels_dir(data_dir: Path) -> Path:
    return data_dir / "berkeley" / "enron_with_categories"


def extract(tarball: Path, data_dir: Path) -> Path:
    """Unpack the archive unless it's already there."""
    root = labels_dir(data_dir)
    if not root.exists():
        with tarfile.open(tarball, "r:gz") as tf:
            tf.extractall(root.parent, filter="data")
    return root


def categories(root: Path) -> pd.DataFrame:
    """`categories.txt` as rows of (group, category, code, name, group_name)."""
    rows = []
    for line in (root / "categories.txt").read_text().splitlines():
        if m := re.match(r"^(\d+)\.(\d+)\s+(.+?)\s*$", line):
            group, category, name = int(m[1]), int(m[2]), m[3]
            rows.append({"group": group, "category": category, "code": f"{group}.{category}",
                         "name": name, "group_name": GROUPS.get(group, str(group))})
    return pd.DataFrame(rows)


def load(data_dir: Path, tarball: Path = DEFAULT_TARBALL) -> pd.DataFrame:
    """One row per (email, assigned category), linked to the corpus.

    Columns: message_id (the corpus's distinct email), berkeley_id, group, category,
    code, name, group_name, annotators (how many assigned it). Emails are matched on the
    same key ingest deduplicates on, so a labeled file that is a non-kept copy of an
    email still links to it.
    """
    root = extract(tarball, data_dir)
    files = []
    for txt in sorted(root.glob("*/*.txt")):
        email = corpus.parse_message(txt, root)
        email["berkeley_id"] = txt.stem
        files.append(email)
    files = pd.DataFrame(files)

    emails = corpus.load(data_dir, columns=["message_id", *corpus.DEDUP_KEY])
    linked = files.drop(columns="message_id").merge(emails, on=corpus.DEDUP_KEY, how="left")
    missing = linked["message_id"].isna().sum()
    if missing:
        raise ValueError(f"{missing} labeled emails not found in the corpus; is data/emails.parquet from the same release?")

    rows = []
    for berkeley_id, message_id, path in linked[["berkeley_id", "message_id", "path"]].itertuples(index=False):
        for line in Path(path).with_suffix(".cats").read_text().split():
            group, category, count = map(int, line.split(","))
            rows.append({"message_id": message_id, "berkeley_id": berkeley_id,
                         "group": group, "category": category, "annotators": count})
    labels = pd.DataFrame(rows)
    return labels.merge(categories(root), on=["group", "category"], how="left")
