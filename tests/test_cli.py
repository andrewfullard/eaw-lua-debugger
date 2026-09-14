import pytest

from eaw_lua_debugger.cli.app import main


def test_verbose_does_not_change_hello_bytes_output(capsys):
    assert main(["hello-bytes", "EAWLuaDebugger:20588"]) == 0
    normal = capsys.readouterr()

    assert main(["-v", "hello-bytes", "EAWLuaDebugger:20588"]) == 0
    verbose = capsys.readouterr()

    assert verbose.out == normal.out
    assert verbose.err == ""


@pytest.mark.parametrize(
    "args",
    [
        ["control", "break"],
        ["context", "script", "7"],
        ["breakpoint", "add", "7", "-1", "Foo.lua", "1"],
    ],
)
def test_one_shot_cli_refuses_stateful_debugger_commands(args, capsys):
    assert main(args) == 1
    assert "use the GUI" in capsys.readouterr().err
