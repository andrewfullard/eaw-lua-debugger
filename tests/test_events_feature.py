from eaw_lua_debugger.cli import app as cli
from eaw_lua_debugger.cli import commands
from eaw_lua_debugger.debugger.events import describe_message
from eaw_lua_debugger.protocol.lua_messages import LuaMessage, LuaMessageId


def test_describe_output_message():
    message = LuaMessage(
        LuaMessageId.OUTPUT,
        {"output_type": 2, "message": "hello"},
        raw_payload=None,
    )

    assert describe_message(message) == "OUTPUT[2] hello"


def test_describe_suspended_message_includes_context():
    message = LuaMessage(
        LuaMessageId.SCRIPT_SUSPENDED,
        {
            "script_id": 7,
            "current_thread_id": 3,
            "full_path_name": "Data/Scripts/Foo.lua",
            "callstack": ["a", "b"],
            "threads": [{"thread_index": 3, "thread_name": "main"}],
        },
        raw_payload=None,
    )

    assert describe_message(message) == (
        "SUSPENDED script=7 thread=3 path=Data/Scripts/Foo.lua "
        "callstack=2 threads=1"
    )


def test_describe_script_lifecycle_messages():
    assert (
        describe_message(
            LuaMessage(
                LuaMessageId.SCRIPT_ADDED,
                {"script_id": 4, "full_path_name": "Foo.lua"},
                raw_payload=None,
            )
        )
        == "SCRIPT_ADDED script=4 path=Foo.lua"
    )
    assert (
        describe_message(
            LuaMessage(LuaMessageId.SCRIPT_REMOVED, {"script_id": 4}, raw_payload=None)
        )
        == "SCRIPT_REMOVED script=4"
    )


class FakeClient:
    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        pass

    def connect(self):
        return "StarWarsI:test"


def test_session_cli_can_show_serviced_messages(monkeypatch, capsys):
    def fake_session(_client, *, script_id, duration, on_message, collect_messages):
        assert script_id is None
        assert duration == 0.25
        assert collect_messages is False
        on_message(
            LuaMessage(
                LuaMessageId.OUTPUT,
                {"output_type": 1, "message": "ready"},
                raw_payload=None,
            )
        )
        return {
            "scripts": [],
            "child_script_names": [],
            "threads": [],
            "message_count": 1,
            "messages": [],
        }

    monkeypatch.setattr(commands, "LuaDebuggerClient", FakeClient)
    monkeypatch.setattr(commands, "run_diagnostic_session", fake_session)

    assert cli.main(["session", "--duration", "0.25", "--show-messages"]) == 0

    output = capsys.readouterr().out
    assert "messages: 1" in output
    assert "OUTPUT[1] ready" in output
