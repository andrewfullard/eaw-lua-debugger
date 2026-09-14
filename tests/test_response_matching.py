from eaw_lua_debugger.debugger.client import LuaDebuggerClient
from eaw_lua_debugger.debugger.types import VariableValue
from eaw_lua_debugger.protocol.lua_messages import LuaMessage, LuaMessageId


def test_dump_variable_skips_mismatched_variable_response():
    client = LuaDebuggerClient()
    client.known_script_ids.add(2)
    client.send_lua = lambda *args: None
    client.messages.extend(
        [
            LuaMessage(
                LuaMessageId.VARIABLE_DUMP,
                {"script_id": 1, "variable_name": "Other", "value_type": 1, "value_text": "bad"},
                raw_payload=None,
            ),
            LuaMessage(
                LuaMessageId.VARIABLE_DUMP,
                {"script_id": 2, "variable_name": "Target", "value_type": 3, "value_text": "ok"},
                raw_payload=None,
            ),
        ]
    )

    assert client.dump_variable(2, "Target") == VariableValue("Target", 3, "ok")
    assert client.messages[0].fields["variable_name"] == "Other"


def test_thread_and_attach_responses_match_requested_script():
    client = LuaDebuggerClient()
    client.known_script_ids.add(2)
    client.send_lua = lambda *args: None
    client.messages.extend(
        [
            LuaMessage(LuaMessageId.THREAD_LIST, {"script_id": 1, "threads": []}, raw_payload=None),
            LuaMessage(
                LuaMessageId.THREAD_LIST,
                {"script_id": 2, "threads": [{"thread_index": 4, "thread_name": "main"}]},
                raw_payload=None,
            ),
            LuaMessage(
                LuaMessageId.CHILD_SCRIPT_LIST,
                {"parent_script_id": 1, "child_script_names": ["wrong"]},
                raw_payload=None,
            ),
            LuaMessage(
                LuaMessageId.CHILD_SCRIPT_LIST,
                {"parent_script_id": 2, "child_script_names": ["right"]},
                raw_payload=None,
            ),
        ]
    )

    assert client.request_threads(2)[0].thread_index == 4
    assert client.attach_script(2) == ["right"]


def test_service_available_emits_async_message_queued_during_a_request():
    class EmptySocket:
        def gettimeout(self):
            return 0.1

        def settimeout(self, _timeout):
            pass

        def recvfrom(self, _size):
            raise TimeoutError

    message = LuaMessage(LuaMessageId.HEARTBEAT, {}, raw_payload=None)
    client = LuaDebuggerClient()
    client.socket = EmptySocket()
    client.messages.append(message)

    assert client.service_available() == [message]
    assert not client.messages


def test_script_refresh_replaces_inventory_and_drops_stale_context():
    client = LuaDebuggerClient()
    client.known_script_ids.update({7, 8})
    client.attached_script_ids.update({7, 8})
    client.context_script_id = 8
    client.send_lua = lambda *args: None
    client.wait_for = lambda *_args, **_kwargs: LuaMessage(
        LuaMessageId.SCRIPT_LIST,
        {
            "scripts": [
                {"script_id": 7, "full_path_name": "Data/Scripts/StillHere.lua"}
            ]
        },
        raw_payload=None,
    )

    client.request_scripts()

    assert client.known_script_ids == {7}
    assert client.attached_script_ids == {7}
    assert client.context_script_id is None
