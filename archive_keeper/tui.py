from __future__ import annotations

import os
import shutil
import sys
from collections import Counter, defaultdict
from pathlib import Path

from .core import choose_keeper, human_bytes, load_rmlint_groups


def clear_screen():
    if sys.stdout.isatty():
        os.system("clear" if os.name != "nt" else "cls")


def term_width(default: int = 88) -> int:
    try:
        return max(60, min(120, shutil.get_terminal_size().columns))
    except OSError:
        return default


def rule(char: str = "═") -> str:
    return char * term_width()


def pause():
    try:
        input("\nPress Enter to continue...")
    except EOFError:
        pass


def prompt_choice(prompt: str, choices: set[str], default: str | None = None) -> str:
    while True:
        suffix = f" [{default}]" if default else ""
        try:
            value = input(f"{prompt}{suffix}: ").strip().lower()
        except EOFError:
            return default or sorted(choices)[0]
        if not value and default:
            return default
        if value in choices:
            return value
        print(f"Choose one of: {', '.join(sorted(choices))}")


def summarize(groups):
    total_files = sum(len(g.files) for g in groups)
    recoverable = sum(g.recoverable_bytes for g in groups)
    largest = sorted(groups, key=lambda g: g.recoverable_bytes, reverse=True)
    ext_bytes = defaultdict(int)
    ext_count = Counter()
    for group in groups:
        for item in group.files[1:]:
            ext = item.path.suffix.lower() or "[no extension]"
            ext_bytes[ext] += item.size
            ext_count[ext] += 1
    return {"groups":len(groups),"files":total_files,"recoverable":recoverable,
            "largest":largest,"ext_bytes":ext_bytes,"ext_count":ext_count}


def print_dashboard(stats, preferred_roots, protected_roots, excluded_roots):
    clear_screen()
    print(rule())
    print(" ARCHIVE KEEPER — REVIEW CONSOLE")
    print(rule())
    print(f"\n Duplicate groups       {stats['groups']:>12,}")
    print(f" Files in groups        {stats['files']:>12,}")
    print(f" Maximum recoverable    {human_bytes(stats['recoverable']):>15}\n")
    print(" Keeper priority")
    for index, root in enumerate(preferred_roots, 1):
        print(f"   {index}. {root}")
    if not preferred_roots:
        print("   No preferred roots configured")
    print(f"\n Protected roots: {len(protected_roots)}")
    print(f" Excluded roots : {len(excluded_roots)}\n")
    print(" Main menu")
    print("   1  Review largest duplicate groups")
    print("   2  Review space by file extension")
    print("   3  Preview keeper decisions")
    print("   4  Show protected and excluded roots")
    print("   5  Export CSV plan")
    print("   6  Show safe pilot command")
    print("   q  Quit\n")


def review_largest(stats, preferred_roots, protected_roots, strategy, limit=20):
    clear_screen(); print(rule()); print(" LARGEST DUPLICATE GROUPS"); print(rule())
    for group in stats["largest"][:limit]:
        keeper = choose_keeper(group, preferred_roots, protected_roots, strategy)
        print(f"\nGroup {group.group_id:,} — {len(group.files):,} copies — {human_bytes(group.recoverable_bytes)} recoverable")
        print(f"  KEEP  {keeper.path}")
        shown=0
        for item in group.files:
            if item.path == keeper.path: continue
            print(f"  MOVE  {item.path}"); shown += 1
            if shown >= 5 and len(group.files)-1 > shown:
                print(f"        …and {len(group.files)-1-shown:,} more"); break
    pause()


def review_extensions(stats, limit=25):
    clear_screen(); print(rule()); print(" DUPLICATE SPACE BY FILE EXTENSION"); print(rule())
    rows=sorted(stats["ext_bytes"].items(), key=lambda pair: pair[1], reverse=True)
    print(f"{'Extension':<18}{'Duplicate files':>18}{'Potential space':>22}")
    print("-" * min(term_width(),70))
    for ext, byte_count in rows[:limit]:
        print(f"{ext[:17]:<18}{stats['ext_count'][ext]:>18,}{human_bytes(byte_count):>22}")
    pause()


def preview_keepers(groups, preferred_roots, protected_roots, strategy, limit=30):
    clear_screen(); print(rule()); print(" KEEPER DECISION PREVIEW"); print(rule())
    for group in groups[:limit]:
        keeper=choose_keeper(group, preferred_roots, protected_roots, strategy)
        print(f"Group {group.group_id:>6}: keep {keeper.path} ({len(group.files)} copies)")
    if len(groups)>limit: print(f"\nShowing {limit} of {len(groups):,} groups.")
    pause()


def show_rules(protected_roots, excluded_roots):
    clear_screen(); print(rule()); print(" SAFETY RULES"); print(rule())
    print("\nProtected roots — may be chosen as keepers, never moved:")
    print("\n".join(f"  • {r}" for r in protected_roots) if protected_roots else "  None")
    print("\nExcluded roots — duplicate entries are ignored entirely:")
    print("\n".join(f"  • {r}" for r in excluded_roots) if excluded_roots else "  None")
    pause()


def pilot_command(report, state_db, mount_roots, preferred_roots, protected_roots, excluded_roots, strategy):
    parts=["archive-keeper","--report",str(report),"--state-db",str(state_db)]
    for r in mount_roots: parts += ["--mount-root",str(r)]
    for r in preferred_roots: parts += ["--prefer",str(r)]
    for r in protected_roots: parts += ["--protect",str(r)]
    for r in excluded_roots: parts += ["--exclude",str(r)]
    if strategy != "preferred-root": parts += ["--strategy",strategy]
    parts += ["quarantine","--run-id","pilot-25","--limit","25","--deep-verify","--apply"]
    lines=[]; current=""
    for part in parts:
        quoted=f"'{part}'" if " " in part else part
        if not current: current=quoted
        elif len(current)+len(quoted)+1 > 82: lines.append(current+" \\"); current="  "+quoted
        else: current += " "+quoted
    if current: lines.append(current)
    return "\n".join(lines)


def run_tui(args, configured_func, export_plan_func):
    roots, preferred, protected, excluded = configured_func(args)
    groups=load_rmlint_groups(args.report.expanduser()); stats=summarize(groups)
    while True:
        print_dashboard(stats, preferred, protected, excluded)
        choice=prompt_choice("Selection", {"1","2","3","4","5","6","q"})
        if choice=="q": clear_screen(); print("No files were changed."); return 0
        if choice=="1": review_largest(stats, preferred, protected, args.strategy)
        elif choice=="2": review_extensions(stats)
        elif choice=="3": preview_keepers(groups, preferred, protected, args.strategy)
        elif choice=="4": show_rules(protected, excluded)
        elif choice=="5":
            output=args.output.expanduser(); export_plan_func(groups, output, preferred, protected, excluded, args.strategy)
            print(f"\nCSV plan written to: {output}"); pause()
        elif choice=="6":
            clear_screen(); print(rule()); print(" SAFE 25-FILE PILOT"); print(rule())
            print("\nThis command performs SHA-256 verification and moves at most 25 files:\n")
            print(pilot_command(args.report.expanduser(), args.state_db.expanduser(), roots, preferred, protected, excluded, args.strategy))
            print("\nReview your mount points before running it."); pause()
