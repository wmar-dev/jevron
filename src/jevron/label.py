"""Ask Jev questions about many emails concurrently, with resumable JSONL output.

Each output line is one email:
    {"message_id": ..., "model": ..., "usage": {...}, "answers": {name: answer}, "questions": fingerprint}
or, if the request failed:
    {"message_id": ..., "error": "...", "questions": fingerprint}
Re-running with the same output file skips emails that already have answers. A file is
only resumed with the questions that produced it, and only while Jev answers with the
same model, so each file holds one question set answered by one model.
"""

import asyncio
import hashlib
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


class ModelChanged(ValueError):
    """Jev answered with a different model than the rest of the results file."""


def fingerprint(questions: dict) -> str:
    """Short hash of a question set (names, types, instructions and criteria)."""
    spec = {name: q if isinstance(q, dict) else q.model_dump(mode="json", exclude_none=True)
            for name, q in questions.items()}
    return hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest()[:12]


@dataclass
class Resume:
    done: set[str]
    model: str | None


def resume(out: Path, questions: dict) -> Resume:
    """Emails already answered in `out`, and the model that answered them. Raises ValueError
    if `out` holds answers to other questions or from more than one model."""
    if not out.exists():
        return Resume(set(), None)
    want = fingerprint(questions)
    done, models = set(), set()
    for message_id, record in read_records(out).items():
        if "error" in record:
            continue
        if record.get("questions") != want:
            raise ValueError(
                f"{out} was labeled with a different question set "
                f"(it answers {', '.join(sorted(record.get('answers', {})))}; now asking {', '.join(sorted(questions))}, "
                f"fingerprint {record.get('questions')} vs {want}). Label into a new --out file, "
                "or restore the original questions.")
        done.add(message_id)
        models.add(record.get("model"))
    if len(models) > 1:
        raise ValueError(f"{out} mixes answers from {', '.join(sorted(map(str, models)))}; "
                         "label into a new --out file")
    return Resume(done, next(iter(models), None))


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
    prior = resume(out, questions) if out else Resume(set(), None)
    model = prior.model
    tag = fingerprint(questions)
    todo = emails[~emails["message_id"].isin(prior.done)]
    summary.skipped = len(emails) - len(todo)
    rows: Iterable = iter(todo.to_dict("records"))
    sink = open(out, "a") if out else None

    async def worker():
        nonlocal model
        for row in rows:
            record = await ask_one(client, row, questions, max_chars) | {"questions": tag}
            if "error" in record:
                summary.errors += 1
            else:
                if out and model is None:
                    model = record["model"]
                elif out and record["model"] != model:
                    raise ModelChanged(
                        f"Jev answered with {record['model']}, but {out} holds answers from {model}. "
                        f"Pin the model with --model {model}, or label into a new --out file.")
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
    except* (*FATAL, ModelChanged) as group:
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


def read_records(path: Path) -> dict[str, dict]:
    """Results file as {message_id: record}. A failed email may be retried and succeed
    later in the file, so the latest record for each email wins."""
    records = {}
    with open(path) as f:
        for lineno, line in enumerate(f, 1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
                records[record["message_id"]] = record
            except (json.JSONDecodeError, KeyError, TypeError) as e:
                raise ValueError(f"{path}:{lineno}: {e!r}") from None
    return records


def read_results(path: Path) -> pd.DataFrame:
    """Results file as a DataFrame: message_id, model, error, plus flattened answers."""
    rows = []
    for record in read_records(path).values():
        row = {"message_id": record["message_id"], "model": record.get("model"), "error": record.get("error")}
        row.update(flatten(record.get("answers", {})))
        rows.append(row)
    return pd.DataFrame(rows)
