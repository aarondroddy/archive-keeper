import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from archive_keeper.ui_bridge import (
    PROTOCOL_VERSION,
    dashboard_snapshot,
    main,
    select_keeper,
    set_file_action,
)


class UIBridgeTests(unittest.TestCase):
    def _report(self, root: Path) -> Path:
        report = root / "rmlint.json"
        report.write_text(
            json.dumps(
                [
                    {"description": "rmlint header"},
                    {"path": str(root / "keeper.bin"), "size": 4096, "type": "duplicate_file", "is_original": True},
                    {"path": str(root / "copy-a.bin"), "size": 4096, "type": "duplicate_file"},
                    {"path": str(root / "copy-b.bin"), "size": 4096, "type": "duplicate_file"},
                    {"description": "rmlint footer"},
                ]
            ),
            encoding="utf-8",
        )
        return report

    def _databases(self, root: Path) -> tuple[Path, Path]:
        decisions = root / "decisions.sqlite3"
        with sqlite3.connect(decisions) as connection:
            connection.executescript(
                """
                CREATE TABLE keeper_decisions (group_id INTEGER PRIMARY KEY, keeper_path TEXT, reason TEXT, updated_at REAL);
                CREATE TABLE favorites (path TEXT PRIMARY KEY, note TEXT, updated_at REAL);
                CREATE TABLE file_decisions (group_id INTEGER, path TEXT, action TEXT, updated_at REAL);
                INSERT INTO keeper_decisions VALUES (1, '/keeper', 'manual', 1);
                INSERT INTO favorites VALUES ('/keeper', '', 1);
                INSERT INTO file_decisions VALUES (1, '/copy-a', 'QUARANTINE', 1);
                INSERT INTO file_decisions VALUES (1, '/copy-b', 'UNDECIDED', 1);
                """
            )

        journal = root / "journal.sqlite3"
        with sqlite3.connect(journal) as connection:
            connection.executescript(
                """
                CREATE TABLE runs (run_id TEXT PRIMARY KEY, created_at REAL, report_path TEXT, mode TEXT, status TEXT);
                CREATE TABLE actions (id INTEGER PRIMARY KEY, run_id TEXT, status TEXT);
                INSERT INTO runs VALUES ('pilot-1', 1, '/report', 'dry-run', 'complete');
                INSERT INTO actions VALUES (1, 'pilot-1', 'moved');
                INSERT INTO actions VALUES (2, 'pilot-1', 'failed');
                """
            )
        return journal, decisions

    @staticmethod
    def _sha256(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def test_dashboard_snapshot_reports_live_read_only_counts(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            report = self._report(root)
            journal, decisions = self._databases(root)
            before = {path: self._sha256(path) for path in (journal, decisions)}

            snapshot = dashboard_snapshot(report, journal, decisions)

            self.assertEqual(snapshot["protocol_version"], PROTOCOL_VERSION)
            self.assertEqual(snapshot["mode"], "read-only")
            self.assertTrue(snapshot["ok"])
            self.assertEqual(snapshot["report"]["groups"], 1)
            self.assertEqual(snapshot["report"]["files"], 3)
            self.assertEqual(snapshot["report"]["recoverable_bytes"], 8192)
            self.assertEqual(len(snapshot["report"]["largest_groups"][0]["files"]), 3)
            self.assertTrue(snapshot["report"]["largest_groups"][0]["files"][0]["original_hint"])
            self.assertEqual(snapshot["decisions"]["keepers"], 1)
            self.assertEqual(snapshot["decisions"]["actions"], {"QUARANTINE": 1, "UNDECIDED": 1})
            self.assertEqual(snapshot["decisions"]["keeper_paths"], {"1": "/keeper"})
            self.assertEqual(
                snapshot["decisions"]["file_actions"],
                {"1\n/copy-a": "QUARANTINE", "1\n/copy-b": "UNDECIDED"},
            )
            self.assertEqual(snapshot["journal"]["runs"], 1)
            self.assertEqual(snapshot["journal"]["status_counts"], {"failed": 1, "moved": 1})
            self.assertEqual(before, {path: self._sha256(path) for path in (journal, decisions)})
            self.assertFalse(Path(str(journal) + "-wal").exists())
            self.assertFalse(Path(str(decisions) + "-wal").exists())

    def test_missing_inputs_are_structured_and_never_created(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            report = root / "missing-report.json"
            journal = root / "missing-journal.sqlite3"
            decisions = root / "missing-decisions.sqlite3"

            snapshot = dashboard_snapshot(report, journal, decisions)

            self.assertFalse(snapshot["ok"])
            self.assertEqual(len(snapshot["warnings"]), 3)
            self.assertFalse(report.exists())
            self.assertFalse(journal.exists())
            self.assertFalse(decisions.exists())

    def test_file_action_requires_keeper_and_never_creates_database(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            report = self._report(root)
            decisions = root / "decisions.sqlite3"

            result = set_file_action(
                report, decisions, 1, root / "copy-a.bin", "QUARANTINE"
            )

            self.assertFalse(result["ok"])
            self.assertEqual(result["files_moved"], 0)
            self.assertFalse(decisions.exists())

    def test_file_action_cannot_stage_keeper_and_can_stage_and_clear_copy(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            report = self._report(root)
            decisions = root / "decisions.sqlite3"
            keeper = root / "keeper.bin"
            copy = root / "copy-a.bin"
            self.assertTrue(select_keeper(report, decisions, 1, keeper)["ok"])

            rejected = set_file_action(report, decisions, 1, keeper, "QUARANTINE")
            staged = set_file_action(report, decisions, 1, copy, "QUARANTINE")
            cleared = set_file_action(report, decisions, 1, copy, "CLEAR")

            self.assertFalse(rejected["ok"])
            self.assertIn("keeper cannot", rejected["error"])
            self.assertTrue(staged["ok"])
            self.assertTrue(cleared["ok"])
            with sqlite3.connect(decisions) as connection:
                count = connection.execute("SELECT COUNT(*) FROM file_decisions").fetchone()[0]
            self.assertEqual(count, 0)

    def test_main_emits_one_json_document(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            report = self._report(root)
            journal = root / "missing-journal.sqlite3"
            decisions = root / "missing-decisions.sqlite3"
            from contextlib import redirect_stdout
            from io import StringIO

            output = StringIO()
            with redirect_stdout(output):
                result = main([
                    "dashboard",
                    "--report", str(report),
                    "--state-db", str(journal),
                    "--decisions-db", str(decisions),
                ])

            self.assertEqual(result, 0)
            payload = json.loads(output.getvalue())
            self.assertEqual(payload["protocol_version"], PROTOCOL_VERSION)

    def test_select_keeper_validates_membership_and_persists_decision(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            report = self._report(root)
            decisions = root / "new-decisions.sqlite3"
            selected = root / "copy-b.bin"

            result = select_keeper(report, decisions, 1, selected)

            self.assertTrue(result["ok"])
            self.assertEqual(result["files_moved"], 0)
            with sqlite3.connect(decisions) as connection:
                row = connection.execute(
                    "SELECT keeper_path, reason FROM keeper_decisions WHERE group_id=1"
                ).fetchone()
            self.assertEqual(row, (str(selected), "selected in Storage Galaxy UI"))

    def test_select_keeper_rejects_path_outside_group_without_creating_db(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            report = self._report(root)
            decisions = root / "decisions.sqlite3"

            result = select_keeper(report, decisions, 1, root / "stranger.bin")

            self.assertFalse(result["ok"])
            self.assertIn("not a member", result["error"])
            self.assertFalse(decisions.exists())

    def test_selecting_keeper_clears_conflicting_file_action(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            report = self._report(root)
            decisions = root / "decisions.sqlite3"
            first = root / "keeper.bin"
            replacement = root / "copy-a.bin"
            self.assertTrue(select_keeper(report, decisions, 1, first)["ok"])
            self.assertTrue(
                set_file_action(report, decisions, 1, replacement, "QUARANTINE")["ok"]
            )

            result = select_keeper(report, decisions, 1, replacement)

            self.assertTrue(result["ok"])
            with sqlite3.connect(decisions) as connection:
                row = connection.execute(
                    "SELECT action FROM file_decisions WHERE group_id=1 AND path=?",
                    (str(replacement),),
                ).fetchone()
            self.assertIsNone(row)


if __name__ == "__main__":
    unittest.main()
