import tarfile

import pytest

from jevron import berkeley, corpus

CATEGORIES = """Format of each line in .cats file:
n1,n2,n3

1 Coarse genre

1.1 Company Business, Strategy, etc. (elaborate in Section 3 [Topics])
1.2 Purely Personal

3 Primary topics (if coarse genre 1.1 is selected)

3.9 alliances / partnerships

4 Emotional tone (if not neutral)

4.11 worry / anxiety
"""


@pytest.fixture
def tarball(ingested, tmp_path):
    """A Berkeley-style archive whose emails are copies of fixture corpus files."""
    src = tmp_path / "src" / "enron_with_categories"
    raw = corpus.maildir(ingested)
    files = {
        # A non-kept copy: ingest keeps lay-k/all_documents/1., so this id isn't in emails.parquet.
        "1/100.txt": (raw / "lay-k" / "inbox" / "1.", "1,1,2\n3,9,1\n"),
        "2/200.txt": (raw / "lay-k" / "sent" / "2.", "1,2,2\n4,11,2\n"),
    }
    for name, (source, cats) in files.items():
        txt = src / name
        txt.parent.mkdir(parents=True, exist_ok=True)
        txt.write_bytes(source.read_bytes())
        txt.with_suffix(".cats").write_text(cats)
    (src / "categories.txt").write_text(CATEGORIES)
    path = tmp_path / "enron_with_categories.tar.gz"
    with tarfile.open(path, "w:gz") as tf:
        tf.add(src, arcname="enron_with_categories")
    return path


def test_categories(tarball, data_dir):
    cats = berkeley.categories(berkeley.extract(tarball, data_dir))
    assert list(cats["code"]) == ["1.1", "1.2", "3.9", "4.11"]
    assert cats.set_index("code").loc["4.11", "name"] == "worry / anxiety"
    assert cats.set_index("code").loc["3.9", "group_name"] == "topic"


def test_load_links_labels_to_corpus(tarball, data_dir):
    labels = berkeley.load(data_dir, tarball)
    emails = corpus.load(data_dir).set_index("message_id")
    assert len(labels) == 4 and set(labels["message_id"]) <= set(emails.index)
    hi = labels[labels["berkeley_id"] == "100"]
    assert set(hi["message_id"]) == {"<1.lay-k.all_documents@x>"}  # linked through the dedup key
    assert set(hi["code"]) == {"1.1", "3.9"} and hi.set_index("code").loc["3.9", "annotators"] == 1
    raptor = labels[labels["berkeley_id"] == "200"].set_index("code")
    assert raptor.loc["4.11", "name"] == "worry / anxiety" and raptor.loc["4.11", "annotators"] == 2


def test_load_rejects_unknown_emails(tarball, data_dir, tmp_path):
    berkeley.extract(tarball, data_dir)
    stray = berkeley.labels_dir(data_dir) / "1" / "999.txt"
    stray.write_text("Message-ID: <nope@x>\r\nFrom: z@z.com\r\nSubject: unknown\r\n\r\nbody")
    stray.with_suffix(".cats").write_text("1,1,1\n")
    with pytest.raises(ValueError, match="1 labeled emails not found"):
        berkeley.load(data_dir, tarball)
