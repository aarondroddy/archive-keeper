# Usage

Preferred keeper order:

1. `/mnt/MyCloud1`
2. `/mnt/MyCloud2`
3. `/mnt/MyCloud3`

Analyze:

```bash
archive-keeper analyze
```

Generate a plan:

```bash
archive-keeper \
  --prefer /mnt/MyCloud1 \
  --prefer /mnt/MyCloud2 \
  --prefer /mnt/MyCloud3 \
  plan
```

Open the reviewer:

```bash
archive-keeper \
  --prefer /mnt/MyCloud1 \
  --prefer /mnt/MyCloud2 \
  --prefer /mnt/MyCloud3 \
  review
```

Before real use, verify the installed interface:

```bash
archive-keeper --help
archive-keeper quarantine --help
archive-keeper restore --help
```


## Restore collision verification

Restore checks an already-existing original against its quarantined copy with SHA-256. The comparison is bounded by `--verify-timeout` (30 seconds by default). Identical files can be reconciled during `--apply`; different-content collisions are skipped without overwriting either file.


## Visible quarantine directories (1.6.6)

New runs default to `ArchiveKeeper Quarantine` on each configured NAS root. Existing runs keep using the directory recorded by their journal, including legacy `.ArchiveKeeper` trees. Archive Keeper never renames or migrates an existing quarantine automatically. Use `--quarantine-name` only when starting a new run if a custom directory name is desired.

## 1.6.7 stale-report handling

A duplicate source referenced by an older rmlint snapshot may already be absent after a prior cleanup. Archive Keeper records that candidate as `stale` rather than `failed` only when the selected keeper is still a regular file and matches the size recorded by the report. Missing, mismatched, or ambiguous keeper states remain failures.
