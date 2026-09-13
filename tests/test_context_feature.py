from eaw_lua_debugger.client import LuaDebuggerClient
from eaw_lua_debugger.lua_messages import LuaMessageId


def test_client_context_commands_send_documented_ids_and_fields():
    sent = []
    client = LuaDebuggerClient()
    client.send_lua = lambda *args: sent.append(args)

    client.select_script(10)
    client.select_thread(20)
    client.set_callstack_depth(10, 3)

    assert sent == [
        (LuaMessageId.SELECT_SCRIPT, 10),
        (LuaMessageId.SELECT_THREAD, 20),
        (LuaMessageId.SET_CALLSTACK_DEPTH, 10, 3),
    ]
