#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"
python3 -m venv .venv
. .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install .
printf '\nArchive Keeper 1.6.1 installed.\n'
printf 'Activate with:\n  source %q/.venv/bin/activate\n' "$PWD"
printf 'Start the visual reviewer with:\n  archive-keeper --prefer /mnt/MyCloud1 --prefer /mnt/MyCloud2 --prefer /mnt/MyCloud3 review\n'
