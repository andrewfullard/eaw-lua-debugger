from eaw_lua_debugger.debugger.client import LuaDebuggerClient
from eaw_lua_debugger.protocol.bitstream import BitWriter
from eaw_lua_debugger.protocol.lua_messages import LuaMessage, LuaMessageId, parse_lua_message


def test_parse_execute_text_response():
    writer = BitWriter()
    writer.write_bits(0xD, 4)
    writer.write_u32(LuaMessageId.EXECUTE_TEXT_RESPONSE)
    writer.write_u32(5)
    writer.write_string("result")

    message = parse_lua_message(writer.buffer())

    assert message.fields == {"script_id": 5, "result_text": "result"}


def test_client_execute_text_matches_script_response():
    sent = []
    client = LuaDebuggerClient()
    client.known_script_ids.add(5)
    client.send_lua = lambda *args: sent.append(args)
    client.messages.extend(
        [
            LuaMessage(
                LuaMessageId.EXECUTE_TEXT_RESPONSE,
                {"script_id": 4, "result_text": "wrong"},
                raw_payload=None,
            ),
            LuaMessage(
                LuaMessageId.EXECUTE_TEXT_RESPONSE,
                {"script_id": 5, "result_text": "right"},
                raw_payload=None,
            ),
        ]
    )

    assert client.execute_text(5, "return 1") == "right"
    assert sent == [(LuaMessageId.EXECUTE_TEXT, 5, "return 1")]
