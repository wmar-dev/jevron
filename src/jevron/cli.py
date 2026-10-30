"""`jevron` command line: build the Enron corpus and label it with Jev."""

import argparse
import asyncio
import json
import sys
from pathlib import Path

import pandas as pd

from jevron import corpus, label, questions

META = ["message_id", "date", "from", "subject", "user", "folder"]


def eprint(*args, **kwargs):
    print(*args, file=sys.stderr, **kwargs)


# --- corpus commands -------------------------------------------------------


def cmd_ingest(args):
    out, locs = corpus.emails_path(args.data_dir), corpus.locations_path(args.data_dir)
    if out.exists() and locs.exists() and not args.force:
        eprint(f"{out} and {locs} already exist (use --force to rebuild)")
        return 0
    if not corpus.maildir(args.data_dir).exists() and not args.tarball.exists():
        eprint(f"tarball not found: {args.tarball} (pass --tarball)")
        return 1
    eprint(f"Extracting {args.tarball} (skipped if already extracted) ...")

    def progress(done, total):
        eprint(f"\r  parsed {done}/{total} mailboxes", end="", flush=True)

    emails, locations = corpus.build(args.tarball, args.data_dir, args.workers, progress)
    eprint(f"\nWrote {len(emails):,} distinct emails to {out} and {len(locations):,} file locations to {locs}")
    return 0


def cmd_stats(args):
    df = corpus.load(args.data_dir, columns=["date", "from", "user", "folder", "n_copies"])
    real = df["date"].between(pd.Timestamp("1998-01-01", tz="UTC"), pd.Timestamp("2003-01-01", tz="UTC"))
    print(f"distinct emails  {len(df):,}")
    print(f"files on disk    {df['n_copies'].sum():,}")
    print(f"mailboxes        {df['user'].nunique()}")
    print(f"senders          {df['from'].nunique():,}")
    print(f"date range       {df.loc[real, 'date'].min():%Y-%m-%d} .. {df.loc[real, 'date'].max():%Y-%m-%d}"
          f"  ({(~real).sum()} emails with implausible dates excluded)")
    print("\ntop folders (first copy of each email)")
    print(df["folder"].str.split("/").str[0].value_counts().head(10).to_string())
    return 0


def select(args, columns=None, default_limit=None) -> pd.DataFrame:
    df = corpus.load(args.data_dir, columns=columns)
    ids = list(args.id or [])
    if args.ids_file:
        ids += [line.strip() for line in open(args.ids_file) if line.strip()]
    return corpus.filter_emails(
        df,
        ids=ids or None,
        user=args.user,
        folder=args.folder,
        sender=args.sender,
        recipient=args.recipient,
        since=args.since,
        until=args.until,
        search=args.search,
        sample=args.sample,
        seed=args.seed,
        limit=args.limit if args.limit is not None else default_limit,
    )


def cmd_emails(args):
    df = select(args, default_limit=20)
    if args.format == "ids":
        print("\n".join(df["message_id"]))
    elif args.format == "jsonl":
        for row in df[META + ["to", "cc"]].to_dict("records"):
            row["date"] = None if pd.isna(row["date"]) else row["date"].isoformat()
            print(json.dumps(row, default=list))
    else:
        view = df[META].assign(date=df["date"].dt.strftime("%Y-%m-%d"))
        print(view.to_string(index=False, max_colwidth=60))
    eprint(f"{len(df):,} emails")
    return 0


def cmd_show(args):
    df = corpus.filter_emails(corpus.load(args.data_dir), ids=[args.message_id])
    if df.empty:
        eprint(f"no email with id {corpus.normalize_id(args.message_id)}")
        return 1
    row = df.iloc[0]
    if args.raw:
        print(Path(row["path"]).read_bytes().decode("cp1252", errors="replace"))
    else:
        print(corpus.to_state(row, args.max_chars, args.quoted))
    eprint(f"\n[{row['n_copies']} copies in: {', '.join(row['mailboxes'])}]")
    return 0


# --- Jev commands ------------------------------------------------------------


def load_questions(args) -> dict:
    qs = {}
    if args.questions:
        qs.update(questions.load(args.questions))
    if args.noul:
        qs.update(questions.inline_nouls(args.noul))
    if not qs:
        raise ValueError("no questions: pass --questions FILE and/or --noul NAME=STATEMENT")
    return qs


def client(args):
    from typesafe_sdk import AsyncTypeSafeClient

    return AsyncTypeSafeClient(model=args.model)


def cmd_ask(args):
    qs = load_questions(args)
    emails = select(args, default_limit=5)
    if emails.empty:
        eprint("no emails match")
        return 1

    def show(record, _summary):
        row = emails.set_index("message_id").loc[record["message_id"]]
        print(f"\n{record['message_id']}  {row['date']:%Y-%m-%d}  {row['from']}")
        print(f"  subject: {row['subject'][:100]}")
        if "error" in record:
            print(f"  ERROR {record['error']}")
        for name, answer in record.get("answers", {}).items():
            print(f"  {name}: {label.format_answer(answer)}")

    async def run():
        async with client(args) as c:
            return await label.label(emails, qs, c, None, args.concurrency, args.max_chars, show)

    summary = asyncio.run(run())
    eprint(f"\n{summary.done} answered, {summary.errors} errors, {summary.input_tokens:,} input tokens")
    return 0 if not summary.errors else 2


def cmd_label(args):
    qs = load_questions(args)
    emails = select(args)
    skip = label.completed_ids(args.out)
    todo = emails[~emails["message_id"].isin(skip)]
    chars = sum(len(corpus.to_state(r, args.max_chars)) for r in todo.to_dict("records"))
    eprint(f"{len(emails):,} emails selected, {len(skip & set(emails['message_id'])):,} already in {args.out}, "
           f"{len(todo):,} to label")
    eprint(f"{len(qs)} questions: {', '.join(qs)}")
    eprint(f"~{chars // 4:,} input tokens of email text (rough estimate: characters / 4)")
    if args.dry_run or todo.empty:
        return 0

    def progress(_record, s):
        eprint(f"\r  {s.done + s.errors:,}/{len(todo):,} labeled, {s.errors} errors", end="", flush=True)

    async def run():
        async with client(args) as c:
            return await label.label(todo, qs, c, args.out, args.concurrency, args.max_chars, progress)

    summary = asyncio.run(run())
    eprint(f"\nDone: {summary.done:,} labeled, {summary.errors:,} errors "
           f"({summary.input_tokens:,} input / {summary.output_tokens:,} output tokens). Results in {args.out}")
    if summary.errors:
        eprint("Re-run the same command to retry failed emails.")
    return 0 if not summary.errors else 2


def cmd_export(args):
    results = label.read_results(args.results)
    meta = corpus.load(args.data_dir, columns=META + ["n_copies"])
    merged = meta.merge(results, on="message_id", how="inner")
    if args.out.suffix == ".parquet":
        merged.to_parquet(args.out, index=False)
    elif args.out.suffix == ".csv":
        merged.to_csv(args.out, index=False)
    else:
        eprint("--out must end in .csv or .parquet")
        return 1
    eprint(f"Wrote {len(merged):,} rows ({merged['error'].notna().sum()} with errors) to {args.out}")
    return 0


def cmd_browse(args):
    from jevron.browse import app

    return app.run(args.data_dir, args.labels or [])


def cmd_models(args):
    from typesafe_sdk import TypeSafeClient

    with TypeSafeClient() as c:
        for m in c.models.list().models:
            print(f"{m.name:20} {m.release_date}  {m.description}")
    return 0


# --- argument parsing --------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="jevron", description=__doc__)
    p.add_argument("--data-dir", type=Path, default=Path("data"), help="where the corpus lives (default: data)")
    sub = p.add_subparsers(dest="command", required=True)

    filters = argparse.ArgumentParser(add_help=False)
    g = filters.add_argument_group("email selection")
    g.add_argument("--id", action="append", help="message id (repeatable)")
    g.add_argument("--ids-file", type=Path, help="file with one message id per line")
    g.add_argument("--user", help="mailbox, e.g. lay-k")
    g.add_argument("--folder", help="top-level folder, e.g. sent or inbox")
    g.add_argument("--from", dest="sender", help="sender address contains")
    g.add_argument("--to", dest="recipient", help="any To/Cc/Bcc address contains")
    g.add_argument("--since", help="on or after date, e.g. 2001-08-01")
    g.add_argument("--until", help="before date")
    g.add_argument("--search", help="subject or body contains (case-insensitive)")
    g.add_argument("--sample", type=int, help="random sample of N matching emails")
    g.add_argument("--seed", type=int, default=0, help="random seed for --sample")
    g.add_argument("--limit", type=int, help="at most N emails (default: 20 for emails, 5 for ask, all for label)")

    jev = argparse.ArgumentParser(add_help=False)
    g = jev.add_argument_group("Jev")
    g.add_argument("--questions", "-q", type=Path, help="TOML question file (see questions/)")
    g.add_argument("--noul", action="append", metavar="NAME=STATEMENT", help="inline yes/no question (repeatable)")
    g.add_argument("--model", default=None, help="Jev model (default: TYPESAFE_DEFAULT_MODEL or the SDK default)")
    g.add_argument("--concurrency", type=int, default=8, help="parallel requests (default: 8)")
    g.add_argument("--max-chars", type=int, default=4000, help="truncate email bodies to N characters (default: 4000)")

    s = sub.add_parser("ingest", help="extract the tarball and build data/emails.parquet and data/locations.parquet")
    s.add_argument("--tarball", type=Path, default=corpus.DEFAULT_TARBALL)
    s.add_argument("--workers", type=int, help="parser processes (default: CPU count)")
    s.add_argument("--force", action="store_true", help="rebuild even if the parquet exists")
    s.set_defaults(func=cmd_ingest)

    s = sub.add_parser("stats", help="corpus summary")
    s.set_defaults(func=cmd_stats)

    s = sub.add_parser("emails", parents=[filters], help="list emails matching filters")
    s.add_argument("--format", choices=["table", "jsonl", "ids"], default="table")
    s.set_defaults(func=cmd_emails)

    s = sub.add_parser("show", help="print one email as Jev would see it")
    s.add_argument("message_id")
    s.add_argument("--raw", action="store_true", help="print the original file instead")
    s.add_argument("--quoted", action="store_true", help="keep quoted reply chains")
    s.add_argument("--max-chars", type=int, default=4000)
    s.set_defaults(func=cmd_show)

    s = sub.add_parser("ask", parents=[filters, jev], help="ask Jev about a few emails and print the answers")
    s.set_defaults(func=cmd_ask)

    s = sub.add_parser("label", parents=[filters, jev], help="label emails in bulk into a resumable JSONL file")
    s.add_argument("--out", "-o", type=Path, required=True, help="results file (.jsonl); appended to and resumed")
    s.add_argument("--dry-run", action="store_true", help="show what would be labeled, without calling Jev")
    s.set_defaults(func=cmd_label)

    s = sub.add_parser("export", help="join label results with email metadata into CSV or parquet")
    s.add_argument("results", type=Path)
    s.add_argument("--out", "-o", type=Path, required=True, help="output .csv or .parquet")
    s.set_defaults(func=cmd_export)

    s = sub.add_parser("browse", help="read-only terminal mail client for the corpus")
    s.add_argument("--labels", type=Path, action="append", metavar="FILE",
                   help="jevron label results to show and filter by (repeatable)")
    s.set_defaults(func=cmd_browse)

    s = sub.add_parser("models", help="list available Jev models")
    s.set_defaults(func=cmd_models)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (FileNotFoundError, ValueError) as e:
        eprint(f"error: {e}")
        return 1
    except Exception as e:
        from typesafe_sdk import TypeSafeError

        if isinstance(e, TypeSafeError):
            eprint(f"Jev error: {e}")
            return 1
        raise


if __name__ == "__main__":
    sys.exit(main())
