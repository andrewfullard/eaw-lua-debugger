from eaw_lua_debugger.debugger.client import LuaDebuggerClient
from eaw_lua_debugger.debugger.types import VariableValue
from eaw_lua_debugger.protocol.bitstream import BitWriter
from eaw_lua_debugger.protocol.lua_messages import LuaMessage, LuaMessageId, parse_lua_message


def test_parse_variable_dump_response():
    writer = BitWriter()
    writer.write_bits(0xD, 4)
    writer.write_u32(LuaMessageId.VARIABLE_DUMP)
    writer.write_u32(9)
    writer.write_string("Foo")
    writer.write_u32(3)
    writer.write_string("Bar")

    message = parse_lua_message(writer.buffer())

    assert message.fields == {
        "script_id": 9,
        "variable_name": "Foo",
        "value_type": 3,
        "value_text": "Bar",
    }


def test_client_dump_variable_sends_request_and_returns_value():
    sent = []
    message = LuaMessage(
        message_id=LuaMessageId.VARIABLE_DUMP,
        fields={
            "script_id": 9,
            "variable_name": "Foo",
            "value_type": 3,
            "value_text": "Bar",
        },
        raw_payload=BitWriter().buffer(),
    )
    client = LuaDebuggerClient()
    client.known_script_ids.add(9)
    client.send_lua = lambda *args: sent.append(args)
    client.wait_for = lambda message_id, **_: message

    assert client.dump_variable(9, "Foo") == VariableValue("Foo", 3, "Bar")
    assert sent == [(LuaMessageId.DUMP_VARIABLE, 9, "Foo")]
