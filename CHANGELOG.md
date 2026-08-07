# Changelog

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
