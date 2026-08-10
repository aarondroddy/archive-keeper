# Changelog

## 1.6.6

- Changed the default quarantine directory for new runs from hidden `.ArchiveKeeper` to visible `ArchiveKeeper Quarantine`.
- Existing journaled runs infer and reuse their original quarantine directory name when resumed, preserving compatibility with pre-1.6.6 `.ArchiveKeeper` runs without migration.
- Conflicting `--quarantine-name` overrides on an existing run now fail closed instead of splitting one run across multiple quarantine roots.
- Added regression coverage for the visible default, custom quarantine names, and legacy-run resume behavior.

## 1.6.5

- Added SHA-256 reconciliation for quarantine destinations that already exist: identical collisions are recorded as `reconciled` instead of failures, while different-content collisions fail closed and leave both files untouched.
- Added SHA-256 reconciliation during restore when the original path already exists: identical originals keep their existing file while the redundant quarantine copy is removed and journaled as `reconciled`.
- Different-content restore collisions remain untouched and are reported as skipped conflicts.
- Added bounded helper-process hashing for restore collision checks so stalled CIFS reads do not freeze the main CLI.
- Added `--verify-timeout` to `restore` for bounded collision verification.
- Corrected quarantine summaries to report `Attempted` separately from `Planned`, and added `Reconciled` counters to progress/status output.
- Added regression tests for identical and different-content collisions in both quarantine and restore paths.

## 1.6.4

- Added item/total progress, percentage, elapsed time, ETA, current path, and running result counters for quarantine and restore operations.
- Added terminal-aware progress output: live-updating status on TTYs and timestamped lines when redirected to a file/log.
- Added percentage detail to report parsing and duplicate-group construction progress.

## 1.6.3

- Moved quarantine live-file verification into a short-lived helper process so a stalled CIFS request cannot freeze the main Archive Keeper CLI.
- Added `--verify-timeout` (30 seconds by default) for bounded per-candidate verification.
- Quarantine now prints the exact file being verified and records verification timeouts distinctly.
- Kept all mutation logic in the parent process: timed-out verifier workers cannot move or alter files.
- Fixed `--limit` so dry runs stop after the requested number of quarantine candidates instead of only counting files actually moved.


## 1.6.2

- Fixed `DuplicateFile` reviewer crash caused by calling `normalize_path` as an instance method.
- Added regression coverage for keeper/action comparison.

## 1.6.1

- Removed implicit live `stat()` and path-resolution calls while parsing rmlint JSON.
- Analysis now builds entirely from report metadata and defers NAS file checks until preview or an actual operation needs them.
- Added visible report-loading and group-building progress messages.
- Improved reviewer paths by showing the filename first and the distinguishing parent-path tail.
- Kept full selected paths visible in the right-hand detail pane.


## 1.6.0 — 2026-08-06

- Rebuilt the full-screen reviewer around explicit per-copy selection.
- Added Enter-to-open group navigation and an individual-copy cursor.
- Added `k` to mark the selected copy KEEP, `x` to mark QUARANTINE, and `u` to mark UNDECIDED.
- Persisted per-file review decisions in the decisions database.
- Made quarantine runs honor UNDECIDED decisions by leaving those files untouched.
- Added selected-file metadata previews and a refreshable preview cache.
- Added durable `moving` journal records before filesystem renames and interrupted-move reconciliation.
- Preserved moved records when a quarantine file is temporarily missing during restore.
- Removed pre-restore unlinking so `os.replace` retains atomic replacement behavior.
- Canonicalized report paths and manual keeper paths for reliable matching through symlinks.
- Prevented reuse of a run ID across dry-run and apply modes.
- Added random suffixes to automatically generated run IDs.
- Completed the MIT license text and expanded regression tests.
