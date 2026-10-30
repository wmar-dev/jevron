"""Curses layer: drawing, prompts, key dispatch.

`App` holds the actions and draws onto any curses-like window, so tests drive it
with a fake window; only `run()` and `CursesPrompt` touch a real terminal.
"""

import curses
import locale
import os
import shutil
import subprocess
import sys
from pathlib import Path

from jevron.browse import text
from jevron.browse.data import Corpus, LabelStore
from jevron.browse.query import parse_label_filter, parse_query
from jevron.browse.views import HelpView, ListView, ReaderView, TextView, ViewStack, format_date, lookup

MIN_H, MIN_W = 24, 80

SPECIAL_KEYS = {
    curses.KEY_DOWN: "Down", curses.KEY_UP: "Up", curses.KEY_LEFT: "Left", curses.KEY_RIGHT: "Right",
    curses.KEY_NPAGE: "PgDn", curses.KEY_PPAGE: "PgUp", curses.KEY_HOME: "Home", curses.KEY_END: "End",
    curses.KEY_ENTER: "Enter", curses.KEY_BACKSPACE: "Backspace", curses.KEY_RESIZE: "Resize",
}


def key_name(key) -> str:
    """Normalize a curses get_wch() result to the names used in views.BINDINGS."""
    if isinstance(key, int):
        return SPECIAL_KEYS.get(key, f"#{key}")
    if key in ("\n", "\r"):
        return "Enter"
    if key == "\x1b":
        return "Esc"
    if key in ("\x7f", "\x08"):
        return "Backspace"
    if key == " ":
        return "Space"
    if len(key) == 1 and ord(key) < 32:
        return "^" + chr(ord(key) + 64)
    return key


def put(win, y: int, x: int, s: str, attr: int = 0):
    """Write `s` clipped to the window; never the bottom-right cell; ignore curses errors."""
    h, w = win.getmaxyx()
    if not (0 <= y < h and 0 <= x < w):
        return
    cols = w - x - (1 if y == h - 1 else 0)
    if cols <= 0:
        return
    try:
        win.addstr(y, x, text.fit(s, cols), attr)
    except curses.error:
        pass


def breadcrumb(parts: list[str], cols: int) -> str:
    """Join the view titles, dropping the oldest ones first so the current view stays visible."""
    for start in range(len(parts)):
        crumb = ("… › " if start else "") + " › ".join(parts[start:])
        if text.width(crumb) <= cols:
            return crumb
    return parts[-1]


def copy_to_clipboard(s: str) -> bool:
    for cmd in (["pbcopy"], ["wl-copy"], ["xclip", "-selection", "clipboard"]):
        if shutil.which(cmd[0]):
            try:
                subprocess.run(cmd, input=s.encode(), timeout=2, check=True, capture_output=True)
                return True
            except (OSError, subprocess.SubprocessError):
                return False
    return False


class App:
    def __init__(self, corpus: Corpus, labels: LabelStore | None = None, ask=None):
        self.corpus, self.labels = corpus, labels
        self.ask = ask or (lambda label: None)  # prompt(label) -> str | None; set by run()
        self.stack = ViewStack()
        self.message = ""
        self.body_h, self.body_w = MIN_H - 2, MIN_W
        self.running = True
        self.stack.push(self.mailbox_list())
        if labels and labels.unknown:
            self.message = f"{labels.unknown:,} label records for unknown emails ignored"

    # --- list builders ---------------------------------------------------------

    def mailbox_list(self) -> ListView:
        return ListView("mailboxes", "mailboxes", self.corpus.mailboxes(),
                        render=lambda item, cols: text.fit(f"  {item[0]:<24}{item[1]:>10,}", cols),
                        match=lambda item: item[0])

    def folder_list(self, user: str) -> ListView:
        return ListView("folders", user, [(user, f, n) for f, n in self.corpus.folders(user)],
                        render=lambda item, cols: text.fit(f"  {item[1]:<{max(cols - 14, 10)}}{item[2]:>10,}", cols),
                        match=lambda item: item[1])

    def message_list(self, title: str, ids: list[str]) -> ListView:
        return ListView("messages", title, ids, render=self.message_row, match=self.message_match)

    def copies_list(self, message_id: str) -> ListView:
        rows = [(u, f, message_id) for u, f in self.corpus.copies(message_id)]
        return ListView("copies", "copies", rows, render=lambda item, cols: text.fit(f"  {item[0]}/{item[1]}", cols),
                        match=lambda item: f"{item[0]}/{item[1]}")

    def message_row(self, message_id: str, cols: int) -> str:
        e = self.corpus.email(message_id)
        mark = "*" if self.labels and self.labels.has(message_id) else " "
        sender_w = 26
        subject_w = max(cols - 12 - 2 - sender_w - 2, 1)
        return (f"{format_date(e['date'], '%Y-%m-%d'):<10}  {mark} "
                f"{text.fit(e['from'] or '(no sender)', sender_w)}  "
                f"{text.fit(e['subject'] or '(no subject)', subject_w)}")

    def message_match(self, message_id: str) -> str:
        e = self.corpus.email(message_id)
        return f"{e['from']} {e['subject']}"

    # --- actions ---------------------------------------------------------------

    def handle(self, key: str):
        if key == "Resize":
            return
        view = self.stack.top
        action = lookup(key, view.context)
        if action == "label_filter" and self.labels is None:
            self.message = "no labels loaded (start with --labels FILE)"
            return
        if action:
            self.message = ""
            getattr(self, f"act_{action}")()

    def act_quit(self):
        self.running = False

    def act_back(self):
        if not self.stack.pop():
            self.running = False

    def act_redraw(self):
        pass

    def act_help(self):
        if not isinstance(self.stack.top, HelpView):
            self.stack.push(HelpView())

    def act_down(self):
        self._move(1)

    def act_up(self):
        self._move(-1)

    def act_page_down(self):
        self._page(1)

    def act_page_up(self):
        self._page(-1)

    def act_home(self):
        self.stack.top.home()

    def act_end(self):
        v = self.stack.top
        v.end() if isinstance(v, ListView) else v.end(self.body_h, self.body_w)

    def _move(self, delta):
        v = self.stack.top
        v.move(delta) if isinstance(v, ListView) else v.move(delta, self.body_h, self.body_w)

    def _page(self, direction):
        v = self.stack.top
        v.page(direction, self.body_h) if isinstance(v, ListView) else v.page(direction, self.body_h, self.body_w)

    def act_open(self):
        v = self.stack.top
        item = v.selected()
        if item is None:
            return
        if v.kind == "mailboxes":
            self.stack.push(self.folder_list(item[0]))
        elif v.kind == "folders":
            user, folder, _ = item
            self.stack.push(self.message_list(f"{user} › {folder}", self.corpus.folder_messages(user, folder)))
        elif v.kind == "messages":
            self.stack.push(ReaderView(self.corpus, item, origin=v, labels=self.labels))
        elif v.kind == "copies":
            user, folder, message_id = item
            view = self.message_list(f"{user} › {folder}", self.corpus.folder_messages(user, folder))
            view.select(message_id)
            self.stack.push(view)

    def act_filter(self):
        v = self.stack.top
        s = self.ask("filter: ")
        if s is not None:
            v.set_filter(s)

    def act_sort(self):
        self.stack.top.toggle_sort()

    def act_search(self):
        s = self.ask("search: ")
        if s:
            self.search(s)

    def search(self, s: str):
        try:
            ids = self.corpus.search(parse_query(s))
        except ValueError as e:
            self.message = str(e)
            return
        if not ids:
            self.message = "no emails match"
            return
        self.stack.push(self.message_list(f"search: {s}", ids))

    def act_label_filter(self):
        s = self.ask("labels: ")
        if s:
            self.label_filter(s)

    def label_filter(self, s: str):
        try:
            ids = self.labels.filter(parse_label_filter(s, self.labels.questions))
        except ValueError as e:
            self.message = str(e)
            return
        if not ids:
            self.message = "no labeled emails match"
            return
        self.stack.push(self.message_list(f"labels: {s}", ids))

    # reader actions

    def act_raw(self):
        self.stack.top.toggle_raw()

    def act_next(self):
        self._neighbor(1)

    def act_prev(self):
        self._neighbor(-1)

    def _neighbor(self, step):
        r = self.stack.top
        message_id = r.neighbor(step)
        if message_id is None:
            self.message = "no more emails in this list"
            return
        self.stack.replace(ReaderView(self.corpus, message_id, origin=r.origin, labels=self.labels))

    def act_thread(self):
        r = self.stack.top
        view = self.message_list(f"conversation: {r.title}", self.corpus.thread(r.message_id))
        view.select(r.message_id)
        self.stack.push(view)

    def act_sender(self):
        r = self.stack.top
        sender = r.email["from"]
        if not sender:
            self.message = "this email has no sender"
            return
        view = self.message_list(f"from: {sender}", self.corpus.by_sender(sender))
        view.select(r.message_id)
        self.stack.push(view)

    def act_copies(self):
        self.stack.push(self.copies_list(self.stack.top.message_id))

    def act_yank(self):
        message_id = self.stack.top.message_id
        self.message = f"copied {message_id}" if copy_to_clipboard(message_id) else f"message id: {message_id}"

    # --- drawing -----------------------------------------------------------------

    def draw(self, win):
        h, w = win.getmaxyx()
        win.erase()
        if h < MIN_H or w < MIN_W:
            msg = f"Enlarge the terminal to at least {MIN_W}x{MIN_H} (now {w}x{h})"
            put(win, h // 2, max((w - len(msg)) // 2, 0), msg)
            return
        self.body_h, self.body_w = h - 2, w
        put(win, 0, 0, " " + breadcrumb([v.breadcrumb() for v in self.stack.views], w - 2), curses.A_REVERSE)
        for i, (row, highlighted) in enumerate(self.stack.top.rows(self.body_h, w)):
            put(win, 1 + i, 0, row, curses.A_REVERSE if highlighted else 0)
        put(win, h - 1, 0, " " + (self.message or self.stack.top.status()), curses.A_BOLD)


class CursesPrompt:
    """Single-line input on the status line, with per-label history."""

    def __init__(self, stdscr):
        self.stdscr = stdscr
        self.history: dict[str, list[str]] = {}

    def __call__(self, label: str) -> str | None:
        history = self.history.setdefault(label, [])
        buf, pos = "", len(history)
        h, w = self.stdscr.getmaxyx()
        curses.curs_set(1)
        try:
            while True:
                line = label + buf
                put(self.stdscr, h - 1, 0, line)
                self.stdscr.move(h - 1, min(text.width(line), w - 2))
                key = key_name(self.stdscr.get_wch())
                if key == "Enter":
                    if buf.strip():
                        history.append(buf)
                    return buf
                if key == "Esc":
                    return None
                if key == "Backspace":
                    buf = buf[:-1]
                elif key in ("Up", "Down") and history:
                    pos = max(0, min(pos + (-1 if key == "Up" else 1), len(history)))
                    buf = history[pos] if pos < len(history) else ""
                elif len(key) == 1 or key == "Space":
                    buf += " " if key == "Space" else key
        finally:
            curses.curs_set(0)


def _main(stdscr, app: App):
    curses.curs_set(0)
    stdscr.keypad(True)
    app.ask = CursesPrompt(stdscr)
    while app.running:
        app.draw(stdscr)
        stdscr.refresh()
        key = key_name(stdscr.get_wch())
        if key == "Resize":
            curses.update_lines_cols()
        app.handle(key)


def run(data_dir: Path, label_files: list[Path]) -> int:
    print("Loading corpus …", file=sys.stderr)
    corpus = Corpus.load(data_dir)
    labels = LabelStore.load(label_files, corpus.emails.index) if label_files else None
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        raise ValueError("jevron browse needs an interactive terminal")
    app = App(corpus, labels)
    locale.setlocale(locale.LC_ALL, "")
    os.environ.setdefault("ESCDELAY", "25")
    curses.wrapper(_main, app)
    return 0
