from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import secrets
import sqlite3
import subprocess
import sys
from collections import Counter
from contextlib import closing
from pathlib import Path
from typing import Any

from . import __version__
from .cli import (
    DEFAULT_DECISIONS,
    DEFAULT_QUARANTINE_NAME,
    DEFAULT_REPORT,
    DEFAULT_ROOTS,
    DEFAULT_STATE,
)
from .core import (
    ArchiveKeeperError,
    Journal,
    bounded_quarantine_preflight,
    human_bytes,
    load_rmlint_groups,
    mount_root_for,
    move_noreplace,
    normalize_path,
    quarantine_destination,
)
from .decisions import DecisionStore


PROTOCOL_VERSION = 1
PREVIEW_RUN_ID = "storage-galaxy-preview"
PATH_PROBE_TIMEOUT = 2.0
MAX_CONTROLLED_APPLY_FILES = 10
MAX_CONTROLLED_RESTORE_FILES = 10


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


def _mount_summary(roots: list[Path], mountinfo_text: str | None = None) -> dict[str, Any]:
    """Read kernel mount metadata without issuing potentially blocking NAS stats."""
    if mountinfo_text is None:
        try:
            mountinfo_text = Path("/proc/self/mountinfo").read_text(encoding="utf-8")
        except OSError:
            mountinfo_text = ""
    mounted: dict[str, tuple[str, str]] = {}
    for line in mountinfo_text.splitlines():
        try:
            left, right = line.split(" - ", 1)
            mount_point = left.split()[4].replace("\\040", " ")
            filesystem, source = right.split()[:2]
            mounted[str(normalize_path(mount_point))] = (filesystem, source.replace("\\040", " "))
        except (IndexError, ValueError):
            continue
    entries = []
    for root in roots:
        filesystem, source = mounted.get(str(root), ("", ""))
        is_mounted = bool(filesystem)
        entries.append({"path": str(root), "mounted": is_mounted, "filesystem": filesystem,
                        "source": source, "status": "ONLINE" if is_mounted else "OFFLINE"})
    return {"all_ready": bool(entries) and all(item["mounted"] for item in entries),
            "roots": entries}


def _report_summary(path: Path, warnings: list[str], roots: list[Path]) -> dict[str, Any]:
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
                "mount_root": str(mount_root_for(normalize_path(group.files[0].path), roots) or "Unmapped"),
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
            for group in sorted(groups, key=lambda item: item.recoverable_bytes, reverse=True)[:24]
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


def dashboard_snapshot(
    report: Path, state_db: Path, decisions_db: Path,
    mount_roots: list[Path] | None = None,
) -> dict[str, Any]:
    warnings: list[str] = []
    roots = [normalize_path(root) for root in (mount_roots or DEFAULT_ROOTS)]
    snapshot = {
        "protocol_version": PROTOCOL_VERSION,
        "ok": True,
        "mode": "read-only",
        "archive_keeper_version": __version__,
        "report": _report_summary(report, warnings, roots),
        "mounts": _mount_summary(roots),
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


def _bounded_path_probe(paths: list[Path]) -> tuple[dict[str, str], str | None]:
    """Inspect a small set of live paths without allowing a stale NAS to hang the UI."""
    script = (
        "import json, os, sys\n"
        "result = {}\n"
        "for value in sys.argv[1:]:\n"
        "    try:\n"
        "        result[value] = 'file' if os.path.isfile(value) else "
        "('exists' if os.path.exists(value) else 'missing')\n"
        "    except OSError as exc:\n"
        "        result[value] = 'error:' + str(exc)\n"
        "print(json.dumps(result))\n"
    )
    values = [str(normalize_path(path)) for path in paths]
    try:
        completed = subprocess.run(
            [sys.executable, "-c", script, *values],
            check=False,
            capture_output=True,
            text=True,
            timeout=PATH_PROBE_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        return {}, f"live path check exceeded {PATH_PROBE_TIMEOUT:g}s"
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "path check failed").strip()
        return {}, detail
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return {}, "live path check returned invalid data"
    return {str(key): str(value) for key, value in payload.items()}, None


def quarantine_plan_snapshot(
    report: Path,
    decisions_db: Path,
    mount_roots: list[Path] | None = None,
    quarantine_name: str = DEFAULT_QUARANTINE_NAME,
    run_id: str = PREVIEW_RUN_ID,
) -> dict[str, Any]:
    """Build a read-only plan from explicit QUARANTINE decisions.

    The destination is computed by the same helper used by the Python engine.
    No journal rows, directories, or archive files are created.
    """
    report = normalize_path(report)
    decisions_db = normalize_path(decisions_db)
    roots = [normalize_path(root) for root in (mount_roots or DEFAULT_ROOTS)]
    warnings: list[str] = []
    result: dict[str, Any] = {
        "protocol_version": PROTOCOL_VERSION,
        "ok": False,
        "mode": "read-only",
        "operation": "quarantine-plan",
        "files_moved": 0,
        "run_id": run_id,
        "quarantine_name": quarantine_name,
        "total_files": 0,
        "total_bytes": 0,
        "total_human": human_bytes(0),
        "ready_files": 0,
        "blocked_files": 0,
        "items": [],
        "warnings": warnings,
    }
    try:
        groups = load_rmlint_groups(report)
    except ArchiveKeeperError as exc:
        warnings.append(str(exc))
        return result
    group_map = {group.group_id: group for group in groups}

    if not decisions_db.is_file():
        warnings.append(f"decision database not found: {decisions_db}")
        result["ok"] = True
        return result
    try:
        with closing(_readonly_connection(decisions_db)) as connection:
            if not _table_exists(connection, "file_decisions"):
                result["ok"] = True
                return result
            staged = connection.execute(
                "SELECT group_id, path FROM file_decisions "
                "WHERE action='QUARANTINE' ORDER BY group_id, path"
            ).fetchall()
            keepers = {}
            if _table_exists(connection, "keeper_decisions"):
                keepers = {
                    int(group_id): normalize_path(path)
                    for group_id, path in connection.execute(
                        "SELECT group_id, keeper_path FROM keeper_decisions"
                    )
                }
    except sqlite3.Error as exc:
        warnings.append(f"cannot read decision database {decisions_db}: {exc}")
        return result

    root_mounted = {root: root.is_dir() and os.path.ismount(root) for root in roots}
    for group_id, path_text in staged:
        source = normalize_path(path_text)
        keeper = keepers.get(int(group_id))
        group = group_map.get(int(group_id))
        reasons: list[str] = []
        destination: Path | None = None
        size = 0

        if group is None:
            reasons.append("group is stale or absent from the current report")
        else:
            members = {normalize_path(item.path): item for item in group.files}
            source_item = members.get(source)
            if source_item is None:
                reasons.append("source is stale or absent from the current report group")
            else:
                size = source_item.size
            if keeper is None:
                reasons.append("keeper decision is missing")
            elif keeper not in members:
                reasons.append("keeper is stale or absent from the current report group")
            elif keeper == source:
                reasons.append("keeper cannot also be quarantined")

        source_root = mount_root_for(source, roots)
        keeper_root = mount_root_for(keeper, roots) if keeper is not None else None
        if source_root is None:
            reasons.append("source is outside configured mount roots")
        else:
            destination = quarantine_destination(source, source_root, quarantine_name, run_id)
            if not root_mounted[source_root]:
                reasons.append(f"source mount is unavailable: {source_root}")
        if keeper is not None:
            if keeper_root is None:
                reasons.append("keeper is outside configured mount roots")
            elif not root_mounted[keeper_root]:
                reasons.append(f"keeper mount is unavailable: {keeper_root}")

        if not reasons and keeper is not None and destination is not None:
            statuses, probe_error = _bounded_path_probe([source, keeper, destination])
            if probe_error:
                reasons.append(f"live validation unavailable: {probe_error}")
            else:
                if statuses.get(str(source)) != "file":
                    reasons.append("source file is missing or not a regular file")
                if statuses.get(str(keeper)) != "file":
                    reasons.append("keeper file is missing or not a regular file")
                destination_status = statuses.get(str(destination))
                if destination_status != "missing":
                    reasons.append("quarantine destination already exists (collision)")

        status = "READY" if not reasons else "BLOCKED"
        result["items"].append(
            {
                "group_id": int(group_id),
                "status": status,
                "size": size,
                "size_human": human_bytes(size),
                "source": str(source),
                "keeper": str(keeper) if keeper is not None else "",
                "destination": str(destination) if destination is not None else "",
                "warnings": reasons,
            }
        )

    result["total_files"] = len(result["items"])
    result["total_bytes"] = sum(item["size"] for item in result["items"])
    result["total_human"] = human_bytes(result["total_bytes"])
    result["ready_files"] = sum(item["status"] == "READY" for item in result["items"])
    result["blocked_files"] = result["total_files"] - result["ready_files"]
    result["ok"] = True
    return result


def quarantine_dry_run(
    report: Path,
    decisions_db: Path,
    mount_roots: list[Path] | None = None,
    quarantine_name: str = DEFAULT_QUARANTINE_NAME,
    run_id: str = PREVIEW_RUN_ID,
    limit: int = 10,
    verify_timeout: float = 5.0,
) -> dict[str, Any]:
    """Run bounded engine preflight checks without moving files or writing a journal."""
    roots = [normalize_path(root) for root in (mount_roots or DEFAULT_ROOTS)]
    plan = quarantine_plan_snapshot(
        report, decisions_db, roots, quarantine_name, run_id
    )
    result: dict[str, Any] = {
        "protocol_version": PROTOCOL_VERSION,
        "ok": plan["ok"],
        "mode": "dry-run",
        "operation": "quarantine-dry-run",
        "files_moved": 0,
        "journal_writes": 0,
        "limit": max(1, int(limit)),
        "verify_timeout": max(0.1, float(verify_timeout)),
        "total_staged": plan["total_files"],
        "attempted": 0,
        "verified": 0,
        "blocked": 0,
        "timed_out": 0,
        "verified_bytes": 0,
        "verified_human": human_bytes(0),
        "limited": False,
        "items": [],
        "warnings": list(plan["warnings"]),
    }
    if not plan["ok"]:
        return result

    selected = plan["items"][: result["limit"]]
    result["limited"] = len(plan["items"]) > len(selected)
    for item in selected:
        dry_item = {
            "group_id": item["group_id"],
            "source": item["source"],
            "keeper": item["keeper"],
            "destination": item["destination"],
            "size_human": item["size_human"],
            "outcome": "blocked",
            "message": " · ".join(item["warnings"]),
        }
        result["attempted"] += 1
        if item["status"] != "READY":
            result["blocked"] += 1
            result["items"].append(dry_item)
            continue

        source = normalize_path(item["source"])
        keeper = normalize_path(item["keeper"])
        destination = normalize_path(item["destination"])
        source_root = mount_root_for(source, roots)
        if source_root is None:
            result["blocked"] += 1
            dry_item["message"] = "source is outside configured mount roots"
            result["items"].append(dry_item)
            continue
        ok, message, timed_out, outcome = bounded_quarantine_preflight(
            keeper,
            source,
            destination,
            source_root,
            expected_size=int(item["size"]),
            timeout=result["verify_timeout"],
        )
        dry_item["outcome"] = outcome if ok else ("timeout" if timed_out else "blocked")
        dry_item["message"] = message
        if ok:
            result["verified"] += 1
            result["verified_bytes"] += int(item["size"])
        else:
            result["blocked"] += 1
        if timed_out:
            result["timed_out"] += 1
        result["items"].append(dry_item)

    result["verified_human"] = human_bytes(result["verified_bytes"])
    return result


def controlled_quarantine_apply(
    report: Path,
    state_db: Path,
    decisions_db: Path,
    confirmation: str,
    mount_roots: list[Path] | None = None,
    quarantine_name: str = DEFAULT_QUARANTINE_NAME,
    run_id: str | None = None,
    limit: int = MAX_CONTROLLED_APPLY_FILES,
    verify_timeout: float = 30.0,
) -> dict[str, Any]:
    """Move only explicitly staged files behind a strict confirmation gate."""
    limit = int(limit)
    expected_confirmation = f"QUARANTINE UP TO {limit} FILES"
    result: dict[str, Any] = {
        "protocol_version": PROTOCOL_VERSION,
        "ok": False,
        "mode": "apply",
        "operation": "quarantine-apply",
        "files_moved": 0,
        "bytes_moved": 0,
        "bytes_moved_human": human_bytes(0),
        "reconciled": 0,
        "stale": 0,
        "failed": 0,
        "timed_out": 0,
        "limit": limit,
        "expected_confirmation": expected_confirmation,
        "run_id": run_id or "",
        "items": [],
        "error": "",
    }
    if limit < 1 or limit > MAX_CONTROLLED_APPLY_FILES:
        result["error"] = (
            f"controlled quarantine limit must be between 1 and "
            f"{MAX_CONTROLLED_APPLY_FILES}"
        )
        return result
    if confirmation != expected_confirmation:
        result["error"] = f"confirmation must exactly match: {expected_confirmation}"
        return result

    roots = [normalize_path(root) for root in (mount_roots or DEFAULT_ROOTS)]
    run_id = run_id or (
        f"ui-{dt.datetime.now(dt.timezone.utc).strftime('%Y%m%d-%H%M%S')}-"
        f"{secrets.token_hex(2)}"
    )
    result["run_id"] = run_id
    plan = quarantine_plan_snapshot(
        report, decisions_db, roots, quarantine_name, run_id
    )
    if not plan["ok"]:
        result["error"] = "; ".join(plan["warnings"]) or "cannot build quarantine plan"
        return result
    candidates = [item for item in plan["items"] if item["status"] == "READY"][:limit]
    if not candidates:
        result["error"] = "no staged files passed the final preview checks"
        return result

    journal: Journal | None = None
    try:
        journal = Journal(normalize_path(state_db))
        journal.create_run(run_id, normalize_path(report), "apply")
        for item in candidates:
            source = normalize_path(item["source"])
            keeper = normalize_path(item["keeper"])
            destination = normalize_path(item["destination"])
            source_root = mount_root_for(source, roots)
            action = {
                "group_id": int(item["group_id"]),
                "source": str(source),
                "keeper": str(keeper),
                "destination": str(destination),
                "size_human": item["size_human"],
                "status": "failed",
                "message": "",
            }
            if source_root is None:
                action["message"] = "source is outside configured mount roots"
                result["failed"] += 1
                result["items"].append(action)
                continue

            ok, message, timed_out, outcome = bounded_quarantine_preflight(
                keeper,
                source,
                destination,
                source_root,
                expected_size=int(item["size"]),
                timeout=max(0.1, float(verify_timeout)),
            )
            if not ok:
                status = "timeout" if timed_out else "failed"
                journal.record_action(
                    run_id, item["group_id"], keeper, source, destination,
                    item["size"], status, message
                )
                action.update(status=status, message=message)
                result["failed"] += 1
                if timed_out:
                    result["timed_out"] += 1
                result["items"].append(action)
                continue
            if outcome == "destination-identical":
                journal.record_action(
                    run_id, item["group_id"], keeper, source, destination,
                    item["size"], "reconciled", message
                )
                action.update(status="reconciled", message=message)
                result["reconciled"] += 1
                result["items"].append(action)
                continue
            if outcome == "source-missing-keeper-valid":
                journal.record_action(
                    run_id, item["group_id"], keeper, source, destination,
                    item["size"], "stale", message
                )
                action.update(status="stale", message=message)
                result["stale"] += 1
                result["items"].append(action)
                continue

            try:
                destination.parent.mkdir(parents=True, exist_ok=True)
                journal.record_action(
                    run_id, item["group_id"], keeper, source, destination,
                    item["size"], "moving", message
                )
                move_noreplace(source, destination)
            except OSError as exc:
                journal.record_action(
                    run_id, item["group_id"], keeper, source, destination,
                    item["size"], "failed", str(exc)
                )
                action.update(status="failed", message=str(exc))
                result["failed"] += 1
            else:
                journal.record_action(
                    run_id, item["group_id"], keeper, source, destination,
                    item["size"], "moved", message
                )
                action.update(status="moved", message=message)
                result["files_moved"] += 1
                result["bytes_moved"] += int(item["size"])
            result["items"].append(action)
        journal.set_run_status(run_id, "complete" if result["failed"] == 0 else "attention")
    except (ArchiveKeeperError, OSError, sqlite3.Error) as exc:
        if journal is not None:
            try:
                journal.set_run_status(run_id, "interrupted")
            except sqlite3.Error:
                pass
        result["error"] = f"controlled quarantine failed: {exc}"
        return result
    finally:
        if journal is not None:
            journal.close()

    result["bytes_moved_human"] = human_bytes(result["bytes_moved"])
    result["ok"] = True
    return result


def restore_catalog_snapshot(state_db: Path) -> dict[str, Any]:
    """List runs that still contain quarantined files, without changing the journal."""
    state_db = normalize_path(state_db)
    result: dict[str, Any] = {
        "protocol_version": PROTOCOL_VERSION,
        "ok": True,
        "mode": "read-only",
        "operation": "restore-catalog",
        "runs": [],
        "warnings": [],
    }
    if not state_db.is_file():
        result["warnings"].append(f"journal database not found: {state_db}")
        return result
    try:
        with closing(_readonly_connection(state_db)) as connection:
            if not (_table_exists(connection, "runs") and _table_exists(connection, "actions")):
                return result
            rows = connection.execute(
                "SELECT r.run_id,r.created_at,r.mode,r.status,COUNT(a.id),"
                "COALESCE(SUM(a.size),0) FROM runs r JOIN actions a ON a.run_id=r.run_id "
                "WHERE a.status='moved' GROUP BY r.run_id,r.created_at,r.mode,r.status "
                "ORDER BY r.created_at DESC LIMIT 50"
            ).fetchall()
            result["runs"] = [
                {
                    "run_id": row[0], "created_at": row[1], "mode": row[2],
                    "status": row[3], "restorable_files": row[4],
                    "restorable_bytes": row[5], "restorable_human": human_bytes(row[5]),
                }
                for row in rows
            ]
    except sqlite3.Error as exc:
        result["ok"] = False
        result["warnings"].append(f"cannot read journal database {state_db}: {exc}")
    return result


def restore_plan_snapshot(
    state_db: Path, run_id: str, mount_roots: list[Path] | None = None
) -> dict[str, Any]:
    """Preview restoration with a fail-closed, no-overwrite policy."""
    state_db = normalize_path(state_db)
    roots = [normalize_path(root) for root in (mount_roots or DEFAULT_ROOTS)]
    result: dict[str, Any] = {
        "protocol_version": PROTOCOL_VERSION, "ok": False, "mode": "read-only",
        "operation": "restore-plan", "run_id": run_id, "total_files": 0,
        "total_bytes": 0, "total_human": human_bytes(0), "ready_files": 0,
        "blocked_files": 0, "items": [], "warnings": [],
    }
    if not state_db.is_file():
        result["warnings"].append(f"journal database not found: {state_db}")
        return result
    try:
        with closing(_readonly_connection(state_db)) as connection:
            run = connection.execute("SELECT 1 FROM runs WHERE run_id=?", (run_id,)).fetchone()
            if run is None:
                result["warnings"].append(f"restore run not found: {run_id}")
                return result
            rows = connection.execute(
                "SELECT group_id,keeper,source,destination,size FROM actions "
                "WHERE run_id=? AND status='moved' ORDER BY id DESC", (run_id,)
            ).fetchall()
    except sqlite3.Error as exc:
        result["warnings"].append(f"cannot read journal database {state_db}: {exc}")
        return result

    mounted = {root: root.is_dir() and os.path.ismount(root) for root in roots}
    for group_id, keeper_text, source_text, destination_text, size in rows:
        source, destination = normalize_path(source_text), normalize_path(destination_text)
        source_root, destination_root = mount_root_for(source, roots), mount_root_for(destination, roots)
        reasons: list[str] = []
        if source_root is None or destination_root is None:
            reasons.append("source or quarantine file is outside configured mount roots")
        elif source_root != destination_root:
            reasons.append("source and quarantine file are on different configured roots")
        elif not mounted[source_root]:
            reasons.append(f"restore mount is unavailable: {source_root}")
        if not reasons:
            statuses, probe_error = _bounded_path_probe([source, destination])
            if probe_error:
                reasons.append(f"live validation unavailable: {probe_error}")
            else:
                if statuses.get(str(destination)) != "file":
                    reasons.append("quarantine file is missing or not a regular file")
                if statuses.get(str(source)) != "missing":
                    reasons.append("original path already exists (no overwrite)")
        result["items"].append({
            "group_id": int(group_id), "status": "READY" if not reasons else "BLOCKED",
            "size": int(size), "size_human": human_bytes(int(size)), "source": str(source),
            "keeper": str(normalize_path(keeper_text)), "destination": str(destination),
            "warnings": reasons,
        })
    result["total_files"] = len(result["items"])
    result["total_bytes"] = sum(item["size"] for item in result["items"])
    result["total_human"] = human_bytes(result["total_bytes"])
    result["ready_files"] = sum(item["status"] == "READY" for item in result["items"])
    result["blocked_files"] = result["total_files"] - result["ready_files"]
    result["ok"] = True
    return result


def controlled_restore_apply(
    state_db: Path, run_id: str, confirmation: str,
    mount_roots: list[Path] | None = None, limit: int = MAX_CONTROLLED_RESTORE_FILES,
) -> dict[str, Any]:
    """Restore a bounded set of journaled moves without replacing any path."""
    limit = int(limit)
    expected = f"RESTORE UP TO {limit} FILES"
    result: dict[str, Any] = {
        "protocol_version": PROTOCOL_VERSION, "ok": False, "mode": "apply",
        "operation": "restore-apply", "run_id": run_id, "restored": 0,
        "bytes_restored": 0, "bytes_restored_human": human_bytes(0), "failed": 0,
        "remaining": 0, "limit": limit, "expected_confirmation": expected,
        "items": [], "error": "",
    }
    if limit < 1 or limit > MAX_CONTROLLED_RESTORE_FILES:
        result["error"] = f"controlled restore limit must be between 1 and {MAX_CONTROLLED_RESTORE_FILES}"
        return result
    if confirmation != expected:
        result["error"] = f"confirmation must exactly match: {expected}"
        return result
    plan = restore_plan_snapshot(state_db, run_id, mount_roots)
    if not plan["ok"]:
        result["error"] = "; ".join(plan["warnings"]) or "cannot build restore plan"
        return result
    candidates = [item for item in plan["items"] if item["status"] == "READY"][:limit]
    if not candidates:
        result["error"] = "no quarantined files passed the final restore checks"
        return result
    journal: Journal | None = None
    try:
        journal = Journal(normalize_path(state_db))
        for item in candidates:
            source, destination = normalize_path(item["source"]), normalize_path(item["destination"])
            action = {"group_id": item["group_id"], "source": str(source),
                      "destination": str(destination), "status": "failed", "message": ""}
            statuses, probe_error = _bounded_path_probe([source, destination])
            message = probe_error or ""
            if probe_error or statuses.get(str(source)) != "missing" or statuses.get(str(destination)) != "file":
                if not message:
                    message = "final check blocked restore: original exists or quarantine file is unavailable"
                # Keep the journal action restorable after a blocked attempt.
                journal.record_action(run_id, item["group_id"], normalize_path(item["keeper"]),
                                      source, destination, item["size"], "moved", message)
                action["message"], result["failed"] = message, result["failed"] + 1
                result["items"].append(action)
                continue
            try:
                source.parent.mkdir(parents=True, exist_ok=True)
                move_noreplace(destination, source)
            except OSError as exc:
                # A failed no-replace move leaves the quarantine copy in place.
                journal.record_action(run_id, item["group_id"], normalize_path(item["keeper"]),
                                      source, destination, item["size"], "moved", str(exc))
                action["message"], result["failed"] = str(exc), result["failed"] + 1
            else:
                journal.record_action(run_id, item["group_id"], normalize_path(item["keeper"]),
                                      source, destination, item["size"], "restored", "restored by UI")
                action["status"] = "restored"
                result["restored"] += 1
                result["bytes_restored"] += item["size"]
            result["items"].append(action)
        remaining = journal.conn.execute(
            "SELECT COUNT(*) FROM actions WHERE run_id=? AND status='moved'", (run_id,)
        ).fetchone()[0]
        result["remaining"] = remaining
        journal.set_run_status(run_id, "restored" if remaining == 0 and result["failed"] == 0 else "attention")
    except (ArchiveKeeperError, OSError, sqlite3.Error) as exc:
        result["error"] = f"controlled restore failed: {exc}"
        return result
    finally:
        if journal is not None:
            journal.close()
    result["bytes_restored_human"] = human_bytes(result["bytes_restored"])
    result["ok"] = True
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="archive-keeper-ui-bridge")
    subparsers = parser.add_subparsers(dest="command", required=True)
    dashboard = subparsers.add_parser("dashboard", help="Emit a read-only dashboard snapshot as JSON")
    dashboard.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    dashboard.add_argument("--state-db", type=Path, default=DEFAULT_STATE)
    dashboard.add_argument("--decisions-db", type=Path, default=DEFAULT_DECISIONS)
    dashboard.add_argument("--mount-root", action="append", type=Path, dest="mount_roots")
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
    preview = subparsers.add_parser(
        "quarantine-plan", help="Emit a read-only preview of explicitly staged files"
    )
    preview.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    preview.add_argument("--decisions-db", type=Path, default=DEFAULT_DECISIONS)
    preview.add_argument("--mount-root", action="append", type=Path, dest="mount_roots")
    preview.add_argument("--quarantine-name", default=DEFAULT_QUARANTINE_NAME)
    preview.add_argument("--run-id", default=PREVIEW_RUN_ID)
    dry_run = subparsers.add_parser(
        "quarantine-dry-run", help="Verify a bounded set of staged files without mutation"
    )
    dry_run.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    dry_run.add_argument("--decisions-db", type=Path, default=DEFAULT_DECISIONS)
    dry_run.add_argument("--mount-root", action="append", type=Path, dest="mount_roots")
    dry_run.add_argument("--quarantine-name", default=DEFAULT_QUARANTINE_NAME)
    dry_run.add_argument("--run-id", default=PREVIEW_RUN_ID)
    dry_run.add_argument("--limit", type=int, default=10)
    dry_run.add_argument("--verify-timeout", type=float, default=5.0)
    apply_run = subparsers.add_parser(
        "quarantine-apply", help="Move an explicitly confirmed bounded set of staged files"
    )
    apply_run.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    apply_run.add_argument("--state-db", type=Path, default=DEFAULT_STATE)
    apply_run.add_argument("--decisions-db", type=Path, default=DEFAULT_DECISIONS)
    apply_run.add_argument("--mount-root", action="append", type=Path, dest="mount_roots")
    apply_run.add_argument("--quarantine-name", default=DEFAULT_QUARANTINE_NAME)
    apply_run.add_argument("--run-id")
    apply_run.add_argument("--limit", type=int, default=MAX_CONTROLLED_APPLY_FILES)
    apply_run.add_argument("--verify-timeout", type=float, default=30.0)
    apply_run.add_argument("--confirm", required=True)
    restore_catalog = subparsers.add_parser("restore-catalog", help="List restorable runs")
    restore_catalog.add_argument("--state-db", type=Path, default=DEFAULT_STATE)
    restore_plan = subparsers.add_parser("restore-plan", help="Preview a no-overwrite restore")
    restore_plan.add_argument("--state-db", type=Path, default=DEFAULT_STATE)
    restore_plan.add_argument("--run-id", required=True)
    restore_plan.add_argument("--mount-root", action="append", type=Path, dest="mount_roots")
    restore_apply = subparsers.add_parser("restore-apply", help="Run a bounded no-overwrite restore")
    restore_apply.add_argument("--state-db", type=Path, default=DEFAULT_STATE)
    restore_apply.add_argument("--run-id", required=True)
    restore_apply.add_argument("--mount-root", action="append", type=Path, dest="mount_roots")
    restore_apply.add_argument("--limit", type=int, default=MAX_CONTROLLED_RESTORE_FILES)
    restore_apply.add_argument("--confirm", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "dashboard":
        json.dump(dashboard_snapshot(args.report, args.state_db, args.decisions_db, args.mount_roots), sys.stdout)
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
    if args.command == "quarantine-plan":
        result = quarantine_plan_snapshot(
            args.report,
            args.decisions_db,
            args.mount_roots,
            args.quarantine_name,
            args.run_id,
        )
        json.dump(result, sys.stdout)
        sys.stdout.write("\n")
        return 0 if result["ok"] else 1
    if args.command == "quarantine-dry-run":
        result = quarantine_dry_run(
            args.report,
            args.decisions_db,
            args.mount_roots,
            args.quarantine_name,
            args.run_id,
            args.limit,
            args.verify_timeout,
        )
        json.dump(result, sys.stdout)
        sys.stdout.write("\n")
        return 0 if result["ok"] else 1
    if args.command == "quarantine-apply":
        result = controlled_quarantine_apply(
            args.report,
            args.state_db,
            args.decisions_db,
            args.confirm,
            args.mount_roots,
            args.quarantine_name,
            args.run_id,
            args.limit,
            args.verify_timeout,
        )
        json.dump(result, sys.stdout)
        sys.stdout.write("\n")
        return 0 if result["ok"] else 1
    if args.command == "restore-catalog":
        result = restore_catalog_snapshot(args.state_db)
    elif args.command == "restore-plan":
        result = restore_plan_snapshot(args.state_db, args.run_id, args.mount_roots)
    elif args.command == "restore-apply":
        result = controlled_restore_apply(
            args.state_db, args.run_id, args.confirm, args.mount_roots, args.limit
        )
    else:
        return 2
    json.dump(result, sys.stdout)
    sys.stdout.write("\n")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
