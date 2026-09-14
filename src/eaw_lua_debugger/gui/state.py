"""Qt-independent debugger state for GUI views."""

from __future__ import annotations

from dataclasses import dataclass, field

from ..debugger.events import describe_message
from ..debugger.types import ScriptInfo, TableMember, ThreadInfo, VariableValue
from ..protocol.lua_messages import LuaMessage, LuaMessageId


@dataclass(frozen=True)
class BreakpointSpec:
    script_id: int
    thread_id: int
    source_name: str
    line_number: int
    condition: str = ""

    def same_location(self, other: BreakpointSpec) -> bool:
        return (
            self.script_id == other.script_id
            and self.thread_id == other.thread_id
            and self.source_name == other.source_name
            and self.line_number == other.line_number
        )

    def matches_native_remove(self, request: BreakpointSpec) -> bool:
        return (
            self.source_name == request.source_name
            and self.line_number == request.line_number
            and (
                self.script_id == -1
                or request.script_id == -1
                or self.script_id == request.script_id
            )
            and (
                self.thread_id == -1
                or request.thread_id == -1
                or self.thread_id == request.thread_id
            )
        )


@dataclass
class DebuggerState:
    server_name: str = ""
    scripts: dict[int, ScriptInfo] = field(default_factory=dict)
    threads: dict[int, list[ThreadInfo]] = field(default_factory=dict)
    child_scripts: dict[int, list[str]] = field(default_factory=dict)
    callstack: list[str] = field(default_factory=list)
    callstacks: dict[int, list[str]] = field(default_factory=dict)
    output: list[str] = field(default_factory=list)
    parse_errors: list[str] = field(default_factory=list)
    variables: dict[str, VariableValue] = field(default_factory=dict)
    tables: dict[str, list[TableMember]] = field(default_factory=dict)
    script_variables: dict[int, list[TableMember]] = field(default_factory=dict)
    breakpoints: list[BreakpointSpec] = field(default_factory=list)
    console_results: list[str] = field(default_factory=list)
    current_script_id: int | None = None
    current_thread_id: int | None = None
    suspended_script_id: int | None = None

    def set_scripts(self, scripts: list[ScriptInfo]) -> None:
        self.scripts = {script.script_id: script for script in scripts}

    def set_threads(self, script_id: int, threads: list[ThreadInfo]) -> None:
        self.threads[script_id] = threads

    def set_child_scripts(self, script_id: int, child_scripts: list[str]) -> None:
        self.child_scripts[script_id] = child_scripts

    def set_variable(self, value: VariableValue) -> None:
        self.variables[value.variable_name] = value

    def set_table_members(self, table_name: str, members: list[TableMember]) -> None:
        self.tables[table_name] = members

    def set_script_variables(self, script_id: int, members: list[TableMember]) -> None:
        self.script_variables[script_id] = members

    def add_breakpoint(self, breakpoint: BreakpointSpec) -> None:
        self.breakpoints = [
            existing
            for existing in self.breakpoints
            if not existing.same_location(breakpoint)
        ]
        self.breakpoints.append(breakpoint)

    def remove_breakpoint(self, breakpoint: BreakpointSpec) -> None:
        self.breakpoints = [
            existing
            for existing in self.breakpoints
            if not existing.matches_native_remove(breakpoint)
        ]

    def apply_message(self, message: LuaMessage) -> None:
        fields = message.fields
        match message.message_id:
            case LuaMessageId.OUTPUT:
                text = describe_message(message)
                self.output.append(text)
                if "parse" in fields["message"].lower() and "error" in fields["message"].lower():
                    self.parse_errors.append(text)
            case LuaMessageId.SCRIPT_ADDED:
                script = ScriptInfo(fields["script_id"], fields["full_path_name"])
                self.scripts[script.script_id] = script
            case LuaMessageId.SCRIPT_REMOVED:
                script_id = fields["script_id"]
                self.scripts.pop(script_id, None)
                self.threads.pop(script_id, None)
                self.child_scripts.pop(script_id, None)
                self.callstacks.pop(script_id, None)
                self.script_variables.pop(script_id, None)
                if self.current_script_id == script_id:
                    self.current_script_id = None
                    self.current_thread_id = None
                    self.callstack = []
                if self.suspended_script_id == script_id:
                    self.suspended_script_id = None
            case LuaMessageId.SCRIPT_SUSPENDED:
                script = ScriptInfo(fields["script_id"], fields["full_path_name"])
                self.scripts[script.script_id] = script
                self.current_script_id = fields["script_id"]
                self.current_thread_id = fields["current_thread_id"]
                self.suspended_script_id = fields["script_id"]
                self.callstack = list(fields["callstack"])
                self.callstacks[fields["script_id"]] = self.callstack
                self.threads[fields["script_id"]] = [
                    ThreadInfo(item["thread_index"], item["thread_name"])
                    for item in fields["threads"]
                ]
            case LuaMessageId.VARIABLE_DUMP:
                self.set_variable(
                    VariableValue(
                        fields["variable_name"],
                        fields["value_type"],
                        fields["value_text"],
                    )
                )
            case LuaMessageId.TABLE_DUMP:
                self.set_table_members(
                    str(fields["response_or_request_id"]),
                    [
                        TableMember(
                            item["key_type"],
                            item["key_text"],
                            item["value_type"],
                            item["value_text"],
                        )
                        for item in fields["members"]
                    ],
                )
            case LuaMessageId.EXECUTE_TEXT_RESPONSE:
                self.console_results.append(fields["result_text"])
