# Installation

## Requirements

- Linux
- Python 3.10 or newer
- an existing rmlint JSON report

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
sha256sum -c archive-keeper-1.6.8.tar.gz.sha256
tar -xzf archive-keeper-1.6.8.tar.gz
cd archive-keeper
./install.sh
source .venv/bin/activate
archive-keeper --version
archive-keeper --help
```

Default report location:

```text
~/rmlint-mycloud-scan/rmlint.json
```
