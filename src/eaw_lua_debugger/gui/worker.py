"""Qt worker that owns the blocking debugger backend client."""

from __future__ import annotations

from ..core.exceptions import ConnectionLost
from ..debugger.client import LuaDebuggerClient
from ..protocol.lua_messages import LuaMessageId
from .state import BreakpointSpec

try:
    from PySide6.QtCore import QObject, Signal, Slot
except ImportError as exc:  # pragma: no cover
    raise SystemExit("PySide6 is required for the GUI. Run: uv sync") from exc


class DebuggerWorker(QObject):
    connected = Signal(str)
    disconnected = Signal()
    error = Signal(str)
    scripts_loaded = Signal(object)
    threads_loaded = Signal(int, object)
    children_loaded = Signal(int, object)
    message_received = Signal(object)
    variable_loaded = Signal(int, object)
    table_loaded = Signal(int, int, str, object)
    execute_finished = Signal(str)
    debug_state_changed = Signal(str)
    feedback = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.client: LuaDebuggerClient | None = None
        self.current_script_id: int | None = None

    @Slot(dict)
    def connect_game(self, settings: dict[str, object]) -> None:
        self.disconnect_game()
        try:
            self.client = LuaDebuggerClient(**settings)
            self.current_script_id = None
            server_name = self.client.connect()
            self.debug_state_changed.emit(self.client.run_state.value)
            self.connected.emit(server_name)
            self.scripts_loaded.emit(self.client.request_scripts())
        except Exception as exc:  # noqa: BLE001
            if self.client is not None:
                self.client.abort()
            self.client = None
            self.current_script_id = None
            self.debug_state_changed.emit("disconnected")
            self.disconnected.emit()
            self.error.emit(str(exc))

    @Slot()
    def disconnect_game(self) -> None:
        if self.client is None:
            return
        self.client.close()
        self.client = None
        self.current_script_id = None
        self.debug_state_changed.emit("disconnected")
        self.disconnected.emit()

    @Slot()
    def service_once(self) -> None:
        if self.client is None:
            return
        try:
            messages = self.client.service_available()
            for message in messages:
                if message.message_id == LuaMessageId.SCRIPT_SUSPENDED:
                    self.current_script_id = message.fields["script_id"]
                elif (
                    message.message_id == LuaMessageId.SCRIPT_REMOVED
                    and message.fields["script_id"] == self.current_script_id
                ):
                    self.current_script_id = None
                self.message_received.emit(message)
            if messages:
                self.debug_state_changed.emit(self.client.run_state.value)
        except ConnectionLost as exc:
            self.client.abort()
            self.client = None
            self.current_script_id = None
            self.debug_state_changed.emit("disconnected")
            self.disconnected.emit()
            self.error.emit(str(exc))
        except Exception as exc:  # noqa: BLE001
            self._report_error(exc)

    @Slot()
    def refresh_scripts(self) -> None:
        if self.client is None:
            return
        try:
            self.scripts_loaded.emit(self.client.request_scripts())
        except Exception as exc:  # noqa: BLE001
            self._report_error(exc)

    @Slot(int)
    def load_script(self, script_id: int) -> None:
        if self.client is None:
            return
        try:
            if script_id not in self.client.attached_script_ids:
                children = self.client.attach_script(script_id)
                self.children_loaded.emit(script_id, children)
            self.current_script_id = script_id
            self.threads_loaded.emit(script_id, self.client.request_threads(script_id))
        except Exception as exc:  # noqa: BLE001
            self._report_error(exc)

    @Slot(str)
    def control(self, command: str) -> None:
        if self.client is None:
            return
        try:
            if command == "break":
                if self.current_script_id is None:
                    raise ValueError("select an active script before requesting Break")
                self.client.break_script(self.current_script_id)
            else:
                self.client.send_control(command)
            self.client.flush()
            self.debug_state_changed.emit(self.client.run_state.value)
        except Exception as exc:  # noqa: BLE001
            self._report_error(exc)

    @Slot(int, int)
    def select_thread(self, script_id: int, thread_id: int) -> None:
        if self.client is None:
            return
        try:
            if script_id not in self.client.attached_script_ids:
                self.client.attach_script(script_id)
            if self.client.context_script_id != script_id:
                self.client.select_script(script_id)
            self.client.break_thread(thread_id)
            self.client.flush()
            self.debug_state_changed.emit(self.client.run_state.value)
        except Exception as exc:  # noqa: BLE001
            self._report_error(exc)

    @Slot(int, int)
    def select_callstack_frame(self, script_id: int, depth: int) -> None:
        if self.client is None:
            return
        try:
            self.client.set_callstack_depth(script_id, depth)
            self.client.flush()
            self.debug_state_changed.emit(self.client.run_state.value)
            self.feedback.emit(f"Selected call-stack frame {depth}")
        except Exception as exc:  # noqa: BLE001
            self._report_error(exc)

    @Slot(int, str)
    def dump_variable(self, script_id: int, name: str) -> None:
        if self.client is None:
            return
        try:
            self.variable_loaded.emit(script_id, self.client.dump_variable(script_id, name))
        except Exception as exc:  # noqa: BLE001
            self._report_error(exc)

    @Slot(int, int, str, object, bool)
    def dump_table(
        self,
        script_id: int,
        context_id: int,
        name: str,
        path: list[int],
        allow_unsafe: bool,
    ) -> None:
        if self.client is None:
            return
        try:
            self.table_loaded.emit(
                script_id,
                context_id,
                name,
                self.client.dump_table(
                    script_id,
                    context_id,
                    name,
                    path,
                    allow_unsafe=allow_unsafe,
                ),
            )
        except Exception as exc:  # noqa: BLE001
            self._report_error(exc)

    @Slot(int, str)
    def execute_text(self, script_id: int, text: str) -> None:
        if self.client is None:
            return
        try:
            self.execute_finished.emit(self.client.execute_text(script_id, text))
        except Exception as exc:  # noqa: BLE001
            self._report_error(exc)

    @Slot(object)
    def add_breakpoint(self, spec: BreakpointSpec) -> None:
        if self.client is None:
            return
        try:
            if (
                spec.script_id >= 0
                and spec.script_id not in self.client.attached_script_ids
            ):
                self.client.attach_script(spec.script_id)
            self.client.add_breakpoint(
                spec.script_id,
                spec.thread_id,
                spec.source_name,
                spec.line_number,
                spec.condition,
            )
            self.client.flush()
        except Exception as exc:  # noqa: BLE001
            self._report_error(exc)

    @Slot(object)
    def remove_breakpoint(self, spec: BreakpointSpec) -> None:
        if self.client is None:
            return
        try:
            self.client.remove_breakpoint(
                spec.script_id,
                spec.thread_id,
                spec.source_name,
                spec.line_number,
                spec.condition,
            )
            self.client.flush()
        except Exception as exc:  # noqa: BLE001
            self._report_error(exc)

    def _report_error(self, exc: Exception) -> None:
        if self.client is not None:
            self.debug_state_changed.emit(self.client.run_state.value)
        self.error.emit(str(exc))
