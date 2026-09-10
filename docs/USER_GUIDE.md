# Archive Keeper User Guide

Archive Keeper helps review and quarantine duplicate files described by an
existing `rmlint.json` report. It does not run the generated `rmlint.sh` and
does not permanently delete duplicates. Files are moved into visible quarantine
trees and every applied action is recorded for later inspection or restoration.

> **Important:** Archive Keeper is pre-release software that can move large
> numbers of files. Start with a dry run, use a small pilot, inspect the result,
> and prove restoration before increasing scope.

## 1. Install and verify

Follow [INSTALL.md](INSTALL.md), activate the virtual environment, and confirm
the installed release:

```bash
archive-keeper --version
archive-keeper --help
archive-keeper ui --health-check
```

The expected release output is `archive-keeper 2.0.0`. The installer creates a
launcher in `~/.local/bin`, so virtual-environment activation is not required.

Start the guided Storage Galaxy interface with `archive-keeper ui`. It is part
of the same installation as the command-line engine; no separate Go setup is
required when using an official combined package.

## 2. Confirm the inputs

The default report is:

```text
~/rmlint-mycloud-scan/rmlint.json
```

The default NAS roots are:

```text
/mnt/MyCloud1
/mnt/MyCloud2
/mnt/MyCloud3
```

### Mount Storage Assistant

From Storage Setup, press `M` to connect a local disk, removable USB drive,
CIFS/SMB share, or NFS export. Choose the storage type, edit each explained
field, and press `A` to review the complete command. Nothing runs until the
final Enter confirmation.

Local and network mount locations must be beneath `/mnt`, `/media`, or
`/run/media`. Removable devices use `udisksctl`, which chooses the normal
desktop mount location. CIFS authentication must use either the `guest` option
or an external `credentials=/absolute/path` file. The assistant rejects inline
passwords and never saves authentication secrets.

The UI attempts privileged commands without opening a password prompt. If sudo
authorization is required, it stops and shows the equivalent command to run in
a separate terminal. Return to Storage Setup and press `R` afterward. The
assistant creates temporary mounts only and never edits `/etc/fstab`.

Before any applied operation, verify that each configured root is a real mounted
filesystem:

```bash
findmnt /mnt/MyCloud1
findmnt /mnt/MyCloud2
findmnt /mnt/MyCloud3
```

Do not proceed if a path is merely an empty local mount-point directory.

Mount policy choices:

- `--mount-policy auto` checks roots and attempts the matching `/etc/fstab`
  mount when needed. This is the default.
- `--mount-policy check` checks without attempting a mount.
- `--mount-policy ignore` bypasses the safeguard and should be reserved for
  deliberate offline report inspection.

Use `--report PATH` or repeated `--mount-root PATH` options when your
locations differ from the defaults.

## 3. Analyze without changing files

```bash
archive-keeper analyze
```

This summarizes duplicate groups and estimated recoverable space. Analysis uses
report metadata and does not perform a live stat of every NAS file.

## 4. Review keeper choices

Open the full-screen reviewer:

```bash
archive-keeper \
  --prefer /mnt/MyCloud1 \
  --prefer /mnt/MyCloud2 \
  --prefer /mnt/MyCloud3 \
  review
```

Important keys:

- Arrow keys browse groups and copies.
- `k` marks the selected copy as the keeper.
- `x` marks a copy for quarantine.
- `u` returns a copy to undecided.
- `f` toggles a favorite.
- `r` refreshes metadata or preview information.
- `q` exits without moving files.

Manual decisions are stored in:

```text
~/.local/state/archive-keeper/decisions.sqlite3
```

Useful command-line review tools include:

```bash
archive-keeper search "vacation 2024"
archive-keeper inspect 481
archive-keeper keep 481 "/mnt/MyCloud2/Organized/Photos/photo.jpg"
archive-keeper folders --depth 5 --limit 100
```

## 5. Protect intentional data

A protected tree may still supply a keeper but is never quarantined:

```bash
archive-keeper --protect "/mnt/MyCloud1/Family Photos" plan
```

An excluded tree is ignored during planning and quarantine:

```bash
archive-keeper --exclude "/mnt/MyCloud2/Intentional Mirror" plan
```

Both options may be repeated.

## 6. Generate and inspect a plan

```bash
archive-keeper \
  --prefer /mnt/MyCloud1 \
  --prefer /mnt/MyCloud2 \
  --prefer /mnt/MyCloud3 \
  plan
```

The default CSV is
`~/rmlint-mycloud-scan/archive-keeper-plan.csv`. Inspect its keeper,
quarantine, skipped, and reason columns before proceeding.

## 7. Run a small verified pilot

Dry run first:

```bash
archive-keeper \
  --prefer /mnt/MyCloud1 \
  --prefer /mnt/MyCloud2 \
  --prefer /mnt/MyCloud3 \
  quarantine --run-id pilot-25 --limit 25 --deep-verify --verify-timeout 30
```

Apply the same bounded pilot only after reviewing the output:

```bash
archive-keeper \
  --prefer /mnt/MyCloud1 \
  --prefer /mnt/MyCloud2 \
  --prefer /mnt/MyCloud3 \
  quarantine --run-id pilot-25 --limit 25 --deep-verify \
  --verify-timeout 30 --apply
```

The same run ID can resume an interrupted or limited run. Do not reuse a dry-run
ID for an applied run.

New runs use a visible `ArchiveKeeper Quarantine` folder on each NAS. Existing
runs preserve their journaled quarantine name, including legacy
`.ArchiveKeeper` folders.

## 8. Inspect status and prove restoration

```bash
archive-keeper status --run-id pilot-25
archive-keeper restore pilot-25
archive-keeper restore pilot-25 --apply
```

The first restore command is a preview. Applied restore verifies collisions.
Identical existing originals may be reconciled; different content is preserved
without overwrite.

The operational journal is stored at:

```text
~/.local/state/archive-keeper/journal.sqlite3
```

Keep the journal, decisions database, and original rmlint report backed up until
the quarantine has been fully reviewed.

## 9. Reconcile an unusual result

Audit unresolved rows without mutation:

```bash
archive-keeper reconcile RUN_ID
```

Applying reconciliation changes only journal rows proven safe:

```bash
archive-keeper reconcile RUN_ID --apply
```

Reconciliation does not move, delete, or overwrite files.

## 10. Retry unresolved rows

Preview all eligible unresolved rows:

```bash
archive-keeper retry RUN_ID --verify-timeout 300
```

Narrow the retry to one action:

```bash
archive-keeper retry RUN_ID --status failed --action-id ACTION_ID
```

Apply only after reviewing the preview:

```bash
archive-keeper retry RUN_ID --status failed --action-id ACTION_ID \
  --deep-verify --verify-timeout 300 --apply
```

Retry uses no-clobber moves. If a different file already occupies the quarantine
destination, Archive Keeper preserves it and may select a deterministic
`__collision-ACTION_ID` alternate path.

For very large files on a slow NAS, sampled verification is available:

```bash
archive-keeper retry RUN_ID --status failed --action-id ACTION_ID \
  --sample-verify
```

Sampled verification hashes deterministic 16 MiB windows rather than every byte.
It is high-confidence verification, not a complete cryptographic proof.
Mutation therefore requires the additional explicit
`--allow-sample-verified` flag.

## 11. When to stop

Stop and inspect manually when:

- A configured NAS root is not mounted.
- A keeper is missing or has an unexpected size.
- Source and destination contain different data.
- Verification repeatedly times out.
- The journal reports an ambiguous interrupted state.
- An alternate collision path is already occupied by different content.

Archive Keeper is designed to fail closed in these cases. A refusal to move a
file is a safety result, not an invitation to force the operation.
