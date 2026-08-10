from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from .core import files_match, human_bytes, sha256_file


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--keeper", type=Path)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--destination", type=Path)
    parser.add_argument("--source-root", type=Path)
    parser.add_argument("--min-free-bytes", type=int, default=0)
    parser.add_argument("--deep-verify", action="store_true")
    parser.add_argument("--compare-a", type=Path)
    parser.add_argument("--compare-b", type=Path)
    return parser


def _sha256_identical(a: Path, b: Path) -> tuple[bool, str]:
    try:
        sa = a.stat()
        sb = b.stat()
        if not a.is_file() or not b.is_file():
            return False, "not a regular file"
        if sa.st_size != sb.st_size:
            return False, "size mismatch"
        if sa.st_dev == sb.st_dev and sa.st_ino == sb.st_ino:
            return True, "same inode"
        identical = sha256_file(a) == sha256_file(b)
        return identical, "sha256 identical" if identical else "sha256 mismatch"
    except OSError as exc:
        return False, f"filesystem check failed: {exc}"


def main() -> int:
    args = build_parser().parse_args()

    if args.compare_a is not None or args.compare_b is not None:
        if args.compare_a is None or args.compare_b is None:
            print(json.dumps({"identical": False, "message": "both comparison paths are required"}), flush=True)
            return 2
        identical, message = _sha256_identical(args.compare_a, args.compare_b)
        print(json.dumps({"identical": identical, "message": message}), flush=True)
        return 0 if identical else 2

    required = (args.keeper, args.source, args.destination, args.source_root)
    if any(value is None for value in required):
        print(json.dumps({"ok": False, "message": "missing quarantine verification arguments", "outcome": "failed"}), flush=True)
        return 2

    result = {"ok": False, "message": "verification failed", "outcome": "failed"}
    try:
        ok, message = files_match(args.keeper, args.source, deep_verify=args.deep_verify)
        if not ok:
            result["message"] = message
        else:
            usage = shutil.disk_usage(args.source_root)
            if usage.free < args.min_free_bytes:
                result["message"] = f"free space below threshold: {human_bytes(usage.free)}"
            elif args.destination.exists():
                identical, collision_message = _sha256_identical(args.source, args.destination)
                if identical:
                    result = {
                        "ok": True,
                        "message": "quarantine destination already exists and is SHA-256 identical",
                        "outcome": "destination-identical",
                    }
                else:
                    result["message"] = f"quarantine destination collision: {collision_message}"
                    result["outcome"] = "destination-conflict"
            else:
                result = {"ok": True, "message": message, "outcome": "ready"}
    except OSError as exc:
        result["message"] = f"filesystem check failed: {exc}"
    except Exception as exc:
        result["message"] = f"verification worker failed: {exc}"
    print(json.dumps(result), flush=True)
    return 0 if result["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
