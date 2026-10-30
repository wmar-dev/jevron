"""Load Jev question sets from TOML files or command-line flags.

A question file has one table per question, named by the question:

    [topic]
    type = "choice"
    instructions = "What is this email mainly about?"
    criteria = { trading = "Energy trading or deals", other = "Anything else" }

    [urgency]
    type = "score"
    instructions = "How urgent is this email?"
    criteria = ["not urgent", "somewhat urgent", "very urgent"]

    [personal]
    type = "noul"
    instructions = "The email is personal rather than business correspondence."
"""

import tomllib
from pathlib import Path

from typesafe_sdk import Choice, Noul, Score

TYPES = {"choice": Choice, "score": Score, "noul": Noul}


def from_dict(spec: dict) -> dict:
    questions = {}
    for name, fields in spec.items():
        fields = dict(fields)
        kind = fields.pop("type", None)
        if kind not in TYPES:
            raise ValueError(f"question {name!r}: type must be one of {sorted(TYPES)}, got {kind!r}")
        try:
            questions[name] = TYPES[kind](**fields)
        except Exception as e:
            raise ValueError(f"question {name!r}: {e}") from e
    if not questions:
        raise ValueError("no questions defined")
    return questions


def load(path: Path) -> dict:
    with open(path, "rb") as f:
        return from_dict(tomllib.load(f))


def inline_nouls(specs: list[str]) -> dict:
    """Parse `NAME=STATEMENT` flags into Noul questions."""
    questions = {}
    for spec in specs:
        name, sep, statement = spec.partition("=")
        if not sep or not name.strip() or not statement.strip():
            raise ValueError(f"--noul expects NAME=STATEMENT, got {spec!r}")
        questions[name.strip()] = Noul(instructions=statement.strip())
    return questions
