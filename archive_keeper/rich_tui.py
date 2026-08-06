from __future__ import annotations

import curses
import textwrap
from pathlib import Path

from .core import human_bytes, load_rmlint_groups
from .decisions import DecisionStore
from .review import duplicate_graph, fuzzy_groups, keeper_reasons, render_preview, resolve_keeper


class ReviewUI:
    def __init__(self, stdscr, args, configured_func):
        self.stdscr = stdscr
        self.args = args
        self.roots, self.preferred, self.protected, self.excluded = configured_func(args)
        self.groups = load_rmlint_groups(args.report.expanduser())
        self.filtered = self.groups[:]
        self.decisions = DecisionStore(args.decisions_db)
        self.index = 0
        self.offset = 0
        self.query = ""
        self.message = "Review-only: no files move from this screen."
        curses.curs_set(0)
        stdscr.keypad(True)

    def close(self):
        self.decisions.close()

    def current(self):
        if not self.filtered:
            return None
        self.index = max(0, min(self.index, len(self.filtered) - 1))
        return self.filtered[self.index]

    def input_query(self):
        h, w = self.stdscr.getmaxyx()
        curses.echo(); curses.curs_set(1)
        prompt = "Search: "
        self.stdscr.move(h - 1, 0); self.stdscr.clrtoeol(); self.stdscr.addstr(h - 1, 0, prompt)
        try:
            raw = self.stdscr.getstr(h - 1, len(prompt), max(1, w - len(prompt) - 1))
            self.query = raw.decode(errors="replace")
        finally:
            curses.noecho(); curses.curs_set(0)
        self.filtered = fuzzy_groups(self.groups, self.query, limit=len(self.groups)) if self.query else self.groups[:]
        self.index = self.offset = 0
        self.message = f"{len(self.filtered):,} matching groups"

    def draw(self):
        self.stdscr.erase()
        h, w = self.stdscr.getmaxyx()
        if h < 18 or w < 90:
            self.stdscr.addstr(0, 0, "Terminal too small. Resize to at least 90x18. Press q to quit.")
            self.stdscr.refresh(); return
        left = max(38, min(58, w // 2))
        recoverable = sum(g.recoverable_bytes for g in self.groups)
        title = f" Archive Keeper 1.4.0 | {len(self.groups):,} groups | {human_bytes(recoverable)} max recoverable "
        self.stdscr.addnstr(0, 0, title.ljust(w), w - 1, curses.A_REVERSE)
        self.stdscr.addnstr(1, 0, f"Search: {self.query or '[none]'}", w - 1)
        self.stdscr.vline(2, left, curses.ACS_VLINE, h - 4)
        self.stdscr.addnstr(2, 0, "Groups", left - 1, curses.A_BOLD)
        self.stdscr.addnstr(2, left + 1, "Selected group / preview", w - left - 2, curses.A_BOLD)

        visible = max(1, h - 6)
        if self.index < self.offset: self.offset = self.index
        if self.index >= self.offset + visible: self.offset = self.index - visible + 1
        for row, group in enumerate(self.filtered[self.offset:self.offset + visible], start=3):
            absolute = self.offset + row - 3
            marker = ">" if absolute == self.index else " "
            line = f"{marker}{group.group_id:>6} {len(group.files):>4}x {human_bytes(group.recoverable_bytes):>10} {group.files[0].path.name}"
            attr = curses.A_REVERSE if absolute == self.index else curses.A_NORMAL
            self.stdscr.addnstr(row, 0, line.ljust(left), left - 1, attr)

        group = self.current()
        if group:
            keeper = resolve_keeper(group, self.preferred, self.protected, self.args.strategy, self.decisions)
            star = "★" if self.decisions.is_favorite(keeper.path) else "☆"
            reasons = "\n".join(f"• {r}" for r in keeper_reasons(keeper, group, self.preferred, self.protected, self.args.strategy))
            detail = f"{star} {duplicate_graph(group, keeper)}\n\nWhy this keeper:\n{reasons}\n\nMetadata / preview:\n{render_preview(keeper.path)}"
            width = w - left - 3
            lines = []
            for raw in detail.splitlines():
                lines.extend(textwrap.wrap(raw, width=width, replace_whitespace=False, drop_whitespace=False) or [""])
            for row, line in enumerate(lines[:h - 5], start=3):
                self.stdscr.addnstr(row, left + 2, line, width)

        help_line = "↑↓ browse  / search  k cycle keeper  f favorite  r refresh  q quit"
        self.stdscr.addnstr(h - 2, 0, help_line.ljust(w), w - 1, curses.A_REVERSE)
        self.stdscr.addnstr(h - 1, 0, self.message.ljust(w), w - 1)
        self.stdscr.refresh()

    def run(self):
        while True:
            self.draw()
            key = self.stdscr.getch()
            if key in (ord('q'), 27):
                return 0
            if key in (curses.KEY_DOWN, ord('j')) and self.filtered:
                self.index = min(len(self.filtered) - 1, self.index + 1)
            elif key in (curses.KEY_UP, ord('k')) and self.filtered:
                # k is keeper below only when used with uppercase K to avoid collision.
                self.index = max(0, self.index - 1)
            elif key == ord('/'):
                self.input_query()
            elif key == ord('K'):
                group = self.current()
                if group:
                    current = resolve_keeper(group, self.preferred, self.protected, self.args.strategy, self.decisions)
                    idx = group.files.index(current)
                    selected = group.files[(idx + 1) % len(group.files)]
                    self.decisions.set_keeper(group.group_id, selected.path, "manually selected in visual reviewer")
                    self.message = f"Keeper set: {selected.path}"
            elif key == ord('f'):
                group = self.current()
                if group:
                    keeper = resolve_keeper(group, self.preferred, self.protected, self.args.strategy, self.decisions)
                    state = self.decisions.toggle_favorite(keeper.path)
                    self.message = ("Favorited: " if state else "Unfavorited: ") + str(keeper.path)
            elif key == ord('r'):
                self.message = "Preview refreshed"


def run_rich_tui(args, configured_func):
    holder = {}
    def wrapped(stdscr):
        ui = ReviewUI(stdscr, args, configured_func); holder['ui'] = ui
        try:
            return ui.run()
        finally:
            ui.close()
    result = curses.wrapper(wrapped)
    print("No files were changed by the review interface.")
    return result or 0
