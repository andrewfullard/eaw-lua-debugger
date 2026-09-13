from eaw_lua_debugger.debugger.client import LuaDebuggerClient
from eaw_lua_debugger.protocol.bitstream import BitWriter
from eaw_lua_debugger.protocol.lua_messages import LuaMessage, LuaMessageId, parse_lua_message


def test_parse_child_script_list_response():
    writer = BitWriter()
    writer.write_bits(0xD, 4)
    writer.write_u32(LuaMessageId.CHILD_SCRIPT_LIST)
    writer.write_u32(7)
    writer.write_u32(2)
    writer.write_string("child_a")
    writer.write_string("child_b")

    message = parse_lua_message(writer.buffer())

    assert message.fields == {
        "parent_script_id": 7,
        "child_count": 2,
        "child_script_names": ["child_a", "child_b"],
    }


def test_client_attach_script_sends_attach_and_returns_child_names():
    sent = []
    message = LuaMessage(
        message_id=LuaMessageId.CHILD_SCRIPT_LIST,
        fields={
            "parent_script_id": 7,
            "child_count": 1,
            "child_script_names": ["child"],
        },
        raw_payload=BitWriter().buffer(),
    )
    client = LuaDebuggerClient()
    client.send_lua = lambda *args: sent.append(args)
    client.wait_for = lambda message_id, **_: message

    assert client.attach_script(7) == ["child"]
    assert sent == [(LuaMessageId.ATTACH_SCRIPT, 7)]
