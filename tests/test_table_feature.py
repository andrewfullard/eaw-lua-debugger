from eaw_lua_debugger.debugger.client import LuaDebuggerClient
from eaw_lua_debugger.debugger.types import TableMember
from eaw_lua_debugger.protocol.bitstream import BitWriter
from eaw_lua_debugger.protocol.lua_messages import LuaMessage, LuaMessageId, parse_lua_message


def test_parse_table_dump_response():
    writer = BitWriter()
    writer.write_bits(0xD, 4)
    writer.write_u32(LuaMessageId.TABLE_DUMP)
    writer.write_u32(77)
    writer.write_u32(1)
    writer.write_u32(4)
    writer.write_string("key")
    writer.write_u32(5)
    writer.write_string("value")

    message = parse_lua_message(writer.buffer())

    assert message.fields == {
        "response_or_request_id": 77,
        "member_count": 1,
        "members": [
            {"key_type": 4, "key_text": "key", "value_type": 5, "value_text": "value"}
        ],
    }


def test_client_dump_table_sends_request_and_matches_context_or_request_id():
    sent = []
    client = LuaDebuggerClient()
    client.send_lua = lambda *args: sent.append(args)
    client.messages.extend(
        [
            LuaMessage(
                LuaMessageId.TABLE_DUMP,
                {
                    "response_or_request_id": 76,
                    "members": [],
                },
                raw_payload=None,
            ),
            LuaMessage(
                LuaMessageId.TABLE_DUMP,
                {
                    "response_or_request_id": 77,
                    "members": [
                        {
                            "key_type": 4,
                            "key_text": "key",
                            "value_type": 5,
                            "value_text": "value",
                        }
                    ],
                },
                raw_payload=None,
            ),
        ]
    )

    assert client.dump_table(9, 77, "Root", [1, 2]) == [
        TableMember(4, "key", 5, "value")
    ]
    assert sent == [(LuaMessageId.DUMP_TABLE, 9, 77, "Root", 2, [1, 2])]
