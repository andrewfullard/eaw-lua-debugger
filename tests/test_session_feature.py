from eaw_lua_debugger.lua_messages import LuaMessage, LuaMessageId
from eaw_lua_debugger.session import run_diagnostic_session


class FakeClient:
    def __init__(self):
        self.calls = []

    def request_scripts(self):
        self.calls.append(("scripts",))
        return ["script"]

    def attach_script(self, script_id):
        self.calls.append(("attach", script_id))
        return ["child"]

    def request_threads(self, script_id):
        self.calls.append(("threads", script_id))
        return ["thread"]

    def iter_messages(self, *, timeout):
        self.calls.append(("iter", timeout))
        yield LuaMessage(LuaMessageId.HEARTBEAT, {}, raw_payload=None)


def test_run_diagnostic_session_keeps_connection_serviced():
    client = FakeClient()

    result = run_diagnostic_session(client, script_id=7, duration=2.5)

    assert client.calls == [("scripts",), ("attach", 7), ("threads", 7), ("iter", 2.5)]
    assert result["scripts"] == ["script"]
    assert result["child_script_names"] == ["child"]
    assert result["threads"] == ["thread"]
    assert result["messages"][0].message_id == LuaMessageId.HEARTBEAT
