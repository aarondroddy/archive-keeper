from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shutil
import sqlite3
import sys
import secrets
from pathlib import Path

from .progress import ProgressTracker

from .core import (
    ArchiveKeeperError,
    Journal,
    choose_keeper,
    export_plan_csv,
    bounded_quarantine_preflight,
    bounded_files_identical,
    human_bytes,
    load_rmlint_groups,
    mount_root_for,
    normalize_path,
    path_is_within,
    quarantine_destination,
)


DEFAULT_REPORT = Path("~/rmlint-mycloud-scan/rmlint.json").expanduser()
DEFAULT_STATE = Path("~/.local/state/archive-keeper/journal.sqlite3").expanduser()
DEFAULT_DECISIONS = Path("~/.local/state/archive-keeper/decisions.sqlite3").expanduser()
DEFAULT_ROOTS = [Path("/mnt/MyCloud1"), Path("/mnt/MyCloud2"), Path("/mnt/MyCloud3")]
DEFAULT_QUARANTINE_NAME = "ArchiveKeeper Quarantine"
LEGACY_QUARANTINE_NAME = ".ArchiveKeeper"

MOUNTED_COMMANDS = {"analyze", "tui", "review", "search", "inspect", "keep", "folders", "plan", "quarantine"}


def path_list(values):
    return [normalize_path(v) for v in (values or [])]


def build_parser():
    parser = argparse.ArgumentParser(
        prog="archive-keeper",
        description="Safe, resumable quarantine workflow for rmlint duplicate reports.",
    )
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--state-db", type=Path, default=DEFAULT_STATE)
    parser.add_argument("--decisions-db", type=Path, default=DEFAULT_DECISIONS, help="Saved keeper overrides and favorites.")
    parser.add_argument(
        "--mount-root", action="append", dest="mount_roots",
        help="Allowed NAS root. Repeat for each root. Defaults to /mnt/MyCloud1..3."
    )
    parser.add_argument(
        "--prefer", action="append", default=[],
        help="Root preference, highest priority first. Repeat as needed."
    )
    parser.add_argument(
        "--protect", action="append", default=[],
        help="Never quarantine files beneath this root. Repeat as needed."
    )
    parser.add_argument(
        "--exclude", action="append", default=[],
        help="Never move a duplicate copy beneath this root. Other copies in the group are still processed. Repeat as needed."
    )
    parser.add_argument(
        "--strategy",
        choices=("preferred-root", "rmlint-original", "oldest", "newest", "shortest-path"),
        default="preferred-root",
    )
    parser.add_argument(
        "--quarantine-name", default=None,
        help=("Quarantine directory created independently on each NAS root. "
              f"New runs default to {DEFAULT_QUARANTINE_NAME!r}; existing runs reuse their journaled directory name."),
    )
    parser.add_argument(
        "--mount-policy", choices=("auto", "check", "ignore"), default="auto",
        help=("Storage-root handling before commands run: auto checks and mounts missing roots "
              "through /etc/fstab; check only verifies; ignore bypasses the safeguard.")
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("analyze", help="Summarize the duplicate report without touching files.")

    tui = sub.add_parser("tui", help="Open the lightweight interactive review console.")
    tui.add_argument(
        "--output", type=Path,
        default=Path("~/rmlint-mycloud-scan/archive-keeper-plan.csv").expanduser()
    )

    rich = sub.add_parser("review", help="Open the full-screen visual review interface.")
    rich.add_argument("--output", type=Path, default=Path("~/rmlint-mycloud-scan/archive-keeper-plan.csv").expanduser())

    search = sub.add_parser("search", help="Fuzzy-search duplicate groups by path or filename.")
    search.add_argument("query")
    search.add_argument("--limit", type=int, default=50)

    inspect = sub.add_parser("inspect", help="Show metadata and preview for a duplicate group.")
    inspect.add_argument("group_id", type=int)

    decide = sub.add_parser("keep", help="Manually choose the keeper for a duplicate group.")
    decide.add_argument("group_id", type=int)
    decide.add_argument("path", type=Path)

    folders = sub.add_parser("folders", help="Summarize duplicate space by folder.")
    folders.add_argument("--depth", type=int, default=4)
    folders.add_argument("--limit", type=int, default=50)

    plan = sub.add_parser("plan", help="Write a reviewable CSV plan.")
    plan.add_argument(
        "--output", type=Path,
        default=Path("~/rmlint-mycloud-scan/archive-keeper-plan.csv").expanduser()
    )

    run = sub.add_parser("quarantine", help="Move duplicate copies into quarantine.")
    run.add_argument("--run-id", help="Resume or name a run.")
    run.add_argument(
        "--apply", action="store_true",
        help="Actually move files. Without this flag, performs a dry run."
    )
    run.add_argument(
        "--deep-verify", action="store_true",
        help="SHA-256 both keeper and duplicate before each move. Slowest, safest."
    )
    run.add_argument(
        "--limit", type=int, default=0,
        help="Process at most this many moves; 0 means no limit."
    )
    run.add_argument(
        "--verify-timeout", type=float, default=30.0,
        help="Maximum seconds to wait for each live NAS verification (default: 30)."
    )
    run.add_argument(
        "--min-free-gib", type=float, default=1.0,
        help="Require this much free space on each NAS. Rename moves need almost no extra space."
    )

    restore = sub.add_parser("restore", help="Restore files moved by a run.")
    restore.add_argument("run_id")
    restore.add_argument("--apply", action="store_true")
    restore.add_argument("--overwrite", action="store_true")
    restore.add_argument(
        "--verify-timeout", type=float, default=30.0,
        help="Maximum seconds to wait when hashing an existing restore destination (default: 30)."
    )

    status = sub.add_parser("status", help="Show journaled runs.")
    status.add_argument("--run-id")

    return parser


def configured(args):
    roots = path_list(args.mount_roots) if args.mount_roots else DEFAULT_ROOTS
    roots = [normalize_path(r) for r in roots]
    preferred = path_list(args.prefer) if args.prefer else roots
    return roots, preferred, path_list(args.protect), path_list(args.exclude)


def _progress(message: str) -> None:
    print(f"Archive Keeper: {message}", flush=True)


def _load_groups(args, *, show_progress: bool = True):
    return load_rmlint_groups(
        args.report.expanduser(),
        progress=_progress if show_progress else None,
    )


def analyze(args):
    groups = _load_groups(args)
    files = sum(len(g.files) for g in groups)
    recoverable = sum(g.recoverable_bytes for g in groups)
    largest = sorted(groups, key=lambda g: g.recoverable_bytes, reverse=True)[:10]
    print(f"Duplicate groups : {len(groups):,}")
    print(f"Files in groups  : {files:,}")
    print(f"Recoverable max  : {human_bytes(recoverable)}")
    print("\nLargest groups:")
    for g in largest:
        print(
            f"  group {g.group_id:>6}: {len(g.files):>5} copies × "
            f"{human_bytes(g.size):>12} = {human_bytes(g.recoverable_bytes)}"
        )
    return 0


def plan(args):
    import csv
    from .decisions import DecisionStore
    from .review import resolve_keeper
    roots, preferred, protected, excluded = configured(args)
    groups = _load_groups(args)
    output = args.output.expanduser()
    output.parent.mkdir(parents=True, exist_ok=True)
    store = DecisionStore(args.decisions_db)
    try:
        with output.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(["group_id", "action", "size", "keeper", "path", "reason"])
            for group in groups:
                keeper = resolve_keeper(group, preferred, protected, args.strategy, store)
                manual = store.get_keeper(group.group_id) is not None
                for item in group.files:
                    if item.path == keeper.path:
                        writer.writerow([group.group_id, "KEEP", item.size, keeper.path, item.path, "manual override" if manual else args.strategy])
                        continue
                    excluded_hit = any(path_is_within(item.path, r) for r in excluded)
                    protected_hit = any(path_is_within(item.path, r) for r in protected)
                    action = "SKIP" if excluded_hit or protected_hit else "QUARANTINE"
                    reason = "excluded root" if excluded_hit else "protected root" if protected_hit else ("manual keeper override" if manual else args.strategy)
                    writer.writerow([group.group_id, action, item.size, keeper.path, item.path, reason])
    finally:
        store.close()
    print(f"Wrote plan: {output}")
    return 0


def _is_excluded(path, roots):
    return any(path_is_within(path, root) for root in roots)


def quarantine(args):
    report = args.report.expanduser().resolve(strict=False)
    roots, preferred, protected, excluded = configured(args)
    groups = load_rmlint_groups(report, progress=_progress)
    run_id = args.run_id or f"{dt.datetime.now().strftime('%Y%m%d-%H%M%S')}-{secrets.token_hex(2)}"
    journal = Journal(args.state_db.expanduser())
    inferred_quarantine_name = journal.infer_quarantine_name(run_id, roots)
    if args.quarantine_name and inferred_quarantine_name and args.quarantine_name != inferred_quarantine_name:
        raise ArchiveKeeperError(
            f"Run {run_id!r} already uses quarantine directory {inferred_quarantine_name!r}; "
            f"refusing to switch it to {args.quarantine_name!r}."
        )
    quarantine_name = args.quarantine_name or inferred_quarantine_name or DEFAULT_QUARANTINE_NAME
    journal.create_run(run_id, report, "apply" if args.apply else "dry-run")
    if inferred_quarantine_name:
        _progress(f"Resuming run {run_id} with existing quarantine directory: {quarantine_name}")
    else:
        _progress(f"Quarantine directory: {quarantine_name}")
    from .decisions import DecisionStore
    from .review import resolve_keeper
    decisions = DecisionStore(args.decisions_db)
    progress_total = args.limit if args.limit else sum(max(0, len(g.files) - 1) for g in groups)
    tracker = ProgressTracker("Quarantine", total=progress_total)

    planned = moved = reconciled = stale = skipped = failed = bytes_moved = attempted = 0
    try:
        for group in groups:
            keeper = resolve_keeper(group, preferred, protected, args.strategy, decisions)
            keeper_root = mount_root_for(keeper.path, roots)
            if keeper_root is None:
                for item in group.files:
                    if item.path != keeper.path:
                        journal.record_action(
                            run_id, group.group_id, keeper.path, item.path, item.path,
                            item.size, "skipped", "keeper is outside allowed mount roots"
                        )
                        skipped += 1
                continue

            for item in group.files:
                if item.path == keeper.path:
                    continue
                if args.limit and attempted >= args.limit:
                    journal.set_run_status(run_id, "paused")
                    tracker.finish(f"paused at --limit={args.limit}")
                    print(f"Stopped at --limit={args.limit}; resume with --run-id {run_id}")
                    print_summary(run_id, attempted, planned, moved, reconciled, stale, skipped, failed, bytes_moved)
                    return 1 if failed else 0
                old_status = journal.action_status(run_id, item.path)
                if old_status in ("moved", "restored", "reconciled", "stale", "skipped"):
                    skipped += 1
                    continue

                explicit_action = decisions.get_action(group.group_id, item.path)
                if explicit_action == "UNDECIDED":
                    journal.record_action(
                        run_id, group.group_id, keeper.path, item.path, item.path,
                        item.size, "skipped", "marked undecided in reviewer"
                    )
                    skipped += 1
                    continue

                source_root = mount_root_for(item.path, roots)
                if source_root is None:
                    journal.record_action(
                        run_id, group.group_id, keeper.path, item.path, item.path,
                        item.size, "skipped", "source is outside allowed mount roots"
                    )
                    skipped += 1
                    continue
                if _is_excluded(item.path, excluded):
                    journal.record_action(
                        run_id, group.group_id, keeper.path, item.path, item.path,
                        item.size, "skipped", "excluded root"
                    )
                    skipped += 1
                    continue
                if _is_excluded(item.path, protected):
                    journal.record_action(
                        run_id, group.group_id, keeper.path, item.path, item.path,
                        item.size, "skipped", "protected root"
                    )
                    skipped += 1
                    continue

                destination = quarantine_destination(
                    item.path, source_root, quarantine_name, run_id
                )
                attempted += 1
                if old_status == "moving":
                    if not item.path.exists() and destination.exists():
                        journal.record_action(
                            run_id, group.group_id, keeper.path, item.path, destination,
                            item.size, "moved", "reconciled interrupted move"
                        )
                        moved += 1
                        bytes_moved += item.size
                        continue
                    if item.path.exists() and not destination.exists():
                        # The rename did not happen; safely retry below.
                        pass
                    else:
                        journal.record_action(
                            run_id, group.group_id, keeper.path, item.path, destination,
                            item.size, "failed", "ambiguous interrupted move state"
                        )
                        failed += 1
                        continue

                needed = int(args.min_free_gib * 1024**3)
                tracker.current(
                    attempted,
                    f"VERIFYING timeout={args.verify_timeout:g}s",
                    str(item.path),
                )
                ok, verify_message, timed_out, verify_outcome = bounded_quarantine_preflight(
                    keeper.path,
                    item.path,
                    destination,
                    source_root,
                    deep_verify=args.deep_verify,
                    min_free_bytes=needed,
                    expected_size=item.size,
                    timeout=args.verify_timeout,
                )
                if not ok:
                    status = "timeout" if timed_out else "failed"
                    journal.record_action(
                        run_id, group.group_id, keeper.path, item.path, destination,
                        item.size, status, verify_message
                    )
                    failed += 1
                    label = "TIMEOUT" if timed_out else "FAILED"
                    tracker.result(label, verify_message, counter=label.lower())
                    continue

                if verify_outcome == "destination-identical":
                    journal.record_action(
                        run_id, group.group_id, keeper.path, item.path, destination,
                        item.size, "reconciled", verify_message
                    )
                    reconciled += 1
                    tracker.result(
                        "RECONCILED / ALREADY QUARANTINED",
                        str(item.path),
                        counter="reconciled",
                    )
                    continue

                if verify_outcome == "source-missing-keeper-valid":
                    journal.record_action(
                        run_id, group.group_id, keeper.path, item.path, destination,
                        item.size, "stale", verify_message
                    )
                    stale += 1
                    tracker.result(
                        "STALE / SOURCE ALREADY ABSENT",
                        str(item.path),
                        counter="stale",
                    )
                    continue

                planned += 1
                if not args.apply:
                    journal.record_action(
                        run_id, group.group_id, keeper.path, item.path, destination,
                        item.size, "planned", verify_message
                    )
                    tracker.result("VERIFIED / WOULD QUARANTINE", str(item.path), counter="verified")
                    continue

                try:
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    journal.record_action(
                        run_id, group.group_id, keeper.path, item.path, destination,
                        item.size, "moving", verify_message
                    )
                    # os.replace is atomic when source and destination are on the same filesystem.
                    os.replace(item.path, destination)
                    journal.record_action(
                        run_id, group.group_id, keeper.path, item.path, destination,
                        item.size, "moved", verify_message
                    )
                    moved += 1
                    bytes_moved += item.size
                    tracker.result("QUARANTINED", str(item.path), counter="moved")
                except OSError as exc:
                    journal.record_action(
                        run_id, group.group_id, keeper.path, item.path, destination,
                        item.size, "failed", str(exc)
                    )
                    failed += 1
                    tracker.result("FAILED MOVE", str(exc), counter="failed")

        journal.set_run_status(run_id, "complete" if args.apply else "dry-run-complete")
        tracker.finish("complete" if args.apply else "dry-run complete")
        print_summary(run_id, attempted, planned, moved, reconciled, stale, skipped, failed, bytes_moved)
        if not args.apply:
            print("\nDry run only. Add --apply after reviewing the CSV plan and settings.")
        return 1 if failed else 0
    except KeyboardInterrupt:
        journal.set_run_status(run_id, "interrupted")
        tracker.finish("interrupted")
        print(f"\nInterrupted safely. Resume with --run-id {run_id}")
        return 130
    finally:
        decisions.close()
        journal.close()


def restore(args):
    journal = Journal(args.state_db.expanduser())
    restored = reconciled = skipped = failed = 0
    try:
        rows = list(journal.iter_actions(args.run_id, ("moved",)))
        if not rows:
            print(f"No moved files found for run {args.run_id}")
            return 0
        tracker = ProgressTracker("Restore", total=len(rows))
        for index, (group_id, keeper, source, destination, size, status, message) in enumerate(rows, 1):
            tracker.current(index, "CHECKING", str(destination))
            source = Path(source)
            destination = Path(destination)
            if not destination.exists():
                print(f"MISSING quarantine file: {destination}", file=sys.stderr)
                failed += 1
                tracker.result("FAILED", "quarantine file missing", counter="failed")
                continue

            if source.exists() and not args.overwrite:
                tracker.current(
                    index,
                    f"VERIFYING EXISTING DESTINATION timeout={args.verify_timeout:g}s",
                    str(source),
                )
                identical, compare_message, timed_out = bounded_files_identical(
                    source, destination, timeout=args.verify_timeout
                )
                if identical:
                    if not args.apply:
                        print(f"WOULD RECONCILE identical: {destination} -> {source}")
                        tracker.result("WOULD RECONCILE IDENTICAL", str(source), counter="reconciled")
                        continue
                    try:
                        if not source.exists() or not destination.exists():
                            raise OSError("file disappeared after identical-file verification")
                        destination.unlink()
                        journal.record_action(
                            args.run_id, group_id, Path(keeper), source, destination,
                            size, "reconciled", "restore destination already existed and was SHA-256 identical; redundant quarantine copy removed"
                        )
                        reconciled += 1
                        tracker.result("RECONCILED IDENTICAL", str(source), counter="reconciled")
                    except OSError as exc:
                        journal.record_action(
                            args.run_id, group_id, Path(keeper), source, destination,
                            size, "failed", f"restore reconciliation failed: {exc}"
                        )
                        failed += 1
                        tracker.result("FAILED", str(exc), counter="failed")
                    continue

                if timed_out:
                    print(f"SKIP comparison timeout: {source}")
                    skipped += 1
                    tracker.result("SKIPPED", compare_message, counter="skipped")
                else:
                    print(f"SKIP conflict (different content): {source}")
                    skipped += 1
                    tracker.result("SKIPPED CONFLICT", compare_message, counter="skipped")
                continue

            if not args.apply:
                print(f"WOULD RESTORE: {destination} -> {source}")
                tracker.result("WOULD RESTORE", str(source), counter="planned")
                continue
            try:
                source.parent.mkdir(parents=True, exist_ok=True)
                if source.exists() and source.is_dir():
                    raise OSError(f"restore destination is a directory: {source}")
                os.replace(destination, source)
                journal.record_action(
                    args.run_id, group_id, Path(keeper), source, destination,
                    size, "restored", ""
                )
                restored += 1
                tracker.result("RESTORED", str(source), counter="restored")
            except OSError as exc:
                journal.record_action(
                    args.run_id, group_id, Path(keeper), source, destination,
                    size, "failed", f"restore failed: {exc}"
                )
                failed += 1
                tracker.result("FAILED", str(exc), counter="failed")
        tracker.finish("complete" if args.apply else "dry-run complete")
        if args.apply and failed == 0:
            journal.set_run_status(args.run_id, "restored")
        print(
            f"Restored: {restored:,}; reconciled: {reconciled:,}; "
            f"skipped: {skipped:,}; failed: {failed:,}"
        )
        if not args.apply:
            print("Dry run only. Add --apply to restore/reconcile.")
        return 1 if failed else 0
    finally:
        journal.close()


def status(args):
    journal = Journal(args.state_db.expanduser())
    try:
        rows = journal.summary(args.run_id)
        if not rows:
            print("No runs found.")
            return 0
        for run_id, created_at, report_path, mode, run_status, counts, bytes_moved in rows:
            timestamp = dt.datetime.fromtimestamp(created_at, tz=dt.timezone.utc).astimezone().isoformat(timespec="seconds")
            print(f"{run_id}  {timestamp}  {mode}  {run_status}")
            print(f"  moved={counts.get('moved',0):,} planned={counts.get('planned',0):,} "
                  f"reconciled={counts.get('reconciled',0):,} stale={counts.get('stale',0):,} "
                  f"skipped={counts.get('skipped',0):,} failed={counts.get('failed',0):,} "
                  f"timeout={counts.get('timeout',0):,} "
                  f"restored={counts.get('restored',0):,}")
            print(f"  moved bytes={human_bytes(bytes_moved)}")
            print(f"  report={report_path}")
        return 0
    finally:
        journal.close()


def print_summary(run_id, attempted, planned, moved, reconciled, stale, skipped, failed, bytes_moved):
    print(f"Run ID        : {run_id}")
    print(f"Attempted     : {attempted:,}")
    print(f"Planned       : {planned:,}")
    print(f"Moved         : {moved:,}")
    print(f"Reconciled    : {reconciled:,}")
    print(f"Stale         : {stale:,}")
    print(f"Skipped       : {skipped:,}")
    print(f"Failed        : {failed:,}")
    print(f"Quarantined   : {human_bytes(bytes_moved)}")


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command in MOUNTED_COMMANDS:
            from .mounts import ensure_mounts
            roots, _preferred, _protected, _excluded = configured(args)
            ensure_mounts(roots, args.mount_policy)
        if args.command == "analyze":
            return analyze(args)
        if args.command == "tui":
            from .tui import run_tui
            return run_tui(args, configured, export_plan_csv)
        if args.command == "plan":
            return plan(args)
        if args.command == "quarantine":
            return quarantine(args)
        if args.command == "restore":
            return restore(args)
        if args.command == "status":
            return status(args)
        if args.command == "review":
            from .rich_tui import run_rich_tui
            return run_rich_tui(args, configured)
        if args.command == "search":
            from .review import fuzzy_groups
            groups = _load_groups(args)
            for group in fuzzy_groups(groups, args.query, args.limit):
                print(f"{group.group_id:>6}  {len(group.files):>4} copies  {human_bytes(group.recoverable_bytes):>12}  {group.files[0].path}")
            return 0
        if args.command == "inspect":
            from .decisions import DecisionStore
            from .review import duplicate_graph, keeper_reasons, render_preview, resolve_keeper
            roots, preferred, protected, excluded = configured(args)
            groups = _load_groups(args)
            group = next((g for g in groups if g.group_id == args.group_id), None)
            if not group:
                raise ArchiveKeeperError(f"Unknown group ID: {args.group_id}")
            store = DecisionStore(args.decisions_db)
            keeper = resolve_keeper(group, preferred, protected, args.strategy, store)
            print(duplicate_graph(group, keeper))
            print("\nWhy this keeper:")
            for reason in keeper_reasons(keeper, group, preferred, protected, args.strategy):
                print(f"  • {reason}")
            print("\nMetadata / preview:\n" + render_preview(keeper.path))
            store.close()
            return 0
        if args.command == "keep":
            from .decisions import DecisionStore
            groups = _load_groups(args)
            group = next((g for g in groups if g.group_id == args.group_id), None)
            if not group:
                raise ArchiveKeeperError(f"Unknown group ID: {args.group_id}")
            target = normalize_path(args.path)
            if target not in [f.path for f in group.files]:
                raise ArchiveKeeperError("The selected path is not in that duplicate group.")
            store = DecisionStore(args.decisions_db)
            try:
                store.set_keeper(group.group_id, target)
            finally:
                store.close()
            print(f"Group {group.group_id}: keeper set to {target}")
            return 0
        if args.command == "folders":
            from .review import folder_summary
            groups = _load_groups(args)
            for folder, (count, size) in folder_summary(groups, args.depth)[:args.limit]:
                print(f"{count:>8,} files  {human_bytes(size):>12}  {folder}")
            return 0
        parser.error("unknown command")
    except (ArchiveKeeperError, OSError, RuntimeError, sqlite3.Error) as exc:
        print(f"archive-keeper: error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
