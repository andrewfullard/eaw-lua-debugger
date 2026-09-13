"""Longer-lived debugger session helpers."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .lua_messages import LuaMessage


def run_diagnostic_session(
    client: Any,
    *,
    script_id: int | None,
    duration: float,
    on_message: Callable[[LuaMessage], None] | None = None,
    collect_messages: bool = True,
) -> dict[str, Any]:
    scripts = client.request_scripts()
    child_script_names = []
    threads = []
    if script_id is not None:
        child_script_names = client.attach_script(script_id)
        threads = client.request_threads(script_id)
    messages = []
    message_count = 0
    for message in client.iter_messages(timeout=duration):
        message_count += 1
        if on_message is not None:
            on_message(message)
        if collect_messages:
            messages.append(message)
    return {
        "scripts": scripts,
        "child_script_names": child_script_names,
        "threads": threads,
        "message_count": message_count,
        "messages": messages,
    }
