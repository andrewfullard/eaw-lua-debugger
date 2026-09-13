"""Longer-lived debugger session helpers."""

from __future__ import annotations

from typing import Any


def run_diagnostic_session(
    client: Any,
    *,
    script_id: int | None,
    duration: float,
) -> dict[str, Any]:
    scripts = client.request_scripts()
    child_script_names = []
    threads = []
    if script_id is not None:
        child_script_names = client.attach_script(script_id)
        threads = client.request_threads(script_id)
    return {
        "scripts": scripts,
        "child_script_names": child_script_names,
        "threads": threads,
        "messages": list(client.iter_messages(timeout=duration)),
    }
