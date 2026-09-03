#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$project_root"

version="$(python3 -c 'from archive_keeper import __version__; print(__version__)')"
archive="archive-keeper-$version.tar.gz"
checksum="$archive.sha256"

if ! git diff --quiet || ! git diff --cached --quiet; then
  printf 'Release check refused: the working tree has uncommitted changes.\n' >&2
  exit 1
fi

printf 'Testing Archive Keeper %s...\n' "$version"
python3 -m unittest discover -s tests -v

release_tmp="$(mktemp -d)"
trap 'rm -rf "$release_tmp"' EXIT
python3 -m venv "$release_tmp/venv"
"$release_tmp/venv/bin/python" -m pip install --quiet .
actual="$("$release_tmp/venv/bin/archive-keeper" --version)"
expected="archive-keeper $version"
if [[ "$actual" != "$expected" ]]; then
  printf 'Smoke test failed: expected %q, got %q\n' "$expected" "$actual" >&2
  exit 1
fi

mkdir -p dist
git archive --format=tar.gz --prefix=archive-keeper/ -o "dist/$archive" HEAD
(
  cd dist
  sha256sum "$archive" > "$checksum"
  sha256sum -c "$checksum"
)

printf '\nRelease candidate ready:\n  dist/%s\n  dist/%s\n' "$archive" "$checksum"
printf 'Next: inspect the archive, tag the reviewed commit, and publish only after the draft PR is merged.\n'
