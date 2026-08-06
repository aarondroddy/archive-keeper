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


if __name__ == "__main__":
    unittest.main()
