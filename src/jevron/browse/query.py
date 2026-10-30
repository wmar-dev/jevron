"""Parse the search prompt and the label-filter prompt."""

import re
import shlex
from dataclasses import dataclass, fields

import pandas as pd

# prompt token -> Query field (and the matching `jevron emails` option)
KEYS = {"from": "sender", "to": "recipient", "since": "since", "until": "until", "user": "user", "folder": "folder"}


@dataclass
class Query:
    text: str | None = None
    sender: str | None = None
    recipient: str | None = None
    since: str | None = None
    until: str | None = None
    user: str | None = None
    folder: str | None = None

    def is_empty(self) -> bool:
        return all(getattr(self, f.name) is None for f in fields(self))


def parse_query(s: str) -> Query:
    """`raptor since:2001-06-01 from:enron.com` -> Query. Unknown `key:` tokens stay in the text."""
    try:
        tokens = shlex.split(s)
    except ValueError:  # unbalanced quotes
        tokens = s.split()
    q, words = Query(), []
    for token in tokens:
        key, sep, value = token.partition(":")
        if sep and key.lower() in KEYS and value:
            field = KEYS[key.lower()]
            if field in ("since", "until"):
                try:
                    pd.Timestamp(value)
                except ValueError:
                    raise ValueError(f"invalid date: {value}") from None
            setattr(q, field, value)
        else:
            words.append(token)
    q.text = " ".join(words) or None
    if q.is_empty():
        raise ValueError("empty search")
    return q


@dataclass
class LabelFilter:
    question: str
    op: str  # ">=", "<=" or "="
    value: float | str


FILTER = re.compile(r"^\s*([\w.-]+)\s*(>=|<=|=)\s*(.+?)\s*$")


def parse_label_filter(s: str, questions: dict[str, str]) -> LabelFilter:
    """`spe>=0.8`, `urgency<=1`, `topic=trading`. `questions` maps column name -> kind
    ("choice", "score", "noul" or "number" for *_confidence columns)."""
    m = FILTER.match(s)
    if not m:
        raise ValueError("expected QUESTION>=NUMBER, QUESTION<=NUMBER or QUESTION=LABEL")
    name, op, value = m.groups()
    if name not in questions:
        raise ValueError(f"unknown question {name!r}; loaded: {', '.join(sorted(questions))}")
    kind = questions[name]
    if op == "=":
        if kind != "choice":
            raise ValueError(f"{name} is a {kind} question; use >= or <=")
        return LabelFilter(name, op, value)
    if kind == "choice":
        raise ValueError(f"{name} is a choice question; use {name}=LABEL")
    try:
        return LabelFilter(name, op, float(value))
    except ValueError:
        raise ValueError(f"{value!r} is not a number") from None
