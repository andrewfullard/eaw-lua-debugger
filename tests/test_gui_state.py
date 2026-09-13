from eaw_lua_debugger.client import ScriptInfo, TableMember, ThreadInfo, VariableValue
from eaw_lua_debugger.gui_state import BreakpointSpec, DebuggerState
from eaw_lua_debugger.lua_messages import LuaMessage, LuaMessageId


def test_debugger_state_tracks_scripts_threads_and_suspended_callstack():
    state = DebuggerState()

    state.set_scripts([ScriptInfo(7, "Data/Scripts/Foo.lua")])
    state.set_threads(7, [ThreadInfo(3, "main")])
    state.apply_message(
        LuaMessage(
            LuaMessageId.SCRIPT_SUSPENDED,
            {
                "script_id": 7,
                "current_thread_id": 3,
                "full_path_name": "Data/Scripts/Foo.lua",
                "callstack": ["Foo.lua:10", "Bar.lua:20"],
                "threads": [{"thread_index": 3, "thread_name": "main"}],
            },
            raw_payload=None,
        )
    )

    assert state.scripts[7].full_path_name == "Data/Scripts/Foo.lua"
    assert state.current_script_id == 7
    assert state.current_thread_id == 3
    assert state.callstack == ["Foo.lua:10", "Bar.lua:20"]
    assert state.threads[7][0].thread_name == "main"


def test_debugger_state_tracks_output_variables_tables_and_breakpoints():
    state = DebuggerState()

    state.apply_message(
        LuaMessage(
            LuaMessageId.OUTPUT,
            {"output_type": 2, "message": "hello"},
            raw_payload=None,
        )
    )
    state.set_variable(VariableValue("PlayerObject", 4, "table: 1234"))
    state.set_table_members("PlayerObject", [TableMember(1, "Name", 2, "Empire")])
    state.add_breakpoint(BreakpointSpec(7, 3, "Foo.lua", 10, "x > 1"))
    state.remove_breakpoint(BreakpointSpec(7, 3, "Foo.lua", 10, ""))

    assert state.output[-1] == "OUTPUT[2] hello"
    assert state.variables["PlayerObject"].value_text == "table: 1234"
    assert state.tables["PlayerObject"][0].value_text == "Empire"
    assert state.breakpoints == []
