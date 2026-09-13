from eaw_lua_debugger.debugger.client import LuaDebuggerClient
from eaw_lua_debugger.protocol.lua_messages import LuaMessageId


def test_client_add_breakpoint_sends_documented_fields():
    sent = []
    client = LuaDebuggerClient()
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
    client.send_lua = lambda *args: sent.append(args)

    client.remove_breakpoint(1, 2, "Data/Scripts/Foo.lua", 33)

    assert sent == [
        (
            LuaMessageId.REMOVE_BREAKPOINT,
            1,
            2,
            "Data/Scripts/Foo.lua",
            33,
        )
    ]
