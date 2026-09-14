"""Qt GUI for the Empire at War Lua debugger."""

from __future__ import annotations

import argparse
import re
from dataclasses import replace

from ..debugger.client import CONTROL_MESSAGES, DebuggerRunState
from ..debugger.types import ScriptInfo, VariableValue
from ..protocol.lua_messages import LuaMessageId
from .source_view import SmartOpenDialog, SourceEditor
from .sources import find_lua_files, load_script_source, source_roots
from .state import BreakpointSpec, DebuggerState
from .worker import DebuggerWorker

try:
    from PySide6.QtCore import QMetaObject, Qt, QThread, QTimer, Signal
    from PySide6.QtGui import QAction, QBrush, QColor, QTextCursor
    from PySide6.QtWidgets import (
        QAbstractItemView,
        QApplication,
        QDialog,
        QFileDialog,
        QFormLayout,
        QHBoxLayout,
        QInputDialog,
        QLineEdit,
        QMainWindow,
        QMessageBox,
        QPlainTextEdit,
        QPushButton,
        QSizePolicy,
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
        "PySide6 is required for the GUI. Run: uv sync"
    ) from exc


def _source_key(path: str) -> str:
    return path.replace("\\", "/").casefold()


def _callstack_location(frame: str) -> tuple[str, int] | None:
    match = re.match(r"^(.*?\.lua):(\d+)(?::|$)", frame, re.IGNORECASE)
    return (match.group(1).lstrip("@"), int(match.group(2))) if match else None


def _same_source(left: str, right: str) -> bool:
    left_key = _source_key(left)
    right_key = _source_key(right)
    return (
        left_key == right_key
        or left_key.endswith(f"/{right_key}")
        or right_key.endswith(f"/{left_key}")
    )


def _breakpoint_key(spec: BreakpointSpec) -> tuple[bool, int, str, int, str]:
    return (
        spec.script_id == -1,
        spec.thread_id,
        _source_key(spec.source_name),
        spec.line_number,
        spec.condition,
    )


class ScriptTreeItem(QTreeWidgetItem):
    def __lt__(self, other: QTreeWidgetItem) -> bool:
        tree = self.treeWidget()
        column = tree.sortColumn() if tree is not None else 0
        if column in {0, 2}:
            return int(self.text(column)) < int(other.text(column))
        return self.text(column).casefold() < other.text(column).casefold()


class MainWindow(QMainWindow):
    connect_requested = Signal(dict)
    disconnect_requested = Signal()
    service_requested = Signal()
    refresh_requested = Signal()
    poll_threads_requested = Signal(object)
    control_requested = Signal(str)
    break_thread_requested = Signal(int, int)
    callstack_requested = Signal(int, int)
    threads_requested = Signal(int)
    variable_requested = Signal(int, str)
    table_requested = Signal(int, int, str, object, bool)
    execute_requested = Signal(int, str)
    add_breakpoint_requested = Signal(object)
    remove_breakpoint_requested = Signal(object)

    def __init__(self, args: argparse.Namespace) -> None:
        super().__init__()
        self.args = args
        self.state = DebuggerState()
        self.source_roots = source_roots(getattr(args, "source_root", []))
        self.source_editors: dict[int, SourceEditor] = {}
        self.frame_source_editors: dict[tuple[int, str], SourceEditor] = {}
        self._file_items: dict[int, QTreeWidgetItem] = {}
        self._next_local_script_id = -2  # -1 is the native all-scripts breakpoint sentinel.
        self._next_table_request_id = 1
        self._pending_variable_requests: dict[int, int] = {}
        self.is_connected = False
        self.run_state: DebuggerRunState | None = None
        self._breakpoints_to_replay: set[tuple[bool, int, str, int, str]] = set()
        self._callstack_depths: dict[int, int] = {}
        self._thread_poll_pending = False
        self.find_text = ""
        self.setWindowTitle("EAWLuaDebugger")
        self.resize(1074, 847)
        self._build_worker()
        self._build_actions()
        self._build_layout()
        self._update_debug_actions()
        self.statusBar().showMessage("Not Connected")
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.service_requested.emit)
        self.timer.start(10)
        self.thread_poll_timer = QTimer(self)
        self.thread_poll_timer.setInterval(5000)
        self.thread_poll_timer.timeout.connect(self._poll_threads)
        self.thread_poll_timer.start()

    def _build_worker(self) -> None:
        self.thread = QThread(self)
        self.worker = DebuggerWorker()
        self.worker.moveToThread(self.thread)
        self.connect_requested.connect(self.worker.connect_game)
        self.disconnect_requested.connect(self.worker.disconnect_game)
        self.service_requested.connect(self.worker.service_once)
        self.refresh_requested.connect(self.worker.refresh_scripts)
        self.poll_threads_requested.connect(self.worker.poll_threads)
        self.control_requested.connect(self.worker.control)
        self.break_thread_requested.connect(self.worker.select_thread)
        self.callstack_requested.connect(self.worker.select_callstack_frame)
        self.threads_requested.connect(self.worker.load_script)
        self.variable_requested.connect(self.worker.dump_variable)
        self.table_requested.connect(self.worker.dump_table)
        self.execute_requested.connect(self.worker.execute_text)
        self.add_breakpoint_requested.connect(self.worker.add_breakpoint)
        self.remove_breakpoint_requested.connect(self.worker.remove_breakpoint)
        self.worker.connected.connect(self._connected)
        self.worker.disconnected.connect(self._disconnected)
        self.worker.error.connect(self._error)
        self.worker.scripts_loaded.connect(self._scripts_loaded)
        self.worker.threads_loaded.connect(self._threads_loaded)
        self.worker.children_loaded.connect(self._children_loaded)
        self.worker.message_received.connect(self._message_received)
        self.worker.variable_loaded.connect(self._variable_loaded)
        self.worker.table_loaded.connect(self._table_loaded)
        self.worker.execute_finished.connect(self._execute_finished)
        self.worker.debug_state_changed.connect(self._debug_state_changed)
        self.worker.feedback.connect(self._feedback)
        self.worker.callstack_frame_selected.connect(self._callstack_frame_selected)
        self.worker.thread_poll_finished.connect(self._thread_poll_finished)
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
        self.connect_action = self._menu_action(
            file_menu, "Connect", self._connect, toolbar=toolbar
        )
        self.disconnect_action = self._menu_action(
            file_menu, "Disconnect", self.disconnect_requested.emit, toolbar=toolbar
        )
        file_menu.addSeparator()
        self._menu_action(file_menu, "Open...", self._open_file)
        self._menu_action(file_menu, "Smart open...", self._smart_open, "Ctrl+O")
        self._menu_action(file_menu, "Close", self._close_source_tab, "Ctrl+F4")
        self._menu_action(file_menu, "Close All", self._close_all_source_tabs)
        self._menu_action(file_menu, "Save", self._save_source, "Ctrl+S")
        self._menu_action(file_menu, "Save a Copy...", self._save_source_copy)
        self._menu_action(file_menu, "Save All", self._save_all_sources)
        file_menu.addSeparator()
        self.refresh_action = self._menu_action(
            file_menu, "Refresh", self.refresh_requested.emit, toolbar=toolbar
        )
        self._menu_action(file_menu, "Exit", self.close)
        toolbar.addSeparator()
        self.control_actions: dict[str, QAction] = {}
        for command in CONTROL_MESSAGES:
            action = QAction(command.replace("-", " ").title(), self)
            action.triggered.connect(
                lambda _checked=False, name=command: self._request_control(name)
            )
            debug_menu.addAction(action)
            toolbar.addAction(action)
            self.control_actions[command] = action
        self.break_thread_action = self._menu_action(
            debug_menu, "Break Thread", self._break_selected_thread
        )
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
        self._update_debug_actions()

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
        self.main_splitter = QSplitter(Qt.Orientation.Vertical)
        self.top_splitter = QSplitter(Qt.Orientation.Horizontal)
        self.source_tabs = QTabWidget()
        self.source_tabs.setMinimumWidth(560)
        self.source_tabs.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )
        self.top_splitter.addWidget(self.source_tabs)
        self.top_splitter.addWidget(self._right_tabs())
        self.top_splitter.setStretchFactor(0, 8)
        self.top_splitter.setStretchFactor(1, 1)
        self.top_splitter.setSizes([820, 240])
        self.main_splitter.addWidget(self.top_splitter)
        self.main_splitter.addWidget(self._bottom_tabs())
        self.main_splitter.setStretchFactor(0, 4)
        self.main_splitter.setStretchFactor(1, 1)
        self.main_splitter.setSizes([610, 230])
        self.setCentralWidget(self.main_splitter)
        self.setStatusBar(QStatusBar())

    def _right_tabs(self) -> QTabWidget:
        tabs = QTabWidget()
        self.right_tabs = tabs
        tabs.setMinimumWidth(220)
        tabs.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )
        self.files = QTreeWidget()
        self.files.setHeaderLabels(["ID", "File", "Threads"])
        self.files.setSortingEnabled(True)
        self.files.sortItems(2, Qt.SortOrder.DescendingOrder)
        self.files.itemSelectionChanged.connect(self._file_selected)
        self.callstack = QTreeWidget()
        self.callstack.setHeaderLabels(["Depth", "Frame"])
        self.callstack.itemDoubleClicked.connect(self._callstack_activated)
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
        self.execute_button = QPushButton("Execute", clicked=self._execute_text)
        row.addWidget(self.execute_button)
        console_layout.addLayout(row)
        self.breakpoints = QTableWidget(0, 5)
        self.breakpoints.setHorizontalHeaderLabels(
            ["Script", "Thread", "Source", "Line", "Condition"]
        )
        self.breakpoints.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        tabs.addTab(self.output, "Debug Output")
        tabs.addTab(self._variables_tab(), "Variables")
        tabs.addTab(console, "Lua Console")
        tabs.addTab(self.breakpoints, "Breakpoints")
        return tabs

    def _variables_tab(self) -> QWidget:
        widget = QWidget()
        layout = QVBoxLayout(widget)
        self.var_script = QSpinBox(maximum=0x7FFFFFFF)
        self.var_name = QLineEdit("_G")
        self.table_name = QLineEdit("_G")
        self.table_path = QLineEdit()
        form = QFormLayout()
        form.addRow("Script", self.var_script)
        form.addRow("Variable", self.var_name)
        form.addRow("Table", self.table_name)
        form.addRow("Table path indexes", self.table_path)
        buttons = QHBoxLayout()
        self.read_variable_button = QPushButton("Read Variable", clicked=self._dump_variable)
        self.expand_table_button = QPushButton("Expand Table (unsafe)", clicked=self._dump_table)
        buttons.addWidget(self.read_variable_button)
        buttons.addWidget(self.expand_table_button)
        layout.addWidget(self.variables)
        layout.addLayout(form)
        layout.addLayout(buttons)
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
        self.is_connected = True
        self.run_state = DebuggerRunState.RUNNING
        self.state.server_name = server_name
        self.statusBar().showMessage(f"Connected to {server_name} — select a script")
        self._update_debug_actions()

    def _disconnected(self) -> None:
        local_scripts = {
            script_id: script
            for script_id, script in self.state.scripts.items()
            if script_id <= -2
        }
        saved_breakpoints = list(self.state.breakpoints)
        self._breakpoints_to_replay.update(
            _breakpoint_key(breakpoint)
            for breakpoint in saved_breakpoints
            if breakpoint.script_id >= -1
        )
        self.state = DebuggerState(
            scripts=local_scripts,
            breakpoints=saved_breakpoints,
        )
        self.is_connected = False
        self.run_state = None
        self._pending_variable_requests.clear()
        self._callstack_depths.clear()
        self._thread_poll_pending = False
        self._clear_active_source_line()
        for editor in self.frame_source_editors.values():
            self.source_tabs.removeTab(self.source_tabs.indexOf(editor))
        self.frame_source_editors.clear()
        self.files.clear()
        self._file_items.clear()
        self.threads.clear()
        self.callstack.clear()
        self.variables.clear()
        self._render_breakpoints()
        for script_id, editor in list(self.source_editors.items()):
            if script_id >= 0:
                self.source_tabs.removeTab(self.source_tabs.indexOf(editor))
                self.source_editors.pop(script_id)
        for script_id in self.source_editors:
            self._render_source_breakpoints(script_id)
        self.statusBar().showMessage("Not Connected")
        self._update_debug_actions()

    def _scripts_loaded(self, scripts: object) -> None:
        local_scripts = [
            script for script in self.state.scripts.values() if script.script_id <= -2
        ]
        game_scripts = [script for script in scripts if script.script_id >= 0]
        scripts_by_source: dict[str, list[ScriptInfo]] = {}
        for script in game_scripts:
            scripts_by_source.setdefault(_source_key(script.full_path_name), []).append(script)
        remapped = []
        for breakpoint in self.state.breakpoints:
            matches = scripts_by_source.get(_source_key(breakpoint.source_name), [])
            if breakpoint.script_id >= 0 and len(matches) == 1:
                breakpoint = replace(
                    breakpoint,
                    script_id=matches[0].script_id,
                    source_name=matches[0].full_path_name,
                )
            remapped.append(breakpoint)
        self.state.breakpoints = remapped
        self.state.set_scripts([*local_scripts, *game_scripts])
        live_ids = {script.script_id for script in game_scripts}
        for key, editor in list(self.frame_source_editors.items()):
            if key[0] not in live_ids:
                self.source_tabs.removeTab(self.source_tabs.indexOf(editor))
                self.frame_source_editors.pop(key)
        if (
            self.state.current_script_id is not None
            and self.state.current_script_id not in self.state.scripts
        ):
            self.state.current_script_id = None
            self.state.current_thread_id = None
            self.state.suspended_script_id = None
            self.state.callstack = []
            self._clear_inspection_results()
        self.files.clear()
        self._file_items.clear()
        for script in sorted(game_scripts, key=lambda item: item.full_path_name):
            item = ScriptTreeItem([str(script.script_id), script.full_path_name, "0"])
            self.files.addTopLevelItem(item)
            self._file_items[script.script_id] = item
            self._highlight_script_threads(script.script_id)
        self.files.resizeColumnToContents(0)
        self.files.resizeColumnToContents(2)
        if self._breakpoints_to_replay:
            replay = [
                breakpoint
                for breakpoint in self.state.breakpoints
                if _breakpoint_key(breakpoint) in self._breakpoints_to_replay
                and self._can_send_breakpoint(breakpoint)
            ]
            for breakpoint in replay:
                self.add_breakpoint_requested.emit(breakpoint)
                self._breakpoints_to_replay.discard(_breakpoint_key(breakpoint))
            if replay:
                self.statusBar().showMessage(f"Restoring {len(replay)} breakpoint(s)")
            if self._breakpoints_to_replay:
                self.statusBar().showMessage(
                    f"{len(self._breakpoints_to_replay)} breakpoint(s) waiting for a unique "
                    "matching script"
                )
        self._render_breakpoints()
        self._update_debug_actions()

    def _threads_loaded(self, script_id: int, threads: object) -> None:
        threads = list(threads)
        self.state.set_threads(script_id, threads)
        self._highlight_script_threads(script_id)
        if (
            script_id == self.state.current_script_id
            and self.state.current_thread_id
            not in {thread.thread_index for thread in threads}
        ):
            self.state.current_thread_id = None
        if script_id == self.state.current_script_id:
            self._render_threads(script_id)
        self._update_debug_actions()

    def _poll_threads(self) -> None:
        script_ids = [script_id for script_id in self.state.scripts if script_id >= 0]
        if self.is_connected and script_ids and not self._thread_poll_pending:
            self._thread_poll_pending = True
            self.poll_threads_requested.emit(script_ids)

    def _thread_poll_finished(self) -> None:
        self._thread_poll_pending = False

    def _highlight_script_threads(self, script_id: int) -> None:
        item = self._file_items.get(script_id)
        if item is None:
            return
        thread_count = len(self.state.threads.get(script_id, []))
        has_threads = thread_count > 0
        item.setText(2, str(thread_count))
        background = QBrush(QColor(46, 160, 67, 100)) if has_threads else QBrush()
        for column in range(item.columnCount()):
            font = item.font(column)
            font.setBold(has_threads)
            item.setFont(column, font)
            item.setBackground(column, background)
        item.setToolTip(
            1,
            f"{thread_count} thread(s) in latest poll"
            if has_threads
            else "No named threads in latest poll",
        )

    def _children_loaded(self, script_id: int, children: object) -> None:
        self.state.set_child_scripts(script_id, list(children))

    def _message_received(self, message: object) -> None:
        previous_script_id = self.state.current_script_id
        message_id = getattr(message, "message_id", None)
        script_was_suspended = message_id == LuaMessageId.SCRIPT_SUSPENDED
        selected_script_was_removed = (
            message_id == LuaMessageId.SCRIPT_REMOVED
            and message.fields["script_id"] == previous_script_id
        )
        deepest_frame = (
            len(message.fields["callstack"]) - 1 if script_was_suspended else None
        )
        if script_was_suspended or selected_script_was_removed:
            self._clear_inspection_results()
        if deepest_frame is not None and deepest_frame >= 0:
            self._callstack_depths[message.fields["script_id"]] = deepest_frame
        if message_id == LuaMessageId.SCRIPT_REMOVED:
            removed_id = message.fields["script_id"]
            self._callstack_depths.pop(removed_id, None)
            self._breakpoints_to_replay.update(
                _breakpoint_key(breakpoint)
                for breakpoint in self.state.breakpoints
                if breakpoint.script_id == removed_id
            )
        self.state.apply_message(message)
        if message_id in {LuaMessageId.SCRIPT_ADDED, LuaMessageId.SCRIPT_REMOVED}:
            self._scripts_loaded(list(self.state.scripts.values()))
            self._render_breakpoints()
            for script_id in self.source_editors:
                self._render_source_breakpoints(script_id)
        if message_id == LuaMessageId.OUTPUT:
            self.output.moveCursor(QTextCursor.MoveOperation.End)
            self.output.insertPlainText(message.fields["message"])
            self.output.ensureCursorVisible()
        if self.state.current_script_id is not None:
            self._render_threads(self.state.current_script_id)
            self._render_callstack(self.state.current_script_id)
            if script_was_suspended or self.state.current_script_id != previous_script_id:
                self._select_game_script(
                    self.state.current_script_id,
                    open_source=script_was_suspended,
                    request_threads=False,
                )
        if script_was_suspended:
            self.run_state = DebuggerRunState.SUSPENDED
            if deepest_frame is not None and deepest_frame >= 0:
                script_id = self.state.current_script_id
                self._show_callstack_source(script_id, deepest_frame)
                if script_id is not None and deepest_frame > 0:
                    self.callstack_requested.emit(script_id, deepest_frame)
                    self.statusBar().showMessage(
                        f"Selecting deepest call-stack frame {deepest_frame}..."
                    )
                else:
                    self.statusBar().showMessage(
                        "Suspended — inspect variables or continue/step"
                    )
            else:
                self.statusBar().showMessage("Suspended — no call-stack frames")
        self._update_debug_actions()
        if script_was_suspended and deepest_frame is not None and deepest_frame > 0:
            self.callstack.setEnabled(False)

    def _variable_loaded(self, script_id: int, value: VariableValue) -> None:
        if script_id != self.state.current_script_id:
            self.statusBar().showMessage(
                f"Ignored stale variable result from script {script_id}"
            )
            return
        self.state.set_variable(value)
        self._render_variables()
        self.statusBar().showMessage(f"Loaded variable {value.variable_name}")

    def _table_loaded(
        self,
        script_id: int,
        context_id: int,
        name: str,
        members: object,
    ) -> None:
        members = list(members)
        pending_script_id = self._pending_variable_requests.pop(context_id, None)
        if script_id != self.state.current_script_id:
            self.statusBar().showMessage(
                f"Ignored stale table result from script {script_id}"
            )
            return
        if pending_script_id == script_id and name == "_G":
            self.state.set_script_variables(script_id, members)
            self.statusBar().showMessage(f"Loaded variables for script {script_id}")
        else:
            self.state.set_table_members(name, members)
        self._render_variables()

    def _execute_finished(self, result: str) -> None:
        self.state.console_results.append(result)
        self.console_output.appendPlainText(result.rstrip())

    def _file_selected(self) -> None:
        selected = self.files.selectedItems()
        if not selected:
            return
        script_id = int(selected[0].text(0))
        if script_id != self.state.current_script_id:
            self.state.current_thread_id = None
            self._clear_inspection_results()
        self._select_game_script(script_id, open_source=True, request_threads=True)

    def _select_game_script(
        self,
        script_id: int,
        *,
        open_source: bool,
        request_threads: bool,
    ) -> None:
        if script_id not in self.state.scripts:
            return
        selected_source = _source_key(self.state.scripts[script_id].full_path_name)
        restored = []
        remapped = []
        for breakpoint in self.state.breakpoints:
            if (
                breakpoint.script_id >= 0
                and _breakpoint_key(breakpoint) in self._breakpoints_to_replay
                and _source_key(breakpoint.source_name) == selected_source
            ):
                old_key = _breakpoint_key(breakpoint)
                breakpoint = replace(
                    breakpoint,
                    script_id=script_id,
                    source_name=self.state.scripts[script_id].full_path_name,
                )
                self._breakpoints_to_replay.discard(old_key)
                restored.append(breakpoint)
            remapped.append(breakpoint)
        self.state.breakpoints = remapped
        for breakpoint in restored:
            self.add_breakpoint_requested.emit(breakpoint)
        self.state.current_script_id = script_id
        self.var_script.setValue(script_id)
        if open_source:
            self._open_source(self.state.scripts[script_id])
        self._render_threads(script_id)
        self._render_callstack(script_id)
        self._render_variables()
        if request_threads and script_id >= 0:
            self.threads_requested.emit(script_id)
        if restored:
            self.statusBar().showMessage(f"Restoring {len(restored)} breakpoint(s)")
            self._render_breakpoints()
        self._update_debug_actions()

    def _thread_selected(self) -> None:
        selected = self.threads.selectedItems()
        if selected:
            thread_id = int(selected[0].text(0))
            if thread_id != self.state.current_thread_id:
                self._clear_inspection_results()
            self.state.current_thread_id = thread_id
        self._update_debug_actions()

    def _break_selected_thread(self) -> None:
        script_id = self.state.current_script_id
        thread_id = self.state.current_thread_id
        if script_id is not None and thread_id is not None:
            self.break_thread_requested.emit(script_id, thread_id)
            self.break_thread_action.setEnabled(False)
            self.statusBar().showMessage("Sending thread break request...")

    def _request_control(self, command: str) -> None:
        self.control_requested.emit(command)
        self.control_actions[command].setEnabled(False)
        self.statusBar().showMessage(f"Sending {command.replace('-', ' ')} request...")

    def _callstack_activated(self, item: QTreeWidgetItem, _column: int) -> None:
        script_id = self.state.current_script_id
        if script_id is None or self.run_state != DebuggerRunState.SUSPENDED:
            return
        self._clear_inspection_results()
        self.callstack_requested.emit(script_id, int(item.text(0)))
        self.callstack.setEnabled(False)
        self.statusBar().showMessage(f"Selecting call-stack frame {item.text(0)}...")

    def _callstack_frame_selected(self, script_id: int, depth: int) -> None:
        self._callstack_depths[script_id] = depth
        if script_id == self.state.current_script_id:
            item = self.callstack.topLevelItem(depth)
            if item is not None:
                self.callstack.setCurrentItem(item)
            self._show_callstack_source(script_id, depth)

    def _show_callstack_source(self, script_id: int | None, depth: int) -> None:
        self._clear_active_source_line()
        if script_id is None:
            return
        callstack = self.state.callstacks.get(script_id, [])
        if not 0 <= depth < len(callstack):
            return
        location = _callstack_location(callstack[depth])
        if location is None:
            return
        source_name, line = location
        editor = self.source_editors.get(script_id)
        if editor is not None and _same_source(
            editor.source.script.full_path_name, source_name
        ):
            self._open_source(editor.source.script)
        else:
            editor = self._open_frame_source(script_id, source_name)
        if editor is not None:
            editor.set_active_line(line)

    def _clear_active_source_line(self) -> None:
        for editor in self._all_source_editors():
            editor.set_active_line(None)

    def _dump_variable(self) -> None:
        name = self.var_name.text()
        self.variable_requested.emit(self.var_script.value(), name)
        self.statusBar().showMessage(f"Reading variable {name}...")

    def _dump_table(self) -> None:
        choice = QMessageBox.warning(
            self,
            "Unsafe table expansion",
            "The game can assert or close if any displayed table key or value is too long. "
            "Only continue if you accept that risk. Never expand _G.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if choice != QMessageBox.StandardButton.Yes:
            return
        path = [int(part) for part in self.table_path.text().split() if part]
        context_id = self._next_table_request_id
        self._next_table_request_id += 1
        self.table_requested.emit(
            self.var_script.value(),
            context_id,
            self.table_name.text(),
            path,
            True,
        )

    def _execute_text(self) -> None:
        self.execute_requested.emit(self.var_script.value(), self.console_input.text())
        self.console_input.clear()

    def _add_breakpoint(self, spec: BreakpointSpec) -> None:
        self.state.add_breakpoint(spec)
        if self._can_send_breakpoint(spec):
            self.add_breakpoint_requested.emit(spec)
        elif spec.script_id >= -1:
            self._breakpoints_to_replay.add(_breakpoint_key(spec))
        self._render_breakpoints()
        self._render_source_breakpoints(spec.script_id)

    def _remove_breakpoint(self, spec: BreakpointSpec) -> None:
        self.state.remove_breakpoint(spec)
        live_keys = {_breakpoint_key(breakpoint) for breakpoint in self.state.breakpoints}
        self._breakpoints_to_replay.intersection_update(live_keys)
        if self._can_send_breakpoint(spec):
            self.remove_breakpoint_requested.emit(spec)
        self._render_breakpoints()
        self._render_source_breakpoints(spec.script_id)

    def _can_send_breakpoint(self, spec: BreakpointSpec) -> bool:
        if spec.script_id >= 0:
            script = self.state.scripts.get(spec.script_id)
            matches = [
                candidate
                for candidate in self.state.scripts.values()
                if candidate.script_id >= 0
                and _source_key(candidate.full_path_name) == _source_key(spec.source_name)
            ]
            return (
                script is not None
                and len(matches) == 1
                and matches[0].script_id == spec.script_id
            )
        return spec.script_id == -1 and spec.thread_id == -1 and any(
            _source_key(script.full_path_name) == _source_key(spec.source_name)
            for script in self.state.scripts.values()
            if script.script_id >= 0
        )

    def _debug_state_changed(self, state: str) -> None:
        previous_run_state = self.run_state
        if state == "disconnected":
            self.run_state = None
        else:
            self.run_state = DebuggerRunState(state)
            if (
                previous_run_state == DebuggerRunState.SUSPENDED
                and self.run_state != DebuggerRunState.SUSPENDED
            ):
                self._clear_inspection_results()
                self._clear_active_source_line()
            if self.run_state != DebuggerRunState.SUSPENDED:
                self.state.suspended_script_id = None
            messages = {
                DebuggerRunState.RUNNING: "Running — select an active script and press Break",
                DebuggerRunState.BREAK_PENDING: (
                    "Break requested — waiting for the script to reach a Lua line"
                ),
                DebuggerRunState.SUSPENDED: "Suspended — inspect variables or continue/step",
            }
            self.statusBar().showMessage(messages[self.run_state])
        self._update_debug_actions()

    def _feedback(self, message: str) -> None:
        if message.startswith("Selected call-stack frame"):
            self._clear_inspection_results()
        self.statusBar().showMessage(message)
        self._update_debug_actions()

    def _update_debug_actions(self) -> None:
        running = self.is_connected and self.run_state == DebuggerRunState.RUNNING
        suspended = self.is_connected and self.run_state == DebuggerRunState.SUSPENDED
        selected_script = self.state.current_script_id in self.state.scripts
        self.connect_action.setEnabled(not self.is_connected)
        self.disconnect_action.setEnabled(self.is_connected)
        self.refresh_action.setEnabled(self.is_connected)
        self.control_actions["break"].setEnabled(running and selected_script)
        for command in ("continue", "step-over", "step-into", "step-out"):
            self.control_actions[command].setEnabled(suspended)
        self.break_thread_action.setEnabled(
            self.is_connected
            and self.run_state
            in {
                DebuggerRunState.RUNNING,
                DebuggerRunState.BREAK_PENDING,
                DebuggerRunState.SUSPENDED,
            }
            and selected_script
            and self.state.current_thread_id is not None
            and (
                self.run_state != DebuggerRunState.SUSPENDED
                or self.state.current_script_id == self.state.suspended_script_id
            )
        )
        if hasattr(self, "callstack"):
            self.callstack.setEnabled(suspended)
        if hasattr(self, "read_variable_button"):
            can_inspect = self.is_connected and selected_script
            self.read_variable_button.setEnabled(can_inspect)
            self.expand_table_button.setEnabled(can_inspect)
            self.execute_button.setEnabled(can_inspect)

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
            filename = script.full_path_name.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
            title = f"[{script.script_id}] {filename}"
            self.source_tabs.addTab(editor, title)
        self._render_source_breakpoints(script.script_id)
        self.source_tabs.setCurrentWidget(editor)

    def _open_frame_source(self, script_id: int, source_name: str) -> SourceEditor | None:
        key = (script_id, _source_key(source_name))
        editor = self.frame_source_editors.get(key)
        if editor is None:
            source = load_script_source(ScriptInfo(script_id, source_name), self.source_roots)
            if not source.found:
                return None
            editor = SourceEditor(source)
            editor.breakpoint_toggled.connect(
                lambda line, context_id=script_id, name=source_name: (
                    self._toggle_source_breakpoint(context_id, line, name)
                )
            )
            self.frame_source_editors[key] = editor
            filename = source_name.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
            index = self.source_tabs.addTab(editor, f"[{script_id}] {filename}")
            self.source_tabs.setTabToolTip(index, source_name)
        self._render_source_breakpoints(script_id)
        self.source_tabs.setCurrentWidget(editor)
        return editor

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
        for key, editor in list(self.frame_source_editors.items()):
            if editor is widget:
                self.frame_source_editors.pop(key)

    def _close_all_source_tabs(self) -> None:
        self.source_tabs.clear()
        self.source_editors.clear()
        self.frame_source_editors.clear()

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
        for editor in self._all_source_editors():
            if editor.source.path is not None:
                editor.source.path.write_text(editor.source_text(), encoding="utf-8")
        self.statusBar().showMessage("Saved all open source files")

    def _focused_edit_call(self, method_name: str) -> None:
        method = getattr(QApplication.focusWidget(), method_name, None)
        if method is not None:
            method()

    def _focus_find(self) -> None:
        text, accepted = QInputDialog.getText(self, "Find", "Text", text=self.find_text)
        if accepted:
            self.find_text = text
            self._find_next()

    def _find_next(self) -> None:
        editor = self._current_editor()
        if editor is not None and self.find_text:
            editor.find(self.find_text)

    def _find_prev(self) -> None:
        editor = self._current_editor()
        if editor is not None and self.find_text:
            editor.find(self.find_text, QPlainTextEdit.FindFlag.FindBackward)

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
        editor = self._current_editor()
        if (
            editor is None
            or editor.source.script.script_id < 0
            or editor.source.script.script_id not in self.state.scripts
        ):
            self.statusBar().showMessage("A global breakpoint requires a game-reported source")
            return
        script_id = editor.source.script.script_id
        spec = BreakpointSpec(
            -1,
            -1,
            editor.source.script.full_path_name,
            editor.source_line(),
            "",
        )
        if any(existing.same_location(spec) for existing in self.state.breakpoints):
            self._remove_breakpoint(spec)
        else:
            self._add_breakpoint(spec)
        self._render_source_breakpoints(script_id)

    def _delete_all_breakpoints(self) -> None:
        for spec in list(self.state.breakpoints):
            if spec not in self.state.breakpoints:
                continue
            if self._can_send_breakpoint(spec):
                self.remove_breakpoint_requested.emit(spec)
            self.state.remove_breakpoint(spec)
        self._breakpoints_to_replay.clear()
        script_ids = set(self.source_editors)
        script_ids.update(key[0] for key in self.frame_source_editors)
        for script_id in script_ids:
            self._render_source_breakpoints(script_id)
        self._render_breakpoints()

    def _toggle_source_breakpoint(
        self,
        script_id: int,
        line_number: int,
        source_name: str | None = None,
    ) -> None:
        if script_id not in self.state.scripts:
            self.statusBar().showMessage("That script is no longer active in the game")
            return
        spec = BreakpointSpec(
            script_id,
            -1,
            source_name or self.state.scripts[script_id].full_path_name,
            line_number,
            "",
        )
        if any(existing.same_location(spec) for existing in self.state.breakpoints):
            self._remove_breakpoint(spec)
        else:
            self._add_breakpoint(spec)

    def _render_source_breakpoints(self, script_id: int) -> None:
        editors = [
            editor
            for editor in self._all_source_editors()
            if editor.source.script.script_id == script_id
        ]
        for editor in editors:
            source_name = editor.source.script.full_path_name
            editor.set_breakpoints(
                {
                    breakpoint.line_number
                    for breakpoint in self.state.breakpoints
                    if _same_source(breakpoint.source_name, source_name)
                    and breakpoint.script_id in {script_id, -1}
                }
            )

    def _all_source_editors(self) -> list[SourceEditor]:
        return [*self.source_editors.values(), *self.frame_source_editors.values()]

    def _render_threads(self, script_id: int) -> None:
        self.threads.clear()
        for thread in self.state.threads.get(script_id, []):
            self.threads.addTopLevelItem(
                QTreeWidgetItem([str(thread.thread_index), thread.thread_name])
            )

    def _render_callstack(self, script_id: int) -> None:
        self.callstack.clear()
        for depth, frame in enumerate(self.state.callstacks.get(script_id, [])):
            self.callstack.addTopLevelItem(QTreeWidgetItem([str(depth), frame]))
        selected = self.callstack.topLevelItem(self._callstack_depths.get(script_id, 0))
        if selected is not None:
            self.callstack.setCurrentItem(selected)
        self.callstack.resizeColumnToContents(0)

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

    def _clear_inspection_results(self) -> None:
        self.state.variables.clear()
        self.state.tables.clear()
        self._render_variables()

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

    def _error(self, message: str) -> None:
        self.statusBar().showMessage(f"Error: {message}")
        QMessageBox.warning(self, "EAWLuaDebugger", message)

    def closeEvent(self, event) -> None:
        self.timer.stop()
        self.thread_poll_timer.stop()
        QMetaObject.invokeMethod(
            self.worker,
            "disconnect_game",
            Qt.ConnectionType.BlockingQueuedConnection,
        )
        self.thread.quit()
        self.thread.wait(2000)
        super().closeEvent(event)
