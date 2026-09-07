import hashlib
import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from archive_keeper.ui_bridge import (
    PROTOCOL_VERSION,
    _mount_summary,
    controlled_quarantine_apply,
    controlled_restore_apply,
    dashboard_snapshot,
    history_run_snapshot,
    main,
    quarantine_dry_run,
    quarantine_plan_snapshot,
    restore_catalog_snapshot,
    restore_plan_snapshot,
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

    def test_file_action_rejection_does_not_initialize_existing_database(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            report = self._report(root)
            decisions = root / "decisions.sqlite3"
            with sqlite3.connect(decisions):
                pass
            before = self._sha256(decisions)

            result = set_file_action(
                report, decisions, 1, root / "copy-a.bin", "QUARANTINE"
            )

            self.assertFalse(result["ok"])
            self.assertEqual(self._sha256(decisions), before)
            with sqlite3.connect(decisions) as connection:
                tables = connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            self.assertEqual(tables, [])

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

    def test_quarantine_plan_is_read_only_and_uses_engine_destination(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            report = self._report(root)
            decisions = root / "decisions.sqlite3"
            keeper = root / "keeper.bin"
            copy = root / "copy-a.bin"
            keeper.write_bytes(b"same")
            copy.write_bytes(b"same")
            self.assertTrue(select_keeper(report, decisions, 1, keeper)["ok"])
            self.assertTrue(set_file_action(report, decisions, 1, copy, "QUARANTINE")["ok"])
            before = self._sha256(decisions)

            with patch("archive_keeper.ui_bridge.os.path.ismount", return_value=True):
                plan = quarantine_plan_snapshot(
                    report,
                    decisions,
                    [root],
                    "ArchiveKeeper Quarantine",
                    "preview-1",
                )

            self.assertTrue(plan["ok"])
            self.assertEqual(plan["mode"], "read-only")
            self.assertEqual(plan["files_moved"], 0)
            self.assertEqual(plan["total_files"], 1)
            self.assertEqual(plan["total_bytes"], 4096)
            self.assertEqual(plan["ready_files"], 1)
            self.assertEqual(plan["blocked_files"], 0)
            self.assertEqual(plan["items"][0]["status"], "READY")
            self.assertEqual(plan["items"][0]["source"], str(copy))
            self.assertEqual(plan["items"][0]["keeper"], str(keeper))
            self.assertEqual(
                plan["items"][0]["destination"],
                str(root / "ArchiveKeeper Quarantine" / "preview-1" / "copy-a.bin"),
            )
            self.assertEqual(self._sha256(decisions), before)
            self.assertFalse((root / "ArchiveKeeper Quarantine").exists())

    def test_quarantine_plan_blocks_unmounted_root_and_never_probes_files(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            report = self._report(root)
            decisions = root / "decisions.sqlite3"
            keeper = root / "keeper.bin"
            copy = root / "copy-a.bin"
            self.assertTrue(select_keeper(report, decisions, 1, keeper)["ok"])
            self.assertTrue(set_file_action(report, decisions, 1, copy, "QUARANTINE")["ok"])

            with (
                patch("archive_keeper.ui_bridge.os.path.ismount", return_value=False),
                patch("archive_keeper.ui_bridge._bounded_path_probe") as probe,
            ):
                plan = quarantine_plan_snapshot(report, decisions, [root])

            self.assertEqual(plan["ready_files"], 0)
            self.assertEqual(plan["blocked_files"], 1)
            self.assertIn("mount is unavailable", " ".join(plan["items"][0]["warnings"]))
            probe.assert_not_called()

    def test_quarantine_plan_flags_existing_destination_collision(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            report = self._report(root)
            decisions = root / "decisions.sqlite3"
            keeper = root / "keeper.bin"
            copy = root / "copy-a.bin"
            keeper.write_bytes(b"same")
            copy.write_bytes(b"same")
            self.assertTrue(select_keeper(report, decisions, 1, keeper)["ok"])
            self.assertTrue(set_file_action(report, decisions, 1, copy, "QUARANTINE")["ok"])
            destination = root / "ArchiveKeeper Quarantine" / "preview-2" / "copy-a.bin"
            destination.parent.mkdir(parents=True)
            destination.write_bytes(b"occupied")

            with patch("archive_keeper.ui_bridge.os.path.ismount", return_value=True):
                plan = quarantine_plan_snapshot(
                    report, decisions, [root], run_id="preview-2"
                )

            self.assertEqual(plan["blocked_files"], 1)
            self.assertIn("collision", " ".join(plan["items"][0]["warnings"]))

    def test_quarantine_dry_run_is_bounded_and_never_mutates(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            report = self._report(root)
            decisions = root / "decisions.sqlite3"
            keeper = root / "keeper.bin"
            first = root / "copy-a.bin"
            second = root / "copy-b.bin"
            for path in (keeper, first, second):
                path.write_bytes(b"same")
            self.assertTrue(select_keeper(report, decisions, 1, keeper)["ok"])
            self.assertTrue(set_file_action(report, decisions, 1, first, "QUARANTINE")["ok"])
            self.assertTrue(set_file_action(report, decisions, 1, second, "QUARANTINE")["ok"])
            before = self._sha256(decisions)

            with (
                patch("archive_keeper.ui_bridge.os.path.ismount", return_value=True),
                patch(
                    "archive_keeper.ui_bridge.bounded_quarantine_preflight",
                    return_value=(True, "size verified; report trusted", False, "ready"),
                ) as preflight,
            ):
                result = quarantine_dry_run(
                    report, decisions, [root], run_id="pilot-preview", limit=1
                )

            self.assertTrue(result["ok"])
            self.assertEqual(result["mode"], "dry-run")
            self.assertEqual(result["files_moved"], 0)
            self.assertEqual(result["journal_writes"], 0)
            self.assertEqual(result["total_staged"], 2)
            self.assertEqual(result["attempted"], 1)
            self.assertEqual(result["verified"], 1)
            self.assertTrue(result["limited"])
            preflight.assert_called_once()
            self.assertEqual(self._sha256(decisions), before)
            self.assertFalse((root / "ArchiveKeeper Quarantine").exists())

    def test_controlled_apply_requires_exact_confirmation_before_journaling(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            report = self._report(root)
            decisions = root / "decisions.sqlite3"
            state = root / "journal.sqlite3"

            result = controlled_quarantine_apply(
                report,
                state,
                decisions,
                "yes",
                [root],
                limit=1,
            )

            self.assertFalse(result["ok"])
            self.assertEqual(result["files_moved"], 0)
            self.assertIn("QUARANTINE UP TO 1 FILES", result["error"])
            self.assertFalse(state.exists())

    def test_controlled_apply_moves_only_staged_copy_and_is_restore_compatible(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            report = self._report(root)
            decisions = root / "decisions.sqlite3"
            state = root / "journal.sqlite3"
            keeper = root / "keeper.bin"
            staged = root / "copy-a.bin"
            untouched = root / "copy-b.bin"
            for path in (keeper, staged, untouched):
                path.write_bytes(b"x" * 4096)
            self.assertTrue(select_keeper(report, decisions, 1, keeper)["ok"])
            self.assertTrue(set_file_action(report, decisions, 1, staged, "QUARANTINE")["ok"])

            with patch("archive_keeper.ui_bridge.os.path.ismount", return_value=True):
                result = controlled_quarantine_apply(
                    report,
                    state,
                    decisions,
                    "QUARANTINE UP TO 1 FILES",
                    [root],
                    run_id="ui-apply-test",
                    limit=1,
                    verify_timeout=5,
                )

            destination = (
                root / "ArchiveKeeper Quarantine" / "ui-apply-test" / "copy-a.bin"
            )
            self.assertTrue(result["ok"])
            self.assertEqual(result["files_moved"], 1)
            self.assertTrue(keeper.exists())
            self.assertFalse(staged.exists())
            self.assertTrue(untouched.exists())
            self.assertTrue(destination.exists())
            with sqlite3.connect(state) as connection:
                row = connection.execute(
                    "SELECT mode, status FROM runs WHERE run_id='ui-apply-test'"
                ).fetchone()
                action = connection.execute(
                    "SELECT source, destination, status FROM actions "
                    "WHERE run_id='ui-apply-test'"
                ).fetchone()
            self.assertEqual(row, ("apply", "complete"))
            self.assertEqual(action, (str(staged), str(destination), "moved"))

            restored = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "archive_keeper",
                    "--state-db",
                    str(state),
                    "restore",
                    "ui-apply-test",
                    "--apply",
                ],
                text=True,
                capture_output=True,
            )
            self.assertEqual(restored.returncode, 0, restored.stderr + restored.stdout)
            self.assertTrue(staged.exists())
            self.assertFalse(destination.exists())

    def test_controlled_apply_no_clobber_guard_survives_race(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            report = self._report(root)
            decisions = root / "decisions.sqlite3"
            state = root / "journal.sqlite3"
            keeper = root / "keeper.bin"
            staged = root / "copy-a.bin"
            keeper.write_bytes(b"x" * 4096)
            staged.write_bytes(b"x" * 4096)
            self.assertTrue(select_keeper(report, decisions, 1, keeper)["ok"])
            self.assertTrue(set_file_action(report, decisions, 1, staged, "QUARANTINE")["ok"])
            destination = root / "ArchiveKeeper Quarantine" / "race-test" / "copy-a.bin"

            def create_collision(*args, **kwargs):
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(b"do not overwrite")
                return True, "verified before race", False, "ready"

            with (
                patch("archive_keeper.ui_bridge.os.path.ismount", return_value=True),
                patch(
                    "archive_keeper.ui_bridge.bounded_quarantine_preflight",
                    side_effect=create_collision,
                ),
            ):
                result = controlled_quarantine_apply(
                    report,
                    state,
                    decisions,
                    "QUARANTINE UP TO 1 FILES",
                    [root],
                    run_id="race-test",
                    limit=1,
                )

            self.assertTrue(result["ok"])
            self.assertEqual(result["files_moved"], 0)
            self.assertEqual(result["failed"], 1)
            self.assertTrue(staged.exists())
            self.assertEqual(destination.read_bytes(), b"do not overwrite")

    def test_restore_catalog_preview_and_controlled_apply_round_trip(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            report = self._report(root)
            decisions = root / "decisions.sqlite3"
            state = root / "journal.sqlite3"
            keeper, staged = root / "keeper.bin", root / "copy-a.bin"
            keeper.write_bytes(b"x" * 4096); staged.write_bytes(b"x" * 4096)
            self.assertTrue(select_keeper(report, decisions, 1, keeper)["ok"])
            self.assertTrue(set_file_action(report, decisions, 1, staged, "QUARANTINE")["ok"])
            with patch("archive_keeper.ui_bridge.os.path.ismount", return_value=True):
                moved = controlled_quarantine_apply(report, state, decisions,
                    "QUARANTINE UP TO 1 FILES", [root], run_id="ui-restore-test", limit=1)
                catalog = restore_catalog_snapshot(state)
                plan = restore_plan_snapshot(state, "ui-restore-test", [root])
                restored = controlled_restore_apply(state, "ui-restore-test",
                    "RESTORE UP TO 1 FILES", [root], limit=1)
            self.assertTrue(moved["ok"])
            self.assertEqual(catalog["runs"][0]["run_id"], "ui-restore-test")
            self.assertEqual(plan["ready_files"], 1)
            self.assertTrue(restored["ok"])
            self.assertEqual(restored["restored"], 1)
            self.assertEqual(restored["remaining"], 0)
            self.assertTrue(staged.exists())
            self.assertFalse((root / "ArchiveKeeper Quarantine" / "ui-restore-test" / "copy-a.bin").exists())

    def test_restore_blocks_existing_original_and_requires_exact_confirmation(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); state = root / "journal.sqlite3"; source = root / "original.bin"
            destination = root / "quarantine" / "original.bin"; keeper = root / "keeper.bin"
            source.write_bytes(b"do not overwrite"); destination.parent.mkdir(); destination.write_bytes(b"archived")
            journal = __import__("archive_keeper.core", fromlist=["Journal"]).Journal(state)
            journal.create_run("collision", root / "report.json", "apply")
            journal.record_action("collision", 1, keeper, source, destination, 8, "moved")
            journal.close()
            with patch("archive_keeper.ui_bridge.os.path.ismount", return_value=True):
                plan = restore_plan_snapshot(state, "collision", [root])
                rejected = controlled_restore_apply(state, "collision", "yes", [root], limit=1)
            self.assertEqual(plan["blocked_files"], 1)
            self.assertIn("no overwrite", plan["items"][0]["warnings"][0])
            self.assertFalse(rejected["ok"])
            self.assertEqual(source.read_bytes(), b"do not overwrite")
            self.assertTrue(destination.exists())

    def test_restore_race_never_overwrites_and_remains_restorable(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td); state = root / "journal.sqlite3"; source = root / "original.bin"
            destination = root / "quarantine" / "original.bin"; keeper = root / "keeper.bin"
            destination.parent.mkdir(); destination.write_bytes(b"archived")
            journal = __import__("archive_keeper.core", fromlist=["Journal"]).Journal(state)
            journal.create_run("race", root / "report.json", "apply")
            journal.record_action("race", 1, keeper, source, destination, 8, "moved"); journal.close()
            def race_probe(paths):
                source.write_bytes(b"new original")
                return {str(source): "missing", str(destination): "file"}, None
            with (patch("archive_keeper.ui_bridge.os.path.ismount", return_value=True),
                  patch("archive_keeper.ui_bridge._bounded_path_probe", side_effect=[
                      ({str(source): "missing", str(destination): "file"}, None),
                      race_probe([source, destination]),
                  ])):
                result = controlled_restore_apply(state, "race", "RESTORE UP TO 1 FILES", [root], 1)
            self.assertTrue(result["ok"]); self.assertEqual(result["failed"], 1)
            self.assertEqual(result["remaining"], 1)
            self.assertEqual(source.read_bytes(), b"new original")
            self.assertTrue(destination.exists())


    def test_mount_summary_uses_kernel_mount_table_without_path_probes(self):
        roots = [Path("/mnt/MyCloud1"), Path("/mnt/MyCloud2")]
        mountinfo = (
            "42 31 0:99 / /mnt/MyCloud1 rw,relatime - cifs //192.168.1.121/MyCloud1 rw\n"
        )
        result = _mount_summary(roots, mountinfo)
        self.assertFalse(result["all_ready"])
        self.assertEqual(result["roots"][0]["status"], "ONLINE")
        self.assertEqual(result["roots"][0]["filesystem"], "cifs")
        self.assertEqual(result["roots"][1]["status"], "OFFLINE")


    def test_history_run_snapshot_returns_read_only_action_details(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            state = root / "journal.sqlite3"
            source = root / "source.bin"
            destination = root / "quarantine" / "source.bin"
            keeper = root / "keeper.bin"
            journal = __import__("archive_keeper.core", fromlist=["Journal"]).Journal(state)
            journal.create_run("history-test", root / "report.json", "apply")
            journal.record_action(
                "history-test", 7, keeper, source, destination, 4096, "moved", "verified"
            )
            journal.set_run_status("history-test", "complete")
            journal.close()
            before = self._sha256(state)

            result = history_run_snapshot(state, "history-test")

            self.assertTrue(result["ok"])
            self.assertEqual(result["mode"], "read-only")
            self.assertEqual(result["run"]["run_id"], "history-test")
            self.assertEqual(result["run"]["status"], "complete")
            self.assertEqual(result["total_actions"], 1)
            self.assertEqual(result["total_bytes"], 4096)
            self.assertEqual(result["status_counts"], {"moved": 1})
            self.assertEqual(result["actions"][0]["group_id"], 7)
            self.assertEqual(result["actions"][0]["source"], str(source))
            self.assertEqual(result["actions"][0]["destination"], str(destination))
            self.assertEqual(result["actions"][0]["keeper"], str(keeper))
            self.assertEqual(result["actions"][0]["message"], "verified")
            self.assertEqual(self._sha256(state), before)


if __name__ == "__main__":
    unittest.main()
