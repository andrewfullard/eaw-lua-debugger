"""Qt worker that owns the blocking debugger backend client."""

from __future__ import annotations

from ..debugger.client import LuaDebuggerClient
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
    variable_loaded = Signal(object)
    table_loaded = Signal(int, int, str, object)
    execute_finished = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.client: LuaDebuggerClient | None = None

    @Slot(dict)
    def connect_game(self, settings: dict[str, object]) -> None:
        self.disconnect_game()
        try:
            self.client = LuaDebuggerClient(**settings)
            server_name = self.client.connect()
            self.connected.emit(server_name)
            self.scripts_loaded.emit(self.client.request_scripts())
        except Exception as exc:  # noqa: BLE001
            self.error.emit(str(exc))

    @Slot()
    def disconnect_game(self) -> None:
        if self.client is None:
            return
        self.client.close()
        self.client = None
        self.disconnected.emit()

    @Slot()
    def service_once(self) -> None:
        if self.client is None:
            return
        try:
            for message in self.client.service_once():
                self.message_received.emit(message)
        except Exception as exc:  # noqa: BLE001
            self.error.emit(str(exc))

    @Slot()
    def refresh_scripts(self) -> None:
        if self.client is None:
            return
        try:
            self.scripts_loaded.emit(self.client.request_scripts())
        except Exception as exc:  # noqa: BLE001
            self.error.emit(str(exc))

    @Slot(int)
    def load_script(self, script_id: int) -> None:
        if self.client is None:
            return
        try:
            self.threads_loaded.emit(script_id, self.client.request_threads(script_id))
        except Exception as exc:  # noqa: BLE001
            self.error.emit(str(exc))

    @Slot(str)
    def control(self, command: str) -> None:
        if self.client is None:
            return
        try:
            self.client.send_control(command)
            self.client.flush()
        except Exception as exc:  # noqa: BLE001
            self.error.emit(str(exc))

    @Slot(int)
    def select_thread(self, thread_id: int) -> None:
        if self.client is None:
            return
        try:
            self.client.select_thread(thread_id)
            self.client.flush()
        except Exception as exc:  # noqa: BLE001
            self.error.emit(str(exc))

    @Slot(int, str)
    def dump_variable(self, script_id: int, name: str) -> None:
        if self.client is None:
            return
        try:
            self.variable_loaded.emit(self.client.dump_variable(script_id, name))
        except Exception as exc:  # noqa: BLE001
            self.error.emit(str(exc))

    @Slot(int, int, str, object)
    def dump_table(self, script_id: int, context_id: int, name: str, path: list[int]) -> None:
        if self.client is None:
            return
        try:
            self.table_loaded.emit(
                script_id,
                context_id,
                name,
                self.client.dump_table(script_id, context_id, name, path),
            )
        except Exception as exc:  # noqa: BLE001
            self.error.emit(str(exc))

    @Slot(int, str)
    def execute_text(self, script_id: int, text: str) -> None:
        if self.client is None:
            return
        try:
            self.execute_finished.emit(self.client.execute_text(script_id, text))
        except Exception as exc:  # noqa: BLE001
            self.error.emit(str(exc))

    @Slot(object)
    def add_breakpoint(self, spec: BreakpointSpec) -> None:
        if self.client is None:
            return
        try:
            self.client.add_breakpoint(
                spec.script_id,
                spec.thread_id,
                spec.source_name,
                spec.line_number,
                spec.condition,
            )
            self.client.flush()
        except Exception as exc:  # noqa: BLE001
            self.error.emit(str(exc))

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
            )
            self.client.flush()
        except Exception as exc:  # noqa: BLE001
            self.error.emit(str(exc))
