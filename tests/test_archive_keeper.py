import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from archive_keeper.core import load_rmlint_groups, choose_keeper


class ArchiveKeeperTests(unittest.TestCase):
    def make_report(self, root: Path):
        a = root / "MyCloud1" / "keep.bin"
        b = root / "MyCloud2" / "copy.bin"
        c = root / "MyCloud3" / "copy.bin"
        for p in (a, b, c):
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b"x" * 1024)

        report = root / "rmlint.json"
        report.write_text(json.dumps([
            {"description": "header"},
            {"type": "duplicate_file", "path": str(a), "size": 1024, "is_original": True},
            {"type": "duplicate_file", "path": str(b), "size": 1024, "is_original": False},
            {"type": "duplicate_file", "path": str(c), "size": 1024, "is_original": False},
            {"description": "footer"}
        ]))
        return report, a, b, c

    def test_parser_and_keeper(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            report, a, b, c = self.make_report(root)
            groups = load_rmlint_groups(report)
            self.assertEqual(len(groups), 1)
            keeper = choose_keeper(
                groups[0],
                [root / "MyCloud1", root / "MyCloud2", root / "MyCloud3"],
                [],
                "preferred-root",
            )
            self.assertEqual(keeper.path, a.resolve())

    def test_quarantine_and_restore(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            report, a, b, c = self.make_report(root)
            state = root / "state.sqlite3"
            run_id = "test-run"
            base = [
                sys.executable, "-m", "archive_keeper",
                "--report", str(report),
                "--mount-policy", "ignore",
                "--state-db", str(state),
                "--mount-root", str(root / "MyCloud1"),
                "--mount-root", str(root / "MyCloud2"),
                "--mount-root", str(root / "MyCloud3"),
                "--prefer", str(root / "MyCloud1"),
            ]
            result = subprocess.run(
                base + ["quarantine", "--run-id", run_id, "--apply"],
                text=True, capture_output=True
            )
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            self.assertTrue(a.exists())
            self.assertFalse(b.exists())
            self.assertFalse(c.exists())
            self.assertTrue((root / "MyCloud2" / "ArchiveKeeper Quarantine" / run_id / "copy.bin").exists())
            self.assertTrue((root / "MyCloud3" / "ArchiveKeeper Quarantine" / run_id / "copy.bin").exists())

            result = subprocess.run(
                base + ["restore", run_id, "--apply"],
                text=True, capture_output=True
            )
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            self.assertTrue(a.exists())
            self.assertTrue(b.exists())
            self.assertTrue(c.exists())


    def test_tui_quits_without_changes(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            report, a, b, c = self.make_report(root)
            state = root / "state.sqlite3"
            result = subprocess.run([
                sys.executable, "-m", "archive_keeper",
                "--report", str(report), "--state-db", str(state),
                "--mount-policy", "ignore",
                "--mount-root", str(root / "MyCloud1"),
                "--mount-root", str(root / "MyCloud2"),
                "--mount-root", str(root / "MyCloud3"),
                "--prefer", str(root / "MyCloud1"), "tui"],
                input="q\n", text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            self.assertTrue(a.exists() and b.exists() and c.exists())
            self.assertIn("No files were changed.", result.stdout)


    def test_manual_keeper_decision(self):
        from archive_keeper.decisions import DecisionStore
        from archive_keeper.review import resolve_keeper
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            report, a, b, c = self.make_report(root)
            group = load_rmlint_groups(report)[0]
            store = DecisionStore(root / "decisions.sqlite3")
            store.set_keeper(group.group_id, c.resolve())
            keeper = resolve_keeper(group, [root / "MyCloud1"], [], "preferred-root", store)
            self.assertEqual(keeper.path, c.resolve())
            store.close()

    def test_text_metadata_preview(self):
        from archive_keeper.metadata import inspect_path
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "note.txt"
            path.write_text("hello archive keeper")
            meta = inspect_path(path)
            self.assertEqual(meta.kind, "text")
            self.assertIn("hello archive keeper", meta.preview)

    def test_file_decisions_round_trip(self):
        from archive_keeper.decisions import DecisionStore
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            path = root / "copy.bin"
            store = DecisionStore(root / "decisions.sqlite3")
            store.set_action(7, path, "UNDECIDED")
            self.assertEqual(store.get_action(7, path), "UNDECIDED")
            store.set_action(7, path, "QUARANTINE")
            self.assertEqual(store.get_action(7, path), "QUARANTINE")
            store.clear_action(7, path)
            self.assertIsNone(store.get_action(7, path))
            store.close()

    def test_undecided_copy_is_not_moved(self):
        from archive_keeper.decisions import DecisionStore
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            report, a, b, c = self.make_report(root)
            state = root / "state.sqlite3"
            decisions_path = root / "decisions.sqlite3"
            group = load_rmlint_groups(report)[0]
            store = DecisionStore(decisions_path)
            store.set_keeper(group.group_id, a)
            store.set_action(group.group_id, b, "UNDECIDED")
            store.close()
            result = subprocess.run([
                sys.executable, "-m", "archive_keeper",
                "--report", str(report), "--state-db", str(state),
                "--mount-policy", "ignore",
                "--decisions-db", str(decisions_path),
                "--mount-root", str(root / "MyCloud1"),
                "--mount-root", str(root / "MyCloud2"),
                "--mount-root", str(root / "MyCloud3"),
                "--prefer", str(root / "MyCloud1"),
                "quarantine", "--run-id", "decision-run", "--apply"
            ], text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            self.assertTrue(a.exists())
            self.assertTrue(b.exists())
            self.assertFalse(c.exists())

    def test_short_path_preserves_filename(self):
        from archive_keeper.rich_tui import _short_path
        root = Path("/mnt/MyCloud1")
        path = root / "very" / "long" / "nested" / "directory" / "distinctive-file-name.mp4"
        shown = _short_path(path, [root], 38)
        self.assertTrue(shown.startswith("distinctive-file"))
        self.assertIn("MyCloud1", shown)
        self.assertLessEqual(len(shown), 38)

    def test_parser_does_not_stat_report_paths(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            missing_a = root / "MyCloud1" / "missing-a.bin"
            missing_b = root / "MyCloud2" / "missing-b.bin"
            report = root / "rmlint.json"
            report.write_text(json.dumps([
                {"description": "header"},
                {"type": "duplicate_file", "path": str(missing_a), "size": 55, "is_original": True},
                {"type": "duplicate_file", "path": str(missing_b), "size": 55, "is_original": False},
                {"description": "footer"},
            ]))
            with patch.object(Path, "stat", side_effect=AssertionError("parser touched filesystem")):
                groups = load_rmlint_groups(report)
            self.assertEqual(len(groups), 1)
            self.assertEqual(groups[0].files[0].mtime, 0.0)

    def test_tui_action_for_compares_duplicate_paths(self):
        from types import SimpleNamespace
        from archive_keeper.rich_tui import ReviewUI
        from archive_keeper.core import DuplicateFile

        keeper = DuplicateFile(Path("/mnt/MyCloud1/a.mp4"), 10, 0.0, None, None, True, None, 1)
        copy = DuplicateFile(Path("/mnt/MyCloud2/a.mp4"), 10, 0.0, None, None, False, None, 1)
        group = SimpleNamespace(group_id=1)
        fake = SimpleNamespace(decisions=SimpleNamespace(get_action=lambda group_id, path: None))

        self.assertEqual(ReviewUI.action_for(fake, group, keeper, keeper), "KEEP")
        self.assertEqual(ReviewUI.action_for(fake, group, copy, keeper), "QUARANTINE")

    def test_mount_check_fails_closed(self):
        from archive_keeper.mounts import ensure_mounts
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(RuntimeError):
                ensure_mounts([Path(td) / "not-mounted"], "check")

    def test_bounded_preflight_timeout_returns_to_parent(self):
        from unittest.mock import patch
        from subprocess import TimeoutExpired
        from archive_keeper.core import bounded_quarantine_preflight

        class FakeProc:
            def __init__(self):
                self.killed = False
                self.returncode = None
            def communicate(self, timeout=None):
                raise TimeoutExpired(cmd="verify-worker", timeout=timeout)
            def kill(self):
                self.killed = True

        fake = FakeProc()
        with patch("archive_keeper.core.subprocess.Popen", return_value=fake):
            ok, message, timed_out, outcome = bounded_quarantine_preflight(
                Path("/mnt/MyCloud1/keep.bin"),
                Path("/mnt/MyCloud2/copy.bin"),
                Path("/mnt/MyCloud2/.ArchiveKeeper/run/copy.bin"),
                Path("/mnt/MyCloud2"),
                timeout=0.1,
            )
        self.assertFalse(ok)
        self.assertTrue(timed_out)
        self.assertTrue(fake.killed)
        self.assertIn("timed out", message)
        self.assertEqual(outcome, "timeout")

    def test_dry_run_limit_counts_candidates(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            a = root / "MyCloud1" / "keep.bin"
            a.parent.mkdir(parents=True, exist_ok=True)
            a.write_bytes(b"x" * 32)
            entries = [{"description": "header"}, {"type": "duplicate_file", "path": str(a), "size": 32, "is_original": True}]
            for i in range(5):
                pth = root / "MyCloud2" / f"copy-{i}.bin"
                pth.parent.mkdir(parents=True, exist_ok=True)
                pth.write_bytes(b"x" * 32)
                entries.append({"type": "duplicate_file", "path": str(pth), "size": 32, "is_original": False})
            entries.append({"description": "footer"})
            report = root / "rmlint.json"
            report.write_text(json.dumps(entries))
            state = root / "state.sqlite3"
            result = subprocess.run([
                sys.executable, "-m", "archive_keeper",
                "--report", str(report), "--state-db", str(state),
                "--mount-policy", "ignore",
                "--mount-root", str(root / "MyCloud1"),
                "--mount-root", str(root / "MyCloud2"),
                "--prefer", str(root / "MyCloud1"),
                "quarantine", "--run-id", "limit-test", "--limit", "2",
                "--verify-timeout", "5"
            ], text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            self.assertIn("Stopped at --limit=2", result.stdout)
            conn = __import__("sqlite3").connect(state)
            count = conn.execute("SELECT COUNT(*) FROM actions WHERE run_id='limit-test'").fetchone()[0]
            conn.close()
            self.assertEqual(count, 2)


    def _base_cli(self, root: Path, report: Path, state: Path):
        return [
            sys.executable, "-m", "archive_keeper",
            "--report", str(report), "--state-db", str(state),
            "--mount-policy", "ignore",
            "--mount-root", str(root / "MyCloud1"),
            "--mount-root", str(root / "MyCloud2"),
            "--mount-root", str(root / "MyCloud3"),
            "--prefer", str(root / "MyCloud1"),
        ]

    def test_quarantine_identical_existing_destination_is_reconciled(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            report, a, b, c = self.make_report(root)
            state = root / "state.sqlite3"
            q = root / "MyCloud2" / "ArchiveKeeper Quarantine" / "collision-identical" / "copy.bin"
            q.parent.mkdir(parents=True, exist_ok=True)
            q.write_bytes(b.read_bytes())

            result = subprocess.run(
                self._base_cli(root, report, state) + [
                    "quarantine", "--run-id", "collision-identical", "--limit", "1", "--apply"
                ], text=True, capture_output=True
            )
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            self.assertTrue(b.exists())
            self.assertTrue(q.exists())
            self.assertIn("Reconciled    : 1", result.stdout)
            self.assertIn("Failed        : 0", result.stdout)
            conn = __import__("sqlite3").connect(state)
            status = conn.execute(
                "SELECT status FROM actions WHERE run_id=? AND source=?",
                ("collision-identical", str(b.resolve())),
            ).fetchone()[0]
            conn.close()
            self.assertEqual(status, "reconciled")

    def test_quarantine_different_existing_destination_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            report, a, b, c = self.make_report(root)
            state = root / "state.sqlite3"
            q = root / "MyCloud2" / "ArchiveKeeper Quarantine" / "collision-different" / "copy.bin"
            q.parent.mkdir(parents=True, exist_ok=True)
            q.write_bytes(b"y" * 1024)

            result = subprocess.run(
                self._base_cli(root, report, state) + [
                    "quarantine", "--run-id", "collision-different", "--limit", "1", "--apply"
                ], text=True, capture_output=True
            )
            self.assertEqual(result.returncode, 1, result.stderr + result.stdout)
            self.assertTrue(b.exists())
            self.assertEqual(q.read_bytes(), b"y" * 1024)
            self.assertIn("Failed        : 1", result.stdout)

    def test_restore_identical_existing_source_reconciles_quarantine_copy(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            report, a, b, c = self.make_report(root)
            state = root / "state.sqlite3"
            base = self._base_cli(root, report, state)
            result = subprocess.run(
                base + ["quarantine", "--run-id", "restore-identical", "--limit", "1", "--apply"],
                text=True, capture_output=True
            )
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            q = root / "MyCloud2" / "ArchiveKeeper Quarantine" / "restore-identical" / "copy.bin"
            self.assertFalse(b.exists())
            self.assertTrue(q.exists())
            b.write_bytes(q.read_bytes())

            result = subprocess.run(
                base + ["restore", "restore-identical", "--apply"],
                text=True, capture_output=True
            )
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            self.assertTrue(b.exists())
            self.assertFalse(q.exists())
            self.assertIn("reconciled: 1", result.stdout)
            conn = __import__("sqlite3").connect(state)
            status = conn.execute(
                "SELECT status FROM actions WHERE run_id=? AND source=?",
                ("restore-identical", str(b.resolve())),
            ).fetchone()[0]
            conn.close()
            self.assertEqual(status, "reconciled")

    def test_restore_different_existing_source_leaves_both_untouched(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            report, a, b, c = self.make_report(root)
            state = root / "state.sqlite3"
            base = self._base_cli(root, report, state)
            result = subprocess.run(
                base + ["quarantine", "--run-id", "restore-different", "--limit", "1", "--apply"],
                text=True, capture_output=True
            )
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            q = root / "MyCloud2" / "ArchiveKeeper Quarantine" / "restore-different" / "copy.bin"
            original_quarantine = q.read_bytes()
            b.write_bytes(b"z" * 1024)

            result = subprocess.run(
                base + ["restore", "restore-different", "--apply"],
                text=True, capture_output=True
            )
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            self.assertEqual(b.read_bytes(), b"z" * 1024)
            self.assertEqual(q.read_bytes(), original_quarantine)
            self.assertIn("skipped: 1", result.stdout)
            conn = __import__("sqlite3").connect(state)
            status = conn.execute(
                "SELECT status FROM actions WHERE run_id=? AND source=?",
                ("restore-different", str(b.resolve())),
            ).fetchone()[0]
            conn.close()
            self.assertEqual(status, "moved")

    def test_custom_quarantine_name_for_new_run(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            report, a, b, c = self.make_report(root)
            state = root / "state.sqlite3"
            result = subprocess.run(
                self._base_cli(root, report, state) + [
                    "--quarantine-name", "My Visible Holding",
                    "quarantine", "--run-id", "custom-name", "--limit", "1", "--apply"
                ], text=True, capture_output=True
            )
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            self.assertTrue((root / "MyCloud2" / "My Visible Holding" / "custom-name" / "copy.bin").exists())

    def test_legacy_hidden_run_reuses_journaled_name_on_resume(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            report, a, b, c = self.make_report(root)
            state = root / "state.sqlite3"
            base = self._base_cli(root, report, state)
            result = subprocess.run(
                base + [
                    "--quarantine-name", ".ArchiveKeeper",
                    "quarantine", "--run-id", "legacy-run", "--limit", "1", "--apply"
                ], text=True, capture_output=True
            )
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            self.assertTrue((root / "MyCloud2" / ".ArchiveKeeper" / "legacy-run" / "copy.bin").exists())

            result = subprocess.run(
                base + ["quarantine", "--run-id", "legacy-run", "--limit", "1", "--apply"],
                text=True, capture_output=True
            )
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            self.assertTrue((root / "MyCloud3" / ".ArchiveKeeper" / "legacy-run" / "copy.bin").exists())
            self.assertFalse((root / "MyCloud3" / "ArchiveKeeper Quarantine" / "legacy-run").exists())
            self.assertIn("existing quarantine directory: .ArchiveKeeper", result.stdout)

    def test_existing_run_rejects_conflicting_quarantine_name(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            report, a, b, c = self.make_report(root)
            state = root / "state.sqlite3"
            base = self._base_cli(root, report, state)
            first = subprocess.run(
                base + [
                    "--quarantine-name", ".ArchiveKeeper",
                    "quarantine", "--run-id", "conflict-name", "--limit", "1", "--apply"
                ], text=True, capture_output=True
            )
            self.assertEqual(first.returncode, 0, first.stderr + first.stdout)
            second = subprocess.run(
                base + [
                    "--quarantine-name", "Other Quarantine",
                    "quarantine", "--run-id", "conflict-name", "--limit", "1", "--apply"
                ], text=True, capture_output=True
            )
            self.assertNotEqual(second.returncode, 0)
            self.assertIn("refusing to switch", second.stderr + second.stdout)
            self.assertFalse((root / "MyCloud3" / "Other Quarantine" / "conflict-name").exists())

    def test_progress_tracker_reports_fraction_and_counter(self):
        import io
        from archive_keeper.progress import ProgressTracker
        stream = io.StringIO()
        tracker = ProgressTracker("Quarantine", total=4, stream=stream)
        tracker.current(1, "VERIFYING", "/tmp/a")
        tracker.result("QUARANTINED", "/tmp/a", counter="moved")
        tracker.finish("complete")
        output = stream.getvalue()
        self.assertIn("1/4", output)
        self.assertIn("25.0%", output)
        self.assertIn("moved=1", output)
        self.assertIn("processed 1/4", output)

    def test_version_is_1_6_6(self):
        from archive_keeper import __version__
        self.assertEqual(__version__, "1.6.6")

if __name__ == "__main__":
    unittest.main()
