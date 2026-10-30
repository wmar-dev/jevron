import asyncio
import json

import httpx2
import pandas as pd
import pytest
from typesafe_sdk import AsyncTypeSafeClient, TypeSafeAuthenticationError

from jevron import cli, corpus, label, questions


def test_parse_and_dedupe(data_dir):
    df = corpus.load(data_dir)
    assert len(df) == 5
    dup = df[df["subject"] == "Hi"].iloc[0]
    assert dup["n_copies"] == 3 and list(dup["mailboxes"]) == ["lay-k", "skilling-j"]
    assert dup["x_from"] == "François"  # cp1252 header bytes decoded
    assert list(dup["to"]) == ["b@enron.com", "c@aol.com"]
    assert dup["date"] == pd.Timestamp("2001-05-14 23:39", tz="UTC")


def test_locations_record_every_copy(data_dir):
    emails, locations = corpus.load(data_dir), corpus.load_locations(data_dir)
    assert len(locations) == 7  # one row per fixture file
    assert set(locations["message_id"]) <= set(emails["message_id"])
    per_email = locations.groupby("message_id")
    for _, row in emails.iterrows():
        rows = per_email.get_group(row["message_id"])
        assert len(rows) == row["n_copies"]
        assert set(rows["user"]) == set(row["mailboxes"])
    hi = emails.loc[emails["subject"] == "Hi", "message_id"].item()
    assert {"lay-k/inbox", "lay-k/all_documents", "skilling-j/inbox"} == set(
        locations.loc[locations["message_id"] == hi, ["user", "folder"]].agg("/".join, axis=1))
    assert "inbox/hist_vols" in set(locations["folder"])


def test_load_locations_missing(tmp_path):
    with pytest.raises(FileNotFoundError, match="jevron ingest --force"):
        corpus.load_locations(tmp_path)


def test_filters_and_state(data_dir):
    df = corpus.load(data_dir)
    assert len(corpus.filter_emails(df, search="raptor")) == 2
    assert len(corpus.filter_emails(df, folder="sent")) == 1
    assert len(corpus.filter_emails(df, recipient="aol.com")) == 5
    assert len(corpus.filter_emails(df, ids=["2.lay-k.sent@x"])) == 1
    state = corpus.to_state(corpus.filter_emails(df, ids=["2.lay-k.sent@x"]).iloc[0])
    assert "About Raptor" in state and "old" not in state and "Subject: Raptor" in state


def test_questions_validation(tmp_path):
    f = tmp_path / "q.toml"
    f.write_text('[t]\ntype = "choice"\ncriteria = { a = "A", b = "B" }\n[u]\ntype = "score"\ncriteria = ["lo", "hi"]\n')
    assert set(questions.load(f)) == {"t", "u"}
    f.write_text('[t]\ntype = "nope"\n')
    with pytest.raises(ValueError, match="type must be"):
        questions.load(f)
    assert set(questions.inline_nouls(["spe=Mentions SPEs"])) == {"spe"}
    with pytest.raises(ValueError):
        questions.inline_nouls(["missing-equals"])


ANSWERS = {
    "topic": {"type": "choice", "choice": "trading", "confidence": 0.9, "probabilities": {"trading": 0.9, "other": 0.1}},
    "spe": {"type": "noul", "noul": 0.8},
    "urgency": {"type": "score", "score": 1.5, "confidence": 0.7, "legend": {"0": "lo", "1": "mid", "2": "hi"},
                "probabilities": {"0": 0.1, "1": 0.3, "2": 0.6}},
}


def mock_client(status=200, fail_subject=None, seen=None):
    def handler(request):
        body = json.loads(request.content)
        if seen is not None:
            seen.append(body)
        if status != 200:
            return httpx2.Response(status, json={"detail": "nope"})
        if fail_subject and f"Subject: {fail_subject}" in body["state"]:
            return httpx2.Response(422, json={"detail": "bad state"})
        return httpx2.Response(200, json={"model": "jev-1.13.0", "usage": {"input_tokens": 10, "output_tokens": 3},
                                          "answers": ANSWERS})

    return AsyncTypeSafeClient(api_key="test", transport=httpx2.MockTransport(handler), compression=False)


QS = {"spe": {"type": "noul", "instructions": "Mentions SPEs"}}


def test_label_writes_resumes_and_exports(data_dir, tmp_path):
    emails = corpus.load(data_dir)
    out = tmp_path / "out.jsonl"
    seen = []

    summary = asyncio.run(label.label(emails, QS, mock_client(fail_subject="Raptor", seen=seen), out, concurrency=2))
    assert (summary.done, summary.errors) == (4, 1)
    assert seen[0]["questions"] == QS and seen[0]["state"].startswith("From: ")

    # Re-running retries only the failed email.
    seen.clear()
    summary = asyncio.run(label.label(emails, QS, mock_client(seen=seen), out))
    assert (summary.done, summary.errors, summary.skipped) == (1, 0, 4)
    assert len(seen) == 1 and "Subject: Raptor" in seen[0]["state"]

    results = label.read_results(out)
    assert len(results) == 5 and results["error"].isna().all()
    row = results.iloc[0]
    assert (row["topic"], row["topic_confidence"], row["spe"], row["urgency"]) == ("trading", 0.9, 0.8, 1.5)

    csv = tmp_path / "out.csv"
    assert cli.main(["--data-dir", str(data_dir), "export", str(out), "--out", str(csv)]) == 0
    exported = pd.read_csv(csv)
    assert {"subject", "user", "topic", "spe"} <= set(exported.columns) and len(exported) == 5


def test_label_stops_on_auth_error(data_dir, tmp_path):
    with pytest.raises(TypeSafeAuthenticationError):
        asyncio.run(label.label(corpus.load(data_dir), QS, mock_client(status=401), tmp_path / "o.jsonl"))


def test_cli_dry_run_and_limits(data_dir, tmp_path, capsys):
    base = ["--data-dir", str(data_dir)]
    assert cli.main(base + ["label", "--noul", "x=y", "--out", str(tmp_path / "o.jsonl"), "--dry-run"]) == 0
    assert "5 emails selected" in capsys.readouterr().err
    # `ask` defaults to 5 emails, but that default must not leak into `label`.
    parser = cli.build_parser()
    assert parser.parse_args(base + ["label", "--out", "o"]).limit is None


def test_read_records_latest_wins_and_reports_bad_lines(tmp_path):
    path = tmp_path / "r.jsonl"
    path.write_text(
        json.dumps({"message_id": "<a>", "error": "boom"}) + "\n"
        + json.dumps({"message_id": "<b>", "error": "boom"}) + "\n"
        + json.dumps({"message_id": "<a>", "model": "jev-1.14.0", "answers": ANSWERS}) + "\n"
    )
    records = label.read_records(path)
    assert records["<a>"]["model"] == "jev-1.14.0" and records["<b>"]["error"] == "boom"
    path.write_text(json.dumps({"message_id": "<a>"}) + "\n{oops\n")
    with pytest.raises(ValueError, match=r"r\.jsonl:2:"):
        label.read_records(path)
