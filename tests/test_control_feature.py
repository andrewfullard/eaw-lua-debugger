import pytest

from eaw_lua_debugger.core.exceptions import InvalidDebuggerState
from eaw_lua_debugger.debugger.client import DebuggerRunState, LuaDebuggerClient
from eaw_lua_debugger.protocol.lua_messages import LuaMessage, LuaMessageId


def suspended_message() -> LuaMessage:
    return LuaMessage(
        LuaMessageId.SCRIPT_SUSPENDED,
        {
            "script_id": 7,
            "current_thread_id": 0,
            "callstack": ["Foo.lua:1"],
            "threads": [],
        },
        raw_payload=None,
    )


@pytest.mark.parametrize(
    ("name", "message_id"),
    [
        ("break", LuaMessageId.BREAK_ALL),
        ("continue", LuaMessageId.CONTINUE),
        ("step-over", LuaMessageId.STEP_OVER),
        ("step-into", LuaMessageId.STEP_INTO),
        ("step-out", LuaMessageId.STEP_OUT),
    ],
)
def test_client_send_control_maps_command_names_to_lua_ids(name, message_id):
    sent = []
    client = LuaDebuggerClient()
    client.send_lua = lambda *args: sent.append(args)
    if name != "break":
        client._track_debug_state(suspended_message())

    client.send_control(name)

    assert sent == [(message_id,)]
    assert client.run_state == (
        DebuggerRunState.RUNNING
        if name == "continue"
        else DebuggerRunState.BREAK_PENDING
    )


def test_client_send_control_rejects_unknown_command():
    with pytest.raises(ValueError, match="unknown control command"):
        LuaDebuggerClient().send_control("nope")


def test_client_rejects_duplicate_break_and_step_while_running():
    client = LuaDebuggerClient()
    client.send_lua = lambda *_args: None

    client.send_control("break")

    with pytest.raises(InvalidDebuggerState, match="break-pending"):
        client.send_control("break")
    client.run_state = DebuggerRunState.RUNNING
    with pytest.raises(InvalidDebuggerState, match="running"):
        client.send_control("step-over")


def test_client_rejects_break_while_a_step_is_pending():
    client = LuaDebuggerClient()
    client.send_lua = lambda *_args: None
    client._track_debug_state(suspended_message())

    client.send_control("step-over")

    with pytest.raises(InvalidDebuggerState, match="break-pending"):
        client.send_control("break")
