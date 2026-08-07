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


if __name__ == "__main__":
    unittest.main()
