from __future__ import annotations

import csv
import ctypes
import errno
import hashlib
import json
import os
import shutil
import subprocess
import sys
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Iterator, Optional


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


def normalize_path(path: Path | str) -> Path:
    """Normalize a path lexically without touching the filesystem.

    Path.resolve(strict=False) can still issue metadata lookups on network
    filesystems. Archive Keeper uses report paths as data until an operation
    explicitly needs to validate a live file.
    """
    return Path(os.path.abspath(os.path.expanduser(str(path))))


def _entry_path(entry: dict) -> Optional[Path]:
    value = entry.get("path") or entry.get("name")
    if not value:
        return None
    return normalize_path(value)


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
    # Do not fall back to path.stat() here. A report may contain hundreds of
    # thousands of paths on SMB/CIFS shares, and one stalled metadata request
    # can block the entire analysis. Live validation is deliberately lazy.
    return 0.0


def _entry_checksum(entry: dict) -> Optional[str]:
    for key in ("checksum", "hash", "digest"):
        value = entry.get(key)
        if value:
            return str(value)
    return None


def load_rmlint_groups(report_path: Path, progress: Callable[[str], None] | None = None) -> list[DuplicateGroup]:
    """
    Parse the standard rmlint JSON output.

    rmlint JSON is usually a top-level list with:
      - a header dictionary,
      - file dictionaries,
      - a footer dictionary.
    Duplicate groups are delimited by entries marked is_original=true.
    This parser also supports explicit group fields when present.
    """
    if progress:
        progress(f"Loading rmlint report: {report_path}")
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

    if progress:
        progress(f"Parsing {len(data):,} JSON records without touching NAS files...")
    file_entries: list[dict] = []
    for index, item in enumerate(data, 1):
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
        if progress and index % 100_000 == 0:
            progress(f"Parsed {index:,} / {len(data):,} JSON records ({index / len(data) * 100:.1f}%)...")

    if not file_entries:
        raise ArchiveKeeperError(
            "No duplicate file entries were found in the rmlint report."
        )

    # Prefer explicit group identifiers when available.
    explicit_keys = ("group", "group_id", "duplicate_group")
    explicit_key = next(
        (key for key in explicit_keys if all(key in e for e in file_entries)), None
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

    if progress:
        progress(f"Building duplicate groups from {len(file_entries):,} file records...")
    groups: list[DuplicateGroup] = []
    gid = 1
    for group_index, entries in enumerate(raw_groups, 1):
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
        if progress and group_index % 25_000 == 0:
            progress(f"Built {len(groups):,} duplicate groups from {group_index:,} / {len(raw_groups):,} raw groups ({group_index / len(raw_groups) * 100:.1f}%)...")

    if not groups:
        raise ArchiveKeeperError("The report contained no duplicate groups with 2+ files.")
    if progress:
        progress(f"Loaded {len(groups):,} duplicate groups. Live file checks deferred until needed.")
    return groups


def _safe_int(value) -> Optional[int]:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def path_is_within(path: Path, root: Path) -> bool:
    try:
        normalize_path(path).relative_to(normalize_path(root))
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


def sampled_sha256_match(
    a: Path,
    b: Path,
    *,
    chunk_size: int = 16 * 1024 * 1024,
) -> tuple[bool, str]:
    """Compare equal-sized files by hashing deterministic samples.

    Samples are taken from the start, 25%, 50%, 75%, and end of the file.
    This is a high-confidence verification tier, not a full-file cryptographic
    proof, so callers must opt in explicitly before using it for mutation.
    """
    try:
        sa = a.stat()
        sb = b.stat()
    except OSError as exc:
        return False, f"sample verification stat failed: {exc}"
    if not a.is_file() or not b.is_file():
        return False, "sample verification requires regular files"
    if sa.st_size != sb.st_size:
        return False, "sample verification size mismatch"
    if sa.st_dev == sb.st_dev and sa.st_ino == sb.st_ino:
        return True, "sample SHA-256 verified: same inode"

    size = sa.st_size
    if size == 0:
        return True, "sample SHA-256 verified: empty files"
    chunk_size = max(1, int(chunk_size))
    last = max(0, size - min(size, chunk_size))
    offsets = [0, size // 4, size // 2, (size * 3) // 4, last]
    # Small files can make sample windows overlap; duplicate offsets add no
    # information, so hash each distinct position once.
    offsets = list(dict.fromkeys(offsets))

    def sample_digest(path: Path, offset: int) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            handle.seek(offset)
            digest.update(handle.read(chunk_size))
        return digest.hexdigest()

    try:
        for index, offset in enumerate(offsets, 1):
            if sample_digest(a, offset) != sample_digest(b, offset):
                return False, (
                    f"sample SHA-256 mismatch at sample {index}/{len(offsets)} "
                    f"offset={offset}"
                )
    except OSError as exc:
        return False, f"sample verification read failed: {exc}"

    return True, (
        f"sample SHA-256 verified: size={size}; samples={len(offsets)}; "
        f"chunk={chunk_size} bytes"
    )


def files_match(
    a: Path,
    b: Path,
    deep_verify: bool = False,
    sample_verify: bool = False,
) -> tuple[bool, str]:
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
    if deep_verify and sample_verify:
        return False, "cannot combine full SHA-256 and sampled SHA-256 verification"
    if deep_verify:
        return (sha256_file(a) == sha256_file(b), "sha256 verification")
    if sample_verify:
        return sampled_sha256_match(a, b)
    return True, "size verified; report trusted"




def bounded_quarantine_preflight(
    keeper: Path,
    source: Path,
    destination: Path,
    source_root: Path,
    *,
    deep_verify: bool = False,
    sample_verify: bool = False,
    min_free_bytes: int = 0,
    expected_size: int | None = None,
    timeout: float | None = 30.0,
) -> tuple[bool, str, bool, str]:
    """Run live NAS validation outside the main Archive Keeper process.

    Returns ``(ok, message, timed_out, outcome)``. ``outcome`` is ``ready``
    for an ordinary move or ``destination-identical`` when an existing
    quarantine destination is byte-for-byte identical to the source.
    Potentially blocking CIFS metadata and
    file reads happen in a short-lived helper process so the main CLI stays
    responsive if the kernel wedges a request in uninterruptible I/O sleep.
    """
    cmd = [
        sys.executable, "-m", "archive_keeper.verify_worker",
        "--keeper", str(keeper),
        "--source", str(source),
        "--destination", str(destination),
        "--source-root", str(source_root),
        "--min-free-bytes", str(int(min_free_bytes)),
    ]
    if expected_size is not None:
        cmd.extend(["--expected-size", str(int(expected_size))])
    if deep_verify:
        cmd.append("--deep-verify")
    if sample_verify:
        cmd.append("--sample-verify")

    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    try:
        wait_timeout = None if timeout is None else max(0.1, float(timeout))
        stdout, stderr = proc.communicate(timeout=wait_timeout)
    except subprocess.TimeoutExpired:
        # SIGKILL may remain pending while a CIFS request is in D state, but the
        # parent must not wait for that kernel call to recover. The helper owns
        # no mutation logic, so timing it out cannot move or alter user files.
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        return False, f"verification timed out after {timeout:g}s", True, "timeout"
    except KeyboardInterrupt:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        raise

    payload = (stdout or "").strip().splitlines()
    if payload:
        try:
            data = json.loads(payload[-1])
            return (
                bool(data.get("ok")),
                str(data.get("message", "verification failed")),
                False,
                str(data.get("outcome", "ready" if data.get("ok") else "failed")),
            )
        except json.JSONDecodeError:
            pass
    detail = (stderr or stdout or f"worker exited with status {proc.returncode}").strip()
    return False, f"verification worker error: {detail}", False, "worker-error"


def bounded_files_identical(a: Path, b: Path, *, timeout: float | None = 30.0) -> tuple[bool, str, bool]:
    """SHA-256 compare two live files in a bounded helper process.

    Returns ``(identical, message, timed_out)``. This is used for restore
    collision reconciliation so a stalled CIFS read cannot freeze the CLI.
    """
    cmd = [
        sys.executable, "-m", "archive_keeper.verify_worker",
        "--compare-a", str(a),
        "--compare-b", str(b),
    ]
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        start_new_session=True,
    )
    try:
        wait_timeout = None if timeout is None else max(0.1, float(timeout))
        stdout, stderr = proc.communicate(timeout=wait_timeout)
    except subprocess.TimeoutExpired:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        return False, f"comparison timed out after {timeout:g}s", True
    except KeyboardInterrupt:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        raise
    payload = (stdout or "").strip().splitlines()
    if payload:
        try:
            data = json.loads(payload[-1])
            return bool(data.get("identical")), str(data.get("message", "comparison failed")), False
        except json.JSONDecodeError:
            pass
    detail = (stderr or stdout or f"worker exited with status {proc.returncode}").strip()
    return False, f"comparison worker error: {detail}", False


def mount_root_for(path: Path, configured_roots: list[Path]) -> Optional[Path]:
    matches = [r for r in configured_roots if path_is_within(path, r)]
    if not matches:
        return None
    return max(matches, key=lambda p: len(str(p)))


def quarantine_destination(
    source: Path, mount_root: Path, quarantine_name: str, run_id: str
) -> Path:
    rel = normalize_path(source).relative_to(normalize_path(mount_root))
    return mount_root / quarantine_name / run_id / rel


def collision_destination(destination: Path, action_id: int) -> Path:
    """Return a deterministic alternate path for a genuine destination collision.

    The action id makes the alternate name stable across retries and directly
    traceable back to the journal row.  The original suffix (including its
    case) is preserved.
    """
    destination = normalize_path(destination)
    return destination.with_name(
        f"{destination.stem}__collision-{int(action_id)}{destination.suffix}"
    )


def _verified_copy_noreplace(source: Path, destination: Path) -> None:
    """Copy without clobbering, verify SHA-256, then remove the source.

    This is a conservative fallback for filesystems that return ``EIO`` for a
    no-replace rename/link even though ordinary reads and writes still work.
    The source is never unlinked until a complete destination copy has been
    flushed, fsynced, and cryptographically verified.
    """
    fd: Optional[int] = None
    destination_created = False
    verified = False
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL

    try:
        fd = os.open(destination, flags, 0o600)
        destination_created = True

        with source.open("rb") as src, os.fdopen(fd, "wb") as dst:
            fd = None  # ownership transferred to dst
            shutil.copyfileobj(src, dst, length=8 * 1024 * 1024)
            dst.flush()
            os.fsync(dst.fileno())

        if sha256_file(source) != sha256_file(destination):
            raise OSError(
                errno.EIO,
                "verified copy fallback failed SHA-256 verification",
                str(destination),
            )
        verified = True

        # Metadata is useful but secondary to preserving file contents.
        try:
            shutil.copystat(source, destination)
        except OSError:
            pass

        # If this fails, both verified copies remain for reconciliation.
        os.unlink(source)
    except BaseException:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass

        # Before verification, a partial/new destination must not linger. After
        # verification, retain it if source unlink failed: two good copies are
        # safer than deleting the newly verified one during error handling.
        if destination_created and not verified:
            try:
                destination.unlink()
            except OSError:
                pass
        raise


def move_noreplace(source: Path, destination: Path) -> None:
    """Move a regular file without ever replacing an existing destination.

    Prefer Linux ``renameat2(RENAME_NOREPLACE)``. If that primitive is not
    supported, retain the existing hard-link/unlink fallback. Some NAS-backed
    filesystems return ``EIO`` for no-replace operations while still supporting
    reliable reads/writes; for that specific failure, use an exclusive copy,
    full SHA-256 verification, and only then unlink the source.
    """
    source_b = os.fsencode(source)
    destination_b = os.fsencode(destination)
    at_fdcwd = -100
    rename_noreplace = 1
    libc = ctypes.CDLL(None, use_errno=True)
    renameat2 = getattr(libc, "renameat2", None)
    unsupported = {errno.ENOSYS, errno.EINVAL, errno.EOPNOTSUPP, errno.ENOTSUP}

    if renameat2 is not None:
        renameat2.argtypes = (
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        )
        renameat2.restype = ctypes.c_int
        if renameat2(at_fdcwd, source_b, at_fdcwd, destination_b, rename_noreplace) == 0:
            return
        error_number = ctypes.get_errno()
        if error_number == errno.EIO:
            _verified_copy_noreplace(source, destination)
            return
        if error_number not in unsupported:
            raise OSError(error_number, os.strerror(error_number), str(destination))

    try:
        os.link(source, destination)
    except OSError as exc:
        if exc.errno == errno.EEXIST:
            raise
        if exc.errno == errno.EIO:
            _verified_copy_noreplace(source, destination)
            return
        raise OSError(
            exc.errno,
            "filesystem cannot perform a no-clobber move; source left untouched",
            str(destination),
        ) from exc
    try:
        os.unlink(source)
    except BaseException:
        # Both names now refer to the same inode. Leave that provably safe state
        # for reconciliation instead of trying a second mutation while failing.
        raise


class Journal:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(db_path), timeout=10.0)
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
        row = self.conn.execute("SELECT mode FROM runs WHERE run_id=?", (run_id,)).fetchone()
        if row and row[0] != mode:
            raise ArchiveKeeperError(
                f"Run {run_id!r} already exists in {row[0]!r} mode; choose a new --run-id."
            )
        self.conn.execute(
            "INSERT OR IGNORE INTO runs(run_id,created_at,report_path,mode,status) VALUES(?,?,?,?,?)",
            (run_id, time.time(), str(report_path), mode, "running"),
        )
        self.conn.execute("UPDATE runs SET status='running' WHERE run_id=?", (run_id,))
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

    def action_id(self, run_id: str, source: Path) -> Optional[int]:
        row = self.conn.execute(
            "SELECT id FROM actions WHERE run_id=? AND source=?",
            (run_id, str(source)),
        ).fetchone()
        return int(row[0]) if row else None

    def infer_quarantine_name(self, run_id: str, mount_roots: list[Path]) -> Optional[str]:
        """Infer the quarantine directory name already journaled for a run.

        This keeps resumed pre-1.6.6 runs on their original hidden `.ArchiveKeeper`
        tree and avoids silently splitting one run across old and new roots.
        """
        rows = self.conn.execute(
            "SELECT destination FROM actions WHERE run_id=? ORDER BY id LIMIT 100",
            (run_id,),
        ).fetchall()
        for (destination_text,) in rows:
            destination = normalize_path(Path(destination_text))
            for mount_root in mount_roots:
                root = normalize_path(mount_root)
                if not path_is_within(destination, root):
                    continue
                try:
                    rel = destination.relative_to(root)
                except ValueError:
                    continue
                parts = rel.parts
                if len(parts) >= 2 and parts[1] == run_id:
                    return parts[0]
        return None

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
