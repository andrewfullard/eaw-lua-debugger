import pytest

from eaw_lua_debugger.core.exceptions import InvalidDebuggerState
from eaw_lua_debugger.debugger.client import DebuggerRunState, LuaDebuggerClient
from eaw_lua_debugger.protocol.lua_messages import LuaMessage, LuaMessageId


def test_client_context_commands_enforce_native_state_and_send_documented_fields():
    sent = []
    client = LuaDebuggerClient()
    client.known_script_ids.add(10)
    client.send_lua = lambda *args: sent.append(args)

    client.select_script(10)
    assert client.run_state == DebuggerRunState.BREAK_PENDING

    client.thread_ids_by_script[10] = {20}
    client.select_thread(20)
    assert client.run_state == DebuggerRunState.BREAK_PENDING

    client._track_debug_state(
        LuaMessage(
            LuaMessageId.SCRIPT_SUSPENDED,
            {
                "script_id": 10,
                "current_thread_id": 20,
                "callstack": ["Foo.lua:3"],
                "threads": [{"thread_index": 20, "thread_name": "main"}],
            },
            raw_payload=None,
        )
    )
    client.set_callstack_depth(10, 0)

    assert sent == [
        (LuaMessageId.SELECT_SCRIPT, 10),
        (LuaMessageId.SELECT_THREAD, 20),
        (LuaMessageId.SET_CALLSTACK_DEPTH, 10, 0),
    ]


def test_same_script_selection_is_noop_and_invalid_callstack_is_local_error():
    sent = []
    client = LuaDebuggerClient()
    client.known_script_ids.add(10)
    client.context_script_id = 10
    client.send_lua = lambda *args: sent.append(args)

    client.select_script(10)

    assert sent == []
    assert client.run_state == DebuggerRunState.RUNNING
    with pytest.raises(InvalidDebuggerState, match="running"):
        client.set_callstack_depth(10, 0)


def test_break_script_uses_implicit_break_only_when_context_changes():
    sent = []
    client = LuaDebuggerClient()
    client.known_script_ids.add(10)
    client.attached_script_ids.add(10)
    client.send_lua = lambda *args: sent.append(args)

    client.break_script(10)

    assert sent == [(LuaMessageId.SELECT_SCRIPT, 10)]
    assert client.run_state == DebuggerRunState.BREAK_PENDING

    client.run_state = DebuggerRunState.RUNNING
    client.break_script(10)

    assert sent[-1] == (LuaMessageId.BREAK_ALL,)


def test_break_script_can_retarget_a_pending_break_but_not_repeat_it():
    sent = []
    client = LuaDebuggerClient()
    client.known_script_ids.update({10, 11})
    client.attached_script_ids.update({10, 11})
    client.send_lua = lambda *args: sent.append(args)

    client.break_script(10)
    client.break_script(11)

    assert sent == [
        (LuaMessageId.SELECT_SCRIPT, 10),
        (LuaMessageId.SELECT_SCRIPT, 11),
    ]
    with pytest.raises(InvalidDebuggerState, match="already pending"):
        client.break_script(11)
