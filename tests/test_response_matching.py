from eaw_lua_debugger.client import LuaDebuggerClient, VariableValue
from eaw_lua_debugger.lua_messages import LuaMessage, LuaMessageId


def test_dump_variable_skips_mismatched_variable_response():
    client = LuaDebuggerClient()
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
