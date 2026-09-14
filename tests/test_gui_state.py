from eaw_lua_debugger.debugger.types import ScriptInfo, TableMember, ThreadInfo, VariableValue
from eaw_lua_debugger.gui.state import BreakpointSpec, DebuggerState
from eaw_lua_debugger.protocol.lua_messages import LuaMessage, LuaMessageId


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
    assert state.callstacks[7] == ["Foo.lua:10", "Bar.lua:20"]
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


def test_breakpoint_removal_mirrors_native_wildcard_scope():
    state = DebuggerState()
    state.breakpoints = [
        BreakpointSpec(-1, -1, "Foo.lua", 10),
        BreakpointSpec(7, -1, "Foo.lua", 10),
        BreakpointSpec(7, 3, "Foo.lua", 10),
        BreakpointSpec(8, 4, "Foo.lua", 11),
    ]

    state.remove_breakpoint(BreakpointSpec(7, -1, "Foo.lua", 10))

    assert state.breakpoints == [BreakpointSpec(8, 4, "Foo.lua", 11)]


def test_removed_script_clears_every_runtime_reference_to_its_id():
    state = DebuggerState()
    state.set_scripts([ScriptInfo(7, "Foo.lua")])
    state.set_threads(7, [ThreadInfo(0, "main")])
    state.set_child_scripts(7, ["Child.lua"])
    state.set_script_variables(7, [])
    state.callstacks[7] = ["Foo.lua:1"]
    state.callstack = state.callstacks[7]
    state.current_script_id = 7
    state.current_thread_id = 0
    state.add_breakpoint(BreakpointSpec(7, -1, "Foo.lua", 1))

    state.apply_message(
        LuaMessage(LuaMessageId.SCRIPT_REMOVED, {"script_id": 7}, raw_payload=None)
    )

    assert state.current_script_id is None
    assert state.current_thread_id is None
    assert state.callstack == []
    assert state.scripts == {}
    assert state.threads == {}
    assert state.child_scripts == {}
    assert state.callstacks == {}
    assert state.script_variables == {}
    assert state.breakpoints == [BreakpointSpec(7, -1, "Foo.lua", 1)]
