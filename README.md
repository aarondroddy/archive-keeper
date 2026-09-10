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

The installer creates an isolated Python virtual environment and installs the
complete safety engine plus the bundled Storage Galaxy executable. Official
combined release archives do not require Go on the user's machine. A raw
development checkout can build the interface during installation when Go is
available.

Optional system helpers for richer previews:

```bash
sudo apt install ffmpeg chafa imagemagick poppler-utils libarchive-tools
```

Archive Keeper still works without these packages.

Verify the installed version:

```bash
archive-keeper --version
```

Launch Storage Galaxy from the same installation:

```bash
archive-keeper ui
```

`archive-keeper ui --health-check` verifies that the bundled interface can be
started without opening the full-screen application. Existing commands such
as `analyze`, `plan`, `quarantine`, `restore`, `retry`, and `reconcile` remain
part of the same package.

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

## Storage Galaxy UI

Build and launch the Bubble Tea interface:

```bash
go build -o archive-keeper-ui ./cmd/archive-keeper-ui
./archive-keeper-ui
```

Installed combined packages use `archive-keeper ui`; the direct binary command
above is retained for source-tree development.

On first launch, Storage Setup detects mounted drives beneath `/mnt`,
`/media`, and `/run/media`. Select the roots Archive Keeper may manage,
then press `S` to save. Press `8` to reopen setup later.

Press `E` in Storage Setup for Advanced Configuration. Each field includes a
plain-language explanation and validates before it is accepted. You can set
the rmlint report, journal database, decisions database, quarantine folder
name, preferred keeper roots, protected roots, and excluded roots. Multiple
rule paths are separated with `:` on Linux. `S` saves everything to
`~/.config/archive-keeper/ui.json` with owner-only permissions and reloads the
runtime configuration.

Preferred roots are suggestions: the copy inspector starts on a matching copy
and labels it `PREFERRED`. Protected and excluded roots are hard rules. The UI
refuses to stage matching copies, and the quarantine preview, dry pilot, and
final apply all recheck the rules so an older staged decision cannot bypass a
new rule. Excluded copies may still appear in an rmlint report, but Archive
Keeper will not stage or move them.

With `rmlint` installed, press `F` from Storage Setup and confirm with Enter
to run a duplicate-only scan. The UI requests JSON output only; it never
creates or runs rmlint's cleanup script. A successful report loads
automatically, while an existing report is kept as a timestamped backup.
A long scan shows rmlint's live discovery, preparation, matching, and
finalization phases, including the scanner's current counts or ETA. When the
installed rmlint exposes an exact percentage, the UI also draws a percentage
bar; otherwise it keeps showing elapsed time and activity so it never appears
frozen. Cancel safely with `X`, `H`, or Left Arrow.

When the scan ends, a dedicated summary explains what happened before you
leave Storage Setup. It shows the elapsed time, roots checked, duplicate-group
and file counts, potentially recoverable space, active report, and any backup.
An empty scan says explicitly that no duplicates were found. A failed scan
explains the error, confirms that the previous report remains active, and
shows the owner-only structured error-log path. Scan and Python-bridge failures
are appended as one JSON object per line to
`~/.local/state/archive-keeper/ui-errors.jsonl`. Set
`ARCHIVE_KEEPER_UI_LOG` to use another path.
Press Enter, `G`, or `2` to review discovered groups; press `H`, Left Arrow,
or `R` to return to Storage Setup. The summary never moves or deletes files.

Duplicate Groups now browses the complete report in small pages instead of
stopping at the dashboard's 24 largest groups. Press `/` to search filenames
and folders, `F` to cycle mounted-root filters, `S` to change the sort order,
and `[` or `]` for the previous or next page. These controls only read the
report. Every primary screen also includes a short basic guide explaining what
to do next and whether that screen can move files; press `?` for the full key
guide at any time.

Inside a group, select the copy that must remain and press Enter to save it as
the keeper. Press `B` to review a group-wide decision that stages every other
copy for quarantine. The confirmation screen names the protected keeper and
shows the exact number of nonkeepers that will be staged. The bridge refuses
the operation unless the saved keeper is still a member of the group, and the
transaction can never add that keeper to the quarantine decisions. This is a
decisions-only step: no files move until the separate dry-pilot and controlled
apply workflow succeeds.

To exercise scanning and the galaxy map without touching real storage, run
the bundled fixture after building the UI:

```bash
bash scripts/ui-galaxy-fixture.sh
```

Inside the fixture UI, press `8`, `F`, Enter, then `2`. It creates four
small duplicate groups spread across three temporary roots so the faint,
low, medium, and high recoverable-space tiers are all visible. The fixture
uses its own temporary report and configuration. This is the quick UI test:
it scans only tiny generated files under `/tmp`, never the selected NAS drives.


History also provides action-scoped recovery. Press `6`, open a run, select
a failed, timed-out, or interrupted action, then press `T` for a retry preview
or `C` for a reconciliation preview. A clean preview enables `A`, which
requires the exact displayed confirmation phrase. Retry re-verifies and may
move only that selected action; reconciliation never moves files and changes
only a proven-safe journal row.

Test both paths with tiny temporary files and no NAS scan:

```bash
bash scripts/ui-recovery-fixture.sh ./archive-keeper-ui
```

Advanced deployments may continue to use `ARCHIVE_KEEPER_MOUNT_ROOTS`,
`ARCHIVE_KEEPER_REPORT`, `ARCHIVE_KEEPER_STATE_DB`,
`ARCHIVE_KEEPER_DECISIONS_DB`, `ARCHIVE_KEEPER_QUARANTINE_NAME`,
`ARCHIVE_KEEPER_PREFERRED_ROOTS`, `ARCHIVE_KEEPER_PROTECTED_ROOTS`, and
`ARCHIVE_KEEPER_EXCLUDED_ROOTS`; environment variables override saved UI
settings.

### Automated terminal reliability tests

Maintainers can exercise the real Bubble Tea application through a Linux PTY:

```bash
python -m unittest tests.test_ui_pty -v
```

The suite verifies arrow-key and help input, clean exit, narrow/wide terminal
redraws, tmux detach and reattach, a searchable synthetic report containing
50,000 duplicate groups, and a simulated long-running scan. The slow-scan tests
put a disposable `rmlint` stand-in first on `PATH`, prove elapsed-time redraws,
cancellation, prior-report preservation, successful temporary activation, and
structured cancellation logging. Everything is generated beneath the operating
system temporary directory. The suite does not invoke the installed rmlint,
run an apply operation, or access `/mnt/MyCloud1`, `/mnt/MyCloud2`, or
`/mnt/MyCloud3`. Go and tmux are required; CI installs both before running it.

### Final target-machine validation

Before releasing 2.0, run the complete read-only validation from the repository
on the target Linux machine:

```bash
bash scripts/v2-target-check.sh
```

It enforces Go formatting; runs Go, Python, PTY, tmux, resize, reconnect,
large-report, and fake-scan tests; builds the UI; verifies a clean combined
installation; and reports storage types from the kernel mount table. It does
not invoke rmlint, scan archive contents, mount or unmount storage, or perform
quarantine/restore operations.

Set `ARCHIVE_KEEPER_LOW_COLOR=1` for a 16-color-compatible palette, or set the
standard `NO_COLOR` variable to remove UI colors. Status words, icons, focus
markers, instructions, and safety results remain visible without relying on
color alone.

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
