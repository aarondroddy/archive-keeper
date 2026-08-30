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
    collision_destination,
    export_plan_csv,
    bounded_quarantine_preflight,
    bounded_files_identical,
    human_bytes,
    load_rmlint_groups,
    mount_root_for,
    normalize_path,
    move_noreplace,
    path_is_within,
    quarantine_destination,
)


DEFAULT_REPORT = Path("~/rmlint-mycloud-scan/rmlint.json").expanduser()
DEFAULT_STATE = Path("~/.local/state/archive-keeper/journal.sqlite3").expanduser()
DEFAULT_DECISIONS = Path("~/.local/state/archive-keeper/decisions.sqlite3").expanduser()
DEFAULT_ROOTS = [Path("/mnt/MyCloud1"), Path("/mnt/MyCloud2"), Path("/mnt/MyCloud3")]
DEFAULT_QUARANTINE_NAME = "ArchiveKeeper Quarantine"
LEGACY_QUARANTINE_NAME = ".ArchiveKeeper"

MOUNTED_COMMANDS = {"analyze", "tui", "review", "search", "inspect", "keep", "folders", "plan", "quarantine", "reconcile", "retry"}


def path_list(values):
    return [normalize_path(v) for v in (values or [])]


def verification_timeout(value: str) -> float | None:
    if value.strip().lower() == "unlimited":
        return None
    try:
        seconds = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("use a positive number of seconds or 'unlimited'") from exc
    if seconds <= 0:
        raise argparse.ArgumentTypeError("timeout must be greater than zero, or use 'unlimited'")
    return seconds


def timeout_label(value: float | None) -> str:
    return "unlimited" if value is None else f"{value:g}s"


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

    reconcile_parser = sub.add_parser(
        "reconcile",
        help="Audit unresolved journal actions against live source/quarantine state.",
    )
    reconcile_parser.add_argument("run_id")
    reconcile_parser.add_argument(
        "--apply", action="store_true",
        help="Update only proven-safe journal rows; never move or delete files.",
    )
    reconcile_parser.add_argument(
        "--verify-timeout", type=float, default=300.0,
        help="Maximum seconds for each SHA-256 comparison (default: 300).",
    )

    retry_parser = sub.add_parser(
        "retry",
        help="Retry only unresolved journal actions from an existing run.",
    )
    retry_parser.add_argument("run_id")
    retry_parser.add_argument(
        "--status", action="append", choices=("failed", "timeout"),
        help="Retry this unresolved status; repeat as needed (default: failed and timeout).",
    )
    retry_parser.add_argument(
        "--apply", action="store_true",
        help="Move verified retry candidates and update their journal rows. Default is read-only.",
    )
    retry_parser.add_argument(
        "--deep-verify", action="store_true",
        help="SHA-256 both keeper and source before moving.",
    )
    retry_parser.add_argument(
        "--sample-verify", action="store_true",
        help=(
            "Compare keeper/source using deterministic sampled SHA-256 windows "
            "instead of hashing the entire file."
        ),
    )
    retry_parser.add_argument(
        "--allow-sample-verified", action="store_true",
        help=(
            "Permit --apply when --sample-verify succeeds. Required because "
            "sampled verification is high-confidence, not a full-file proof."
        ),
    )
    retry_parser.add_argument(
        "--limit", type=int, default=0,
        help="Process at most this many selected journal rows; 0 means no limit.",
    )
    retry_parser.add_argument(
        "--action-id", type=int,
        help="Retry exactly one journal action id from this run.",
    )
    retry_parser.add_argument(
        "--verify-timeout", type=verification_timeout, default=300.0,
        help="Maximum seconds per verification (default: 300); use 'unlimited' explicitly for no limit.",
    )
    retry_parser.add_argument(
        "--min-free-gib", type=float, default=1.0,
        help="Require this much free space on the source NAS (default: 1).",
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


def retry(args):
    """Retry selected unresolved rows without reloading the rmlint report."""
    if args.limit < 0:
        raise ArchiveKeeperError("--limit cannot be negative")
    if args.min_free_gib < 0:
        raise ArchiveKeeperError("--min-free-gib cannot be negative")
    sample_verify = bool(getattr(args, "sample_verify", False))
    allow_sample_verified = bool(getattr(args, "allow_sample_verified", False))
    if args.deep_verify and sample_verify:
        raise ArchiveKeeperError("choose either --deep-verify or --sample-verify, not both")
    if allow_sample_verified and not sample_verify:
        raise ArchiveKeeperError("--allow-sample-verified requires --sample-verify")
    if args.apply and sample_verify and not allow_sample_verified:
        raise ArchiveKeeperError(
            "--apply with --sample-verify requires explicit --allow-sample-verified"
        )

    roots, _preferred, protected, excluded = configured(args)
    selected_statuses = tuple(dict.fromkeys(args.status or ("failed", "timeout")))
    # A SIGINT or power loss can leave the current row at "moving". Always
    # include it so retry is resumable even when the user filters old statuses.
    query_statuses = (*selected_statuses, "moving")
    journal = Journal(args.state_db.expanduser())
    planned = moved = reconciled = stale = failed = timed_out = bytes_moved = 0
    try:
        rows = list(journal.iter_actions(args.run_id, query_statuses))
        if getattr(args, "action_id", None) is not None:
            if args.action_id <= 0:
                raise ArchiveKeeperError("--action-id must be a positive integer")
            rows = [
                row for row in rows
                if journal.action_id(args.run_id, normalize_path(row[2])) == args.action_id
            ]
        if args.limit:
            rows = rows[:args.limit]
        if not rows:
            joined = ", ".join(selected_statuses)
            print(f"No retryable actions with status {joined} found for run {args.run_id}")
            return 0

        print(
            f"Retrying run {args.run_id}: statuses={','.join(selected_statuses)}; "
            f"rows={len(rows):,}; verification timeout={timeout_label(args.verify_timeout)}"
        )
        if not args.apply:
            print("Read-only dry run: files and journal rows will remain unchanged.")

        tracker = ProgressTracker("Retry", total=len(rows))
        needed = int(args.min_free_gib * 1024**3)
        for index, row in enumerate(rows, 1):
            group_id, keeper_s, source_s, destination_s, size, old_status, _old_message = row
            keeper = normalize_path(keeper_s)
            source = normalize_path(source_s)
            destination = normalize_path(destination_s)
            tracker.current(
                index,
                f"VERIFYING timeout={timeout_label(args.verify_timeout)}",
                str(source),
            )

            source_root = mount_root_for(source, roots)
            destination_root = mount_root_for(destination, roots)
            safety_error = None
            if source_root is None:
                safety_error = "source is outside allowed mount roots"
            elif destination_root != source_root:
                safety_error = "journal destination is not on the source mount root"
            elif source == destination:
                safety_error = "journal source and destination are identical paths"
            elif _is_excluded(source, excluded):
                safety_error = "source is beneath an excluded root"
            elif _is_excluded(source, protected):
                safety_error = "source is beneath a protected root"

            if safety_error:
                failed += 1
                if args.apply:
                    journal.record_action(
                        args.run_id, group_id, keeper, source, destination, size,
                        "failed", f"retry refused: previous status={old_status}; {safety_error}",
                    )
                tracker.result("REFUSED", safety_error, counter="failed")
                continue

            ok, verify_message, did_timeout, outcome = bounded_quarantine_preflight(
                keeper,
                source,
                destination,
                source_root,
                deep_verify=args.deep_verify,
                sample_verify=sample_verify,
                min_free_bytes=needed,
                expected_size=size,
                timeout=args.verify_timeout,
            )
            if not ok and outcome == "destination-conflict":
                action_id = journal.action_id(args.run_id, source)
                if action_id is None:
                    failed += 1
                    detail = "retry could not resolve journal action id for collision"
                    if args.apply:
                        journal.record_action(
                            args.run_id, group_id, keeper, source, destination, size,
                            "failed", f"retry: previous status={old_status}; {detail}",
                        )
                    tracker.result("REFUSED", detail, counter="failed")
                    continue

                original_destination = destination
                alternate = collision_destination(destination, action_id)
                alternate_root = mount_root_for(alternate, roots)
                if alternate_root != source_root or alternate == source:
                    failed += 1
                    detail = f"unsafe alternate collision destination: {alternate}"
                    if args.apply:
                        journal.record_action(
                            args.run_id, group_id, keeper, source, original_destination, size,
                            "failed", f"retry: previous status={old_status}; {detail}",
                        )
                    tracker.result("REFUSED", detail, counter="failed")
                    continue

                original_conflict = verify_message
                alt_ok, alt_message, alt_timeout, alt_outcome = bounded_quarantine_preflight(
                    keeper,
                    source,
                    alternate,
                    source_root,
                    deep_verify=args.deep_verify,
                    sample_verify=sample_verify,
                    min_free_bytes=needed,
                    expected_size=size,
                    timeout=args.verify_timeout,
                )
                if not alt_ok:
                    new_status = "timeout" if alt_timeout else "failed"
                    if alt_timeout:
                        timed_out += 1
                        label, counter = "TIMEOUT", "timeout"
                    else:
                        failed += 1
                        label, counter = "FAILED", "failed"
                    detail = (
                        f"{original_conflict}; alternate destination {alternate}: {alt_message}"
                    )
                    if args.apply:
                        journal.record_action(
                            args.run_id, group_id, keeper, source, original_destination, size,
                            new_status, f"retry: previous status={old_status}; {detail}",
                        )
                    tracker.result(label, detail, counter=counter)
                    continue

                destination = alternate
                verify_message = (
                    f"{original_conflict}; preserved existing destination; "
                    f"alternate destination={alternate}; {alt_message}"
                )
                ok = alt_ok
                did_timeout = alt_timeout
                outcome = alt_outcome

            if not ok and outcome != "destination-conflict":
                new_status = "timeout" if did_timeout else "failed"
                if did_timeout:
                    timed_out += 1
                    label, counter = "TIMEOUT", "timeout"
                else:
                    failed += 1
                    label, counter = "FAILED", "failed"
                if args.apply:
                    journal.record_action(
                        args.run_id, group_id, keeper, source, destination, size,
                        new_status,
                        f"retry: previous status={old_status}; {verify_message}",
                    )
                tracker.result(label, verify_message, counter=counter)
                continue

            if outcome == "destination-identical":
                reconciled += 1
                if args.apply:
                    journal.record_action(
                        args.run_id, group_id, keeper, source, destination, size,
                        "reconciled",
                        f"retry: existing destination is identical; previous status={old_status}; {verify_message}",
                    )
                    label = "RECONCILED / BOTH KEPT"
                else:
                    label = "WOULD RECONCILE / BOTH KEPT"
                tracker.result(label, str(source), counter="reconciled")
                continue

            if outcome == "source-missing-keeper-valid":
                stale += 1
                if args.apply:
                    journal.record_action(
                        args.run_id, group_id, keeper, source, destination, size,
                        "stale", f"retry: previous status={old_status}; {verify_message}",
                    )
                    label = "STALE"
                else:
                    label = "WOULD MARK STALE"
                tracker.result(label, str(source), counter="stale")
                continue

            if outcome != "ready":
                failed += 1
                detail = f"unexpected verification outcome: {outcome}; {verify_message}"
                if args.apply:
                    journal.record_action(
                        args.run_id, group_id, keeper, source, destination, size,
                        "failed", f"retry: previous status={old_status}; {detail}",
                    )
                tracker.result("REFUSED", detail, counter="failed")
                continue

            planned += 1
            if not args.apply:
                tracker.result("VERIFIED / WOULD QUARANTINE", f"{source} -> {destination}", counter="verified")
                continue

            try:
                destination.parent.mkdir(parents=True, exist_ok=True)
                journal.record_action(
                    args.run_id, group_id, keeper, source, destination, size,
                    "moving", f"retry: previous status={old_status}; {verify_message}",
                )
                move_noreplace(source, destination)
                journal.record_action(
                    args.run_id, group_id, keeper, source, destination, size,
                    "moved", f"retry: previous status={old_status}; {verify_message}",
                )
                moved += 1
                bytes_moved += size
                tracker.result("QUARANTINED", str(source), counter="moved")
            except OSError as exc:
                failed += 1
                journal.record_action(
                    args.run_id, group_id, keeper, source, destination, size,
                    "failed", f"retry move failed; previous status={old_status}; {exc}",
                )
                tracker.result("FAILED MOVE", str(exc), counter="failed")

        tracker.finish("complete" if args.apply else "dry-run complete")
        print("\nRetry summary")
        print(f"Selected       : {len(rows):,}")
        print(f"Verified       : {planned:,}")
        print(f"Moved          : {moved:,}")
        print(f"Reconciled     : {reconciled:,}")
        print(f"Stale          : {stale:,}")
        print(f"Timed out      : {timed_out:,}")
        print(f"Failed         : {failed:,}")
        print(f"Quarantined    : {human_bytes(bytes_moved)}")
        if not args.apply:
            print("\nDry run only. Add --apply to move verified candidates and journal results.")
        return 1 if failed or timed_out else 0
    except KeyboardInterrupt:
        if "tracker" in locals():
            tracker.finish("interrupted")
        print(f"\nInterrupted safely. Resume with: archive-keeper retry {args.run_id} --apply")
        return 130
    finally:
        journal.close()



def reconcile(args):
    """Audit failed/timeout actions; --apply updates journal state only."""
    journal = Journal(args.state_db.expanduser())
    labels = ("DEST_ONLY_MATCH", "SOURCE_ONLY", "BOTH_IDENTICAL", "BOTH_DIFFERENT", "NEITHER", "ERROR")
    counts = {label: 0 for label in labels}
    applied = 0
    try:
        rows = list(journal.iter_actions(args.run_id, ("failed", "timeout")))
        if not rows:
            print(f"No failed/timeout actions found for run {args.run_id}")
            return 0
        tracker = ProgressTracker("Reconcile", total=len(rows))
        for index, row in enumerate(rows, 1):
            group_id, keeper_s, source_s, dest_s, size, old_status, old_message = row
            keeper, source, destination = Path(keeper_s), Path(source_s), Path(dest_s)
            tracker.current(index, "CHECKING", str(source))
            try:
                src, dst = source.exists(), destination.exists()
                if not src and not dst:
                    result, detail = "NEITHER", "source and quarantine destination are both absent"
                elif src and not dst:
                    actual = source.stat().st_size
                    result, detail = "SOURCE_ONLY", f"source exists; size={actual}; expected={size}"
                elif not src and dst:
                    destination_size = destination.stat().st_size
                    if destination_size != size:
                        result, detail = "BOTH_DIFFERENT", f"destination size={destination_size}; expected={size}"
                    elif not keeper.exists() or not keeper.is_file():
                        result, detail = "ERROR", "keeper unavailable for destination verification"
                    elif keeper.stat().st_size != size:
                        result, detail = "BOTH_DIFFERENT", f"keeper size={keeper.stat().st_size}; expected={size}"
                    else:
                        identical, msg, timed_out = bounded_files_identical(keeper, destination, timeout=args.verify_timeout)
                        if identical:
                            result, detail = "DEST_ONLY_MATCH", f"destination SHA-256 matches keeper; {msg}"
                        elif timed_out:
                            result, detail = "ERROR", msg
                        else:
                            result, detail = "BOTH_DIFFERENT", f"destination differs from keeper; {msg}"
                else:
                    source_size, destination_size = source.stat().st_size, destination.stat().st_size
                    if source_size != destination_size:
                        result, detail = "BOTH_DIFFERENT", f"source size={source_size}; destination size={destination_size}"
                    else:
                        identical, msg, timed_out = bounded_files_identical(source, destination, timeout=args.verify_timeout)
                        if identical:
                            result, detail = "BOTH_IDENTICAL", msg
                        elif timed_out:
                            result, detail = "ERROR", msg
                        else:
                            result, detail = "BOTH_DIFFERENT", msg
            except OSError as exc:
                result, detail = "ERROR", str(exc)
            counts[result] += 1
            print(f"{index:04d}/{len(rows)}  {result:<16} old={old_status:<7}  {source}")
            print(f"  {detail}")
            if args.apply and result in ("DEST_ONLY_MATCH", "BOTH_IDENTICAL"):
                journal.record_action(args.run_id, group_id, keeper, source, destination, size, "reconciled", f"reconcile: {result}; previous status={old_status}; {detail}")
                applied += 1
                tracker.result("RECONCILED", str(source), counter="reconciled")
            else:
                tracker.result(result, str(source), counter=result.lower())
        tracker.finish("complete")
        print("\nReconciliation summary")
        for label in labels:
            print(f"{label:<18} {counts[label]:>8,}")
        safe = counts["DEST_ONLY_MATCH"] + counts["BOTH_IDENTICAL"]
        print(f"{'SAFE_TO_RECONCILE':<18} {safe:>8,}")
        if args.apply:
            print(f"{'JOURNAL_UPDATED':<18} {applied:>8,}")
        else:
            print("\nDry run only. Add --apply to update proven-safe journal rows.")
        return 1 if counts["ERROR"] else 0
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
        if args.command == "reconcile":
            return reconcile(args)
        if args.command == "retry":
            return retry(args)
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
