from __future__ import annotations

import csv
import hashlib
import json
import os
import shutil
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator, Optional


class ArchiveKeeperError(RuntimeError):
    pass


@dataclass(frozen=True)
class DuplicateFile:
    path: Path
    size: int
    mtime: float
    inode: Optional[int]
    device: Optional[int]
    is_original_hint: bool
    checksum: Optional[str]
    group_id: int


@dataclass
class DuplicateGroup:
    group_id: int
    files: list[DuplicateFile]

    @property
    def size(self) -> int:
        return max((f.size for f in self.files), default=0)

    @property
    def recoverable_bytes(self) -> int:
        return self.size * max(0, len(self.files) - 1)


def human_bytes(value: int) -> str:
    units = ("B", "KiB", "MiB", "GiB", "TiB", "PiB")
    n = float(value)
    for unit in units:
        if abs(n) < 1024 or unit == units[-1]:
            return f"{n:.2f} {unit}"
        n /= 1024
    return f"{value} B"


def _entry_path(entry: dict) -> Optional[Path]:
    value = entry.get("path") or entry.get("name")
    if not value:
        return None
    return Path(os.path.abspath(os.path.expanduser(str(value))))


def _entry_size(entry: dict) -> int:
    for key in ("size", "file_size", "filesize"):
        if key in entry:
            try:
                return int(entry[key])
            except (TypeError, ValueError):
                pass
    return 0


def _entry_mtime(entry: dict) -> float:
    for key in ("mtime", "mtime_ns"):
        if key in entry:
            try:
                value = float(entry[key])
                if key == "mtime_ns":
                    value /= 1_000_000_000
                return value
            except (TypeError, ValueError):
                pass
    path = _entry_path(entry)
    if path:
        try:
            return path.stat().st_mtime
        except OSError:
            pass
    return 0.0


def _entry_checksum(entry: dict) -> Optional[str]:
    for key in ("checksum", "hash", "digest"):
        value = entry.get(key)
        if value:
            return str(value)
    return None


def load_rmlint_groups(report_path: Path) -> list[DuplicateGroup]:
    """
    Parse the standard rmlint JSON output.

    rmlint JSON is usually a top-level list with:
      - a header dictionary,
      - file dictionaries,
      - a footer dictionary.
    Duplicate groups are delimited by entries marked is_original=true.
    This parser also supports explicit group fields when present.
    """
    try:
        with report_path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
    except FileNotFoundError as exc:
        raise ArchiveKeeperError(f"Report not found: {report_path}") from exc
    except json.JSONDecodeError as exc:
        raise ArchiveKeeperError(
            f"Invalid JSON in {report_path} at line {exc.lineno}, column {exc.colno}"
        ) from exc

    if not isinstance(data, list):
        raise ArchiveKeeperError("Expected rmlint report to contain a top-level JSON list.")

    file_entries: list[dict] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        path = _entry_path(item)
        if path is None:
            continue
        lint_type = str(item.get("type", item.get("lint_type", ""))).lower()
        # Keep duplicate-file-like entries; ignore obvious non-duplicate lint.
        if lint_type and lint_type not in {
            "duplicate_file", "duplicate_dir", "df", "duplicate", "duplicates"
        }:
            continue
        file_entries.append(item)

    if not file_entries:
        raise ArchiveKeeperError(
            "No duplicate file entries were found in the rmlint report."
        )

    # Prefer explicit group identifiers when available.
    explicit_keys = ("group", "group_id", "duplicate_group", "digest")
    explicit_key = next(
        (key for key in explicit_keys if any(key in e for e in file_entries)), None
    )

    raw_groups: list[list[dict]] = []
    if explicit_key and explicit_key != "digest":
        buckets: dict[str, list[dict]] = {}
        order: list[str] = []
        for entry in file_entries:
            key = str(entry.get(explicit_key, ""))
            if key not in buckets:
                buckets[key] = []
                order.append(key)
            buckets[key].append(entry)
        raw_groups = [buckets[key] for key in order]
    else:
        current: list[dict] = []
        for entry in file_entries:
            is_original = bool(entry.get("is_original", entry.get("original", False)))
            if is_original and current:
                raw_groups.append(current)
                current = []
            current.append(entry)
        if current:
            raw_groups.append(current)

    groups: list[DuplicateGroup] = []
    gid = 1
    for entries in raw_groups:
        if len(entries) < 2:
            continue
        files: list[DuplicateFile] = []
        for entry in entries:
            path = _entry_path(entry)
            if path is None:
                continue
            files.append(
                DuplicateFile(
                    path=path,
                    size=_entry_size(entry),
                    mtime=_entry_mtime(entry),
                    inode=_safe_int(entry.get("inode")),
                    device=_safe_int(entry.get("device")),
                    is_original_hint=bool(
                        entry.get("is_original", entry.get("original", False))
                    ),
                    checksum=_entry_checksum(entry),
                    group_id=gid,
                )
            )
        if len(files) >= 2:
            groups.append(DuplicateGroup(group_id=gid, files=files))
            gid += 1

    if not groups:
        raise ArchiveKeeperError("The report contained no duplicate groups with 2+ files.")
    return groups


def _safe_int(value) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def path_is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(root.resolve(strict=False))
        return True
    except ValueError:
        return False


def choose_keeper(
    group: DuplicateGroup,
    preferred_roots: list[Path],
    protected_roots: list[Path],
    strategy: str,
) -> DuplicateFile:
    def root_rank(path: Path, roots: list[Path], default: int) -> int:
        for idx, root in enumerate(roots):
            if path_is_within(path, root):
                return idx
        return default

    protected_matches = [
        f for f in group.files if root_rank(f.path, protected_roots, 10**6) < 10**6
    ]
    candidates = protected_matches or group.files

    preferred_default = len(preferred_roots) + 100
    def score(f: DuplicateFile):
        pref = root_rank(f.path, preferred_roots, preferred_default)
        original_hint = 0 if f.is_original_hint else 1
        if strategy == "oldest":
            tie = (f.mtime, len(str(f.path)), str(f.path))
        elif strategy == "newest":
            tie = (-f.mtime, len(str(f.path)), str(f.path))
        elif strategy == "shortest-path":
            tie = (len(str(f.path)), f.mtime, str(f.path))
        elif strategy == "rmlint-original":
            tie = (original_hint, pref, len(str(f.path)), str(f.path))
            return tie
        else:  # preferred-root
            tie = (pref, original_hint, len(str(f.path)), f.mtime, str(f.path))
        return tie

    return min(candidates, key=score)


def sha256_file(path: Path, chunk_size: int = 8 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def files_match(a: Path, b: Path, deep_verify: bool = False) -> tuple[bool, str]:
    try:
        sa = a.stat()
        sb = b.stat()
    except OSError as exc:
        return False, f"stat failed: {exc}"
    if not a.is_file() or not b.is_file():
        return False, "not a regular file"
    if sa.st_size != sb.st_size:
        return False, "size mismatch"
    if sa.st_dev == sb.st_dev and sa.st_ino == sb.st_ino:
        return True, "same inode"
    if deep_verify:
        return (sha256_file(a) == sha256_file(b), "sha256 verification")
    return True, "size verified; report trusted"


def mount_root_for(path: Path, configured_roots: list[Path]) -> Optional[Path]:
    matches = [r for r in configured_roots if path_is_within(path, r)]
    if not matches:
        return None
    return max(matches, key=lambda p: len(str(p)))


def quarantine_destination(
    source: Path, mount_root: Path, quarantine_name: str, run_id: str
) -> Path:
    rel = source.resolve(strict=False).relative_to(mount_root.resolve(strict=False))
    return mount_root / quarantine_name / run_id / rel


class Journal:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(db_path))
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=FULL")
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS runs (
                run_id TEXT PRIMARY KEY,
                created_at REAL NOT NULL,
                report_path TEXT NOT NULL,
                mode TEXT NOT NULL,
                status TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS actions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT NOT NULL,
                group_id INTEGER NOT NULL,
                keeper TEXT NOT NULL,
                source TEXT NOT NULL,
                destination TEXT NOT NULL,
                size INTEGER NOT NULL,
                status TEXT NOT NULL,
                message TEXT,
                created_at REAL NOT NULL,
                updated_at REAL NOT NULL,
                UNIQUE(run_id, source)
            );
            """
        )
        self.conn.commit()

    def close(self):
        self.conn.close()

    def create_run(self, run_id: str, report_path: Path, mode: str):
        self.conn.execute(
            "INSERT OR IGNORE INTO runs(run_id,created_at,report_path,mode,status) VALUES(?,?,?,?,?)",
            (run_id, time.time(), str(report_path), mode, "running"),
        )
        self.conn.commit()

    def set_run_status(self, run_id: str, status: str):
        self.conn.execute("UPDATE runs SET status=? WHERE run_id=?", (status, run_id))
        self.conn.commit()

    def action_status(self, run_id: str, source: Path) -> Optional[str]:
        row = self.conn.execute(
            "SELECT status FROM actions WHERE run_id=? AND source=?",
            (run_id, str(source)),
        ).fetchone()
        return row[0] if row else None

    def record_action(
        self,
        run_id: str,
        group_id: int,
        keeper: Path,
        source: Path,
        destination: Path,
        size: int,
        status: str,
        message: str = "",
    ):
        now = time.time()
        self.conn.execute(
            """
            INSERT INTO actions(run_id,group_id,keeper,source,destination,size,status,message,created_at,updated_at)
            VALUES(?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(run_id,source) DO UPDATE SET
              destination=excluded.destination,
              keeper=excluded.keeper,
              size=excluded.size,
              status=excluded.status,
              message=excluded.message,
              updated_at=excluded.updated_at
            """,
            (
                run_id, group_id, str(keeper), str(source), str(destination), size,
                status, message, now, now
            ),
        )
        self.conn.commit()

    def iter_actions(self, run_id: str, statuses: tuple[str, ...] = ("moved",)):
        marks = ",".join("?" for _ in statuses)
        query = f"""
          SELECT group_id,keeper,source,destination,size,status,message
          FROM actions WHERE run_id=? AND status IN ({marks}) ORDER BY id DESC
        """
        yield from self.conn.execute(query, (run_id, *statuses))

    def summary(self, run_id: Optional[str] = None):
        if run_id:
            run_rows = self.conn.execute(
                "SELECT run_id,created_at,report_path,mode,status FROM runs WHERE run_id=?",
                (run_id,),
            ).fetchall()
        else:
            run_rows = self.conn.execute(
                "SELECT run_id,created_at,report_path,mode,status FROM runs ORDER BY created_at DESC"
            ).fetchall()
        result = []
        for row in run_rows:
            counts = dict(
                self.conn.execute(
                    "SELECT status,COUNT(*) FROM actions WHERE run_id=? GROUP BY status",
                    (row[0],),
                ).fetchall()
            )
            bytes_moved = self.conn.execute(
                "SELECT COALESCE(SUM(size),0) FROM actions WHERE run_id=? AND status='moved'",
                (row[0],),
            ).fetchone()[0]
            result.append((*row, counts, bytes_moved))
        return result


def export_plan_csv(
    groups: list[DuplicateGroup],
    output_path: Path,
    preferred_roots: list[Path],
    protected_roots: list[Path],
    excluded_roots: list[Path],
    strategy: str,
):
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            ["group_id", "action", "size", "keeper", "path", "reason"]
        )
        for group in groups:
            keeper = choose_keeper(group, preferred_roots, protected_roots, strategy)
            for item in group.files:
                if item.path == keeper.path:
                    writer.writerow(
                        [group.group_id, "KEEP", item.size, keeper.path, item.path, strategy]
                    )
                    continue
                excluded = any(path_is_within(item.path, r) for r in excluded_roots)
                protected = any(path_is_within(item.path, r) for r in protected_roots)
                action = "SKIP" if excluded or protected else "QUARANTINE"
                reason = "excluded root" if excluded else "protected root" if protected else strategy
                writer.writerow(
                    [group.group_id, action, item.size, keeper.path, item.path, reason]
                )
