# Archive Keeper 1.6.8

Archive Keeper turns an existing `rmlint.json` scan into a safe, reviewable,
resumable deduplication workflow. It never runs `rmlint.sh` and never deletes
files directly: duplicates are moved into a per-NAS quarantine tree and every
action is journaled for restoration.

## 1.6.8 highlights

- New quarantine runs use a visible `ArchiveKeeper Quarantine` directory on each NAS root so quarantined files can be browsed in NAS/mobile file apps that hide dot-directories.
- Existing runs automatically reuse their journaled quarantine directory (including legacy `.ArchiveKeeper`) when resumed; nothing is renamed or migrated.
- `--quarantine-name` still overrides the directory for new runs, while conflicting overrides on an existing run fail closed.

- Reconciles identical quarantine-destination collisions with SHA-256 instead of counting them as failures.
- Reconciles restore collisions when the original already exists and is SHA-256 identical, removing only the redundant quarantine copy.
- Leaves different-content collisions untouched in both directions.
- Reports attempted, moved, restored, reconciled, skipped, and failed outcomes more clearly.


- Added a reusable progress tracker for long multi-file operations.
- Quarantine now shows current item/total, percentage, elapsed time, ETA, current path, operation, and running result counters.
- Restore now reports the same item-level progress for dry runs and applied restores.
- Interactive terminals use a compact live-updating line; redirected output emits timestamped log-friendly progress lines.
- Report parsing/group-building progress now includes percentages.

- Quarantine verification now runs in an isolated helper process with a per-file timeout, preventing a stalled CIFS metadata/hash request from freezing the main CLI.
- New `--verify-timeout SECONDS` option (default: 30).
- Quarantine prints the exact file being verified and reports `TIMEOUT`/`FAILED`/`VERIFIED` status as it goes.
- `--limit` now correctly limits dry-run candidates as well as applied moves.

- Fix reviewer crash when comparing selected copies with the current keeper.
- Preserve the 1.6.1 lazy NAS validation and progress behavior.

- Fast, filesystem-free report parsing: analysis no longer stats every NAS path.
- Visible loading and group-building progress messages.
- Clearer copy rows with filename-first, distinguishing parent paths.
- Live NAS checks remain lazy and are revalidated before file operations.

- Full-screen visual review interface powered by Python’s built-in curses library.
- Fuzzy search across duplicate paths and filenames.
- Manual keeper selection saved between sessions.
- Favorites/bookmarks for important copies.
- Folder-centric duplicate-space summaries.
- Side-by-side group/path comparison in the reviewer.
- Automatic metadata for images, video, audio, PDFs, text, archives, and Office files.
- Terminal image thumbnails when `chafa` is available.
- Video/audio codec, duration, resolution, and bitrate through `ffprobe`.
- PDF metadata and first-page text through `pdfinfo`/`pdftotext`.
- Text and archive previews.
- Clear “Why this keeper?” explanations.
- Duplicate-group tree/graph views.
- Journaled history, resumable quarantine, and complete restore support.
- Progress reporting and pilot-run limits.
- CSV plans now honor manual keeper decisions.

External preview helpers are optional. Archive Keeper degrades gracefully when
a helper is unavailable.

## Safety model

- Dry run unless `--apply` is explicitly supplied.
- Only operates beneath configured `--mount-root` paths.
- Keeps at least one copy from every duplicate group.
- Supports protected and excluded trees.
- Verifies file sizes before every move.
- Optional SHA-256 verification with `--deep-verify`.
- Uses same-filesystem atomic renames via `os.replace`.
- Journals each action immediately in SQLite.
- Resumes safely with the same `--run-id`.
- Manual keeper choices are validated against the actual duplicate group.
- Never calls the generated `rmlint.sh`.

## Install on Kali

Extract the `.tar.gz`, then:

```bash
cd ~/archive-keeper
./install.sh
source .venv/bin/activate
archive-keeper --help
```

The installer creates an isolated Python virtual environment. The full-screen interface uses only Python standard-library components.

Optional system helpers for richer previews:

```bash
sudo apt install ffmpeg chafa imagemagick poppler-utils libarchive-tools
```

Archive Keeper still works without these packages.

Verify the installed version:

```bash
archive-keeper --version
```

## Open the visual reviewer

```bash
archive-keeper \
  --prefer /mnt/MyCloud1 \
  --prefer /mnt/MyCloud2 \
  --prefer /mnt/MyCloud3 \
  review
```

Key bindings:

- `q` — quit without moving files
- type in the search box — fuzzy-search groups
- arrow keys — browse groups
- `K` — cycle/select a different keeper for the highlighted group
- `f` — favorite the current keeper
- `r` — refresh metadata/preview

Manual choices are stored in:

```text
~/.local/state/archive-keeper/decisions.sqlite3
```

## Command-line review tools

Search:

```bash
archive-keeper search "vacation 2024"
```

Inspect a group with metadata and the keeper explanation:

```bash
archive-keeper inspect 481
```

Choose a keeper explicitly:

```bash
archive-keeper keep 481 "/mnt/MyCloud2/Organized/Photos/photo.jpg"
```

Summarize duplicate space by folder:

```bash
archive-keeper folders --depth 5 --limit 100
```

## Create a decision-aware plan

```bash
archive-keeper \
  --prefer /mnt/MyCloud1 \
  --prefer /mnt/MyCloud2 \
  --prefer /mnt/MyCloud3 \
  plan
```

Output:

```text
~/rmlint-mycloud-scan/archive-keeper-plan.csv
```

The CSV includes automatic and manually selected keepers.

## Safe pilot

First perform a dry run:

```bash
archive-keeper \
  --prefer /mnt/MyCloud1 \
  --prefer /mnt/MyCloud2 \
  --prefer /mnt/MyCloud3 \
  quarantine --run-id pilot-25 --limit 25 --deep-verify --verify-timeout 30
```

Then apply the same pilot:

```bash
archive-keeper \
  --prefer /mnt/MyCloud1 \
  --prefer /mnt/MyCloud2 \
  --prefer /mnt/MyCloud3 \
  quarantine --run-id pilot-25 --limit 25 --deep-verify --verify-timeout 30 --apply
```

## Restore

Preview restoration:

```bash
archive-keeper restore pilot-25
```

Apply restoration:

```bash
archive-keeper restore pilot-25 --apply
```

## Reconcile unresolved actions

Audit the live source and quarantine state for only the `failed` and `timeout`
rows already recorded for a run:

```bash
archive-keeper reconcile full-2026-08
```

The command is read-only unless `--apply` is supplied. Applying reconciliation
updates only journal rows proven safe (`DEST_ONLY_MATCH` and `BOTH_IDENTICAL`);
it does not move, delete, or overwrite either copy.

## Targeted retry

Preview retries directly from unresolved journal rows without replaying the
original rmlint report:

```bash
archive-keeper retry full-2026-08 --verify-timeout 300
```

Apply verified retries:

```bash
archive-keeper retry full-2026-08 --verify-timeout 300 --apply
```

By default, retry selects both `failed` and `timeout` rows. Use repeated
`--status` options to narrow the selection, `--limit` for a small test, or
`--verify-timeout unlimited` only when an intentionally unbounded verification
is acceptable. Existing destinations are never overwritten. Identical copies
are journaled as reconciled. When retry encounters a genuine different-content
destination collision, it preserves the existing quarantine file and selects a
deterministic alternate name such as `Peeps__collision-590923.ZIP`; `--apply`
moves the source there and journals that actual destination. Dry runs show the
alternate path without changing files or journal state. If the alternate path
is itself occupied by different content, retry still fails closed. Interrupted
`moving` rows are automatically included on the next retry.

## Resume after interruption

Repeat the quarantine command with the same run ID. Already handled files are
not moved again.

```bash
archive-keeper \
  --prefer /mnt/MyCloud1 \
  --prefer /mnt/MyCloud2 \
  --prefer /mnt/MyCloud3 \
  quarantine --run-id full-2026-08 --apply
```

## Protect and exclude paths

Protected paths may be retained as keepers but are never quarantined:

```bash
--protect "/mnt/MyCloud1/Family Photos"
```

Excluded paths are ignored during planning and quarantine:

```bash
--exclude "/mnt/MyCloud2/Intentional Mirror"
```

## Keeper strategies

- `preferred-root`
- `rmlint-original`
- `oldest`
- `newest`
- `shortest-path`

Manual keeper choices override the automatic strategy.

## Operational warning

Before any applied run, confirm `/mnt/MyCloud1`, `/mnt/MyCloud2`, and
`/mnt/MyCloud3` are real mounted NAS filesystems—not empty local mount-point
directories. Keep the original `rmlint.json`, the journal database, and the
decisions database backed up until the quarantine has been reviewed.

## Documentation

- [Installation](docs/INSTALL.md)
- [User guide](docs/USER_GUIDE.md)
- [Command reference](docs/USAGE.md)
- [Safety model](docs/SAFETY.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Contributing](CONTRIBUTING.md)
- [Security policy](SECURITY.md)

> [!WARNING]
> Archive Keeper is pre-release software that can move large numbers of files.
> Inspect the plan, run a limited pilot, and prove restoration before applying
> it to production data.

## Automatic mount safety

Before commands that inspect or act on report paths, Archive Keeper checks every configured
`--mount-root`. The default `--mount-policy auto` attempts `sudo mount <root>`, which uses the
matching `/etc/fstab` entry. If any root remains unavailable, Archive Keeper stops before
reviewing or moving files. Use `--mount-policy check` to verify without mounting, or
`--mount-policy ignore` only for deliberate offline report inspection.

### Sampled retry verification

For very large files on slow NAS storage, `retry --sample-verify` hashes deterministic 16 MiB windows at the start, 25%, 50%, 75%, and end of equal-sized keeper/source files. This is high-confidence verification, not a full-file cryptographic proof. Applying a sampled-verified retry therefore also requires the explicit `--allow-sample-verified` flag. Journal messages preserve the sampled-verification provenance.
