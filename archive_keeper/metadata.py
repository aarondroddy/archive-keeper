from __future__ import annotations

import json
import mimetypes
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class MediaMetadata:
    path: Path
    kind: str
    mime: str
    details: dict[str, str] = field(default_factory=dict)
    preview: str = ""
    preview_command: list[str] | None = None


def _run(command: list[str], timeout: int = 8) -> str:
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return result.stdout.strip()


def _kind(path: Path, mime: str) -> str:
    if mime.startswith("image/"):
        return "image"
    if mime.startswith("video/"):
        return "video"
    if mime.startswith("audio/"):
        return "audio"
    if mime == "application/pdf":
        return "pdf"
    if mime.startswith("text/") or path.suffix.lower() in {".md", ".json", ".toml", ".yaml", ".yml", ".csv", ".log"}:
        return "text"
    if path.suffix.lower() in {".doc", ".docx", ".odt", ".xls", ".xlsx", ".ppt", ".pptx"}:
        return "office"
    if path.suffix.lower() in {".zip", ".tar", ".gz", ".bz2", ".xz", ".7z", ".rar"}:
        return "archive"
    return "other"


def inspect_path(path: Path) -> MediaMetadata:
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    kind = _kind(path, mime)
    meta = MediaMetadata(path=path, kind=kind, mime=mime)
    try:
        stat = path.stat()
        meta.details.update({
            "size": str(stat.st_size),
            "modified": str(int(stat.st_mtime)),
            "mode": oct(stat.st_mode & 0o777),
        })
    except OSError as exc:
        meta.details["error"] = str(exc)
        return meta

    if kind in {"video", "audio"} and shutil.which("ffprobe"):
        raw = _run(["ffprobe", "-v", "quiet", "-print_format", "json", "-show_format", "-show_streams", str(path)], timeout=15)
        try:
            data = json.loads(raw)
            fmt = data.get("format", {})
            if fmt.get("duration"):
                meta.details["duration"] = f"{float(fmt['duration']):.2f}s"
            if fmt.get("bit_rate"):
                meta.details["bitrate"] = fmt["bit_rate"]
            for stream in data.get("streams", []):
                stype = stream.get("codec_type")
                if stype == "video":
                    meta.details["video_codec"] = stream.get("codec_name", "")
                    if stream.get("width") and stream.get("height"):
                        meta.details["resolution"] = f"{stream['width']}x{stream['height']}"
                elif stype == "audio":
                    meta.details.setdefault("audio_codec", stream.get("codec_name", ""))
        except (json.JSONDecodeError, TypeError, ValueError):
            pass

    elif kind == "image":
        if shutil.which("identify"):
            line = _run(["identify", "-format", "%m %wx%h %[EXIF:DateTimeOriginal]", str(path)])
            if line:
                parts = line.split(maxsplit=2)
                if parts:
                    meta.details["format"] = parts[0]
                if len(parts) > 1:
                    meta.details["resolution"] = parts[1]
                if len(parts) > 2 and parts[2]:
                    meta.details["date_taken"] = parts[2]
        if shutil.which("chafa"):
            meta.preview_command = ["chafa", "--size", "60x20", str(path)]

    elif kind == "pdf":
        if shutil.which("pdfinfo"):
            for line in _run(["pdfinfo", str(path)]).splitlines():
                if ":" in line:
                    key, value = line.split(":", 1)
                    if key.strip() in {"Pages", "Title", "Author", "Page size"}:
                        meta.details[key.strip().lower().replace(" ", "_")] = value.strip()
        if shutil.which("pdftotext"):
            meta.preview = _run(["pdftotext", "-f", "1", "-l", "1", str(path), "-"])[:3000]

    elif kind == "text":
        try:
            meta.preview = path.read_text(encoding="utf-8", errors="replace")[:3000]
        except OSError:
            pass

    elif kind == "office" and shutil.which("libreoffice"):
        meta.details["preview_support"] = "LibreOffice available; open externally for full preview"

    elif kind == "archive":
        if shutil.which("bsdtar"):
            meta.preview = _run(["bsdtar", "-tf", str(path)])[:3000]
        elif shutil.which("unzip") and path.suffix.lower() == ".zip":
            meta.preview = _run(["unzip", "-l", str(path)])[:3000]

    return meta
