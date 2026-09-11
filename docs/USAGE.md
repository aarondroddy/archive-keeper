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
archive-keeper --version
archive-keeper --help
archive-keeper quarantine --help
archive-keeper restore --help
archive-keeper reconcile --help
archive-keeper retry --help
archive-keeper ui --health-check
```

Open the packaged Storage Galaxy interface with:

```bash
archive-keeper ui
```

Storage Setup lists mounted storage plus an optional `LOCAL` entry for the
current user's home folder. Choose `LOCAL` to scan files on the Linux system
disk without scanning the entire `/` filesystem or the separate mounts beneath
`/mnt` and `/media`.

This launches the UI shipped with the same installation; all quarantine,
restore, retry, and reconciliation work continues to use the Python safety
engine in that package.

During a UI-started rmlint scan, Archive Keeper shows elapsed time, the rmlint
process ID, and whether the temporary report has begun to grow. Missing
progress output is labeled as missing telemetry rather than activity. A
possible-stall warning suggests checking storage and network health but does
not stop the process; `X`, `H`, or Left Arrow cancels safely.

rmlint does not support checkpoint resume. On a failed or cancelled scan, `F`
offers a confirmed retry of the same roots from the beginning. The previous
active report remains untouched unless that retry completes successfully.


## Restore collision verification

Restore checks an already-existing original against its quarantined copy with SHA-256. The comparison is bounded by `--verify-timeout` (30 seconds by default). Identical files can be reconciled during `--apply`; different-content collisions are skipped without overwriting either file.

## Reconcile and targeted retry

`archive-keeper reconcile RUN_ID` audits only unresolved journal actions and is
read-only by default. `--apply` changes journal state only for destination-only
matches and identical source/destination pairs; it never deletes either copy.

`archive-keeper retry RUN_ID` selects only unresolved `failed` and `timeout`
journal rows, plus any interrupted `moving` row. It does not parse or replay the
original duplicate report. Dry runs leave both files and journal rows unchanged.
Use `--apply` to move verified source-only candidates, `--status` to select a
specific unresolved status, and `--limit` for a small first run. Verification
defaults to 300 seconds per row; `--verify-timeout unlimited` is available only
when explicitly requested. Retry moves use a no-clobber filesystem operation,
so an existing or newly appearing destination is never blindly overwritten.
For a verified different-content destination collision, retry derives a stable
`__collision-ACTION_ID` alternate filename, preserves the occupied destination,
and journals the alternate path actually used. If that alternate is also
occupied by different content, the row remains failed and all files stay put.


## Visible quarantine directories (1.6.6)

New runs default to `ArchiveKeeper Quarantine` on each configured NAS root. Existing runs keep using the directory recorded by their journal, including legacy `.ArchiveKeeper` trees. Archive Keeper never renames or migrates an existing quarantine automatically. Use `--quarantine-name` only when starting a new run if a custom directory name is desired.

## 1.6.7 stale-report handling

A duplicate source referenced by an older rmlint snapshot may already be absent after a prior cleanup. Archive Keeper records that candidate as `stale` rather than `failed` only when the selected keeper is still a regular file and matches the size recorded by the report. Missing, mismatched, or ambiguous keeper states remain failures.


## Sampled verification for very large retry candidates

When full SHA-256 is impractical over slow NAS storage, retry can compare deterministic sampled SHA-256 windows instead:

```bash
archive-keeper retry RUN_ID --status failed --action-id ACTION_ID --sample-verify
```

This is read-only by default. Because sampled verification is not equivalent to hashing every byte, applying it requires an additional explicit acknowledgement:

```bash
archive-keeper retry RUN_ID --status failed --action-id ACTION_ID \
  --sample-verify --allow-sample-verified --apply
```

Archive Keeper requires equal file sizes and hashes distinct 16 MiB windows at the start, 25%, 50%, 75%, and end. A mismatch in any sampled window rejects the candidate. Successful moves record `sample SHA-256 verified` in the journal. `--sample-verify` and `--deep-verify` are mutually exclusive.
