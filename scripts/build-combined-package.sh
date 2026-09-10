#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$project_root"

command -v go >/dev/null 2>&1 || {
    printf 'Go is required to build the maintainer release package. End users do not need Go.\n' >&2
    exit 1
}

version="$(python3 -c 'from archive_keeper import __version__; print(__version__)')"
go_os="$(go env GOOS)"
go_arch="$(go env GOARCH)"
bundle_name="archive-keeper-$version-$go_os-$go_arch"
build_root="$(mktemp -d "${TMPDIR:-/tmp}/archive-keeper-package.XXXXXX")"
stage="$build_root/$bundle_name"
trap 'rm -rf -- "$build_root"' EXIT

mkdir -p "$stage"
git archive HEAD | tar -x -C "$stage"
mkdir -p "$stage/archive_keeper/bin"

printf 'Building Storage Galaxy for %s/%s...\n' "$go_os" "$go_arch"
CGO_ENABLED=0 \
    go build -trimpath -ldflags='-s -w' \
    -o "$stage/archive_keeper/bin/archive-keeper-ui" ./cmd/archive-keeper-ui
chmod 755 "$stage/archive_keeper/bin/archive-keeper-ui"

mkdir -p dist
python3 -m pip wheel --no-deps --wheel-dir dist "$stage"
tar -C "$build_root" -czf "dist/$bundle_name.tar.gz" "$bundle_name"
(
    cd dist
    sha256sum "$bundle_name.tar.gz" > "$bundle_name.tar.gz.sha256"
    sha256sum -c "$bundle_name.tar.gz.sha256"
)

printf '\nCombined package ready:\n'
printf '  dist/%s.tar.gz\n' "$bundle_name"
printf '  dist/%s.tar.gz.sha256\n' "$bundle_name"
printf '  dist/archive_keeper-%s-*.whl\n' "${version//-/_}"
