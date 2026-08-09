from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from .core import files_match, human_bytes


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--keeper", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--min-free-bytes", type=int, default=0)
    parser.add_argument("--deep-verify", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    result = {"ok": False, "message": "verification failed"}
    try:
        ok, message = files_match(args.keeper, args.source, deep_verify=args.deep_verify)
        if not ok:
            result["message"] = message
        else:
            usage = shutil.disk_usage(args.source_root)
            if usage.free < args.min_free_bytes:
                result["message"] = f"free space below threshold: {human_bytes(usage.free)}"
            elif args.destination.exists():
                result["message"] = "quarantine destination already exists"
            else:
                result = {"ok": True, "message": message}
    except OSError as exc:
        result["message"] = f"filesystem check failed: {exc}"
    except Exception as exc:  # keep worker failures contained and machine-readable
        result["message"] = f"verification worker failed: {exc}"
    print(json.dumps(result), flush=True)
    return 0 if result["ok"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
