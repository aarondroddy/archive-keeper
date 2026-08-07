from __future__ import annotations

import difflib
import os
import shutil
import subprocess
from collections import Counter, defaultdict
from pathlib import Path

from .core import DuplicateFile, DuplicateGroup, choose_keeper, normalize_path, human_bytes, path_is_within
from .decisions import DecisionStore
from .metadata import inspect_path


def keeper_reasons(item: DuplicateFile, group: DuplicateGroup, preferred: list[Path], protected: list[Path], strategy: str) -> list[str]:
    reasons: list[str] = []
    for idx, root in enumerate(preferred, 1):
        if path_is_within(item.path, root):
            reasons.append(f"preferred root rank {idx}: {root}")
            break
    if any(path_is_within(item.path, root) for root in protected):
        reasons.append("inside a protected root")
    if item.is_original_hint:
        reasons.append("marked original by rmlint")
    if item.mtime == min(f.mtime for f in group.files):
        reasons.append("oldest timestamp in group")
    if len(str(item.path)) == min(len(str(f.path)) for f in group.files):
        reasons.append("shortest path in group")
    reasons.append(f"strategy: {strategy}")
    return reasons


def resolve_keeper(group: DuplicateGroup, preferred: list[Path], protected: list[Path], strategy: str, decisions: DecisionStore | None = None) -> DuplicateFile:
    if decisions:
        selected = decisions.get_keeper(group.group_id)
        if selected:
            selected = normalize_path(selected)
            for item in group.files:
                if normalize_path(item.path) == selected:
                    return item
    return choose_keeper(group, preferred, protected, strategy)


def fuzzy_groups(groups: list[DuplicateGroup], query: str, limit: int = 100) -> list[DuplicateGroup]:
    query = query.strip().lower()
    if not query:
        return groups[:limit]
    scored = []
    for group in groups:
        hay = " ".join(str(f.path).lower() for f in group.files)
        if query in hay:
            score = 2.0
        else:
            score = difflib.SequenceMatcher(None, query, hay[:500]).ratio()
        if score >= 0.12:
            scored.append((score, group.recoverable_bytes, group))
    scored.sort(key=lambda row: (row[0], row[1]), reverse=True)
    return [row[2] for row in scored[:limit]]


def folder_summary(groups: list[DuplicateGroup], depth: int = 4):
    totals = defaultdict(lambda: [0, 0])
    for group in groups:
        for item in group.files[1:]:
            parts = item.path.parts[:depth]
            key = Path(*parts)
            totals[key][0] += 1
            totals[key][1] += item.size
    return sorted(totals.items(), key=lambda kv: kv[1][1], reverse=True)


def render_preview(path: Path) -> str:
    meta = inspect_path(path)
    lines = [f"Type: {meta.kind} ({meta.mime})"]
    lines.extend(f"{key}: {value}" for key, value in meta.details.items())
    if meta.preview:
        lines += ["", "Preview:", meta.preview]
    if meta.preview_command:
        try:
            result = subprocess.run(meta.preview_command, capture_output=True, text=True, timeout=15, check=False)
            if result.stdout:
                lines += ["", result.stdout]
        except (OSError, subprocess.TimeoutExpired):
            pass
    return "\n".join(lines)


def duplicate_graph(group: DuplicateGroup, keeper: DuplicateFile) -> str:
    lines = [f"Group {group.group_id} ({len(group.files)} copies)"]
    for idx, item in enumerate(group.files):
        branch = "└──" if idx == len(group.files) - 1 else "├──"
        marker = "KEEP" if item.path == keeper.path else "MOVE"
        lines.append(f"{branch} [{marker}] {item.path}")
    return "\n".join(lines)
