from eaw_lua_debugger.cli import app as cli
from eaw_lua_debugger.cli import commands
from eaw_lua_debugger.debugger.types import TableMember


class FakeClient:
    def __init__(self, *args, **kwargs):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        pass

    def connect(self):
        return "StarWarsI:test"

    def dump_table(self, script_id, context_or_request_id, table_name, path):
        self.args = (script_id, context_or_request_id, table_name, path)
        return [TableMember(1, "k", 2, "v")]


def test_table_cli_prints_members(monkeypatch, capsys):
    monkeypatch.setattr(commands, "LuaDebuggerClient", FakeClient)

    assert cli.main(["table", "9", "77", "Root", "--path", "1", "2"]) == 0

    output = capsys.readouterr().out
    assert "k\t1\tv\t2" in output
