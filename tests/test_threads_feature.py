from eaw_lua_debugger.debugger.client import LuaDebuggerClient
from eaw_lua_debugger.debugger.types import ThreadInfo
from eaw_lua_debugger.protocol.bitstream import BitWriter
from eaw_lua_debugger.protocol.lua_messages import LuaMessage, LuaMessageId, parse_lua_message


def test_parse_thread_list_response():
    writer = BitWriter()
    writer.write_bits(0xD, 4)
    writer.write_u32(LuaMessageId.THREAD_LIST)
    writer.write_u32(42)
    writer.write_u32(2)
    writer.write_u32(0)
    writer.write_string("main")
    writer.write_u32(7)
    writer.write_string("worker")

    message = parse_lua_message(writer.buffer())

    assert message.fields == {
        "script_id": 42,
        "active_thread_count": 2,
        "threads": [
            {"thread_index": 0, "thread_name": "main"},
            {"thread_index": 7, "thread_name": "worker"},
        ],
    }


def test_client_request_threads_sends_request_and_returns_threads():
    sent = []
    message = LuaMessage(
        message_id=LuaMessageId.THREAD_LIST,
        fields={
            "script_id": 42,
            "active_thread_count": 1,
            "threads": [{"thread_index": 3, "thread_name": "main"}],
        },
        raw_payload=BitWriter().buffer(),
    )
    client = LuaDebuggerClient()
    client.send_lua = lambda *args: sent.append(args)
    client.wait_for = lambda message_id, **_: message

    assert client.request_threads(42) == [ThreadInfo(thread_index=3, thread_name="main")]
    assert sent == [(LuaMessageId.REQUEST_THREAD_LIST, 42)]
