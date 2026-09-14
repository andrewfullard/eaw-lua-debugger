import pytest

from eaw_lua_debugger.core.exceptions import InvalidDebuggerState
from eaw_lua_debugger.debugger.client import LuaDebuggerClient
from eaw_lua_debugger.protocol.lua_messages import LuaMessageId, encode_lua_message


def test_client_add_breakpoint_sends_documented_fields():
    sent = []
    client = LuaDebuggerClient()
    client.known_script_ids.add(1)
    client.attached_script_ids.add(1)
    client.thread_ids_by_script[1] = {2}
    client.send_lua = lambda *args: sent.append(args)

    client.add_breakpoint(1, 2, "Data/Scripts/Foo.lua", 33, "x > 0")

    assert sent == [
        (
            LuaMessageId.ADD_BREAKPOINT,
            1,
            2,
            "Data/Scripts/Foo.lua",
            33,
            "x > 0",
        )
    ]


def test_client_remove_breakpoint_sends_documented_fields():
    sent = []
    client = LuaDebuggerClient()
    client.known_script_ids.add(1)
    client.thread_ids_by_script[1] = {2}
    client.send_lua = lambda *args: sent.append(args)

    client.remove_breakpoint(1, 2, "Data/Scripts/Foo.lua", 33)

    assert sent == [
        (
            LuaMessageId.REMOVE_BREAKPOINT,
            1,
            2,
            "Data/Scripts/Foo.lua",
            33,
            "",
        )
    ]


def test_client_rejects_stale_script_breakpoint_before_sending():
    sent = []
    client = LuaDebuggerClient()
    client.send_lua = lambda *args: sent.append(args)

    with pytest.raises(InvalidDebuggerState, match="latest game script list"):
        client.add_breakpoint(99, -1, "Gone.lua", 1)

    assert sent == []


def test_client_rejects_unknown_breakpoint_thread_and_unattached_script():
    client = LuaDebuggerClient()
    client.known_script_ids.add(1)
    client.thread_ids_by_script[1] = {2}
    client.send_lua = lambda *_args: None

    with pytest.raises(InvalidDebuggerState, match="thread 3"):
        client.add_breakpoint(1, 3, "Foo.lua", 1)
    with pytest.raises(InvalidDebuggerState, match="must be attached"):
        client.add_breakpoint(1, 2, "Foo.lua", 1)
    with pytest.raises(InvalidDebuggerState, match="thread 3"):
        client.remove_breakpoint(1, 3, "Foo.lua", 1)


def test_global_breakpoint_encodes_negative_sentinels_as_uint32():
    reader = encode_lua_message(
        LuaMessageId.ADD_BREAKPOINT,
        -1,
        -1,
        "Data/Scripts/Foo.lua",
        33,
        "",
    ).reader()

    assert reader.read_bits(4) == 0xD
    assert reader.read_u32() == LuaMessageId.ADD_BREAKPOINT
    assert reader.read_u32() == 0xFFFFFFFF
    assert reader.read_u32() == 0xFFFFFFFF


def test_other_negative_debugger_fields_are_rejected():
    with pytest.raises(ValueError, match="32-bit"):
        encode_lua_message(LuaMessageId.ADD_BREAKPOINT, -2)
