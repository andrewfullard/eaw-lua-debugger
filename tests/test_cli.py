from eaw_lua_debugger.cli import main


def test_verbose_does_not_change_hello_bytes_output(capsys):
    assert main(["hello-bytes", "LuaDebuggerNET:20588"]) == 0
    normal = capsys.readouterr()

    assert main(["-v", "hello-bytes", "LuaDebuggerNET:20588"]) == 0
    verbose = capsys.readouterr()

    assert verbose.out == normal.out
    assert verbose.err == ""
