# Archive Keeper 2.0 — Implementation Checklist

This tracks Storage Galaxy work on `feature/v2-storage-galaxy` and the remaining
path to a production-ready v2.

## Completed or implemented

### Existing safety engine

- [x] Parse rmlint JSON without executing `rmlint.sh`.
- [x] Preserve at least one keeper per duplicate group.
- [x] Persist manual keeper and per-file staging decisions in SQLite.
- [x] Validate configured mount roots before operations.
- [x] Quarantine with no-replace moves instead of deletion.
- [x] Journal every applied move under a recoverable run ID.
- [x] Restore journaled moves without overwriting an existing original.
- [x] Support resumable reconcile and retry engine workflows.
- [x] Bound verification work with timeouts and explicit limits.

### Storage Galaxy UI

- [x] Bubble Tea v2 shell with Home, Groups, Keepers, Quarantine, Restore,
  History, Help, and Storage Setup.
- [x] Responsive compact layout for iPad remote terminals.
- [x] Versioned JSON bridge to the Python safety engine.
- [x] Read-only dashboard loading for reports and existing SQLite state.
- [x] Home metrics and live mount-array status.
- [x] Quarantine and restore locked when configured mounts are not ready.
- [x] Galaxy visualization grouped by mount root.
- [x] Keyboard navigation and `G` Galaxy/list toggle.
- [x] Copy inspector, keeper selection, and QUARANTINE/UNDECIDED/CLEAR staging.
- [x] Bounded dry pilot and controlled quarantine apply gate.
- [x] Exact confirmation phrase and maximum 10-file controlled apply.
- [x] Restore catalog, live collision preview, controlled restore, and verified
  result.
- [x] Journal-backed History summary.
- [x] Read-only History drill-down with per-run status totals and navigable
  action details: group, size, source, keeper, destination, and message.
- [x] Help screen with navigation and safety keys.
- [x] Magic Keyboard alternatives for Escape: `H`, Left Arrow, and `Ctrl-G`
  in confirmation input.
- [x] Named-space handling in exact confirmation phrases.
- [x] Galaxy panel width/background fix for terminal wrapping artifacts.
- [x] Plain-language basic guides on every workflow screen, with explicit notes
  about which steps are read-only and which confirmed steps may move files.

### Portable configuration and scanning

- [x] Open first-run Storage Setup when no managed roots are configured.
- [x] Detect mounted storage beneath `/mnt`, `/media`, and `/run/media`.
- [x] Select managed roots and retain configured-but-offline roots visibly.
- [x] Save `~/.config/archive-keeper/ui.json` with owner-only permissions.
- [x] Keep environment variables as higher-priority overrides.
- [x] Reopen Storage Setup with `8`.
- [x] Launch a confirmed duplicate-only rmlint scan with `F`.
- [x] Invoke rmlint directly with JSON-only output.
- [x] Never create or run rmlint's cleanup script from the UI.
- [x] Show elapsed time and allow cancellation with `X`, `H`, or Left Arrow.
- [x] Write the scan to a temporary report first.
- [x] Activate only a successful, non-empty report.
- [x] Preserve the previous report as a timestamped backup.
- [x] Reload the dashboard after a successful scan.
- [x] Add focused tests for mount parsing, saved configuration, and rmlint
  arguments.
- [x] Document setup, scanning, backup, and safety behavior.

### User-verified end-to-end fixture

- [x] Display a small fake duplicate fixture without a full NAS scan.
- [x] Select a keeper and stage the duplicate.
- [x] Run the dry pilot and controlled quarantine.
- [x] Restore the quarantined test file.
- [x] Show RESTORE VERIFIED and the restored run in History.
- [x] Return to an empty Restore catalog after restoration.
- [x] Add an isolated recovery fixture for retry and reconciliation without a NAS scan.

## Still to do

### Workflow depth

- [x] Add action-scoped, preview-first UI controls for safe reconcile and retry workflows.
- [x] Add report-wide path search, mount-root filtering, five sort modes, and
  paginated group browsing beyond the 24-group dashboard preview.
- [x] Add confirmed bulk decision review that atomically stages every
  nonkeeper while validating and protecting the group's saved keeper.
- [x] Add guided advanced settings for report path, state DB, decisions DB, quarantine
  name, preferred roots, protected roots, and exclusions.
- [x] Enforce protected and excluded roots at single staging, atomic bulk
  staging, quarantine preview, dry pilot, and controlled apply boundaries.
- [x] Highlight preferred copies and open group review on the first matching
  preferred root without automatically changing the saved keeper.
- [ ] Add richer live rmlint progress when the installed version exposes
  machine-readable progress.
- [x] Add a beginner-friendly post-scan summary with duration, scanned roots,
  result counts, active/backup report paths, empty results, errors, and direct
  navigation to Duplicate Groups.
- [ ] Add a guided Mount Storage wizard for local/removable disks, SMB/CIFS,
  and NFS. Start with previewed temporary mounts; keep persistent boot-time
  mount changes behind a separate explicit confirmation and never store sudo
  or share passwords in the UI configuration.

### Packaging and reliability

- [ ] Package/install the Go UI with the Python engine.
- [ ] Add a stable launcher such as `archive-keeper ui`.
- [x] Add CI checks for Go vet/tests, Python bridge tests, and the Go build.
- [ ] Add an explicit Go formatting check to CI.
- [ ] Add PTY end-to-end tests for keyboard input, tmux, resize, reconnect, and
  redraw.
- [ ] Test Setup on local disks, CIFS, NFS, removable media, and offline mounts.
- [ ] Test long scans and very large reports.
- [ ] Complete accessibility and low-color terminal review.
- [ ] Add structured logging for bridge and scan failures.

### Release work

- [ ] Run all Python and Go tests on the target machine.
- [ ] Perform a fresh-install test without environment variables or old config.
- [ ] Perform a controlled real-data pilot on one tiny group.
- [ ] Review and merge the feature branch.
- [ ] Update version/changelog and publish release notes.
- [ ] Produce checksummed release artifacts.

## Intentional safety boundaries

- [x] Setup does not mount or unmount drives.
- [x] Scanning does not move, quarantine, restore, or delete archive files.
- [x] A failed/cancelled scan cannot replace the active report.
- [x] Decisions alone do not move files.
- [x] Quarantine and restore remain separate, explicit, bounded, journaled
  operations.
