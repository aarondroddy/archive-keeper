from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


@dataclass(frozen=True)
class MountStatus:
    root: Path
    mounted: bool
    detail: str = ""


def is_mountpoint(path: Path) -> bool:
    """Return True only when *path* is an active mount point."""
    path = path.expanduser().resolve(strict=False)
    return path.is_dir() and os.path.ismount(path)


def check_mounts(roots: Iterable[Path]) -> list[MountStatus]:
    """Check configured storage roots without changing the system."""
    statuses = []
    for root in roots:
        normalized = root.expanduser().resolve(strict=False)
        statuses.append(MountStatus(normalized, is_mountpoint(normalized)))
    return statuses


def _mount_command(root: Path, non_interactive: bool) -> list[str]:
    command = ["sudo"]
    if non_interactive:
        command.append("-n")
    command.extend(["mount", str(root)])
    return command


def attempt_mount(root: Path) -> tuple[bool, str]:
    """Mount a root through its /etc/fstab entry, prompting for sudo if needed."""
    root = root.expanduser().resolve(strict=False)
    root.mkdir(parents=True, exist_ok=True)

    first = subprocess.run(
        _mount_command(root, non_interactive=True),
        text=True,
        capture_output=True,
    )
    if first.returncode == 0 and is_mountpoint(root):
        return True, "mounted"

    # If sudo merely needed a password, retry interactively while still outside curses.
    stderr = (first.stderr or "").lower()
    needs_password = "password" in stderr or "a password is required" in stderr
    if needs_password and sys.stdin.isatty():
        second = subprocess.run(_mount_command(root, non_interactive=False), text=True)
        if second.returncode == 0 and is_mountpoint(root):
            return True, "mounted"
        return False, f"mount command exited with status {second.returncode}"

    message = (first.stderr or first.stdout or "mount command failed").strip()
    return False, message


def ensure_mounts(roots: Iterable[Path], policy: str = "auto") -> None:
    """Check required roots, optionally mount them, and fail closed if unavailable."""
    normalized = list(dict.fromkeys(r.expanduser().resolve(strict=False) for r in roots))
    missing = [status.root for status in check_mounts(normalized) if not status.mounted]
    if not missing or policy == "ignore":
        return

    if policy == "check":
        names = "\n  ".join(str(root) for root in missing)
        raise RuntimeError(
            "Required storage roots are not mounted:\n  " + names +
            "\nMount them first, or use --mount-policy auto to let Archive Keeper try."
        )

    failures = []
    for root in missing:
        print(f"Archive Keeper: {root} is not mounted; attempting to mount it...")
        ok, detail = attempt_mount(root)
        if ok:
            print(f"Archive Keeper: mounted {root}")
        else:
            failures.append((root, detail))

    still_missing = [status.root for status in check_mounts(normalized) if not status.mounted]
    if still_missing:
        details = []
        for root in still_missing:
            reason = next((detail for failed_root, detail in failures if failed_root == root), "still not mounted")
            details.append(f"  {root}: {reason}")
        raise RuntimeError(
            "Archive Keeper could not mount all required storage roots.\n" + "\n".join(details) +
            "\nAutomatic mounting requires a valid /etc/fstab entry for each root. "
            "No file operation was started."
        )
