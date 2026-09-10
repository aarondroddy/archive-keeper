"""End-to-end terminal reliability tests for Storage Galaxy.

Every fixture lives under the operating system's temporary directory.  The
suite writes rmlint-compatible JSON itself and never invokes rmlint, scans a
mounted filesystem, or performs an Archive Keeper apply operation.
"""

from __future__ import annotations

import fcntl
import json
import os
import pty
import re
import select
import shutil
import signal
import struct
import subprocess
import sys
import tempfile
import termios
import time
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
ANSI_ESCAPE = re.compile(
    rb"(?:\x1B[@-_][0-?]*[ -/]*[@-~]|\x1B\][^\x07]*(?:\x07|\x1B\\))"
)
REAL_STORAGE_PREFIXES = ("/mnt/MyCloud1", "/mnt/MyCloud2", "/mnt/MyCloud3")


def _set_window_size(fd: int, columns: int, rows: int) -> None:
    fcntl.ioctl(fd, termios.TIOCSWINSZ,
                struct.pack("HHHH", rows, columns, 0, 0))


def _claim_controlling_terminal(slave: int) -> None:
    """Start a new session and make the PTY slave available as /dev/tty."""
    os.setsid()
    fcntl.ioctl(slave, termios.TIOCSCTTY, 0)


class TerminalProcess:
    """Small dependency-free PTY driver suitable for Bubble Tea programs."""

    def __init__(self, command: list[str], environment: dict[str, str],
                 columns: int = 140, rows: int = 44):
        self.master, slave = pty.openpty()
        _set_window_size(slave, columns, rows)
        self.process = subprocess.Popen(
            command,
            cwd=REPOSITORY_ROOT,
            env=environment,
            stdin=slave,
            stdout=slave,
            stderr=slave,
            preexec_fn=lambda: _claim_controlling_terminal(slave),
            close_fds=True,
        )
        os.close(slave)
        os.set_blocking(self.master, False)
        self.output = bytearray()

    def send(self, data: bytes) -> None:
        os.write(self.master, data)

    def resize(self, columns: int, rows: int) -> None:
        _set_window_size(self.master, columns, rows)
        os.killpg(self.process.pid, signal.SIGWINCH)

    def _read_once(self, timeout: float = 0.1) -> None:
        readable, _, _ = select.select([self.master], [], [], timeout)
        if not readable:
            return
        try:
            chunk = os.read(self.master, 1 << 20)
        except (BlockingIOError, OSError):
            return
        self.output.extend(chunk)

    def plain_output(self, start: int = 0) -> str:
        clean = ANSI_ESCAPE.sub(b"", bytes(self.output[start:]))
        return clean.replace(b"\r", b"").decode("utf-8", "replace")

    def wait_for(self, text: str, timeout: float = 15.0, start: int = 0) -> str:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self._read_once()
            rendered = self.plain_output(start)
            if text in rendered:
                return rendered
            if self.process.poll() is not None:
                break
        rendered = self.plain_output(start)
        self.close(force=True)
        raise AssertionError(
            f"terminal did not render {text!r}; exit={self.process.poll()}; "
            f"tail={rendered[-2000:]!r}"
        )

    def wait(self, timeout: float = 8.0) -> int:
        return self.process.wait(timeout=timeout)

    def close(self, force: bool = False) -> None:
        if self.process.poll() is None:
            try:
                if not force:
                    self.send(b"q")
                    self.process.wait(timeout=2)
                else:
                    raise subprocess.TimeoutExpired(self.process.args, 0)
            except (BrokenPipeError, OSError, subprocess.TimeoutExpired):
                os.killpg(self.process.pid, signal.SIGTERM)
                try:
                    self.process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    os.killpg(self.process.pid, signal.SIGKILL)
                    self.process.wait(timeout=2)
        try:
            os.close(self.master)
        except OSError:
            pass


class DisposableGalaxyFixture:
    def __init__(self, group_count: int):
        self._temporary = tempfile.TemporaryDirectory(prefix="archive-keeper-pty-")
        self.root = Path(self._temporary.name).resolve()
        self.storage_roots = [self.root / name for name in ("Orion", "Lyra", "Draco")]
        self._assert_disposable()
        for path in self.storage_roots:
            path.mkdir()
        self.report = self.root / "rmlint.json"
        self._write_report(group_count)

    def _assert_disposable(self) -> None:
        temporary_root = Path(tempfile.gettempdir()).resolve()
        if temporary_root not in self.root.parents:
            raise AssertionError(f"fixture escaped the temporary directory: {self.root}")
        rendered = str(self.root)
        if rendered.startswith("/mnt/") or any(
                rendered.startswith(prefix) for prefix in REAL_STORAGE_PREFIXES):
            raise AssertionError(f"fixture points at real storage: {self.root}")

    def _write_report(self, group_count: int) -> None:
        # Stream the JSON so the test can create a six-figure-record report
        # without holding a second large copy in memory.
        with self.report.open("w", encoding="utf-8") as handle:
            handle.write('[{"type":"header","generator":"archive-keeper-pty"}')
            for group in range(1, group_count + 1):
                size = 1024 + group
                first = self.storage_roots[group % len(self.storage_roots)]
                second = self.storage_roots[(group + 1) % len(self.storage_roots)]
                for original, root, suffix in (
                    (True, first, "a"), (False, second, "b")
                ):
                    record = {
                        "type": "duplicate_file",
                        "path": str(root / f"group-{group:05d}-{suffix}.bin"),
                        "size": size,
                        "mtime": 1_700_000_000 + group,
                        "group": group,
                        "is_original": original,
                    }
                    handle.write(",")
                    json.dump(record, handle, separators=(",", ":"))
            handle.write(',{"type":"footer"}]')

    def environment(self) -> dict[str, str]:
        env = os.environ.copy()
        for name in tuple(env):
            if name.startswith("ARCHIVE_KEEPER_"):
                env.pop(name)
        python_path = [str(REPOSITORY_ROOT)]
        if env.get("PYTHONPATH"):
            python_path.append(env["PYTHONPATH"])
        env.update({
            "ARCHIVE_KEEPER_PYTHON": sys.executable,
            "ARCHIVE_KEEPER_MOUNT_ROOTS": os.pathsep.join(map(str, self.storage_roots)),
            "ARCHIVE_KEEPER_REPORT": str(self.report),
            "ARCHIVE_KEEPER_STATE_DB": str(self.root / "journal.sqlite3"),
            "ARCHIVE_KEEPER_DECISIONS_DB": str(self.root / "decisions.sqlite3"),
            "ARCHIVE_KEEPER_UI_CONFIG": str(self.root / "ui.json"),
            "PYTHONPATH": os.pathsep.join(python_path),
            "TERM": "xterm-256color",
        })
        for value in env.values():
            if any(prefix in value for prefix in REAL_STORAGE_PREFIXES):
                raise AssertionError("real MyCloud path leaked into PTY test environment")
        return env

    def close(self) -> None:
        self._temporary.cleanup()


@unittest.skipUnless(os.name == "posix", "PTY tests require a POSIX terminal")
class StorageGalaxyPTYTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if shutil.which("go") is None:
            raise unittest.SkipTest("Go toolchain is not installed")
        cls._build = tempfile.TemporaryDirectory(prefix="archive-keeper-ui-build-")
        cls.binary = Path(cls._build.name) / "archive-keeper-ui"
        subprocess.run(
            ["go", "build", "-trimpath", "-o", str(cls.binary),
             "./cmd/archive-keeper-ui"],
            cwd=REPOSITORY_ROOT,
            check=True,
            timeout=120,
        )

    @classmethod
    def tearDownClass(cls) -> None:
        cls._build.cleanup()

    def test_keyboard_navigation_help_and_clean_exit(self) -> None:
        fixture = DisposableGalaxyFixture(group_count=8)
        terminal = TerminalProcess([str(self.binary)], fixture.environment())
        try:
            terminal.wait_for("MISSION CONTROL")
            terminal.send(b"\x1b[B")  # Down Arrow selects Duplicate Groups.
            terminal.send(b"\r")
            terminal.wait_for("DUPLICATE CONSTELLATIONS")
            terminal.send(b"?")
            terminal.wait_for("GALACTIC FIELD GUIDE")
            terminal.send(b"q")
            self.assertEqual(terminal.wait(), 0)
        finally:
            terminal.close(force=True)
            fixture.close()

    def test_resize_causes_complete_redraw(self) -> None:
        fixture = DisposableGalaxyFixture(group_count=8)
        terminal = TerminalProcess([str(self.binary)], fixture.environment(), 150, 46)
        try:
            terminal.wait_for("MISSION CONTROL")
            start = len(terminal.output)
            terminal.resize(86, 28)
            rendered = terminal.wait_for("FILES UNTOUCHED", start=start)
            self.assertIn("MISSION CONTROL", rendered)
            self.assertIn("ARCHIVE KEEPER", rendered)
            start = len(terminal.output)
            terminal.resize(168, 52)
            rendered = terminal.wait_for("FILES UNTOUCHED", start=start)
            self.assertIn("MISSION CONTROL", rendered)
        finally:
            terminal.close()
            fixture.close()

    def test_tmux_detach_reattach_preserves_screen_and_redraws(self) -> None:
        tmux = shutil.which("tmux")
        if tmux is None:
            self.skipTest("tmux is not installed")
        fixture = DisposableGalaxyFixture(group_count=8)
        socket = "archive-keeper-" + self.binary.parent.name[-8:]
        session = "pty-reconnect"
        environment = fixture.environment()
        subprocess.run(
            [tmux, "-L", socket, "new-session", "-d", "-s", session,
             "-x", "140", "-y", "44", str(self.binary)],
            env=environment,
            check=True,
            timeout=10,
        )
        first = TerminalProcess(
            [tmux, "-L", socket, "attach-session", "-t", session], environment
        )
        second = None
        try:
            first.wait_for("MISSION CONTROL")
            first.send(b"2")
            first.wait_for("DUPLICATE CONSTELLATIONS")
            first.send(b"\x02d")  # tmux prefix Ctrl-B, then detach.
            self.assertEqual(first.wait(), 0)
            first.close(force=True)

            second = TerminalProcess(
                [tmux, "-L", socket, "attach-session", "-t", session], environment,
                112, 34,
            )
            second.wait_for("DUPLICATE CONSTELLATIONS")
            start = len(second.output)
            second.resize(160, 48)
            rendered = second.wait_for("FILES UNTOUCHED", start=start)
            self.assertIn("DUPLICATE CONSTELLATIONS", rendered)
            second.send(b"q")
            self.assertEqual(second.wait(), 0)
        finally:
            first.close(force=True)
            if second is not None:
                second.close(force=True)
            subprocess.run(
                [tmux, "-L", socket, "kill-server"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5,
            )
            fixture.close()

    def test_very_large_fake_report_is_searchable(self) -> None:
        # 50,000 groups / 100,000 duplicate records is intentionally much
        # larger than the dashboard preview while remaining CI-friendly.
        fixture = DisposableGalaxyFixture(group_count=50_000)
        terminal = TerminalProcess([str(self.binary)], fixture.environment(), 160, 48)
        try:
            terminal.wait_for("MISSION CONTROL", timeout=45)
            terminal.send(b"2")
            terminal.wait_for("DUPLICATE CONSTELLATIONS", timeout=45)
            terminal.send(b"/")
            terminal.wait_for("SEARCH ALL DUPLICATE PATHS")
            terminal.send(b"group-50000\r")
            rendered = terminal.wait_for("G50000", timeout=45)
            if "49.83 KiB" not in rendered:
                rendered = terminal.wait_for("49.83 KiB", timeout=5)
            self.assertIn("49.83 KiB", rendered)
        finally:
            terminal.close()
            fixture.close()


if __name__ == "__main__":
    unittest.main()
