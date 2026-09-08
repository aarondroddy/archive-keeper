#!/usr/bin/env bash
set -euo pipefail

UI_BINARY="${1:-/tmp/archive-keeper-ui}"
if [[ ! -x "$UI_BINARY" ]]; then
  echo "UI binary is not executable: $UI_BINARY" >&2
  echo "Build it first: go build -o /tmp/archive-keeper-ui ./cmd/archive-keeper-ui" >&2
  exit 1
fi

FIXTURE_DIR="$(mktemp -d /tmp/archive-keeper-recovery.XXXXXX)"
trap 'rm -rf -- "$FIXTURE_DIR"' EXIT

export ARCHIVE_KEEPER_REPORT="$FIXTURE_DIR/rmlint.json"
export ARCHIVE_KEEPER_STATE_DB="$FIXTURE_DIR/journal.sqlite3"
export ARCHIVE_KEEPER_DECISIONS_DB="$FIXTURE_DIR/decisions.sqlite3"
export ARCHIVE_KEEPER_MOUNT_ROOTS="/"
export ARCHIVE_KEEPER_RECOVERY_FIXTURE="$FIXTURE_DIR"

python3 - <<'PY'
import json
import os
from pathlib import Path

from archive_keeper.core import Journal

root = Path(os.environ["ARCHIVE_KEEPER_RECOVERY_FIXTURE"])
keeper = root / "keeper.bin"
retry_source = root / "retry-source.bin"
retry_destination = root / "quarantine" / "retry-source.bin"
reconcile_source = root / "reconcile-source.bin"
reconcile_destination = root / "quarantine" / "reconcile-source.bin"

keeper.write_bytes(b"archive-keeper recovery fixture\n")
retry_source.write_bytes(keeper.read_bytes())
reconcile_source.write_bytes(keeper.read_bytes())
reconcile_destination.parent.mkdir(parents=True)
reconcile_destination.write_bytes(keeper.read_bytes())

Path(os.environ["ARCHIVE_KEEPER_REPORT"]).write_text(json.dumps([
    {"description": "rmlint header"},
    {"path": str(keeper), "size": keeper.stat().st_size, "type": "duplicate_file", "is_original": True},
    {"path": str(retry_source), "size": retry_source.stat().st_size, "type": "duplicate_file"},
    {"description": "rmlint footer"},
]), encoding="utf-8")

journal = Journal(Path(os.environ["ARCHIVE_KEEPER_STATE_DB"]))
journal.create_run("ui-recovery-fixture", Path(os.environ["ARCHIVE_KEEPER_REPORT"]), "apply")
journal.record_action(
    "ui-recovery-fixture", 1, keeper, retry_source, retry_destination,
    retry_source.stat().st_size, "failed", "fixture: retry moves this selected source",
)
journal.record_action(
    "ui-recovery-fixture", 2, keeper, reconcile_source, reconcile_destination,
    reconcile_source.stat().st_size, "failed",
    "fixture: source and destination already match; reconcile changes journal only",
)
journal.set_run_status("ui-recovery-fixture", "paused")
journal.close()
PY

echo "Temporary recovery fixture: $FIXTURE_DIR"
echo "In the UI: press 6, Enter, select an action, then T or C. A opens the typed apply gate."
"$UI_BINARY"
