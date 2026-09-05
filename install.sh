#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install .
installed_version="$(python -c 'from archive_keeper import __version__; print(__version__)')"
printf '\nArchive Keeper %s installed.\n' "$installed_version"
printf 'Activate with:\n  source %q/.venv/bin/activate\n' "$PWD"
printf 'Verify with:\n  archive-keeper --version\n'
printf 'Start the visual reviewer with:\n  archive-keeper --prefer /mnt/MyCloud1 --prefer /mnt/MyCloud2 --prefer /mnt/MyCloud3 review\n'
