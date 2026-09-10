# Archive Keeper 2.0.0 release notes

Archive Keeper 2.0 introduces **Storage Galaxy**, a guided terminal interface
for the complete Archive Keeper safety engine. The UI and engine ship together;
end users do not need Go when installing an official combined package.

## What is new

- Guided setup for local, removable, CIFS/SMB, and NFS storage roots.
- Safe rmlint duplicate scans with live progress, cancellation, report backup,
  and a plain-language results screen.
- Galaxy and list views with recoverable-space intensity, search, filtering,
  sorting, pagination, keeper decisions, and protected/excluded roots.
- Preview-first, bounded quarantine and restore workflows with journaled
  recovery, plus retry and reconcile controls.
- Read-only operational History with run and action drill-down.
- Basic instructions throughout the UI, Magic Keyboard alternatives,
  low-color/`NO_COLOR` support, and structured diagnostic logs.

## Safety guarantees

Archive Keeper never executes rmlint's cleanup script and never directly
deletes duplicates. Scanning cannot move files. Decisions cannot move files.
Mutation requires a successful dry pilot followed by a separate exact-phrase
confirmation; operations are bounded, collision-safe, journaled, and
restorable. A cancelled or failed scan cannot replace the active report.

The Mount Storage Assistant shows the exact command before running it, performs
temporary mounts only, never stores passwords, and never edits `/etc/fstab`.

## Validation completed

- Python safety-engine and bridge suite.
- Go formatting, vet, unit tests, and build.
- PTY keyboard, resize, redraw, reconnect, and tmux reliability suite.
- Simulated long-running/cancelled scans and a 50,000-group fake report.
- Synthetic local, removable, CIFS, NFS, and offline mount coverage.
- Low-color terminal review, combined packaging, clean isolated installation,
  target-machine checks, and a tiny quarantine/restore pilot.

All automated storage fixtures use temporary directories. They do not scan or
move files on the configured archive drives.

## Installation

Verify the checksum, unpack the archive, and run the installer:

```bash
sha256sum -c archive-keeper-2.0.0-linux-amd64.tar.gz.sha256
tar -xzf archive-keeper-2.0.0-linux-amd64.tar.gz
cd archive-keeper-2.0.0-linux-amd64
./install.sh
archive-keeper --version
archive-keeper ui --health-check
archive-keeper ui
```

The installer creates `~/.local/bin/archive-keeper`; the command can be used
from any directory without manually activating the private virtual environment.

## Deliberately deferred

Persistent boot-time mount configuration and mergerfs pooling are planned for
later work. Version 2.0 keeps roots separate and uses temporary mounts by
default, which matches the tested safety boundary.
