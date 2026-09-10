# Changelog

## Unreleased

_No changes yet._

## 2.0.0 — 2026-09-10

- Added Storage Galaxy, a responsive guided terminal UI bundled with the
  Python safety engine and available through `archive-keeper ui`.
- Added portable storage discovery and configuration, temporary guided mounts
  for local/removable disks, CIFS/SMB, and NFS, plus safe duplicate-only rmlint
  scans with progress, cancellation, report backup, and post-scan summaries.
- Added galaxy/list duplicate browsing, search, filtering, sorting, pagination,
  keeper selection, atomic bulk staging, protected/excluded roots, and preferred
  root guidance.
- Added bounded preview-first quarantine, restore, retry, and reconcile flows
  with exact confirmation gates and journal-backed History drill-down.
- Added beginner guidance on every workflow screen, keyboard alternatives,
  16-color and `NO_COLOR` accessibility modes, and owner-only structured error
  logging.
- Added combined platform packages and extensive Python, Go, PTY, tmux,
  reconnect, resize, simulated long-scan, large-report, mount-matrix, and
  target-machine validation.
- Added a stable per-user launcher so `archive-keeper` uses its private virtual
  environment from any directory without manual activation.
- Persistent boot-time mounts and mergerfs pooling are deliberately deferred;
  Archive Keeper 2.0 manages storage roots separately and temporary mounts are
  the default.

## 1.6.8 — 2026-08-30

- Add explicit sampled SHA-256 verification for very large retry candidates, with mutation gated by `--allow-sample-verified` and journaled verification provenance.
- Added read-only-by-default `reconcile` for classifying unresolved journal rows and applying only proven-safe journal reconciliation.
- Added targeted, read-only-by-default `retry` for existing `failed` and `timeout` journal rows without replaying the original rmlint report.
- Added retry status filtering, limits, deep verification, a longer 300-second default timeout, and explicit `--verify-timeout unlimited` support.
- Retry writes `moving` before mutation, resumes interrupted `moving` rows, journals every applied outcome, and never changes the original run's overall status.
- Added atomic no-clobber moves for retry so a destination appearing after verification cannot be overwritten.
- Retry now resolves genuine different-content destination collisions with a deterministic `__collision-ACTION_ID` alternate filename, preserving the existing destination and journaling the actual alternate path used.
- Added retry regression coverage for dry runs, status selection, successful moves, interruption recovery, timeouts, collision-safe alternate names, and fail-closed alternate-path conflicts.

## 1.6.7

- Classify stale rmlint duplicate candidates as `stale` instead of `failed` when the source is already absent but the selected keeper still exists as a regular file and matches the report size.
- Missing sources remain hard failures when the keeper is missing, not a regular file, the keeper size differs from the report, or an unexpected quarantine destination makes the state ambiguous.
- Surface stale counts in quarantine progress, summaries, status output, and resumable journal state.

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
