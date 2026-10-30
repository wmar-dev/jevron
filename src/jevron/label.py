"""Ask Jev questions about many emails concurrently, with resumable JSONL output.

Each output line is one email:
    {"message_id": ..., "model": ..., "usage": {...}, "answers": {name: answer}}
or, if the request failed:
    {"message_id": ..., "error": "..."}
Re-running with the same output file skips emails that already have answers.
"""

import asyncio
import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

import pandas as pd
from typesafe_sdk import (
    AsyncTypeSafeClient,
    ChoiceAnswer,
    NoulAnswer,
    ScoreAnswer,
    TypeSafeAuthenticationError,
    TypeSafeError,
    TypeSafePermissionDeniedError,
)

from jevron.corpus import to_state

# Errors that will fail every request, so the run stops instead of recording them per email.
FATAL = (TypeSafeAuthenticationError, TypeSafePermissionDeniedError)


@dataclass
class Summary:
    done: int = 0
    errors: int = 0
    skipped: int = 0
    input_tokens: int = 0
    output_tokens: int = 0


def completed_ids(out: Path) -> set[str]:
    if not out.exists():
        return set()
    with open(out) as f:
        return {r["message_id"] for r in map(json.loads, f) if "error" not in r}


async def ask_one(client: AsyncTypeSafeClient, row, questions: dict, max_chars: int | None) -> dict:
    try:
        response = await client.system_one(state=to_state(row, max_chars), questions=questions)
    except FATAL:
        raise
    except TypeSafeError as e:
        return {"message_id": row["message_id"], "error": f"{type(e).__name__}: {e}"}
    return {
        "message_id": row["message_id"],
        "model": response.model,
        "usage": response.usage.model_dump(),
        "answers": {name: answer.model_dump(mode="json") for name, answer in response.answers.items()},
    }


async def label(
    emails: pd.DataFrame,
    questions: dict,
    client: AsyncTypeSafeClient,
    out: Path | None = None,
    concurrency: int = 8,
    max_chars: int | None = 4000,
    on_record: Callable[[dict, Summary], None] | None = None,
) -> Summary:
    """Label `emails`, appending one JSON line per email to `out` (if given)."""
    summary = Summary()
    skip = completed_ids(out) if out else set()
    todo = emails[~emails["message_id"].isin(skip)]
    summary.skipped = len(emails) - len(todo)
    rows: Iterable = iter(todo.to_dict("records"))
    sink = open(out, "a") if out else None

    async def worker():
        for row in rows:
            record = await ask_one(client, row, questions, max_chars)
            if "error" in record:
                summary.errors += 1
            else:
                summary.done += 1
                summary.input_tokens += record["usage"].get("input_tokens") or 0
                summary.output_tokens += record["usage"].get("output_tokens") or 0
            if sink:
                sink.write(json.dumps(record) + "\n")
                sink.flush()
            if on_record:
                on_record(record, summary)

    try:
        async with asyncio.TaskGroup() as tg:
            for _ in range(concurrency):
                tg.create_task(worker())
    except* FATAL as group:
        raise group.exceptions[0] from None
    finally:
        if sink:
            sink.close()
    return summary


def flatten(answers: dict) -> dict:
    """One column per question (the choice, score or yes-probability), plus
    `<name>_confidence` for choice and score questions."""
    flat = {}
    for name, answer in answers.items():
        match answer["type"]:
            case "choice":
                flat[name] = answer["choice"]
                flat[f"{name}_confidence"] = answer["confidence"]
            case "score":
                flat[name] = answer["score"]
                flat[f"{name}_confidence"] = answer["confidence"]
            case "noul":
                flat[name] = answer["noul"]
    return flat


def format_answer(answer: ChoiceAnswer | ScoreAnswer | NoulAnswer | dict) -> str:
    a = answer if isinstance(answer, dict) else answer.model_dump(mode="json")
    match a["type"]:
        case "choice":
            return f"{a['choice']}  (confidence {a['confidence']:.2f})"
        case "score":
            top = max(int(level) for level in a["legend"])
            return f"{a['score']:.2f} on 0–{top}  (confidence {a['confidence']:.2f})"
        case "noul":
            return f"{a['noul']:.2f}  (probability yes)"
    return json.dumps(a)


def read_results(path: Path) -> pd.DataFrame:
    """Results file as a DataFrame: message_id, model, error, plus flattened answers."""
    rows = []
    with open(path) as f:
        for record in map(json.loads, f):
            row = {"message_id": record["message_id"], "model": record.get("model"), "error": record.get("error")}
            row.update(flatten(record.get("answers", {})))
            rows.append(row)
    # A failed email may be retried and succeed later in the file; keep its latest record.
    return pd.DataFrame(rows).drop_duplicates("message_id", keep="last")
