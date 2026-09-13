import pytest

from eaw_lua_debugger.client import LuaDebuggerClient
from eaw_lua_debugger.lua_messages import LuaMessageId


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

    client.send_control(name)

    assert sent == [(message_id,)]


def test_client_send_control_rejects_unknown_command():
    with pytest.raises(ValueError, match="unknown control command"):
        LuaDebuggerClient().send_control("nope")
