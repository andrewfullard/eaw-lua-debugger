"""Debugger domain value objects."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ScriptInfo:
    script_id: int
    full_path_name: str


@dataclass(frozen=True)
class ThreadInfo:
    thread_index: int
    thread_name: str


@dataclass(frozen=True)
class VariableValue:
    variable_name: str
    value_type: int
    value_text: str


@dataclass(frozen=True)
class TableMember:
    key_type: int
    key_text: str
    value_type: int
    value_text: str
