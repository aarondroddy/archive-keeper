#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$project_root"

for command_name in git go gofmt python3 tmux rmlint; do
    if ! command -v "$command_name" >/dev/null 2>&1; then
        printf 'Target check stopped: required command is missing: %s\n' "$command_name" >&2
        exit 1
    fi
done

check_root="$(mktemp -d "${TMPDIR:-/tmp}/archive-keeper-target-check.XXXXXX")"
trap 'rm -rf -- "$check_root"' EXIT

printf 'Archive Keeper 2.0 target-machine validation\n'
printf 'Safety: no rmlint scan, quarantine, restore, mount, or unmount will run.\n\n'

printf '[1/7] Checking Go formatting...\n'
unformatted="$(gofmt -l cmd/archive-keeper-ui)"
if [[ -n "$unformatted" ]]; then
    printf 'Go files require gofmt:\n%s\n' "$unformatted" >&2
    exit 1
fi

printf '[2/7] Running Go vet and unit tests...\n'
go vet ./...
go test ./...

printf '[3/7] Running Python engine and bridge tests...\n'
python3 -m unittest tests.test_archive_keeper tests.test_ui_bridge -v

printf '[4/7] Running isolated PTY, keyboard, resize, tmux, and fake-scan tests...\n'
python3 -m unittest tests.test_ui_pty -v

printf '[5/7] Building the Storage Galaxy binary...\n'
ui_binary="$check_root/archive-keeper-ui"
go build -trimpath -o "$ui_binary" ./cmd/archive-keeper-ui
"$ui_binary" --health-check

printf '[6/7] Verifying a combined isolated installation...\n'
stage="$check_root/source"
mkdir -p "$stage"
git archive HEAD | tar -x -C "$stage"
mkdir -p "$stage/archive_keeper/bin"
cp "$ui_binary" "$stage/archive_keeper/bin/archive-keeper-ui"
chmod 755 "$stage/archive_keeper/bin/archive-keeper-ui"
wheelhouse="$check_root/wheelhouse"
mkdir -p "$wheelhouse"
if ! python3 -c 'import setuptools.build_meta' >/dev/null 2>&1; then
    printf 'Target check stopped: the system Python needs setuptools to build the isolated wheel.\n' >&2
    printf 'On Kali, install it with: sudo apt install python3-setuptools\n' >&2
    exit 1
fi
python3 -m pip wheel --quiet --no-deps --no-build-isolation \
    --wheel-dir "$wheelhouse" "$stage"
python3 -m venv "$check_root/venv"
"$check_root/venv/bin/pip" install --quiet --no-deps "$wheelhouse"/*.whl
"$check_root/venv/bin/archive-keeper" --version
"$check_root/venv/bin/archive-keeper" ui --health-check

printf '[7/7] Reading kernel mount metadata (no filesystem scan)...\n'
python3 - <<'PY'
from pathlib import Path

prefixes = ("/mnt/", "/media/", "/run/media/")
rows = []
for line in Path("/proc/self/mountinfo").read_text(encoding="utf-8").splitlines():
    try:
        left, right = line.split(" - ", 1)
        mountpoint = left.split()[4].replace("\\040", " ")
        filesystem, source = right.split()[:2]
    except (IndexError, ValueError):
        continue
    if mountpoint.startswith(prefixes):
        rows.append((mountpoint, filesystem, source.replace("\\040", " ")))

if rows:
    for mountpoint, filesystem, source in sorted(rows):
        print(f"  ONLINE  {filesystem:<10} {mountpoint}  ({source})")
else:
    print("  No mounted storage was detected beneath /mnt, /media, or /run/media.")
    print("  This does not fail the code suite; inspect Storage Setup before real use.")
PY

printf '\nTARGET CHECK PASSED\n'
printf 'Only temporary fixtures beneath %s were exercised.\n' "$check_root"
printf 'No archive files were scanned or moved.\n'
