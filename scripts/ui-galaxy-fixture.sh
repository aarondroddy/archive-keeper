#!/usr/bin/env bash
set -euo pipefail

if [[ $# -gt 0 ]]; then
    [[ -x "$1" ]] || { printf 'Archive Keeper UI binary is not executable: %s\n' "$1" >&2; exit 1; }
    ui_command=("$1")
elif command -v archive-keeper >/dev/null 2>&1; then
    ui_command=(archive-keeper ui)
elif [[ -x /tmp/archive-keeper-ui ]]; then
    ui_command=(/tmp/archive-keeper-ui)
elif command -v archive-keeper-ui >/dev/null 2>&1; then
    ui_command=("$(command -v archive-keeper-ui)")
else
    printf 'Archive Keeper UI not found. Install the combined package or build it with:\n  go build -o /tmp/archive-keeper-ui ./cmd/archive-keeper-ui\n' >&2
    exit 1
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

# Add enough uniquely sized tiny pairs to force a second 12-group catalog page.
# Every file remains inside the disposable fixture; real storage is never read.
for index in $(seq 5 16); do
    bytes=$((2048 + index))
    make_pair "$bytes" "$orion/demo-${index}-a.bin" "$lyra/demo-${index}-b.bin"
done

printf '\nGalaxy fixture ready at %s\n' "$fixture_root"
printf 'Inside the UI: press 8, then F, then Enter. After the scan, press 2.\n'
printf 'Try / to search for demo-16, F to filter roots, S to sort, and [ or ] to change pages.\n'
printf 'Expected intensity legend: · faint, ✦ low, ✦✦ medium, ✦✦✦ high.\n\n'

ARCHIVE_KEEPER_MOUNT_ROOTS="$orion:$lyra:$draco" \
ARCHIVE_KEEPER_REPORT="$fixture_root/rmlint.json" \
ARCHIVE_KEEPER_UI_CONFIG="$fixture_root/ui.json" \
"${ui_command[@]}"

printf '\nFixture retained for inspection: %s\n' "$fixture_root"
