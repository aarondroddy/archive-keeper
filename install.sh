#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

ui_binary="archive_keeper/bin/archive-keeper-ui"
if [[ ! -x "$ui_binary" ]]; then
    if command -v go >/dev/null 2>&1; then
        printf 'Building the Storage Galaxy interface...\n'
        go build -trimpath -o "$ui_binary" ./cmd/archive-keeper-ui
        chmod 755 "$ui_binary"
    else
        printf 'Installation stopped: this source tree does not contain the bundled Storage Galaxy binary.\n' >&2
        printf 'Install from the combined release archive, or install Go to build a development checkout.\n' >&2
        exit 1
    fi
fi

python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install .
installed_version="$(python -c 'from archive_keeper import __version__; print(__version__)')"
printf '\nArchive Keeper %s installed.\n' "$installed_version"
printf 'Activate with:\n  source %q/.venv/bin/activate\n' "$PWD"
printf 'Verify with:\n  archive-keeper --version\n'
printf 'Start Storage Galaxy with:\n  archive-keeper ui\n'
printf 'Verify the bundled interface with:\n  archive-keeper ui --health-check\n'
printf 'Start the visual reviewer with:\n  archive-keeper --prefer /mnt/MyCloud1 --prefer /mnt/MyCloud2 --prefer /mnt/MyCloud3 review\n'
