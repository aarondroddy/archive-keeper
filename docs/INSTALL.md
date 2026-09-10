# Installation

## Requirements

- Linux
- Python 3.10 or newer
- an existing rmlint JSON report

The official combined archive includes Storage Galaxy. Go is required only by
maintainers building a release or by developers installing directly from a
source checkout that does not contain the bundled executable.

Optional preview tools:

- `ffprobe` from `ffmpeg`
- `chafa`
- ImageMagick
- Poppler utilities

On Kali or Debian:

```bash
sudo apt update
sudo apt install python3-venv ffmpeg chafa imagemagick poppler-utils
```

## Install from a release archive

Run these commands from the directory containing the release files:

```bash
sha256sum -c archive-keeper-2.0.0-linux-amd64.tar.gz.sha256
tar -xzf archive-keeper-2.0.0-linux-amd64.tar.gz
cd archive-keeper
./install.sh
source .venv/bin/activate
archive-keeper --version
archive-keeper --help
archive-keeper ui --health-check
archive-keeper ui
```

The architecture suffix may differ on a non-amd64 system.

The single installation contains the complete Python safety engine and the
Storage Galaxy interface. `archive-keeper ui` locates the packaged interface;
users do not compile or install a second program.

## Build a combined package (maintainers)

```bash
bash scripts/build-combined-package.sh
```

The builder compiles Storage Galaxy, embeds it in the Python package, creates
an installable wheel and a full source-plus-binary archive, and writes a
SHA-256 checksum. The artifact name records its operating system and CPU
architecture because the embedded interface is platform-specific.

Default report location:

```text
~/rmlint-mycloud-scan/rmlint.json
```
