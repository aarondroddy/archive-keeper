# Archive Keeper 1.4.0

Archive Keeper turns an existing `rmlint.json` scan into a safe, reviewable,
resumable deduplication workflow. It never runs `rmlint.sh` and never deletes
files directly: duplicates are moved into a per-NAS quarantine tree and every
action is journaled for restoration.

## 1.4.0 highlights

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
  quarantine --run-id pilot-25 --limit 25 --deep-verify
```

Then apply the same pilot:

```bash
archive-keeper \
  --prefer /mnt/MyCloud1 \
  --prefer /mnt/MyCloud2 \
  --prefer /mnt/MyCloud3 \
  quarantine --run-id pilot-25 --limit 25 --deep-verify --apply
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
