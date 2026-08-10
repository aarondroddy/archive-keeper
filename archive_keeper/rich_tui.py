from __future__ import annotations

import curses
import textwrap
from pathlib import Path

from .core import human_bytes, load_rmlint_groups, normalize_path
from .decisions import DecisionStore
from .review import fuzzy_groups, keeper_reasons, render_preview, resolve_keeper


def _short_path(path: Path, roots: list[Path], width: int) -> str:
    """Show the filename first, then enough parent path to distinguish copies."""
    resolved = normalize_path(path)
    normalized_roots = [normalize_path(root) for root in roots]
    root = next((candidate for candidate in normalized_roots if resolved == candidate or candidate in resolved.parents), None)
    filename = resolved.name or str(resolved)
    if root is not None:
        try:
            relative_parent = resolved.parent.relative_to(root)
            location = f"{root.name}:/{relative_parent}" if str(relative_parent) != "." else f"{root.name}:/"
        except ValueError:
            location = str(resolved.parent)
    else:
        location = str(resolved.parent)

    full = f"{filename}  ←  {location}"
    if len(full) <= width:
        return full

    separator = "  ←  "
    # Keep the beginning of the filename and the end of the parent path, because
    # duplicate copies often share a name but differ near the path tail.
    file_budget = max(12, min(len(filename), width // 2))
    location_budget = max(8, width - file_budget - len(separator))
    shown_file = filename if len(filename) <= file_budget else filename[:max(1, file_budget - 1)] + "…"
    if len(location) <= location_budget:
        shown_location = location
    elif root is not None:
        root_prefix = f"{root.name}:/"
        tail_budget = max(1, location_budget - len(root_prefix) - 1)
        relative_location = location[len(root_prefix):] if location.startswith(root_prefix) else location
        shown_location = root_prefix + "…" + relative_location[-tail_budget:]
    else:
        shown_location = "…" + location[-max(1, location_budget - 1):]
    return (shown_file + separator + shown_location)[:width]


class ReviewUI:
    """Full-screen, review-only duplicate decision editor."""

    def __init__(self, stdscr, args, configured_func):
        self.stdscr = stdscr
        self.args = args
        self.roots, self.preferred, self.protected, self.excluded = configured_func(args)
        self.groups = getattr(args, "_preloaded_groups", None) or load_rmlint_groups(args.report.expanduser())
        self.filtered = self.groups[:]
        self.decisions = DecisionStore(args.decisions_db)
        self.group_index = 0
        self.group_offset = 0
        self.file_index = 0
        self.file_offset = 0
        self.mode = "groups"
        self.query = ""
        self.message = "Review-only: decisions are saved; no files move from this screen."
        self.preview_cache: dict[tuple[Path, int], str] = {}
        curses.curs_set(0)
        stdscr.keypad(True)

    def close(self):
        self.decisions.close()

    def current_group(self):
        if not self.filtered:
            return None
        self.group_index = max(0, min(self.group_index, len(self.filtered) - 1))
        return self.filtered[self.group_index]

    def current_file(self):
        group = self.current_group()
        if not group:
            return None
        self.file_index = max(0, min(self.file_index, len(group.files) - 1))
        return group.files[self.file_index]

    def input_query(self):
        h, w = self.stdscr.getmaxyx()
        curses.echo()
        curses.curs_set(1)
        prompt = "Search: "
        self.stdscr.move(h - 1, 0)
        self.stdscr.clrtoeol()
        self.stdscr.addstr(h - 1, 0, prompt)
        try:
            raw = self.stdscr.getstr(h - 1, len(prompt), max(1, w - len(prompt) - 1))
            self.query = raw.decode(errors="replace")
        finally:
            curses.noecho()
            curses.curs_set(0)
        self.filtered = fuzzy_groups(self.groups, self.query, limit=len(self.groups)) if self.query else self.groups[:]
        self.group_index = self.group_offset = self.file_index = self.file_offset = 0
        self.mode = "groups"
        self.message = f"{len(self.filtered):,} matching groups"

    def preview(self, path: Path) -> str:
        try:
            stamp = path.stat().st_mtime_ns
        except OSError:
            stamp = -1
        key = (path, stamp)
        if key not in self.preview_cache:
            self.preview_cache[key] = render_preview(path)
        return self.preview_cache[key]

    def action_for(self, group, item, keeper) -> str:
        if normalize_path(item.path) == normalize_path(keeper.path):
            return "KEEP"
        return self.decisions.get_action(group.group_id, item.path) or "QUARANTINE"

    def draw_groups(self, h, w, left):
        self.stdscr.addnstr(2, 0, "Groups", left - 1, curses.A_BOLD)
        visible = max(1, h - 6)
        if self.group_index < self.group_offset:
            self.group_offset = self.group_index
        if self.group_index >= self.group_offset + visible:
            self.group_offset = self.group_index - visible + 1
        for row, group in enumerate(self.filtered[self.group_offset:self.group_offset + visible], start=3):
            absolute = self.group_offset + row - 3
            marker = ">" if absolute == self.group_index else " "
            line = f"{marker}{group.group_id:>6} {len(group.files):>4}x {human_bytes(group.recoverable_bytes):>10} {group.files[0].path.name}"
            attr = curses.A_REVERSE if absolute == self.group_index else curses.A_NORMAL
            self.stdscr.addnstr(row, 0, line.ljust(left), left - 1, attr)

    def draw_files(self, h, w, left, group, keeper):
        self.stdscr.addnstr(2, 0, f"Group {group.group_id} copies", left - 1, curses.A_BOLD)
        visible = max(1, h - 6)
        if self.file_index < self.file_offset:
            self.file_offset = self.file_index
        if self.file_index >= self.file_offset + visible:
            self.file_offset = self.file_index - visible + 1
        for row, item in enumerate(group.files[self.file_offset:self.file_offset + visible], start=3):
            absolute = self.file_offset + row - 3
            action = self.action_for(group, item, keeper)
            marker = ">" if absolute == self.file_index else " "
            label = {"KEEP": "★ KEEP", "QUARANTINE": "✗ QUAR", "UNDECIDED": "? WAIT"}[action]
            path_width = max(12, left - 12)
            shown = _short_path(item.path, self.roots, path_width)
            line = f"{marker} {label:<8} {shown}"
            attr = curses.A_REVERSE if absolute == self.file_index else curses.A_NORMAL
            self.stdscr.addnstr(row, 0, line.ljust(left), left - 1, attr)

    def draw(self):
        self.stdscr.erase()
        h, w = self.stdscr.getmaxyx()
        if h < 18 or w < 90:
            self.stdscr.addstr(0, 0, "Terminal too small. Resize to at least 90x18. Press q to quit.")
            self.stdscr.refresh()
            return
        left = max(46, min(72, w // 2))
        recoverable = sum(g.recoverable_bytes for g in self.groups)
        title = f" Archive Keeper 1.6.6 | {len(self.groups):,} groups | {human_bytes(recoverable)} max recoverable "
        self.stdscr.addnstr(0, 0, title.ljust(w), w - 1, curses.A_REVERSE)
        self.stdscr.addnstr(1, 0, f"Search: {self.query or '[none]'} | Mode: {self.mode}", w - 1)
        self.stdscr.vline(2, left, curses.ACS_VLINE, h - 4)
        self.stdscr.addnstr(2, left + 1, "Selected copy / preview", w - left - 2, curses.A_BOLD)

        group = self.current_group()
        if group:
            keeper = resolve_keeper(group, self.preferred, self.protected, self.args.strategy, self.decisions)
            if self.mode == "files":
                self.draw_files(h, w, left, group, keeper)
                selected = self.current_file()
            else:
                self.draw_groups(h, w, left)
                selected = keeper
            if selected:
                action = self.action_for(group, selected, keeper)
                reasons = "\n".join(f"• {r}" for r in keeper_reasons(keeper, group, self.preferred, self.protected, self.args.strategy))
                detail = (
                    f"Group {group.group_id} | {len(group.files)} copies\n"
                    f"Selected action: {action}\nSelected path: {selected.path}\n\n"
                    f"Keeper: {keeper.path}\n\nWhy this keeper:\n{reasons}\n\n"
                    f"Metadata / preview:\n{self.preview(selected.path)}"
                )
                width = w - left - 3
                lines = []
                for raw in detail.splitlines():
                    lines.extend(textwrap.wrap(raw, width=width, replace_whitespace=False, drop_whitespace=False) or [""])
                for row, line in enumerate(lines[:h - 5], start=3):
                    self.stdscr.addnstr(row, left + 2, line, width)

        if self.mode == "groups":
            help_line = "↑↓ browse  Enter open group  / search  f favorite  r refresh  q quit"
        else:
            help_line = "↑↓ select copy  k KEEP  x QUARANTINE  u UNDECIDED  p preview  b/Esc back  q quit"
        self.stdscr.addnstr(h - 2, 0, help_line.ljust(w), w - 1, curses.A_REVERSE)
        self.stdscr.addnstr(h - 1, 0, self.message.ljust(w), w - 1)
        self.stdscr.refresh()

    def run(self):
        while True:
            self.draw()
            key = self.stdscr.getch()
            if key == ord('q'):
                return 0
            if self.mode == "groups":
                if key in (curses.KEY_DOWN, ord('j')) and self.filtered:
                    self.group_index = min(len(self.filtered) - 1, self.group_index + 1)
                elif key in (curses.KEY_UP, ord('k')) and self.filtered:
                    self.group_index = max(0, self.group_index - 1)
                elif key in (curses.KEY_ENTER, 10, 13):
                    if self.current_group():
                        keeper = resolve_keeper(self.current_group(), self.preferred, self.protected, self.args.strategy, self.decisions)
                        self.file_index = self.current_group().files.index(keeper)
                        self.file_offset = 0
                        self.mode = "files"
                        self.message = "Choose each copy explicitly. Decisions save immediately."
                elif key == ord('/'):
                    self.input_query()
                elif key == ord('f'):
                    group = self.current_group()
                    if group:
                        keeper = resolve_keeper(group, self.preferred, self.protected, self.args.strategy, self.decisions)
                        state = self.decisions.toggle_favorite(keeper.path)
                        self.message = ("Favorited: " if state else "Unfavorited: ") + str(keeper.path)
                elif key == ord('r'):
                    self.preview_cache.clear()
                    self.message = "Preview cache refreshed"
            else:
                group = self.current_group()
                if not group:
                    self.mode = "groups"
                    continue
                if key in (27, curses.KEY_LEFT, ord('b')):
                    self.mode = "groups"
                    self.message = "Returned to group list"
                elif key in (curses.KEY_DOWN, ord('j')):
                    self.file_index = min(len(group.files) - 1, self.file_index + 1)
                elif key in (curses.KEY_UP, ord('i')):
                    self.file_index = max(0, self.file_index - 1)
                elif key == ord('k'):
                    selected = self.current_file()
                    self.decisions.set_keeper(group.group_id, selected.path, "manually selected in visual reviewer")
                    self.decisions.clear_action(group.group_id, selected.path)
                    self.message = f"KEEP saved: {selected.path}"
                elif key == ord('x'):
                    selected = self.current_file()
                    keeper = resolve_keeper(group, self.preferred, self.protected, self.args.strategy, self.decisions)
                    if normalize_path(selected.path) == normalize_path(keeper.path):
                        self.message = "Choose another keeper before quarantining the current keeper."
                    else:
                        self.decisions.set_action(group.group_id, selected.path, "QUARANTINE")
                        self.message = f"QUARANTINE saved: {selected.path}"
                elif key == ord('u'):
                    selected = self.current_file()
                    keeper = resolve_keeper(group, self.preferred, self.protected, self.args.strategy, self.decisions)
                    if normalize_path(selected.path) == normalize_path(keeper.path):
                        self.message = "The keeper cannot be undecided. Choose another keeper first."
                    else:
                        self.decisions.set_action(group.group_id, selected.path, "UNDECIDED")
                        self.message = f"UNDECIDED saved: {selected.path}"
                elif key in (ord('p'), ord('r')):
                    selected = self.current_file()
                    for cache_key in list(self.preview_cache):
                        if cache_key[0] == selected.path:
                            del self.preview_cache[cache_key]
                    self.message = "Preview refreshed"


def run_rich_tui(args, configured_func):
    def progress(message: str) -> None:
        print(f"Archive Keeper: {message}", flush=True)

    args._preloaded_groups = load_rmlint_groups(args.report.expanduser(), progress=progress)
    holder = {}

    def wrapped(stdscr):
        ui = ReviewUI(stdscr, args, configured_func)
        holder['ui'] = ui
        try:
            return ui.run()
        finally:
            ui.close()

    result = curses.wrapper(wrapped)
    print("No files were changed by the review interface; saved decisions will affect plans and quarantine runs.")
    return result or 0
