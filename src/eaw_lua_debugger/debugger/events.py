"""Human-readable debugger event descriptions."""

from __future__ import annotations

from ..protocol.lua_messages import LuaMessage, LuaMessageId


def describe_message(message: LuaMessage) -> str:
    fields = message.fields
    match message.message_id:
        case LuaMessageId.OUTPUT:
            return f"OUTPUT[{fields['output_type']}] {fields['message']}"
        case LuaMessageId.SCRIPT_ADDED:
            return f"SCRIPT_ADDED script={fields['script_id']} path={fields['full_path_name']}"
        case LuaMessageId.SCRIPT_REMOVED:
            return f"SCRIPT_REMOVED script={fields['script_id']}"
        case LuaMessageId.SCRIPT_SUSPENDED:
            return (
                f"SUSPENDED script={fields['script_id']} "
                f"thread={fields['current_thread_id']} "
                f"path={fields['full_path_name']} "
                f"callstack={len(fields['callstack'])} "
                f"threads={len(fields['threads'])}"
            )
        case _:
            return message.name
