"""View state, navigation and key bindings (no curses)."""

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from jevron import label
from jevron.browse import text


# --- key bindings ------------------------------------------------------------
# Key names are produced by app.key_name(); contexts are "list", "reader", "help" or "any".
# This table drives both dispatch and the help screen, so the two can't drift.


@dataclass(frozen=True)
class Binding:
    keys: tuple[str, ...]
    context: str
    description: str
    action: str


BINDINGS = [
    Binding(("?",), "any", "help", "help"),
    Binding(("/",), "any", "search: text from: to: since: until: user: folder:", "search"),
    Binding(("L",), "any", "filter by Jev label, e.g. spe>=0.8 or topic=trading (needs --labels)", "label_filter"),
    Binding(("q", "Esc", "Left", "h"), "any", "back (quit from the first view)", "back"),
    Binding(("Q",), "any", "quit", "quit"),
    Binding(("^L",), "any", "redraw", "redraw"),
    Binding(("Down", "j"), "list", "next row", "down"),
    Binding(("Up", "k"), "list", "previous row", "up"),
    Binding(("PgDn", "Space", "^F"), "list", "page down", "page_down"),
    Binding(("PgUp", "b", "^B"), "list", "page up", "page_up"),
    Binding(("Home", "g"), "list", "first", "home"),
    Binding(("End", "G"), "list", "last", "end"),
    Binding(("Enter", "Right", "l"), "list", "open", "open"),
    Binding(("f",), "list", "filter this list", "filter"),
    Binding(("o",), "list", "reverse sort order", "sort"),
    Binding(("Down", "j"), "reader", "scroll down", "down"),
    Binding(("Up", "k"), "reader", "scroll up", "up"),
    Binding(("PgDn", "Space", "^F"), "reader", "page down", "page_down"),
    Binding(("PgUp", "b", "^B"), "reader", "page up", "page_up"),
    Binding(("Home", "g"), "reader", "top", "home"),
    Binding(("End", "G"), "reader", "bottom", "end"),
    Binding(("n",), "reader", "next email in list", "next"),
    Binding(("p",), "reader", "previous email in list", "prev"),
    Binding(("r",), "reader", "toggle raw original file", "raw"),
    Binding(("t",), "reader", "conversation (same subject)", "thread"),
    Binding(("s",), "reader", "more from this sender", "sender"),
    Binding(("c",), "reader", "mailboxes/folders holding a copy", "copies"),
    Binding(("y",), "reader", "copy message id", "yank"),
    Binding(("Down", "j"), "help", "scroll down", "down"),
    Binding(("Up", "k"), "help", "scroll up", "up"),
    Binding(("PgDn", "Space"), "help", "page down", "page_down"),
    Binding(("PgUp", "b"), "help", "page up", "page_up"),
]


def lookup(key: str, context: str) -> str | None:
    """Action for `key` in `context`; view-specific bindings win over global ones."""
    for b in BINDINGS:
        if b.context == context and key in b.keys:
            return b.action
    for b in BINDINGS:
        if b.context == "any" and key in b.keys:
            return b.action
    return None


# --- views -------------------------------------------------------------------


@dataclass
class ListView:
    """A scrollable, filterable list. `render(item, cols)` draws a row; `match(item)` is the
    text the in-view filter searches."""

    kind: str
    title: str
    items: list
    render: Callable[[object, int], str]
    match: Callable[[object], str] = str
    cursor: int = 0
    top: int = 0
    filter_text: str = ""
    sort_desc: bool = True
    _visible: list | None = field(default=None, repr=False)

    context = "list"

    @property
    def visible(self) -> list:
        if self._visible is None:
            items = self.items if self.sort_desc else self.items[::-1]
            if self.filter_text:
                needle = self.filter_text.lower()
                items = [i for i in items if needle in self.match(i).lower()]
            self._visible = items
        return self._visible

    def selected(self):
        return self.visible[self.cursor] if self.visible else None

    def move(self, delta: int):
        self.cursor = max(0, min(self.cursor + delta, len(self.visible) - 1)) if self.visible else 0

    def page(self, direction: int, height: int):
        self.move(direction * max(height - 1, 1))

    def home(self):
        self.cursor = 0

    def end(self):
        self.cursor = max(len(self.visible) - 1, 0)

    def select(self, item):
        """Put the cursor on `item` if it is visible."""
        try:
            self.cursor = self.visible.index(item)
        except ValueError:
            pass

    def set_filter(self, s: str):
        current = self.selected()
        self.filter_text, self._visible, self.cursor, self.top = s.strip(), None, 0, 0
        self.select(current)

    def toggle_sort(self):
        current = self.selected()
        self.sort_desc, self._visible = not self.sort_desc, None
        self.select(current)

    def scroll_into_view(self, height: int):
        if self.cursor < self.top:
            self.top = self.cursor
        elif self.cursor >= self.top + height:
            self.top = self.cursor - height + 1
        self.top = max(0, min(self.top, max(len(self.visible) - height, 0)))

    def breadcrumb(self) -> str:
        crumb = f"{self.title} ({len(self.visible):,})"
        return crumb + (f" [filter: {self.filter_text}]" if self.filter_text else "")

    def status(self) -> str:
        n = len(self.visible)
        pos = f"{self.cursor + 1:,}/{n:,}" if n else "empty"
        return f"{pos}   Enter open  f filter  o sort  / search  ? help  q back"

    def rows(self, height: int, cols: int) -> list[tuple[str, bool]]:
        """(text, highlighted) for each visible row."""
        self.scroll_into_view(height)
        if not self.visible:
            return [(text.fit("  (empty)", cols), False)]
        end = min(self.top + height, len(self.visible))
        return [(self.render(self.visible[i], cols), i == self.cursor) for i in range(self.top, end)]


class TextView:
    """A scrollable block of lines, wrapped to the window width on demand."""

    context = "reader"

    def __init__(self, title: str):
        self.title = title
        self.scroll = 0
        self._cache: tuple | None = None

    def source(self) -> str:
        raise NotImplementedError

    def cache_key(self) -> tuple:
        return ()

    def lines(self, cols: int) -> list[str]:
        key = (cols, *self.cache_key())
        if self._cache is None or self._cache[0] != key:
            self._cache = (key, text.wrap(self.source(), cols))
        return self._cache[1]

    def clamp(self, height: int, cols: int):
        self.scroll = max(0, min(self.scroll, max(len(self.lines(cols)) - height, 0)))

    def move(self, delta: int, height: int, cols: int):
        self.scroll += delta
        self.clamp(height, cols)

    def page(self, direction: int, height: int, cols: int):
        self.move(direction * max(height - 1, 1), height, cols)

    def home(self):
        self.scroll = 0

    def end(self, height: int, cols: int):
        self.scroll = len(self.lines(cols))
        self.clamp(height, cols)

    def breadcrumb(self) -> str:
        return self.title

    def status(self) -> str:
        return "? help  q back"

    def rows(self, height: int, cols: int) -> list[tuple[str, bool]]:
        self.clamp(height, cols)
        return [(text.fit(line, cols), False) for line in self.lines(cols)[self.scroll:self.scroll + height]]


def format_date(date, fmt="%Y-%m-%d %H:%M UTC") -> str:
    return "(no date)" if pd.isna(date) else date.strftime(fmt)


class ReaderView(TextView):
    """One email: headers, optional Jev labels, and the full body (or the raw file)."""

    def __init__(self, corpus, message_id: str, origin: ListView | None = None, labels=None):
        super().__init__(title="")
        self.corpus, self.message_id, self.origin, self.labels = corpus, message_id, origin, labels
        self.raw = False
        self.title = text.clean(self.email["subject"]) or "(no subject)"

    @property
    def email(self):
        return self.corpus.email(self.message_id)

    def cache_key(self) -> tuple:
        return (self.raw,)

    def toggle_raw(self):
        self.raw, self.scroll = not self.raw, 0

    def headers(self) -> list[str]:
        e = self.email
        copies = self.corpus.copies(self.message_id)
        lines = [
            f"From:       {e['from'] or '(no sender)'}" + (f"  ({e['x_from']})" if e["x_from"] else ""),
            f"To:         {', '.join(e['to']) or '-'}",
        ]
        if len(e["cc"]):
            lines.append(f"Cc:         {', '.join(e['cc'])}")
        lines += [
            f"Date:       {format_date(e['date'])}",
            f"Subject:    {e['subject'] or '(no subject)'}",
            f"Message-ID: {self.message_id}",
            f"Copies:     {len(copies)} in " + ", ".join(f"{u}/{f}" for u, f in copies),
        ]
        return lines

    def label_lines(self) -> list[str]:
        if not self.labels:
            return []
        lines = []
        for source, record in self.labels.for_email(self.message_id):
            lines.append(f"Labels (model {record.get('model') or '?'}, {source}):")
            if record.get("error"):
                lines.append(f"  ERROR {record['error']}")
            for name, answer in record.get("answers", {}).items():
                lines.append(f"  {name}: {label.format_answer(answer)}")
        return lines

    def source(self) -> str:
        if self.raw:
            try:
                return Path(self.email["path"]).read_bytes().decode("cp1252", errors="replace")
            except OSError as e:
                return f"(cannot read original file: {e})"
        return "\n".join(self.headers() + self.label_lines() + ["", self.email["body"]])

    def neighbor(self, step: int) -> str | None:
        """Message id `step` rows away in the list this email was opened from."""
        if self.origin is None:
            return None
        visible = self.origin.visible
        try:
            i = visible.index(self.message_id) + step
        except ValueError:
            return None
        if 0 <= i < len(visible):
            self.origin.cursor = i
            return visible[i]
        return None

    def status(self) -> str:
        mode = "raw  " if self.raw else ""
        return f"{mode}line {self.scroll + 1:,}   t thread  s sender  c copies  r raw  y copy id  n/p next/prev  q back"


class HelpView(TextView):
    """Key bindings, generated from BINDINGS."""

    context = "help"

    def __init__(self):
        super().__init__(title="help")

    def source(self) -> str:
        sections = {"any": "Everywhere", "list": "Lists", "reader": "Reader"}
        out = ["jevron browse: read-only browser for the Enron corpus", ""]
        for context, heading in sections.items():
            out.append(heading)
            for b in BINDINGS:
                if b.context == context:
                    out.append(f"  {', '.join(b.keys):<22} {b.description}")
            out.append("")
        return "\n".join(out)


class ViewStack:
    def __init__(self):
        self.views: list = []

    def push(self, view):
        self.views.append(view)

    def pop(self) -> bool:
        """Drop the top view; False when nothing is left (time to quit)."""
        if self.views:
            self.views.pop()
        return bool(self.views)

    @property
    def top(self):
        return self.views[-1]

    def replace(self, view):
        self.views[-1] = view
