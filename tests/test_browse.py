import time

import pytest

from jevron.browse import text


# --- text (T007) -------------------------------------------------------------


def test_clean_removes_control_characters():
    cleaned = text.clean("a\x1b[2J\x0cb\nc\td\ud800")
    assert "\x1b" not in cleaned and "\x0c" not in cleaned and "\ud800" not in cleaned
    assert cleaned == "a^[[2J^Lb\nc    d�"
    assert text.clean("x\r\ny") == "x\ny"


def test_width_and_fit():
    assert text.width("佐藤") == 4 and text.width("abc") == 3
    assert text.fit("hello world", 8) == "hello w…"
    assert text.fit("hi", 5) == "hi   "
    fitted = text.fit("佐藤佐藤佐藤", 7)
    assert fitted == "佐藤佐…" and text.width(fitted) == 7
    assert text.fit("anything", 0) == ""


def test_wrap_keeps_blank_lines_and_is_fast():
    assert text.wrap("a\n\nb", 10) == ["a", "", "b"]
    assert all(len(line) <= 5 for line in text.wrap("one two three four", 5))
    start = time.time()
    lines = text.wrap("word " * 400_000, 78)
    assert time.time() - start < 1 and len(lines) > 20_000


# --- fixtures ----------------------------------------------------------------

import json

import pandas as pd
from conftest import FakeWindow

from jevron import cli, corpus, label
from jevron.browse import app as app_mod
from jevron.browse.app import App, breadcrumb, put
from jevron.browse.data import Corpus, LabelStore, thread_key, thread_keys
from jevron.browse.query import Query, parse_label_filter, parse_query
from jevron.browse.views import BINDINGS, HelpView, ListView, ReaderView


@pytest.fixture
def corp(data_dir):
    return Corpus.load(data_dir)


def ids_by_subject(c):
    return {s: i for i, s in zip(c.df["message_id"], c.df["subject"])}


def open_path(app, *names):
    """Open list rows by their rendered name, e.g. open_path(app, "lay-k", "inbox")."""
    for name in names:
        view = app.stack.top
        view.select(next(i for i in view.visible if name in view.match(i).split() or view.match(i) == name))
        app.handle("Enter")


# --- safe drawing (T011) -----------------------------------------------------


def test_put_never_writes_out_of_bounds():
    win = FakeWindow(24, 80)
    put(win, 0, 0, "x" * 500)
    put(win, 23, 0, "y" * 500)  # last row: must not touch bottom-right cell
    put(win, 23, 79, "z")
    put(win, 5, 70, "佐藤" * 20)
    put(win, 30, 0, "off screen")
    put(win, 3, 0, "a\x1b[2Jb")
    assert "\x1b" not in win.text()


def test_browse_requires_terminal(data_dir, capsys, monkeypatch):
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    assert cli.main(["--data-dir", str(data_dir), "browse"]) == 1
    assert "needs an interactive terminal" in capsys.readouterr().err


def test_missing_locations_message(tmp_path, data_dir):
    corpus.locations_path(data_dir).unlink()
    with pytest.raises(FileNotFoundError, match="jevron ingest --force"):
        Corpus.load(data_dir)


# --- US1: browse and read (T013-T015, T021) ----------------------------------


def test_corpus_indexes(corp):
    assert corp.mailboxes() == [("lay-k", 5), ("skilling-j", 2)]
    assert dict(corp.folders("lay-k")) == {"all_documents": 1, "inbox": 2, "inbox/hist_vols": 1, "sent": 1}
    subj = ids_by_subject(corp)
    assert corp.folder_messages("lay-k", "all_documents") == [subj["Hi"]]  # copy shown in every folder (FR-004)
    assert corp.folder_messages("lay-k", "inbox") == [subj["Hi"], subj["Glitch"]]  # newest first
    assert sorted(corp.copies(subj["Hi"])) == [("lay-k", "all_documents"), ("lay-k", "inbox"), ("skilling-j", "inbox")]
    assert corp.df["message_id"].iloc[-1] == subj["Vols"]  # missing date sorts last


def test_navigation_and_back_restores_position(corp):
    app = App(corp)
    app.handle("j")  # cursor on skilling-j
    app.handle("k")
    open_path(app, "lay-k", "inbox")
    assert app.stack.top.title == "lay-k › inbox"
    app.handle("j")
    app.handle("Enter")
    assert isinstance(app.stack.top, ReaderView) and app.stack.top.title == "Glitch"
    app.handle("q")
    assert app.stack.top.cursor == 1  # restored (FR-012)
    app.handle("o")
    assert app.stack.top.selected() == ids_by_subject(corp)["Glitch"] and app.stack.top.sort_desc is False
    app.handle("q"), app.handle("q")
    assert app.stack.top.kind == "mailboxes" and app.stack.top.cursor == 0
    app.handle("q")
    assert app.running is False


def test_list_clamps_and_empty_list():
    view = ListView("messages", "t", list(range(5)), render=lambda i, c: str(i))
    view.move(-3)
    assert view.cursor == 0
    view.page(1, 10)
    assert view.cursor == 4
    empty = ListView("messages", "t", [], render=lambda i, c: str(i))
    empty.move(1), empty.end()
    assert empty.selected() is None and empty.rows(5, 80)[0][0].strip() == "(empty)"


def test_reader_headers_body_raw_and_neighbors(corp):
    subj = ids_by_subject(corp)
    context = ListView("messages", "t", corp.folder_messages("lay-k", "inbox"), render=str)
    reader = ReaderView(corp, subj["Glitch"], origin=context)
    lines = reader.lines(78)
    for header in ("From:", "To:", "Date:", "Subject:", "Message-ID:", "Copies:"):
        assert any(line.startswith(header) for line in lines)
    body = "\n".join(lines)
    assert "before^[[2J^Lafter" in body and "\x1b" not in body  # full body, cleaned for display
    reader.toggle_raw()
    raw = "\n".join(reader.lines(78))
    assert raw.startswith("Message-ID: <4.lay-k.inbox@x>") and "X-From: A" in raw
    assert reader.neighbor(-1) == subj["Hi"] and reader.neighbor(+5) is None


def test_full_screen_render_is_safe(corp):
    app = App(corp)
    open_path(app, "lay-k", "inbox")
    app.handle("Enter")
    for size in [(24, 80), (50, 200)]:
        win = FakeWindow(*size)
        app.draw(win)
        assert "Hi" in win.text() and "\x1b" not in win.text()
    small = FakeWindow(10, 40)
    app.draw(small)
    assert "Enlarge the terminal" in small.text()


def test_breadcrumb_keeps_the_current_view():
    parts = ["mailboxes (150)", "dasovich-j (28,234)", "dasovich-j › all_documents (11,896)", "search: raptor (409)"]
    assert breadcrumb(parts, 200) == " › ".join(parts)
    short = breadcrumb(parts, 40)
    assert short == "… › search: raptor (409)" and text.width(short) <= 40


def test_help_lists_every_binding(corp):
    help_text = HelpView().source()
    for b in BINDINGS:
        assert b.description in help_text


def test_yank_falls_back_without_clipboard(corp, monkeypatch):
    monkeypatch.setattr(app_mod.shutil, "which", lambda name: None)
    app = App(corp)
    open_path(app, "lay-k", "inbox")
    app.handle("Enter")
    app.handle("y")
    assert app.message.startswith("message id: <")


# --- US2: search and filter (T022-T023) --------------------------------------


def test_parse_query():
    q = parse_query('raptor "special purpose" from:enron.com to:aol since:2001-06-01 until:2002-01-01 user:lay-k folder:inbox')
    assert q == Query("raptor special purpose", "enron.com", "aol", "2001-06-01", "2002-01-01", "lay-k", "inbox")
    assert parse_query("re: q3").text == "re: q3"
    assert parse_query('"unbalanced').text == '"unbalanced'
    with pytest.raises(ValueError, match="invalid date"):
        parse_query("since:yesterday")
    with pytest.raises(ValueError):
        parse_query("   ")


@pytest.mark.parametrize("q, kwargs", [
    ("raptor", dict(search="raptor")),
    ("from:skilling", dict(sender="skilling")),
    ("to:aol.com since:2001-05-02", dict(recipient="aol.com", since="2001-05-02")),
    ("hello user:lay-k folder:inbox", dict(search="hello", user="lay-k", folder="inbox")),
])
def test_search_parity_with_jevron_emails(corp, data_dir, q, kwargs):
    expected = set(corpus.filter_emails(corpus.load(data_dir), **kwargs)["message_id"])
    assert set(corp.search(parse_query(q))) == expected


def test_search_and_filter_in_app(corp):
    app = App(corp, ask=lambda label: "raptor")
    app.handle("/")
    assert app.stack.top.breadcrumb() == "search: raptor (2)"
    app.search("nothingmatchesthis")
    assert app.message == "no emails match" and app.stack.top.title == "search: raptor"
    app.search("since:nope")
    assert app.message == "invalid date: nope"
    app.ask = lambda label: "skilling"
    app.handle("f")
    assert len(app.stack.top.visible) == 1 and "[filter: skilling]" in app.stack.top.breadcrumb()
    app.stack.top.set_filter("")
    assert len(app.stack.top.visible) == 2


# --- US3: conversations, sender, copies (T028) -------------------------------


def test_thread_key():
    for s in ["RE: Raptor", "Re:  re: raptor", "FW: Raptor", "Fwd:Raptor", "  raptor "]:
        assert thread_key(s) == "raptor"
    assert thread_key("") == "" and thread_key(None) == ""
    subjects = pd.Series(["RE: Raptor", "Re:  re: raptor", "FW:Fwd: Q3  Plan ", "", None, "Re: re", "Fwd raptor"])
    assert list(thread_keys(subjects)) == [thread_key(s) for s in subjects]


def test_conversation_sender_and_copies(corp):
    subj = ids_by_subject(corp)
    assert corp.thread(subj["RE: Raptor"]) == [subj["Raptor"], subj["RE: Raptor"]]
    assert corp.thread(subj["Vols"]) == [subj["Vols"]]
    assert corp.by_sender("a@enron.com")[0] == subj["Hi"]

    app = App(corp)
    app.search("raptor")
    app.stack.top.select(subj["RE: Raptor"])
    app.handle("Enter")
    app.handle("t")
    assert app.stack.top.title.startswith("conversation:") and app.stack.top.selected() == subj["RE: Raptor"]
    app.handle("q")
    app.handle("s")
    assert app.stack.top.title == "from: j.skilling@enron.com"
    app.handle("q")
    app.stack.top.message_id = subj["Hi"]
    app.handle("c")
    assert len(app.stack.top.visible) == 3
    app.stack.top.select(("skilling-j", "inbox", subj["Hi"]))
    app.handle("Enter")
    assert app.stack.top.title == "skilling-j › inbox" and app.stack.top.selected() == subj["Hi"]


# --- US4: labels (T032-T033) -------------------------------------------------


def write_results(path, records):
    path.write_text("".join(json.dumps(r) + "\n" for r in records))
    return path


def noul(p):
    return {"type": "noul", "noul": p}


def choice(c, conf):
    return {"type": "choice", "choice": c, "confidence": conf, "probabilities": {c: conf}}


@pytest.fixture
def labels(corp, tmp_path):
    subj = ids_by_subject(corp)
    a = write_results(tmp_path / "a.jsonl", [
        {"message_id": subj["Raptor"], "model": "jev-1.14.0", "usage": {}, "answers": {"spe": noul(0.9)}},
        {"message_id": subj["Hi"], "model": "jev-1.14.0", "usage": {}, "answers": {"spe": noul(0.1)}},
        {"message_id": "<unknown@x>", "model": "jev-1.14.0", "usage": {}, "answers": {"spe": noul(0.5)}},
    ])
    b = write_results(tmp_path / "b.jsonl", [
        {"message_id": subj["Raptor"], "model": "jev-1.13.0", "usage": {}, "answers": {"topic": choice("finance", 0.8)}},
        {"message_id": subj["Glitch"], "error": "TypeSafeAPIError: 500"},
    ])
    return LabelStore.load([a, b], corp.emails.index)


def test_label_store(corp, labels):
    subj = ids_by_subject(corp)
    assert labels.unknown == 1 and labels.has(subj["Raptor"]) and not labels.has(subj["Vols"])
    assert labels.questions == {"spe": "noul", "topic": "choice", "topic_confidence": "number"}
    assert labels.filter(parse_label_filter("spe>=0.5", labels.questions)) == [subj["Raptor"]]
    assert labels.filter(parse_label_filter("spe<=1", labels.questions)) == [subj["Raptor"], subj["Hi"]]
    assert labels.filter(parse_label_filter("topic=finance", labels.questions)) == [subj["Raptor"]]
    for bad, msg in [("nope>=1", "unknown question"), ("topic>=0.5", "choice question"),
                     ("spe=yes", "use >= or <="), ("spe>=x", "not a number"), ("garbage", "expected")]:
        with pytest.raises(ValueError, match=msg):
            parse_label_filter(bad, labels.questions)


def test_labels_in_reader_and_lists(corp, labels):
    subj = ids_by_subject(corp)
    reader = "\n".join(ReaderView(corp, subj["Raptor"], labels=labels).lines(100))
    assert "Labels (model jev-1.14.0, a.jsonl):" in reader and "spe: 0.90" in reader
    assert "Labels (model jev-1.13.0, b.jsonl):" in reader and "topic: finance" in reader
    assert "ERROR TypeSafeAPIError" in "\n".join(ReaderView(corp, subj["Glitch"], labels=labels).lines(100))
    assert "Labels" not in "\n".join(ReaderView(corp, subj["Vols"], labels=labels).lines(100))

    app = App(corp, labels, ask=lambda label: "spe>=0.5")
    assert "1 label records for unknown emails ignored" in app.message
    app.handle("L")
    assert app.stack.top.breadcrumb() == "labels: spe>=0.5 (1)"
    win = FakeWindow()
    app.draw(win)
    assert "  * a@enron.com" in win.text()
    assert App(corp).stack.top and (lambda a: (a.handle("L"), a.message)[1])(App(corp)).startswith("no labels loaded")


def test_bad_labels_file(corp, tmp_path):
    bad = tmp_path / "bad.jsonl"
    bad.write_text('{"message_id": "<x>"}\nnot json\n')
    with pytest.raises(ValueError, match="cannot read labels from .*bad.jsonl:.*:2:"):
        LabelStore.load([bad], corp.emails.index)
    with pytest.raises(ValueError, match="cannot read labels from"):
        LabelStore.load([tmp_path / "missing.jsonl"], corp.emails.index)


def test_browser_never_calls_jev(corp, labels, monkeypatch):
    import typesafe_sdk

    def boom(*a, **k):
        raise AssertionError("browser constructed a Jev client")

    monkeypatch.setattr(typesafe_sdk, "TypeSafeClient", boom)
    monkeypatch.setattr(typesafe_sdk, "AsyncTypeSafeClient", boom)
    app = App(corp, labels, ask=lambda label: "spe>=0")
    app.handle("L")
    app.handle("Enter")
    app.draw(FakeWindow())
