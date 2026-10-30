# Contract: `jevron browse` command

```text
jevron [--data-dir DIR] browse [--labels FILE]...
```

| Option | Default | Meaning |
| --- | --- | --- |
| `--data-dir DIR` | `data` | Global option shared with every subcommand. The browser reads `DIR/emails.parquet` and `DIR/locations.parquet` |
| `--labels FILE` | none | A `jevron label` results file (JSONL). Can be given more than once. Enables the label area and the `L` label filter |

## Exit behavior

| Situation | Exit code | Output (stderr) |
| --- | --- | --- |
| Normal quit | 0 | none |
| `emails.parquet` missing | 1 | `error: DIR/emails.parquet not found; run `jevron ingest` first` |
| `locations.parquet` missing (corpus ingested before this feature) | 1 | `error: DIR/locations.parquet not found; run `jevron ingest --force` to rebuild with folder locations` |
| `--labels` file missing or not valid JSONL | 1 | `error: cannot read labels from FILE: <reason>` |
| stdout is not a terminal | 1 | `error: jevron browse needs an interactive terminal` |
| Terminal smaller than 80×24 | stays running | A centered message inside the UI asks for a larger window. The UI redraws when the window is resized |

Errors must never leave the terminal in curses mode. Curses setup and teardown use
`curses.wrapper` or an equivalent `try`/`finally`.

## Guarantees

- No network access (FR-016). The browser never imports or constructs a TypeSafe client.
- No writes under `--data-dir` or to the `--labels` files (FR-017).

## Change to `jevron ingest`

- It writes `DIR/locations.parquet` in addition to `DIR/emails.parquet`. See
  [data-model.md](../data-model.md) for the schema.
- Without `--force`, it skips only when both files exist. If either is missing, it rebuilds.
- Its success message reports both: `Wrote N distinct emails to …/emails.parquet and M file
  locations to …/locations.parquet`.
