"""Qt GUI for the Empire at War Lua debugger."""

from __future__ import annotations

import argparse
import re
import sys

from .client import CONTROL_MESSAGES, LuaDebuggerClient, ScriptInfo
from .gui_sources import SourceFile, format_source_lines, load_script_source, source_roots
from .gui_state import BreakpointSpec, DebuggerState

try:
    from pygments import lex
    from pygments.lexers import LuaLexer
    from pygments.token import Comment, Keyword, Literal, Name, Number, String
    from PySide6.QtCore import QMetaObject, QObject, Qt, QThread, QTimer, Signal, Slot
    from PySide6.QtGui import (
        QAction,
        QColor,
        QFont,
        QIcon,
        QSyntaxHighlighter,
        QTextCharFormat,
        QTextCursor,
    )
    from PySide6.QtWidgets import (
        QApplication,
        QFormLayout,
        QHBoxLayout,
        QLineEdit,
        QListWidget,
        QMainWindow,
        QMessageBox,
        QPlainTextEdit,
        QPushButton,
        QSpinBox,
        QSplitter,
        QStatusBar,
        QTableWidget,
        QTableWidgetItem,
        QTabWidget,
        QToolBar,
        QTreeWidget,
        QTreeWidgetItem,
        QVBoxLayout,
        QWidget,
    )
except ImportError as exc:  # pragma: no cover
    raise SystemExit(
        "PySide6 and Pygments are required for the GUI. "
        "Run: uv run --extra gui eaw-lua-debugger-gui"
    ) from exc


class LuaHighlighter(QSyntaxHighlighter):
    def __init__(self, document) -> None:
        super().__init__(document)
        self.lexer = LuaLexer()
        self.formats = {
            Comment: self._format("#008000"),
            Keyword: self._format("#0000aa", bold=True),
            Name.Function: self._format("#aa0000", bold=True),
            Number: self._format("#008080"),
            String: self._format("#aa0000", bold=True),
            Literal.String: self._format("#aa0000", bold=True),
        }

    def highlightBlock(self, text: str) -> None:
        start = _source_prefix_length(text)
        offset = start
        for token_type, value in lex(text[start:], self.lexer):
            form = self._token_format(token_type)
            if form is not None:
                self.setFormat(offset, len(value), form)
            offset += len(value)

    def _token_format(self, token_type):
        for parent, form in self.formats.items():
            if token_type in parent:
                return form
        return None

    @staticmethod
    def _format(color: str, *, bold: bool = False) -> QTextCharFormat:
        form = QTextCharFormat()
        form.setForeground(QColor(color))
        if bold:
            form.setFontWeight(QFont.Weight.Bold)
        return form


def _source_prefix_length(line: str) -> int:
    match = re.match(r"^\s*\d+\s[ \u25cf]\s", line)
    return 0 if match is None else match.end()


class DebuggerWorker(QObject):
    connected = Signal(str)
    disconnected = Signal()
    error = Signal(str)
    scripts_loaded = Signal(object)
    threads_loaded = Signal(int, object)
    children_loaded = Signal(int, object)
    message_received = Signal(object)
    variable_loaded = Signal(object)
    table_loaded = Signal(str, object)
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
            self.table_loaded.emit(name, self.client.dump_table(script_id, context_id, name, path))
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


class SourceEditor(QPlainTextEdit):
    breakpoint_toggled = Signal(int)

    def __init__(self, source: SourceFile) -> None:
        super().__init__()
        self.source = source
        self.breakpoint_lines: set[int] = set()
        self.setReadOnly(True)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.setFont(QFont("Consolas", 10))
        self.highlighter = LuaHighlighter(self.document())
        self.render()

    def render(self) -> None:
        cursor = self.textCursor()
        line = cursor.blockNumber()
        self.setPlainText(format_source_lines(self.source.text, self.breakpoint_lines))
        cursor = QTextCursor(self.document().findBlockByNumber(max(0, line)))
        self.setTextCursor(cursor)

    def set_breakpoints(self, lines: set[int]) -> None:
        self.breakpoint_lines = lines
        self.render()

    def mouseDoubleClickEvent(self, event) -> None:
        cursor = self.cursorForPosition(event.position().toPoint())
        self.breakpoint_toggled.emit(cursor.blockNumber() + 1)
        super().mouseDoubleClickEvent(event)


class MainWindow(QMainWindow):
    connect_requested = Signal(dict)
    disconnect_requested = Signal()
    service_requested = Signal()
    refresh_requested = Signal()
    control_requested = Signal(str)
    variable_requested = Signal(int, str)
    table_requested = Signal(int, int, str, object)
    execute_requested = Signal(int, str)
    add_breakpoint_requested = Signal(object)
    remove_breakpoint_requested = Signal(object)

    def __init__(self, args: argparse.Namespace) -> None:
        super().__init__()
        self.args = args
        self.state = DebuggerState()
        self.source_roots = source_roots(getattr(args, "source_root", []))
        self.source_editors: dict[int, SourceEditor] = {}
        self.setWindowTitle("LuaDebuggerNET")
        self.resize(1074, 847)
        self._build_worker()
        self._build_actions()
        self._build_layout()
        self.statusBar().showMessage("Not Connected")
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.service_requested.emit)
        self.timer.start(80)

    def _build_worker(self) -> None:
        self.thread = QThread(self)
        self.worker = DebuggerWorker()
        self.worker.moveToThread(self.thread)
        self.connect_requested.connect(self.worker.connect_game)
        self.disconnect_requested.connect(self.worker.disconnect_game)
        self.service_requested.connect(self.worker.service_once)
        self.refresh_requested.connect(self.worker.refresh_scripts)
        self.control_requested.connect(self.worker.control)
        self.variable_requested.connect(self.worker.dump_variable)
        self.table_requested.connect(self.worker.dump_table)
        self.execute_requested.connect(self.worker.execute_text)
        self.add_breakpoint_requested.connect(self.worker.add_breakpoint)
        self.remove_breakpoint_requested.connect(self.worker.remove_breakpoint)
        self.worker.connected.connect(self._connected)
        self.worker.disconnected.connect(lambda: self.statusBar().showMessage("Not Connected"))
        self.worker.error.connect(self._error)
        self.worker.scripts_loaded.connect(self._scripts_loaded)
        self.worker.threads_loaded.connect(self._threads_loaded)
        self.worker.children_loaded.connect(self._children_loaded)
        self.worker.message_received.connect(self._message_received)
        self.worker.variable_loaded.connect(self._variable_loaded)
        self.worker.table_loaded.connect(self._table_loaded)
        self.worker.execute_finished.connect(self._execute_finished)
        self.thread.start()

    def _build_actions(self) -> None:
        file_menu = self.menuBar().addMenu("&File")
        edit_menu = self.menuBar().addMenu("&Edit")
        debug_menu = self.menuBar().addMenu("&Debug")
        breakpoints_menu = self.menuBar().addMenu("&Breakpoints")
        self.menuBar().addMenu("&Settings")
        self.menuBar().addMenu("&Help")
        toolbar = QToolBar()
        self.addToolBar(toolbar)
        for text, slot, menu in [
            ("Connect", self._connect, file_menu),
            ("Disconnect", self.disconnect_requested.emit, file_menu),
            ("Refresh", self.refresh_requested.emit, file_menu),
        ]:
            action = QAction(text, self)
            action.triggered.connect(slot)
            menu.addAction(action)
            toolbar.addAction(action)
        toolbar.addSeparator()
        for command in CONTROL_MESSAGES:
            action = QAction(command.replace("-", " ").title(), self)
            action.triggered.connect(
                lambda _checked=False, name=command: self.control_requested.emit(name)
            )
            debug_menu.addAction(action)
            toolbar.addAction(action)
        edit_menu.addAction(QAction("Copy", self))
        breakpoints_menu.addAction(QAction("Add Breakpoint", self, triggered=self._add_breakpoint))

    def _build_layout(self) -> None:
        split = QSplitter(Qt.Orientation.Vertical)
        top = QSplitter(Qt.Orientation.Horizontal)
        self.source_tabs = QTabWidget()
        top.addWidget(self.source_tabs)
        top.addWidget(self._right_tabs())
        top.setStretchFactor(0, 5)
        top.setStretchFactor(1, 1)
        split.addWidget(top)
        split.addWidget(self._bottom_tabs())
        split.setStretchFactor(0, 4)
        split.setStretchFactor(1, 1)
        self.setCentralWidget(split)
        self.setStatusBar(QStatusBar())

    def _right_tabs(self) -> QTabWidget:
        tabs = QTabWidget()
        self.files = QTreeWidget()
        self.files.setHeaderLabels(["ID", "File"])
        self.files.itemSelectionChanged.connect(self._file_selected)
        self.callstack = QListWidget()
        self.threads = QTreeWidget()
        self.threads.setHeaderLabels(["ID", "Thread"])
        self.threads.itemSelectionChanged.connect(self._thread_selected)
        tabs.addTab(self.files, "Files")
        tabs.addTab(self.callstack, "Call Stack")
        tabs.addTab(self.threads, "Threads")
        return tabs

    def _bottom_tabs(self) -> QTabWidget:
        tabs = QTabWidget()
        self.output = QPlainTextEdit(readOnly=True)
        self.variables = QTreeWidget()
        self.variables.setHeaderLabels(["Name", "Type", "Value"])
        self.console_output = QPlainTextEdit(readOnly=True)
        self.console_input = QLineEdit()
        console = QWidget()
        console_layout = QVBoxLayout(console)
        console_layout.addWidget(self.console_output)
        row = QHBoxLayout()
        row.addWidget(self.console_input)
        row.addWidget(QPushButton("Execute", clicked=self._execute_text))
        console_layout.addLayout(row)
        self.breakpoints = QTableWidget(0, 5)
        self.breakpoints.setHorizontalHeaderLabels(
            ["Script", "Thread", "Source", "Line", "Condition"]
        )
        self.parse_errors = QListWidget()
        self.find_text = QLineEdit()
        self.find_results = QListWidget()
        find = QWidget()
        find_layout = QVBoxLayout(find)
        find_layout.addWidget(self.find_text)
        find_layout.addWidget(self.find_results)
        self.find_text.textChanged.connect(self._find_files)
        tabs.addTab(self.output, "Debug Output")
        tabs.addTab(self._variables_tab(), "Variables")
        tabs.addTab(console, "Lua Console")
        tabs.addTab(self._breakpoints_tab(), "Breakpoints")
        tabs.addTab(self.parse_errors, "Parse Errors")
        tabs.addTab(find, "Find In Files")
        return tabs

    def _variables_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        form = QFormLayout()
        self.var_script = QSpinBox(maximum=0x7FFFFFFF)
        self.var_name = QLineEdit("_G")
        self.table_context = QSpinBox(maximum=0x7FFFFFFF)
        self.table_name = QLineEdit("_G")
        self.table_path = QLineEdit()
        form.addRow("Script", self.var_script)
        form.addRow("Variable", self.var_name)
        form.addRow("Table Context", self.table_context)
        form.addRow("Table", self.table_name)
        form.addRow("Path", self.table_path)
        buttons = QHBoxLayout()
        buttons.addWidget(QPushButton("Dump Variable", clicked=self._dump_variable))
        buttons.addWidget(QPushButton("Dump Table", clicked=self._dump_table))
        layout.addLayout(form)
        layout.addLayout(buttons)
        layout.addWidget(self.variables)
        return widget

    def _breakpoints_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        form = QFormLayout()
        self.bp_script = QSpinBox(maximum=0x7FFFFFFF)
        self.bp_thread = QSpinBox(maximum=0x7FFFFFFF)
        self.bp_source = QLineEdit()
        self.bp_line = QSpinBox(maximum=1_000_000)
        self.bp_condition = QLineEdit()
        form.addRow("Script", self.bp_script)
        form.addRow("Thread", self.bp_thread)
        form.addRow("Source", self.bp_source)
        form.addRow("Line", self.bp_line)
        form.addRow("Condition", self.bp_condition)
        row = QHBoxLayout()
        row.addWidget(QPushButton("Add", clicked=self._add_breakpoint))
        row.addWidget(QPushButton("Remove", clicked=self._remove_breakpoint))
        layout.addLayout(form)
        layout.addLayout(row)
        layout.addWidget(self.breakpoints)
        return widget

    def _connect(self) -> None:
        self.statusBar().showMessage("Connecting...")
        self.connect_requested.emit(
            {
                "host": self.args.host,
                "port": self.args.port,
                "local_port": self.args.local_port,
                "client_name": self.args.client_name,
                "timeout": self.args.timeout,
            }
        )

    def _connected(self, server_name: str) -> None:
        self.state.server_name = server_name
        self.statusBar().showMessage(f"Connected to {server_name}")

    def _scripts_loaded(self, scripts: object) -> None:
        self.state.set_scripts(list(scripts))
        self.files.clear()
        for script in sorted(self.state.scripts.values(), key=lambda item: item.full_path_name):
            self.files.addTopLevelItem(
                QTreeWidgetItem([str(script.script_id), script.full_path_name])
            )
        self._find_files(self.find_text.text())

    def _threads_loaded(self, script_id: int, threads: object) -> None:
        self.state.set_threads(script_id, list(threads))
        self._render_threads(script_id)

    def _children_loaded(self, script_id: int, children: object) -> None:
        self.state.set_child_scripts(script_id, list(children))

    def _message_received(self, message: object) -> None:
        self.state.apply_message(message)
        if self.state.output:
            self.output.appendPlainText(self.state.output[-1])
        if self.state.parse_errors:
            self.parse_errors.clear()
            self.parse_errors.addItems(self.state.parse_errors[-500:])
        self.callstack.clear()
        self.callstack.addItems(self.state.callstack)
        if self.state.current_script_id is not None:
            self._render_threads(self.state.current_script_id)

    def _variable_loaded(self, value: object) -> None:
        self.state.set_variable(value)
        self._render_variables()

    def _table_loaded(self, name: str, members: object) -> None:
        self.state.set_table_members(name, list(members))
        self._render_variables()

    def _execute_finished(self, result: str) -> None:
        self.state.console_results.append(result)
        self.console_output.appendPlainText(result.rstrip())

    def _file_selected(self) -> None:
        selected = self.files.selectedItems()
        if not selected:
            return
        script_id = int(selected[0].text(0))
        self.state.current_script_id = script_id
        self.var_script.setValue(script_id)
        self.bp_script.setValue(script_id)
        self._open_source(self.state.scripts[script_id])

    def _thread_selected(self) -> None:
        selected = self.threads.selectedItems()
        if selected:
            thread_id = int(selected[0].text(0))
            self.state.current_thread_id = thread_id
            self.bp_thread.setValue(thread_id)

    def _dump_variable(self) -> None:
        self.variable_requested.emit(self.var_script.value(), self.var_name.text())

    def _dump_table(self) -> None:
        path = [int(part) for part in self.table_path.text().split() if part]
        self.table_requested.emit(
            self.var_script.value(),
            self.table_context.value(),
            self.table_name.text(),
            path,
        )

    def _execute_text(self) -> None:
        self.execute_requested.emit(self.var_script.value(), self.console_input.text())
        self.console_input.clear()

    def _add_breakpoint(self) -> None:
        spec = self._breakpoint_spec()
        self.state.add_breakpoint(spec)
        self.add_breakpoint_requested.emit(spec)
        self._render_breakpoints()
        self._render_source_breakpoints(spec.script_id)
        self.output.appendPlainText(f"\u25cf {spec.source_name} - Line: {spec.line_number}")

    def _remove_breakpoint(self) -> None:
        spec = self._breakpoint_spec()
        self.state.remove_breakpoint(spec)
        self.remove_breakpoint_requested.emit(spec)
        self._render_breakpoints()
        self._render_source_breakpoints(spec.script_id)

    def _breakpoint_spec(self) -> BreakpointSpec:
        script_id = self.bp_script.value()
        source_name = self.bp_source.text()
        if not source_name and script_id in self.state.scripts:
            source_name = self.state.scripts[script_id].full_path_name
        return BreakpointSpec(
            script_id,
            self.bp_thread.value(),
            source_name,
            self.bp_line.value(),
            self.bp_condition.text(),
        )

    def _open_source(self, script: ScriptInfo) -> None:
        editor = self.source_editors.get(script.script_id)
        if editor is None:
            editor = SourceEditor(load_script_source(script, self.source_roots))
            editor.breakpoint_toggled.connect(
                lambda line, script_id=script.script_id: self._toggle_source_breakpoint(
                    script_id,
                    line,
                )
            )
            self.source_editors[script.script_id] = editor
            title = script.full_path_name.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
            self.source_tabs.addTab(editor, title)
        self._render_source_breakpoints(script.script_id)
        self.source_tabs.setCurrentWidget(editor)
        self.bp_source.setText(script.full_path_name)

    def _toggle_source_breakpoint(self, script_id: int, line_number: int) -> None:
        if script_id not in self.state.scripts:
            return
        self.bp_script.setValue(script_id)
        self.bp_line.setValue(line_number)
        self.bp_source.setText(self.state.scripts[script_id].full_path_name)
        spec = self._breakpoint_spec()
        if any(existing.same_location(spec) for existing in self.state.breakpoints):
            self._remove_breakpoint()
        else:
            self._add_breakpoint()

    def _render_source_breakpoints(self, script_id: int) -> None:
        editor = self.source_editors.get(script_id)
        if editor is None:
            return
        editor.set_breakpoints(
            {
                breakpoint.line_number
                for breakpoint in self.state.breakpoints
                if breakpoint.script_id == script_id
            }
        )

    def _render_threads(self, script_id: int) -> None:
        self.threads.clear()
        for thread in self.state.threads.get(script_id, []):
            self.threads.addTopLevelItem(
                QTreeWidgetItem([str(thread.thread_index), thread.thread_name])
            )

    def _render_variables(self) -> None:
        self.variables.clear()
        for value in self.state.variables.values():
            self.variables.addTopLevelItem(
                QTreeWidgetItem([value.variable_name, str(value.value_type), value.value_text])
            )
        for table_name, members in self.state.tables.items():
            parent = QTreeWidgetItem([table_name, "table", f"{len(members)} members"])
            for member in members:
                parent.addChild(
                    QTreeWidgetItem([member.key_text, str(member.value_type), member.value_text])
                )
            self.variables.addTopLevelItem(parent)
        self.variables.expandAll()

    def _render_breakpoints(self) -> None:
        self.breakpoints.setRowCount(len(self.state.breakpoints))
        for row, spec in enumerate(self.state.breakpoints):
            values = [
                spec.script_id,
                spec.thread_id,
                spec.source_name,
                spec.line_number,
                spec.condition,
            ]
            for col, value in enumerate(values):
                self.breakpoints.setItem(row, col, QTableWidgetItem(str(value)))

    def _find_files(self, text: str) -> None:
        self.find_results.clear()
        needle = text.lower()
        if not needle:
            return
        for script in self.state.scripts.values():
            if needle in script.full_path_name.lower():
                self.find_results.addItem(f"{script.script_id}\t{script.full_path_name}")

    def _error(self, message: str) -> None:
        self.statusBar().showMessage(f"Error: {message}")
        QMessageBox.warning(self, "LuaDebuggerNET", message)

    def closeEvent(self, event) -> None:
        self.timer.stop()
        QMetaObject.invokeMethod(
            self.worker,
            "disconnect_game",
            Qt.ConnectionType.BlockingQueuedConnection,
        )
        self.thread.quit()
        self.thread.wait(2000)
        super().closeEvent(event)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="eaw-lua-debugger-gui")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=1234)
    parser.add_argument("--local-port", type=int, default=0)
    parser.add_argument("--client-name", default=None)
    parser.add_argument("--timeout", type=float, default=5.0)
    parser.add_argument(
        "--source-root",
        action="append",
        default=[],
        help="local root to search for game-reported Lua source paths",
    )
    args = parser.parse_args(argv)
    app = QApplication(sys.argv[:1])
    app.setWindowIcon(QIcon())
    window = MainWindow(args)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
