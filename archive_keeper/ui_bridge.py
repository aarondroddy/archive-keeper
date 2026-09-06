from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import Counter
from contextlib import closing
from pathlib import Path
from typing import Any

from . import __version__
from .cli import DEFAULT_DECISIONS, DEFAULT_REPORT, DEFAULT_STATE
from .core import ArchiveKeeperError, human_bytes, load_rmlint_groups, normalize_path
from .decisions import DecisionStore


PROTOCOL_VERSION = 1


def _readonly_connection(path: Path) -> sqlite3.Connection:
    """Open an existing SQLite database without creating or changing it."""
    absolute = normalize_path(path)
    connection = sqlite3.connect(f"{absolute.as_uri()}?mode=ro", uri=True)
    connection.execute("PRAGMA query_only=ON")
    return connection


def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
    row = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    return row is not None


def _report_summary(path: Path, warnings: list[str]) -> dict[str, Any]:
    path = normalize_path(path)
    result: dict[str, Any] = {
        "path": str(path),
        "exists": path.is_file(),
        "groups": 0,
        "files": 0,
        "recoverable_bytes": 0,
        "recoverable_human": human_bytes(0),
        "largest_groups": [],
    }
    if not result["exists"]:
        warnings.append(f"rmlint report not found: {path}")
        return result

    try:
        groups = load_rmlint_groups(path)
    except ArchiveKeeperError as exc:
        warnings.append(str(exc))
        return result

    recoverable = sum(group.recoverable_bytes for group in groups)
    result.update(
        groups=len(groups),
        files=sum(len(group.files) for group in groups),
        recoverable_bytes=recoverable,
        recoverable_human=human_bytes(recoverable),
        largest_groups=[
            {
                "group_id": group.group_id,
                "copies": len(group.files),
                "size": group.size,
                "recoverable_bytes": group.recoverable_bytes,
                "recoverable_human": human_bytes(group.recoverable_bytes),
                "sample_path": str(group.files[0].path),
                "files": [
                    {
                        "path": str(item.path),
                        "size": item.size,
                        "size_human": human_bytes(item.size),
                        "original_hint": item.is_original_hint,
                        "checksum": item.checksum,
                    }
                    for item in group.files
                ],
            }
            for group in sorted(groups, key=lambda item: item.recoverable_bytes, reverse=True)[:8]
        ],
    )
    return result


def _decision_summary(path: Path, warnings: list[str]) -> dict[str, Any]:
    path = normalize_path(path)
    result: dict[str, Any] = {
        "path": str(path),
        "exists": path.is_file(),
        "keepers": 0,
        "file_decisions": 0,
        "favorites": 0,
        "actions": {},
        "keeper_paths": {},
        "file_actions": {},
    }
    if not result["exists"]:
        warnings.append(f"decision database not found: {path}")
        return result

    try:
        with closing(_readonly_connection(path)) as connection:
            if _table_exists(connection, "keeper_decisions"):
                keeper_rows = connection.execute(
                    "SELECT group_id, keeper_path FROM keeper_decisions"
                ).fetchall()
                result["keepers"] = len(keeper_rows)
                result["keeper_paths"] = {
                    str(group_id): str(keeper_path) for group_id, keeper_path in keeper_rows
                }
            if _table_exists(connection, "file_decisions"):
                rows = connection.execute(
                    "SELECT action, COUNT(*) FROM file_decisions GROUP BY action"
                ).fetchall()
                result["actions"] = {str(action): count for action, count in rows}
                result["file_decisions"] = sum(result["actions"].values())
                action_rows = connection.execute(
                    "SELECT group_id, path, action FROM file_decisions"
                ).fetchall()
                result["file_actions"] = {
                    f"{group_id}\n{path}": str(action)
                    for group_id, path, action in action_rows
                }
            if _table_exists(connection, "favorites"):
                result["favorites"] = connection.execute(
                    "SELECT COUNT(*) FROM favorites"
                ).fetchone()[0]
    except sqlite3.Error as exc:
        warnings.append(f"cannot read decision database {path}: {exc}")
    return result


def _journal_summary(path: Path, warnings: list[str]) -> dict[str, Any]:
    path = normalize_path(path)
    result: dict[str, Any] = {
        "path": str(path),
        "exists": path.is_file(),
        "runs": 0,
        "status_counts": {},
        "latest_runs": [],
    }
    if not result["exists"]:
        warnings.append(f"journal database not found: {path}")
        return result

    try:
        with closing(_readonly_connection(path)) as connection:
            if _table_exists(connection, "runs"):
                result["runs"] = connection.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
                rows = connection.execute(
                    "SELECT run_id, created_at, mode, status FROM runs "
                    "ORDER BY created_at DESC LIMIT 5"
                ).fetchall()
                result["latest_runs"] = [
                    {"run_id": row[0], "created_at": row[1], "mode": row[2], "status": row[3]}
                    for row in rows
                ]
            if _table_exists(connection, "actions"):
                counts = Counter(
                    {str(status): count for status, count in connection.execute(
                        "SELECT status, COUNT(*) FROM actions GROUP BY status"
                    )}
                )
                result["status_counts"] = dict(counts)
    except sqlite3.Error as exc:
        warnings.append(f"cannot read journal database {path}: {exc}")
    return result


def dashboard_snapshot(report: Path, state_db: Path, decisions_db: Path) -> dict[str, Any]:
    warnings: list[str] = []
    snapshot = {
        "protocol_version": PROTOCOL_VERSION,
        "ok": True,
        "mode": "read-only",
        "archive_keeper_version": __version__,
        "report": _report_summary(report, warnings),
        "decisions": _decision_summary(decisions_db, warnings),
        "journal": _journal_summary(state_db, warnings),
        "warnings": warnings,
    }
    snapshot["ok"] = snapshot["report"]["exists"] and not any(
        warning.startswith(("Invalid JSON", "No duplicate", "Expected rmlint"))
        for warning in warnings
    )
    return snapshot


def select_keeper(report: Path, decisions_db: Path, group_id: int, keeper: Path) -> dict[str, Any]:
    """Validate and persist one keeper decision without touching archive files."""
    report = normalize_path(report)
    keeper = normalize_path(keeper)
    result: dict[str, Any] = {
        "protocol_version": PROTOCOL_VERSION,
        "ok": False,
        "operation": "select-keeper",
        "files_moved": 0,
        "group_id": group_id,
        "keeper_path": str(keeper),
    }

    try:
        groups = load_rmlint_groups(report)
    except ArchiveKeeperError as exc:
        result["error"] = str(exc)
        return result

    group = next((item for item in groups if item.group_id == group_id), None)
    if group is None:
        result["error"] = f"duplicate group not found in report: {group_id}"
        return result
    if keeper not in {normalize_path(item.path) for item in group.files}:
        result["error"] = f"selected keeper is not a member of group {group_id}"
        return result

    try:
        store = DecisionStore(decisions_db)
        try:
            store.set_keeper(group_id, keeper, "selected in Storage Galaxy UI")
            store.clear_action(group_id, keeper)
        finally:
            store.close()
    except (OSError, sqlite3.Error) as exc:
        result["error"] = f"cannot save keeper decision: {exc}"
        return result
    result["ok"] = True
    return result


def set_file_action(
    report: Path, decisions_db: Path, group_id: int, target: Path, action: str
) -> dict[str, Any]:
    """Stage or clear one file decision without moving an archive file."""
    report = normalize_path(report)
    decisions_db = normalize_path(decisions_db)
    target = normalize_path(target)
    action = action.upper()
    result: dict[str, Any] = {
        "protocol_version": PROTOCOL_VERSION,
        "ok": False,
        "operation": "set-file-action",
        "files_moved": 0,
        "group_id": group_id,
        "path": str(target),
        "action": action,
    }
    if action not in {"QUARANTINE", "UNDECIDED", "CLEAR"}:
        result["error"] = f"unsupported file action: {action}"
        return result

    try:
        groups = load_rmlint_groups(report)
    except ArchiveKeeperError as exc:
        result["error"] = str(exc)
        return result
    group = next((item for item in groups if item.group_id == group_id), None)
    if group is None:
        result["error"] = f"duplicate group not found in report: {group_id}"
        return result
    if target not in {normalize_path(item.path) for item in group.files}:
        result["error"] = f"selected file is not a member of group {group_id}"
        return result
    if not decisions_db.is_file():
        result["error"] = "choose a keeper before staging file decisions"
        return result

    try:
        with closing(_readonly_connection(decisions_db)) as connection:
            if not _table_exists(connection, "keeper_decisions"):
                result["error"] = "choose a keeper before staging file decisions"
                return result
            row = connection.execute(
                "SELECT keeper_path FROM keeper_decisions WHERE group_id=?", (group_id,)
            ).fetchone()
        if row is None:
            result["error"] = f"choose a keeper for group {group_id} first"
            return result
        keeper = normalize_path(row[0])
        if target == keeper and action != "CLEAR":
            result["error"] = "the selected keeper cannot be staged for quarantine"
            return result

        store = DecisionStore(decisions_db)
        try:
            if action == "CLEAR":
                store.clear_action(group_id, target)
            else:
                store.set_action(group_id, target, action)
        finally:
            store.close()
    except (OSError, sqlite3.Error) as exc:
        result["error"] = f"cannot save file decision: {exc}"
        return result
    result["ok"] = True
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="archive-keeper-ui-bridge")
    subparsers = parser.add_subparsers(dest="command", required=True)
    dashboard = subparsers.add_parser("dashboard", help="Emit a read-only dashboard snapshot as JSON")
    dashboard.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    dashboard.add_argument("--state-db", type=Path, default=DEFAULT_STATE)
    dashboard.add_argument("--decisions-db", type=Path, default=DEFAULT_DECISIONS)
    keeper = subparsers.add_parser("select-keeper", help="Validate and save one keeper decision")
    keeper.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    keeper.add_argument("--decisions-db", type=Path, default=DEFAULT_DECISIONS)
    keeper.add_argument("--group-id", type=int, required=True)
    keeper.add_argument("--keeper", type=Path, required=True)
    file_action = subparsers.add_parser(
        "set-file-action", help="Validate and stage one non-destructive file decision"
    )
    file_action.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    file_action.add_argument("--decisions-db", type=Path, default=DEFAULT_DECISIONS)
    file_action.add_argument("--group-id", type=int, required=True)
    file_action.add_argument("--path", type=Path, required=True)
    file_action.add_argument(
        "--action", choices=("QUARANTINE", "UNDECIDED", "CLEAR"), required=True
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "dashboard":
        json.dump(dashboard_snapshot(args.report, args.state_db, args.decisions_db), sys.stdout)
        sys.stdout.write("\n")
        return 0
    if args.command == "select-keeper":
        result = select_keeper(args.report, args.decisions_db, args.group_id, args.keeper)
        json.dump(result, sys.stdout)
        sys.stdout.write("\n")
        return 0 if result["ok"] else 1
    if args.command == "set-file-action":
        result = set_file_action(
            args.report, args.decisions_db, args.group_id, args.path, args.action
        )
        json.dump(result, sys.stdout)
        sys.stdout.write("\n")
        return 0 if result["ok"] else 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
