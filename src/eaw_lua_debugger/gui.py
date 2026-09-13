"""Qt GUI for the Empire at War Lua debugger."""

from __future__ import annotations

import argparse
import sys

from .client import CONTROL_MESSAGES, LuaDebuggerClient, ScriptInfo
from .gui_source_view import SmartOpenDialog, SourceEditor
from .gui_sources import find_lua_files, load_script_source, source_roots
from .gui_state import BreakpointSpec, DebuggerState

try:
    from PySide6.QtCore import QMetaObject, QObject, Qt, QThread, QTimer, Signal, Slot
    from PySide6.QtGui import QAction, QIcon, QTextCursor
    from PySide6.QtWidgets import (
        QApplication,
        QDialog,
        QFileDialog,
        QFormLayout,
        QHBoxLayout,
        QInputDialog,
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
        "PySide6 is required for the GUI. Run: uv run --extra gui eaw-lua-debugger-gui"
    ) from exc


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
        self._next_local_script_id = -1
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
        self._menu_action(file_menu, "Connect", self._connect, toolbar=toolbar)
        self._menu_action(file_menu, "Disconnect", self.disconnect_requested.emit, toolbar=toolbar)
        file_menu.addSeparator()
        self._menu_action(file_menu, "Open...", self._open_file)
        self._menu_action(file_menu, "Smart open...", self._smart_open, "Ctrl+O")
        self._menu_action(file_menu, "Close", self._close_source_tab, "Ctrl+F4")
        self._menu_action(file_menu, "Close All", self._close_all_source_tabs)
        self._menu_action(file_menu, "Save", self._save_source, "Ctrl+S")
        self._menu_action(file_menu, "Save a Copy...", self._save_source_copy)
        self._menu_action(file_menu, "Save All", self._save_all_sources)
        file_menu.addSeparator()
        self._menu_action(file_menu, "Refresh", self.refresh_requested.emit, toolbar=toolbar)
        self._menu_action(file_menu, "Exit", self.close)
        toolbar.addSeparator()
        for command in CONTROL_MESSAGES:
            action = QAction(command.replace("-", " ").title(), self)
            action.triggered.connect(
                lambda _checked=False, name=command: self.control_requested.emit(name)
            )
            debug_menu.addAction(action)
            toolbar.addAction(action)
        self._menu_action(edit_menu, "Cut", lambda: self._focused_edit_call("cut"), "Ctrl+X")
        self._menu_action(edit_menu, "Copy", lambda: self._focused_edit_call("copy"), "Ctrl+C")
        self._menu_action(edit_menu, "Paste", lambda: self._focused_edit_call("paste"), "Ctrl+V")
        edit_menu.addSeparator()
        self._menu_action(edit_menu, "Undo", lambda: self._focused_edit_call("undo"), "Ctrl+Z")
        self._menu_action(edit_menu, "Redo", lambda: self._focused_edit_call("redo"), "Ctrl+Y")
        edit_menu.addSeparator()
        self._menu_action(edit_menu, "Find", self._focus_find, "Ctrl+F")
        self._menu_action(edit_menu, "Find Next", self._find_next, "F3")
        self._menu_action(edit_menu, "Find Prev", self._find_prev, "Shift+F3")
        self._menu_action(edit_menu, "Replace", self._replace_text, "Ctrl+R")
        self._menu_action(edit_menu, "Go to line", self._go_to_line, "Ctrl+G")
        self._menu_action(edit_menu, "Find In Files", self._focus_find, "Ctrl+Shift+F")
        edit_menu.addSeparator()
        self._menu_action(edit_menu, "Parse", self._parse_current_source, "F7")
        self._menu_action(
            breakpoints_menu,
            "Toggle Breakpoint",
            self._toggle_current_line_breakpoint,
            "Shift+F9",
        )
        self._menu_action(
            breakpoints_menu,
            "Toggle Global Breakpoint",
            self._toggle_global_breakpoint,
            "F9",
        )
        breakpoints_menu.addSeparator()
        self._menu_action(breakpoints_menu, "Delete All Breakpoints", self._delete_all_breakpoints)

    def _menu_action(
        self,
        menu,
        text: str,
        slot,
        shortcut: str | None = None,
        *,
        toolbar: QToolBar | None = None,
    ) -> QAction:
        action = QAction(text, self)
        if shortcut is not None:
            action.setShortcut(shortcut)
        action.triggered.connect(slot)
        menu.addAction(action)
        if toolbar is not None:
            toolbar.addAction(action)
        return action

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

    def _open_file(self) -> None:
        path, _filter = QFileDialog.getOpenFileName(
            self,
            "Open Lua File",
            str(self.source_roots[0]) if self.source_roots else "",
            "Lua files (*.lua);;All files (*)",
        )
        if path:
            self._open_local_path(path)

    def _smart_open(self) -> None:
        dialog = SmartOpenDialog(find_lua_files(self.source_roots), self)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.selected_path:
            self._open_local_path(dialog.selected_path)

    def _open_local_path(self, path: str) -> None:
        script = ScriptInfo(self._next_local_script_id, path)
        self._next_local_script_id -= 1
        self.state.scripts[script.script_id] = script
        self._open_source(script)

    def _current_editor(self) -> SourceEditor | None:
        widget = self.source_tabs.currentWidget()
        return widget if isinstance(widget, SourceEditor) else None

    def _close_source_tab(self) -> None:
        index = self.source_tabs.currentIndex()
        if index < 0:
            return
        widget = self.source_tabs.widget(index)
        self.source_tabs.removeTab(index)
        for script_id, editor in list(self.source_editors.items()):
            if editor is widget:
                self.source_editors.pop(script_id)

    def _close_all_source_tabs(self) -> None:
        self.source_tabs.clear()
        self.source_editors.clear()

    def _save_source(self) -> None:
        editor = self._current_editor()
        if editor is None:
            return
        if editor.source.path is None:
            self._save_source_copy()
            return
        editor.source.path.write_text(editor.source_text(), encoding="utf-8")
        self.statusBar().showMessage(f"Saved {editor.source.path}")

    def _save_source_copy(self) -> None:
        editor = self._current_editor()
        if editor is None:
            return
        path, _filter = QFileDialog.getSaveFileName(
            self,
            "Save Lua File",
            str(editor.source.path or editor.source.script.full_path_name),
            "Lua files (*.lua);;All files (*)",
        )
        if path:
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(editor.source_text())

    def _save_all_sources(self) -> None:
        for editor in self.source_editors.values():
            if editor.source.path is not None:
                editor.source.path.write_text(editor.source_text(), encoding="utf-8")
        self.statusBar().showMessage("Saved all open source files")

    def _focused_edit_call(self, method_name: str) -> None:
        method = getattr(QApplication.focusWidget(), method_name, None)
        if method is not None:
            method()

    def _focus_find(self) -> None:
        self.find_text.setFocus()

    def _find_next(self) -> None:
        editor = self._current_editor()
        if editor is not None and self.find_text.text():
            editor.find(self.find_text.text())

    def _find_prev(self) -> None:
        editor = self._current_editor()
        if editor is not None and self.find_text.text():
            editor.find(self.find_text.text(), QPlainTextEdit.FindFlag.FindBackward)

    def _replace_text(self) -> None:
        self.statusBar().showMessage("Replace is available in editable source tabs")

    def _go_to_line(self) -> None:
        editor = self._current_editor()
        if editor is None:
            return
        line, ok = QInputDialog.getInt(self, "Go to line", "Line", editor.source_line(), 1)
        if ok:
            cursor = QTextCursor(editor.document().findBlockByNumber(line - 1))
            editor.setTextCursor(cursor)
            editor.centerCursor()

    def _parse_current_source(self) -> None:
        editor = self._current_editor()
        if editor is not None:
            self.statusBar().showMessage(f"Parsed {editor.source.script.full_path_name}")

    def _toggle_current_line_breakpoint(self) -> None:
        editor = self._current_editor()
        if editor is not None:
            self._toggle_source_breakpoint(editor.source.script.script_id, editor.source_line())

    def _toggle_global_breakpoint(self) -> None:
        self.bp_thread.setValue(0)
        self._toggle_current_line_breakpoint()

    def _delete_all_breakpoints(self) -> None:
        for spec in list(self.state.breakpoints):
            self.state.remove_breakpoint(spec)
            self.remove_breakpoint_requested.emit(spec)
            self._render_source_breakpoints(spec.script_id)
        self._render_breakpoints()

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
