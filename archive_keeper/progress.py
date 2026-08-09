from __future__ import annotations

import sys
import time
from dataclasses import dataclass, field
from typing import TextIO


def _fmt_duration(seconds: float | None) -> str:
    if seconds is None or seconds < 0:
        return "--:--"
    seconds = int(seconds)
    hours, rem = divmod(seconds, 3600)
    minutes, secs = divmod(rem, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}" if hours else f"{minutes:02d}:{secs:02d}"


@dataclass
class ProgressTracker:
    """Small dependency-free progress reporter for long-running CLI work.

    Interactive terminals get a compact live status line. Redirected output gets
    ordinary timestamped lines so logs remain readable.
    """

    label: str
    total: int | None = None
    stream: TextIO = sys.stdout
    start: float = field(default_factory=time.monotonic)
    completed: int = 0
    counters: dict[str, int] = field(default_factory=dict)
    _live_len: int = 0

    @property
    def interactive(self) -> bool:
        try:
            return bool(self.stream.isatty())
        except Exception:
            return False

    def _fraction(self) -> str:
        if self.total and self.total > 0:
            pct = min(100.0, (self.completed / self.total) * 100.0)
            return f"{self.completed:,}/{self.total:,} ({pct:5.1f}%)"
        return f"{self.completed:,}"

    def _eta(self) -> str:
        if not self.total or self.completed <= 0 or self.completed >= self.total:
            return "--:--"
        elapsed = time.monotonic() - self.start
        rate = self.completed / elapsed if elapsed > 0 else 0
        if rate <= 0:
            return "--:--"
        return _fmt_duration((self.total - self.completed) / rate)

    def _bar(self, width: int = 20) -> str:
        if not self.total or self.total <= 0:
            return ""
        ratio = max(0.0, min(1.0, self.completed / self.total))
        full = int(ratio * width)
        return "[" + "#" * full + "-" * (width - full) + "]"

    def line(self, status: str, item: str = "", *, advance: bool = False, counter: str | None = None) -> None:
        if advance:
            self.completed += 1
        if counter:
            self.counters[counter] = self.counters.get(counter, 0) + 1
        elapsed = _fmt_duration(time.monotonic() - self.start)
        counts = " ".join(f"{k}={v:,}" for k, v in sorted(self.counters.items()))
        prefix = f"{self.label}: {self._fraction()}"
        bar = self._bar()
        detail = f" {status}"
        if item:
            detail += f"  {item}"
        tail = f"  elapsed={elapsed}"
        if self.total:
            tail += f" eta={self._eta()}"
        if counts:
            tail += f"  {counts}"
        message = " ".join(part for part in (prefix, bar, detail, tail) if part)
        if self.interactive:
            padded = message.ljust(self._live_len)
            print("\r" + padded, end="", file=self.stream, flush=True)
            self._live_len = max(self._live_len, len(message))
        else:
            stamp = time.strftime("%H:%M:%S")
            print(f"[{stamp}] {message}", file=self.stream, flush=True)

    def current(self, index: int, status: str, item: str = "") -> None:
        self.completed = max(0, index - 1)
        self.line(status, item)

    def result(self, status: str, item: str = "", *, counter: str | None = None) -> None:
        self.line(status, item, advance=True, counter=counter)

    def finish(self, status: str = "complete") -> None:
        if self.interactive and self._live_len:
            print(file=self.stream, flush=True)
        elapsed = _fmt_duration(time.monotonic() - self.start)
        counts = ", ".join(f"{k}={v:,}" for k, v in sorted(self.counters.items())) or "no result counters"
        print(f"{self.label}: {status}; processed {self.completed:,}" + (f"/{self.total:,}" if self.total else "") + f" in {elapsed}; {counts}", file=self.stream, flush=True)
