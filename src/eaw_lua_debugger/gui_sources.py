"""Source-file loading helpers for the GUI."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from .client import ScriptInfo


@dataclass(frozen=True)
class SourceFile:
    script: ScriptInfo
    path: Path | None
    text: str
    found: bool


def source_roots(paths: list[str] | None) -> list[Path]:
    roots = [Path.cwd()]
    env_roots = os.environ.get("EAW_LUA_SOURCE_ROOT", "")
    roots.extend(Path(path) for path in env_roots.split(os.pathsep) if path)
    roots.extend(Path(path) for path in paths or [])
    return _dedupe(roots)


def load_script_source(script: ScriptInfo, roots: list[str | Path] | None) -> SourceFile:
    for candidate in _candidates(script.full_path_name, [Path(root) for root in roots or []]):
        if candidate.is_file():
            return SourceFile(script, candidate, candidate.read_text(encoding="utf-8"), True)
    return SourceFile(
        script,
        None,
        f"-- Source file not found for {script.full_path_name}\n",
        False,
    )


def format_source_lines(text: str, breakpoint_lines: set[int] | None = None) -> str:
    breakpoint_lines = breakpoint_lines or set()
    lines = text.splitlines()
    width = max(3, len(str(len(lines))))
    return "\n".join(
        f"{line_number:{width}} {'\u25cf' if line_number in breakpoint_lines else ' '} {line}"
        for line_number, line in enumerate(lines, 1)
    )


def _candidates(reported_path: str, roots: list[Path]) -> list[Path]:
    candidates: list[Path] = []
    direct = Path(reported_path)
    if direct.is_absolute():
        candidates.append(direct)

    normalized = reported_path.replace("\\", "/").lstrip("/")
    parts = [part for part in re.split(r"/+", normalized) if part and ":" not in part]
    suffixes = [parts]
    lowered = [part.lower() for part in parts]
    for anchor in ("data", "scripts"):
        if anchor in lowered:
            index = lowered.index(anchor)
            suffixes.append(parts[index:])
            if anchor == "scripts" and index + 1 < len(parts):
                suffixes.append(parts[index + 1 :])
    if parts:
        suffixes.append([parts[-1]])

    for root in roots:
        for suffix in suffixes:
            if suffix:
                candidates.append(root.joinpath(*suffix))
    return _dedupe(candidates)


def _dedupe(paths: list[Path]) -> list[Path]:
    seen = set()
    result = []
    for path in paths:
        key = path.resolve(strict=False)
        if key not in seen:
            seen.add(key)
            result.append(path)
    return result
