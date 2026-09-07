#!/usr/bin/env bash
set -euo pipefail

ui_binary="${1:-/tmp/archive-keeper-ui}"
if [[ ! -x "$ui_binary" ]]; then
    if command -v archive-keeper-ui >/dev/null 2>&1; then
        ui_binary="$(command -v archive-keeper-ui)"
    else
        printf 'Archive Keeper UI binary not found.\nBuild it first with:\n  go build -o /tmp/archive-keeper-ui ./cmd/archive-keeper-ui\n' >&2
        exit 1
    fi
fi
if ! command -v rmlint >/dev/null 2>&1; then
    printf 'rmlint is not installed or is not on PATH.\n' >&2
    exit 1
fi

fixture_root="$(mktemp -d "${TMPDIR:-/tmp}/archive-keeper-galaxy.XXXXXX")"
orion="$fixture_root/Orion"
lyra="$fixture_root/Lyra"
draco="$fixture_root/Draco"
mkdir -p "$orion" "$lyra" "$draco"

make_pair() {
    local bytes="$1"
    local first="$2"
    local second="$3"
    head -c "$bytes" /dev/zero >"$first"
    cp "$first" "$second"
}

make_pair 1024 "$orion/faint-a.bin" "$lyra/faint-b.bin"
make_pair 131072 "$lyra/low-a.bin" "$draco/low-b.bin"
make_pair 393216 "$draco/medium-a.bin" "$orion/medium-b.bin"
make_pair 1048576 "$orion/high-a.bin" "$draco/high-b.bin"

printf '\nGalaxy fixture ready at %s\n' "$fixture_root"
printf 'Inside the UI: press 8, then F, then Enter. After the scan, press 2.\n'
printf 'Expected intensity legend: · faint, ✦ low, ✦✦ medium, ✦✦✦ high.\n\n'

ARCHIVE_KEEPER_MOUNT_ROOTS="$orion:$lyra:$draco" \
ARCHIVE_KEEPER_REPORT="$fixture_root/rmlint.json" \
ARCHIVE_KEEPER_UI_CONFIG="$fixture_root/ui.json" \
"$ui_binary"

printf '\nFixture retained for inspection: %s\n' "$fixture_root"
