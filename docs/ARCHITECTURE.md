# Architecture

Archive Keeper converts an existing `rmlint.json` report into a reviewable,
journaled workflow. Report analysis is separated from live filesystem mutation
so browsing a large report does not wake every NAS path.

## Data flow

```text
rmlint.json
    |
    v
report parser -----> duplicate groups -----> reviewer / CSV plan
                            |                         |
                            v                         v
                    keeper decisions           decisions.sqlite3
                            |
                            v
mount validation -> bounded verification -> quarantine move
                                               |
                                               v
                                         journal.sqlite3
                                          /          \
                                         v            v
                                    reconcile        retry
                                         \            /
                                          v          v
                                             restore
```

## Components

- `archive_keeper.cli` defines commands, safety defaults, and orchestration.
- `archive_keeper.core` parses reports, selects keepers, verifies candidates,
  calculates collision-safe destinations, performs no-clobber moves, and owns
  the SQLite journal abstraction.
- `archive_keeper.decisions` stores manual keeper, per-copy, and favorite
  choices separately from operational history.
- `archive_keeper.review`, `tui`, and `rich_tui` provide read-mostly
  inspection interfaces. Merely opening or quitting a reviewer does not move
  files.
- `archive_keeper.mounts` validates configured roots and optionally invokes
  the matching `/etc/fstab` mount.
- `archive_keeper.progress` renders terminal-aware progress and log-friendly
  output.

## Storage boundaries

Every actionable path must belong to a configured `--mount-root`. The default
roots are `/mnt/MyCloud1`, `/mnt/MyCloud2`, and `/mnt/MyCloud3`.
`--protect` prevents quarantine beneath selected trees; `--exclude` removes
selected trees from processing. Mount checks occur before commands that inspect
or mutate report paths.

New runs create a visible `ArchiveKeeper Quarantine` directory within each NAS
root. Resumed runs reuse their journaled directory, including the legacy
`.ArchiveKeeper` name. A conflicting override fails closed.

## Verification and mutation

Quarantine verifies live keeper/source state immediately before mutation.
Potentially blocking CIFS metadata and hashing work runs in a bounded helper
process. The parent process alone performs mutations.

Applied moves use same-filesystem rename semantics and record a durable
`moving` journal state before mutation. Normal quarantine uses atomic rename;
targeted retry uses a no-clobber move so a destination that appears after
verification cannot be overwritten. Different-content retry collisions receive
a deterministic `__collision-ACTION_ID` alternate name when that alternate is
safe and unoccupied.

## Journal lifecycle

Operational state lives in `~/.local/state/archive-keeper/journal.sqlite3`.
Typical action states are:

- `planned`: verified dry-run candidate.
- `moving`: durable pre-mutation record.
- `moved`: source was quarantined.
- `reconciled`: an identical or otherwise proven-safe state was recognized.
- `stale`: an old report references an absent source while a valid keeper remains.
- `timeout` or `failed`: unresolved and eligible for inspection or retry.
- `skipped`: intentionally untouched.
- `restored`: returned to its original path.

Repeating a run ID resumes journaled work rather than blindly replaying completed
actions. Dry-run and applied modes cannot share a run ID.

## Recovery paths

`reconcile RUN_ID` reads unresolved rows and classifies live source and
quarantine state. Without `--apply` it is an audit only. With `--apply`, it
updates only proven-safe journal rows and never moves or deletes files.

`retry RUN_ID` operates directly from unresolved journal rows without
re-parsing the original report. It is read-only unless `--apply` is supplied.
Full SHA-256 is available with `--deep-verify`; deterministic sampled SHA-256
is available for very large files but requires
`--allow-sample-verified` before mutation.

`restore RUN_ID` previews restoration by default. Applied restoration verifies
collisions and does not overwrite different content.

## Optional preview providers

`ffprobe`, `chafa`, ImageMagick, Poppler, and archive utilities enrich
previews. They are optional and never participate in core safety decisions.
