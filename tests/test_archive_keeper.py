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

    def _seed_retry_action(self, state, run_id, group_id, keeper, source, destination, status):
        from archive_keeper.core import Journal
        journal = Journal(state)
        journal.create_run(run_id, Path("/tmp/original-rmlint.json"), "apply")
        journal.record_action(
            run_id, group_id, keeper.resolve(), source.resolve(), destination.resolve(),
            source.stat().st_size, status, f"seeded {status}",
        )
        journal.set_run_status(run_id, "complete")
        journal.close()

    def test_retry_dry_run_is_read_only(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            report, keeper, source, other = self.make_report(root)
            state = root / "state.sqlite3"
            destination = root / "MyCloud2" / "ArchiveKeeper Quarantine" / "retry-dry" / "copy.bin"
            self._seed_retry_action(state, "retry-dry", 1, keeper, source, destination, "timeout")

            result = subprocess.run(
                self._base_cli(root, report, state) + [
                    "retry", "retry-dry", "--verify-timeout", "5",
                ], text=True, capture_output=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            self.assertTrue(source.exists())
            self.assertFalse(destination.exists())
            conn = __import__("sqlite3").connect(state)
            row = conn.execute(
                "SELECT status,message FROM actions WHERE run_id=? AND source=?",
                ("retry-dry", str(source.resolve())),
            ).fetchone()
            conn.close()
            self.assertEqual(row, ("timeout", "seeded timeout"))
            self.assertIn("Read-only dry run", result.stdout)
            self.assertIn("Verified       : 1", result.stdout)

    def test_retry_apply_moves_only_selected_status(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            report, keeper, failed_source, timeout_source = self.make_report(root)
            state = root / "state.sqlite3"
            failed_destination = root / "MyCloud2" / "ArchiveKeeper Quarantine" / "retry-filter" / "copy.bin"
            timeout_destination = root / "MyCloud3" / "ArchiveKeeper Quarantine" / "retry-filter" / "copy.bin"
            self._seed_retry_action(
                state, "retry-filter", 1, keeper, failed_source, failed_destination, "failed"
            )
            self._seed_retry_action(
                state, "retry-filter", 1, keeper, timeout_source, timeout_destination, "timeout"
            )

            result = subprocess.run(
                self._base_cli(root, report, state) + [
                    "retry", "retry-filter", "--status", "timeout",
                    "--verify-timeout", "5", "--apply",
                ], text=True, capture_output=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            self.assertTrue(failed_source.exists())
            self.assertFalse(failed_destination.exists())
            self.assertFalse(timeout_source.exists())
            self.assertTrue(timeout_destination.exists())
            conn = __import__("sqlite3").connect(state)
            statuses = dict(conn.execute(
                "SELECT source,status FROM actions WHERE run_id=?", ("retry-filter",)
            ).fetchall())
            conn.close()
            self.assertEqual(statuses[str(failed_source.resolve())], "failed")
            self.assertEqual(statuses[str(timeout_source.resolve())], "moved")

    def test_retry_existing_different_destination_fails_closed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            report, keeper, source, other = self.make_report(root)
            state = root / "state.sqlite3"
            destination = root / "MyCloud2" / "ArchiveKeeper Quarantine" / "retry-conflict" / "copy.bin"
            destination.parent.mkdir(parents=True)
            destination.write_bytes(b"different")
            self._seed_retry_action(state, "retry-conflict", 1, keeper, source, destination, "failed")

            result = subprocess.run(
                self._base_cli(root, report, state) + [
                    "retry", "retry-conflict", "--verify-timeout", "5", "--apply",
                ], text=True, capture_output=True,
            )
            self.assertEqual(result.returncode, 1, result.stderr + result.stdout)
            self.assertTrue(source.exists())
            self.assertEqual(destination.read_bytes(), b"different")
            self.assertIn("destination collision", result.stdout)

    def test_retry_existing_identical_destination_reconciles_without_deleting(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            report, keeper, source, other = self.make_report(root)
            state = root / "state.sqlite3"
            destination = root / "MyCloud2" / "ArchiveKeeper Quarantine" / "retry-identical" / "copy.bin"
            destination.parent.mkdir(parents=True)
            destination.write_bytes(source.read_bytes())
            self._seed_retry_action(state, "retry-identical", 1, keeper, source, destination, "failed")

            result = subprocess.run(
                self._base_cli(root, report, state) + [
                    "retry", "retry-identical", "--verify-timeout", "5", "--apply",
                ], text=True, capture_output=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            self.assertTrue(source.exists())
            self.assertTrue(destination.exists())
            conn = __import__("sqlite3").connect(state)
            status = conn.execute(
                "SELECT status FROM actions WHERE run_id=? AND source=?",
                ("retry-identical", str(source.resolve())),
            ).fetchone()[0]
            conn.close()
            self.assertEqual(status, "reconciled")
            self.assertIn("BOTH KEPT", result.stdout)

    def test_retry_recovers_moving_row_after_interruption(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            report, keeper, source, other = self.make_report(root)
            state = root / "state.sqlite3"
            destination = root / "MyCloud2" / "ArchiveKeeper Quarantine" / "retry-moving" / "copy.bin"
            self._seed_retry_action(state, "retry-moving", 1, keeper, source, destination, "moving")

            result = subprocess.run(
                self._base_cli(root, report, state) + [
                    "retry", "retry-moving", "--verify-timeout", "5", "--apply",
                ], text=True, capture_output=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            self.assertFalse(source.exists())
            self.assertTrue(destination.exists())
            conn = __import__("sqlite3").connect(state)
            status = conn.execute(
                "SELECT status FROM actions WHERE run_id=? AND source=?",
                ("retry-moving", str(source.resolve())),
            ).fetchone()[0]
            conn.close()
            self.assertEqual(status, "moved")

    def test_retry_timeout_is_journaled_and_source_is_untouched(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        from archive_keeper.cli import retry

        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            report, keeper, source, other = self.make_report(root)
            state = root / "state.sqlite3"
            destination = root / "MyCloud2" / "ArchiveKeeper Quarantine" / "retry-timeout" / "copy.bin"
            self._seed_retry_action(state, "retry-timeout", 1, keeper, source, destination, "failed")
            args = SimpleNamespace(
                run_id="retry-timeout", state_db=state,
                mount_roots=[str(root / "MyCloud1"), str(root / "MyCloud2"), str(root / "MyCloud3")],
                prefer=[], protect=[], exclude=[], status=None, limit=0,
                min_free_gib=0, verify_timeout=300.0, deep_verify=False, apply=True,
            )
            with patch(
                "archive_keeper.cli.bounded_quarantine_preflight",
                return_value=(False, "verification timed out after 300s", True, "timeout"),
            ):
                result = retry(args)
            self.assertEqual(result, 1)
            self.assertTrue(source.exists())
            self.assertFalse(destination.exists())
            conn = __import__("sqlite3").connect(state)
            status = conn.execute(
                "SELECT status FROM actions WHERE run_id=? AND source=?",
                ("retry-timeout", str(source.resolve())),
            ).fetchone()[0]
            conn.close()
            self.assertEqual(status, "timeout")

    def test_retry_accepts_explicit_unlimited_timeout(self):
        from archive_keeper.cli import build_parser
        args = build_parser().parse_args(["retry", "run-id", "--verify-timeout", "unlimited"])
        self.assertIsNone(args.verify_timeout)

    def test_no_clobber_move_refuses_existing_destination(self):
        from archive_keeper.core import move_noreplace
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            source = root / "source.bin"
            destination = root / "destination.bin"
            source.write_bytes(b"source")
            destination.write_bytes(b"destination")
            with self.assertRaises(OSError):
                move_noreplace(source, destination)
            self.assertEqual(source.read_bytes(), b"source")
            self.assertEqual(destination.read_bytes(), b"destination")

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

    def test_missing_source_with_valid_keeper_is_stale_not_failed(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            report, a, b, c = self.make_report(root)
            state = root / "state.sqlite3"
            b.unlink()
            result = subprocess.run(
                self._base_cli(root, report, state) + [
                    "quarantine", "--run-id", "stale-valid", "--limit", "1", "--apply"
                ], text=True, capture_output=True
            )
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            self.assertIn("Stale         : 1", result.stdout)
            self.assertIn("Failed        : 0", result.stdout)
            self.assertTrue(a.exists())
            conn = __import__("sqlite3").connect(state)
            row = conn.execute(
                "SELECT status,message FROM actions WHERE run_id=? AND source=?",
                ("stale-valid", str(b.resolve())),
            ).fetchone()
            conn.close()
            self.assertEqual(row[0], "stale")
            self.assertIn("source already absent", row[1])

    def test_missing_source_with_missing_keeper_still_fails(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            report, a, b, c = self.make_report(root)
            state = root / "state.sqlite3"
            a.unlink()
            b.unlink()
            result = subprocess.run(
                self._base_cli(root, report, state) + [
                    "quarantine", "--run-id", "stale-no-keeper", "--limit", "1", "--apply"
                ], text=True, capture_output=True
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Failed        : 1", result.stdout)

    def test_missing_source_with_wrong_size_keeper_still_fails(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            report, a, b, c = self.make_report(root)
            state = root / "state.sqlite3"
            b.unlink()
            a.write_bytes(b"x" * 17)
            result = subprocess.run(
                self._base_cli(root, report, state) + [
                    "quarantine", "--run-id", "stale-bad-keeper", "--limit", "1", "--apply"
                ], text=True, capture_output=True
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Failed        : 1", result.stdout)
            self.assertIn("keeper size mismatch", result.stdout)

    def test_version_is_1_6_7(self):
        from archive_keeper import __version__
        self.assertEqual(__version__, "1.6.7")

if __name__ == "__main__":
    unittest.main()
