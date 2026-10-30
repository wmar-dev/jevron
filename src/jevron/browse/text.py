"""Display-safe text: cleaning, width, fitting and wrapping.

Cleaning is for display only; the stored corpus is never modified.
"""

import textwrap
import unicodedata

TAB = "    "


def _clean_char(ch: str) -> str:
    code = ord(ch)
    if ch == "\n":
        return ch
    if ch == "\t":
        return TAB
    if code < 0x20 or code == 0x7F:
        return "^" + chr(code ^ 0x40)  # \x1b -> ^[, \x0c -> ^L, \x7f -> ^?
    if 0xD800 <= code <= 0xDFFF:  # lone surrogate
        return "�"
    if 0x80 <= code < 0xA0:  # C1 controls
        return "�"
    return ch


def clean(s: str) -> str:
    """Make `s` safe to draw: no control characters other than newline."""
    if s is None:
        return ""
    s = s.replace("\r\n", "\n").replace("\r", "\n")
    if s.isprintable() and "\t" not in s:
        return s
    return "".join(_clean_char(ch) for ch in s)


def char_width(ch: str) -> int:
    if unicodedata.combining(ch):
        return 0
    return 2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1


def width(s: str) -> int:
    """Number of terminal columns `s` occupies."""
    if s.isascii():
        return len(s)
    return sum(char_width(ch) for ch in s)


def fit(s: str, cols: int) -> str:
    """Truncate (with …) or pad `s` to exactly `cols` columns."""
    if cols <= 0:
        return ""
    s = clean(s).replace("\n", " ")
    if width(s) <= cols:
        return s + " " * (cols - width(s))
    out, used = [], 0
    for ch in s:
        w = char_width(ch)
        if used + w > cols - 1:
            break
        out.append(ch)
        used += w
    out.append("…")
    used += 1
    return "".join(out) + " " * (cols - used)


def wrap(s: str, cols: int) -> list[str]:
    """Clean `s` and wrap it into display lines of at most `cols` characters, keeping blank lines."""
    cols = max(cols, 1)
    lines = []
    for line in clean(s).split("\n"):
        if len(line) <= cols:
            lines.append(line)
        else:
            lines.extend(textwrap.wrap(line, cols, replace_whitespace=False, drop_whitespace=False,
                                       break_on_hyphens=False) or [""])
    return lines
