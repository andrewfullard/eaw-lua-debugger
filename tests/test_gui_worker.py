import pytest

pytest.importorskip("PySide6")

import argparse

from PySide6.QtCore import Qt
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QApplication, QMessageBox, QSizePolicy

from eaw_lua_debugger.core.exceptions import ConnectionLost
from eaw_lua_debugger.debugger.client import DebuggerRunState
from eaw_lua_debugger.debugger.types import (
    ScriptInfo,
    TableMember,
    ThreadInfo,
    VariableValue,
)
from eaw_lua_debugger.gui import DebuggerWorker, MainWindow
from eaw_lua_debugger.gui.state import BreakpointSpec
from eaw_lua_debugger.protocol.lua_messages import LuaMessage, LuaMessageId


class FakeClient:
    def __init__(self):
        self.calls = []
        self.attached_script_ids = set()
        self.context_script_id = None
        self.run_state = DebuggerRunState.RUNNING

    def select_script(self, script_id):
        self.calls.append(("select_script", script_id))
        self.context_script_id = script_id
        self.run_state = DebuggerRunState.BREAK_PENDING

    def select_thread(self, thread_id):
        self.calls.append(("select_thread", thread_id))

    def break_thread(self, thread_id):
        self.calls.append(("break_thread", thread_id))
        self.run_state = DebuggerRunState.BREAK_PENDING

    def set_callstack_depth(self, script_id, depth):
        self.calls.append(("set_callstack_depth", script_id, depth))

    def attach_script(self, script_id):
        self.calls.append(("attach_script", script_id))
        self.attached_script_ids.add(script_id)
        return []

    def request_threads(self, script_id):
        self.calls.append(("request_threads", script_id))
        return [ThreadInfo(3, "main")]

    def service_available(self):
        self.calls.append(("service_available",))
        return []

    def abort(self):
        self.calls.append(("abort",))

    def break_script(self, script_id):
        self.calls.append(("break_script", script_id))
        self.run_state = DebuggerRunState.BREAK_PENDING

    def send_control(self, command):
        self.calls.append(("send_control", command))
        self.run_state = (
            DebuggerRunState.RUNNING
            if command == "continue"
            else DebuggerRunState.BREAK_PENDING
        )

    def flush(self):
        self.calls.append(("flush",))

    def add_breakpoint(self, *args):
        self.calls.append(("add_breakpoint", *args))

    def remove_breakpoint(self, *args):
        self.calls.append(("remove_breakpoint", *args))

    def dump_table(self, script_id, context_id, name, path, *, allow_unsafe=False):
        self.calls.append(("dump_table", script_id, context_id, name, path, allow_unsafe))
        return [TableMember(4, "GlobalName", 2, "GlobalValue")]


def test_gui_loading_a_script_attaches_hook_without_breaking():
    worker = DebuggerWorker()
    client = FakeClient()
    worker.client = client
    children = []
    worker.children_loaded.connect(lambda *args: children.append(args))

    worker.load_script(7)

    assert client.calls == [("attach_script", 7), ("request_threads", 7)]
    assert children == [(7, [])]


def test_gui_worker_polls_threads_without_attaching_or_selecting_scripts():
    class PollClient(FakeClient):
        def request_threads(self, script_id):
            self.calls.append(("request_threads", script_id))
            return [ThreadInfo(script_id, "main")] if script_id == 7 else []

    worker = DebuggerWorker()
    client = PollClient()
    worker.client = client
    loaded = []
    finished = []
    worker.threads_loaded.connect(lambda *args: loaded.append(args))
    worker.thread_poll_finished.connect(lambda: finished.append(True))

    worker.poll_threads([7, 8])

    assert client.calls == [("request_threads", 7), ("request_threads", 8)]
    assert loaded == [(7, [ThreadInfo(7, "main")]), (8, [])]
    assert finished == [True]


def test_gui_break_targets_current_attached_script():
    worker = DebuggerWorker()
    client = FakeClient()
    worker.client = client
    worker.current_script_id = 7

    worker.control("break")

    assert client.calls == [("break_script", 7), ("flush",)]


def test_gui_worker_tracks_script_from_suspended_event():
    message = LuaMessage(
        LuaMessageId.SCRIPT_SUSPENDED,
        {
            "script_id": 9,
            "current_thread_id": 2,
            "full_path_name": "Data/Scripts/Foo.lua",
            "callstack": [],
            "threads": [],
        },
        raw_payload=None,
    )

    class EventClient(FakeClient):
        def service_available(self):
            return [message]

    worker = DebuggerWorker()
    worker.client = EventClient()

    worker.service_once()

    assert worker.current_script_id == 9


def test_gui_worker_clears_removed_script_before_next_break():
    removed = LuaMessage(
        LuaMessageId.SCRIPT_REMOVED,
        {"script_id": 9},
        raw_payload=None,
    )

    class EventClient(FakeClient):
        def service_available(self):
            self.run_state = DebuggerRunState.RUNNING
            return [removed]

    worker = DebuggerWorker()
    client = EventClient()
    worker.client = client
    worker.current_script_id = 9
    errors = []
    states = []
    worker.error.connect(errors.append)
    worker.debug_state_changed.connect(states.append)

    worker.service_once()
    worker.control("break")

    assert worker.current_script_id is None
    assert not any(call[0] == "break_script" for call in client.calls)
    assert errors == ["select an active script before requesting Break"]
    assert states == ["running", "running"]


def test_gui_worker_attaches_before_adding_script_breakpoint():
    worker = DebuggerWorker()
    client = FakeClient()
    worker.client = client
    spec = BreakpointSpec(7, -1, "Foo.lua", 12, "")

    worker.add_breakpoint(spec)

    assert client.calls == [
        ("attach_script", 7),
        ("add_breakpoint", 7, -1, "Foo.lua", 12, ""),
        ("flush",),
    ]


def test_gui_worker_break_thread_matches_stock_context_order():
    worker = DebuggerWorker()
    client = FakeClient()
    worker.client = client

    worker.select_thread(7, 3)

    assert client.calls == [
        ("attach_script", 7),
        ("select_script", 7),
        ("break_thread", 3),
        ("flush",),
    ]


def test_gui_worker_selects_callstack_frame_only_through_client_guard():
    worker = DebuggerWorker()
    client = FakeClient()
    worker.client = client
    selected = []
    worker.callstack_frame_selected.connect(lambda *args: selected.append(args))

    worker.select_callstack_frame(7, 2)

    assert client.calls == [("set_callstack_depth", 7, 2), ("flush",)]
    assert selected == [(7, 2)]


def test_gui_worker_remove_breakpoint_includes_native_condition_field():
    worker = DebuggerWorker()
    client = FakeClient()
    worker.client = client

    worker.remove_breakpoint(BreakpointSpec(7, -1, "Foo.lua", 12, "x > 0"))

    assert client.calls == [
        ("remove_breakpoint", 7, -1, "Foo.lua", 12, "x > 0"),
        ("flush",),
    ]


def test_gui_worker_reports_backend_timeout_without_traceback():
    class TimeoutClient(FakeClient):
        def request_threads(self, script_id):
            raise TimeoutError("boom")

    worker = DebuggerWorker()
    worker.client = TimeoutClient()
    errors = []
    worker.error.connect(errors.append)

    worker.load_script(7)

    assert errors == ["boom"]


def test_gui_worker_restores_actual_state_after_command_failure():
    class RejectingClient(FakeClient):
        def send_control(self, command):
            raise ValueError(f"cannot {command}")

    worker = DebuggerWorker()
    worker.client = RejectingClient()
    states = []
    errors = []
    worker.debug_state_changed.connect(states.append)
    worker.error.connect(errors.append)

    worker.control("continue")

    assert states == ["running"]
    assert errors == ["cannot continue"]


def test_gui_worker_drains_available_packets():
    worker = DebuggerWorker()
    client = FakeClient()
    worker.client = client

    worker.service_once()

    assert client.calls == [("service_available",)]


def test_gui_worker_disconnects_when_game_resets_connection():
    class LostClient(FakeClient):
        def service_available(self):
            raise ConnectionLost("game reset")

    worker = DebuggerWorker()
    client = LostClient()
    worker.client = client
    disconnected = []
    errors = []
    worker.disconnected.connect(lambda: disconnected.append(True))
    worker.error.connect(errors.append)

    worker.service_once()

    assert worker.client is None
    assert client.calls == [("abort",)]
    assert disconnected == [True]
    assert errors == ["game reset"]


def test_gui_worker_table_dump_reports_script_context_and_members():
    worker = DebuggerWorker()
    client = FakeClient()
    worker.client = client
    loaded = []
    worker.table_loaded.connect(lambda *args: loaded.append(args))

    worker.dump_table(7, 99, "_G", [], True)

    assert client.calls == [("dump_table", 7, 99, "_G", [], True)]
    assert loaded == [(7, 99, "_G", [TableMember(4, "GlobalName", 2, "GlobalValue")])]


def test_gui_worker_variable_result_includes_requesting_script():
    worker = DebuggerWorker()
    client = FakeClient()
    client.dump_variable = lambda script_id, name: VariableValue(name, 4, "table: 1234")
    worker.client = client
    loaded = []
    worker.variable_loaded.connect(lambda *args: loaded.append(args))

    worker.dump_variable(7, "planet")

    assert loaded == [(7, VariableValue("planet", 4, "table: 1234"))]


def test_gui_layout_prioritizes_source_editor_width():
    app = QApplication.instance() or QApplication([])
    window = MainWindow(
        argparse.Namespace(
            host="127.0.0.1",
            port=1234,
            local_port=0,
            client_name=None,
            timeout=5.0,
            source_root=[],
        )
    )
    try:
        assert window.source_tabs.minimumWidth() >= 560
        assert window.right_tabs.minimumWidth() == 220
        assert window.right_tabs.maximumWidth() > 10_000
        assert (
            window.right_tabs.sizePolicy().horizontalPolicy()
            == QSizePolicy.Policy.Expanding
        )
        assert window.top_splitter.sizes()[0] > window.top_splitter.sizes()[1]

        bottom_tabs = window.main_splitter.widget(1)
        breakpoint_tab = bottom_tabs.indexOf(window.breakpoints)
        assert breakpoint_tab >= 0
        assert bottom_tabs.tabText(breakpoint_tab) == "Breakpoints"
    finally:
        window.close()
        app.processEvents()


def test_gui_breakpoints_render_in_table_and_source_gutter_not_output(tmp_path):
    app = QApplication.instance() or QApplication([])
    source = tmp_path / "Foo.lua"
    source.write_text("a\nb\n", encoding="utf-8")
    window = MainWindow(
        argparse.Namespace(
            host="127.0.0.1",
            port=1234,
            local_port=0,
            client_name=None,
            timeout=5.0,
            source_root=[str(tmp_path)],
        )
    )
    try:
        script = ScriptInfo(7, str(source))
        window.state.scripts[7] = script
        window._open_source(script)

        window._add_breakpoint(BreakpointSpec(7, -1, str(source), 2))

        editor = window.source_editors[7]
        assert window.source_tabs.tabText(window.source_tabs.indexOf(editor)) == "[7] Foo.lua"
        assert window.breakpoints.rowCount() == 1
        assert window.output.toPlainText() == ""
        assert editor.toPlainText().splitlines()[1].startswith("  2 \u25cf")
    finally:
        window.close()
        app.processEvents()


def test_breakpoint_render_preserves_editor_position_and_view(tmp_path):
    app = QApplication.instance() or QApplication([])
    source = tmp_path / "Foo.lua"
    source.write_text(
        "\n".join(f"line_{line} = '{'.' * 200}'" for line in range(300)),
        encoding="utf-8",
    )
    window = MainWindow(
        argparse.Namespace(
            host="127.0.0.1",
            port=1234,
            local_port=0,
            client_name=None,
            timeout=5.0,
            source_root=[str(tmp_path)],
        )
    )
    try:
        script = ScriptInfo(7, str(source))
        window.state.scripts[7] = script
        window._open_source(script)
        window.show()
        app.processEvents()
        editor = window.source_editors[7]
        cursor = QTextCursor(editor.document().findBlockByNumber(200))
        cursor.movePosition(QTextCursor.MoveOperation.Right, n=25)
        editor.setTextCursor(cursor)
        editor.verticalScrollBar().setValue(0)
        editor.horizontalScrollBar().setValue(editor.horizontalScrollBar().maximum())
        position = editor.textCursor().position()
        vertical_scroll = editor.verticalScrollBar().value()
        horizontal_scroll = editor.horizontalScrollBar().value()

        editor.set_breakpoints({201})

        assert editor.textCursor().position() == position
        assert editor.verticalScrollBar().value() == vertical_scroll
        assert editor.horizontalScrollBar().value() == horizontal_scroll
    finally:
        window.close()
        app.processEvents()


def test_global_breakpoint_uses_native_sentinels_and_delete_clears_gutter(tmp_path):
    app = QApplication.instance() or QApplication([])
    source = tmp_path / "Foo.lua"
    source.write_text("a\nb\n", encoding="utf-8")
    window = MainWindow(
        argparse.Namespace(
            host="127.0.0.1",
            port=1234,
            local_port=0,
            client_name=None,
            timeout=5.0,
            source_root=[str(tmp_path)],
        )
    )
    sent = []
    window.add_breakpoint_requested.connect(sent.append)
    try:
        script = ScriptInfo(7, str(source))
        window.state.scripts[7] = script
        window._open_source(script)
        editor = window.source_editors[7]
        cursor = editor.textCursor()
        cursor.movePosition(cursor.MoveOperation.Down)
        editor.setTextCursor(cursor)

        window._toggle_global_breakpoint()

        assert sent[0].script_id == -1
        assert sent[0].thread_id == -1
        assert editor.toPlainText().splitlines()[1].startswith("  2 \u25cf")

        window._delete_all_breakpoints()

        assert not window.state.breakpoints
        assert not editor.toPlainText().splitlines()[1].startswith("  2 \u25cf")
    finally:
        window.close()
        app.processEvents()


def test_disconnect_keeps_breakpoints_for_replay_after_goodbye(tmp_path):
    app = QApplication.instance() or QApplication([])
    source = tmp_path / "Foo.lua"
    source.write_text("a\n", encoding="utf-8")
    window = MainWindow(
        argparse.Namespace(
            host="127.0.0.1",
            port=1234,
            local_port=0,
            client_name=None,
            timeout=5.0,
            source_root=[str(tmp_path)],
        )
    )
    try:
        script = ScriptInfo(7, str(source))
        window.state.scripts[7] = script
        window._open_source(script)
        window.state.current_script_id = 7
        window.state.add_breakpoint(BreakpointSpec(7, -1, str(source), 1))
        window._render_breakpoints()
        window._render_source_breakpoints(7)

        window._disconnected()

        assert window.state.current_script_id is None
        assert window.state.breakpoints == [BreakpointSpec(7, -1, str(source), 1)]
        assert window.breakpoints.rowCount() == 1
    finally:
        window.close()
        app.processEvents()


def test_reconnect_remaps_and_replays_breakpoints_by_source(tmp_path):
    app = QApplication.instance() or QApplication([])
    source = tmp_path / "Foo.lua"
    source.write_text("a\n", encoding="utf-8")
    window = MainWindow(
        argparse.Namespace(
            host="127.0.0.1",
            port=1234,
            local_port=0,
            client_name=None,
            timeout=5.0,
            source_root=[str(tmp_path)],
        )
    )
    replayed = []
    window.add_breakpoint_requested.connect(replayed.append)
    try:
        window.state.scripts[7] = ScriptInfo(7, str(source))
        window.state.add_breakpoint(BreakpointSpec(7, -1, str(source), 1, "ready"))

        window._disconnected()
        window._connected("StarWarsI:test")
        window._scripts_loaded([ScriptInfo(42, str(source))])

        expected = BreakpointSpec(42, -1, str(source), 1, "ready")
        assert window.state.breakpoints == [expected]
        assert replayed == [expected]
    finally:
        window.close()
        app.processEvents()


def test_breakpoint_replay_waits_for_unique_matching_script(tmp_path):
    app = QApplication.instance() or QApplication([])
    source = str(tmp_path / "Foo.lua")
    window = MainWindow(
        argparse.Namespace(
            host="127.0.0.1",
            port=1234,
            local_port=0,
            client_name=None,
            timeout=5.0,
            source_root=[str(tmp_path)],
        )
    )
    replayed = []
    window.add_breakpoint_requested.connect(replayed.append)
    try:
        window.state.scripts[7] = ScriptInfo(7, source)
        window.state.add_breakpoint(BreakpointSpec(7, -1, source, 1))
        window._disconnected()
        window._connected("StarWarsI:test")

        window._scripts_loaded([ScriptInfo(40, "Other.lua")])
        assert replayed == []

        window._scripts_loaded([ScriptInfo(40, "Other.lua"), ScriptInfo(42, source)])
        assert replayed == [BreakpointSpec(42, -1, source, 1)]
    finally:
        window.close()
        app.processEvents()


def test_breakpoint_replay_does_not_guess_between_duplicate_lua_states(tmp_path):
    app = QApplication.instance() or QApplication([])
    source = str(tmp_path / "Foo.lua")
    window = MainWindow(
        argparse.Namespace(
            host="127.0.0.1",
            port=1234,
            local_port=0,
            client_name=None,
            timeout=5.0,
            source_root=[str(tmp_path)],
        )
    )
    replayed = []
    window.add_breakpoint_requested.connect(replayed.append)
    try:
        window.state.scripts[7] = ScriptInfo(7, source)
        window.state.add_breakpoint(BreakpointSpec(7, -1, source, 1))
        window._disconnected()
        window._connected("StarWarsI:test")

        window._scripts_loaded([ScriptInfo(41, source), ScriptInfo(42, source)])

        assert replayed == []
        assert "waiting for a unique matching script" in window.statusBar().currentMessage()

        window._select_game_script(41, open_source=False, request_threads=False)

        assert replayed == [BreakpointSpec(41, -1, source, 1)]
    finally:
        window.close()
        app.processEvents()


def test_local_breakpoint_replay_waits_for_selected_duplicate_game_script(tmp_path):
    app = QApplication.instance() or QApplication([])
    source = str(tmp_path / "Foo.lua")
    window = MainWindow(
        argparse.Namespace(
            host="127.0.0.1",
            port=1234,
            local_port=0,
            client_name=None,
            timeout=5.0,
            source_root=[str(tmp_path)],
        )
    )
    replayed = []
    window.add_breakpoint_requested.connect(replayed.append)
    try:
        window._open_local_path(source)
        local_script_id = window._current_editor().source.script.script_id
        window._toggle_source_breakpoint(local_script_id, 1)
        window._scripts_loaded([ScriptInfo(41, source), ScriptInfo(42, source)])

        assert replayed == []

        window._select_game_script(42, open_source=False, request_threads=False)

        assert replayed == [BreakpointSpec(42, -1, source, 1)]
    finally:
        window.close()
        app.processEvents()


def test_gui_actions_follow_stock_running_and_suspended_states():
    app = QApplication.instance() or QApplication([])
    window = MainWindow(
        argparse.Namespace(
            host="127.0.0.1",
            port=1234,
            local_port=0,
            client_name=None,
            timeout=5.0,
            source_root=[],
        )
    )
    try:
        window.state.scripts[7] = ScriptInfo(7, "Foo.lua")
        window.state.current_script_id = 7
        window._connected("StarWarsI:test")
        window._update_debug_actions()

        assert window.control_actions["break"].isEnabled()
        assert not window.control_actions["step-over"].isEnabled()

        window._request_control("break")

        assert window.run_state == DebuggerRunState.RUNNING

        window.state.current_thread_id = 3
        window.state.suspended_script_id = 7
        window._debug_state_changed("suspended")

        assert not window.control_actions["break"].isEnabled()
        assert window.control_actions["continue"].isEnabled()
        assert window.control_actions["step-over"].isEnabled()
        assert window.callstack.isEnabled()
        assert window.break_thread_action.isEnabled()
    finally:
        window.close()
        app.processEvents()


def test_gui_table_expansion_requires_confirmation(monkeypatch):
    app = QApplication.instance() or QApplication([])
    window = MainWindow(
        argparse.Namespace(
            host="127.0.0.1",
            port=1234,
            local_port=0,
            client_name=None,
            timeout=5.0,
            source_root=[],
        )
    )
    requested = []
    window.table_requested.connect(lambda *args: requested.append(args))
    try:
        monkeypatch.setattr(
            QMessageBox,
            "warning",
            lambda *_args, **_kwargs: QMessageBox.StandardButton.Yes,
        )
        window.var_script.setValue(7)
        window.table_name.setText("SmallTable")

        window._dump_table()

        assert requested == [(7, 1, "SmallTable", [], True)]
    finally:
        window.close()
        app.processEvents()


def test_loaded_variable_is_visible_while_game_script_is_selected():
    app = QApplication.instance() or QApplication([])
    window = MainWindow(
        argparse.Namespace(
            host="127.0.0.1",
            port=1234,
            local_port=0,
            client_name=None,
            timeout=5.0,
            source_root=[],
        )
    )
    try:
        window.state.current_script_id = 7

        window._variable_loaded(7, VariableValue("planet", 4, "table: 1234"))

        assert window.variables.topLevelItemCount() == 1
        item = window.variables.topLevelItem(0)
        assert (item.text(0), item.text(1), item.text(2)) == (
            "planet",
            "4",
            "table: 1234",
        )
        assert window.statusBar().currentMessage() == "Loaded variable planet"
    finally:
        window.close()
        app.processEvents()


def test_variable_result_from_previous_script_is_ignored():
    app = QApplication.instance() or QApplication([])
    window = MainWindow(
        argparse.Namespace(
            host="127.0.0.1",
            port=1234,
            local_port=0,
            client_name=None,
            timeout=5.0,
            source_root=[],
        )
    )
    try:
        window.state.current_script_id = 8

        window._variable_loaded(7, VariableValue("planet", 4, "table: 1234"))

        assert window.variables.topLevelItemCount() == 0
        assert "Ignored stale variable result" in window.statusBar().currentMessage()
    finally:
        window.close()
        app.processEvents()


def test_removing_selected_script_clears_visible_inspection_results():
    app = QApplication.instance() or QApplication([])
    window = MainWindow(
        argparse.Namespace(
            host="127.0.0.1",
            port=1234,
            local_port=0,
            client_name=None,
            timeout=5.0,
            source_root=[],
        )
    )
    try:
        window.state.scripts[7] = ScriptInfo(7, "Foo.lua")
        window.state.current_script_id = 7
        window.state.set_variable(VariableValue("planet", 4, "table: 1234"))
        window._render_variables()

        window._message_received(
            LuaMessage(LuaMessageId.SCRIPT_REMOVED, {"script_id": 7}, raw_payload=None)
        )

        assert window.state.current_script_id is None
        assert window.variables.topLevelItemCount() == 0
    finally:
        window.close()
        app.processEvents()


def test_legacy_script_variable_cache_is_not_mixed_with_frame_values():
    app = QApplication.instance() or QApplication([])
    window = MainWindow(
        argparse.Namespace(
            host="127.0.0.1",
            port=1234,
            local_port=0,
            client_name=None,
            timeout=5.0,
            source_root=[],
        )
    )
    try:
        window.state.current_script_id = 7
        window.state.set_script_variables(
            7, [TableMember(3, "planet", 4, "old table")]
        )

        window._variable_loaded(7, VariableValue("planet", 4, "current table"))

        assert window.variables.topLevelItemCount() == 1
        assert window.variables.topLevelItem(0).text(2) == "current table"
    finally:
        window.close()
        app.processEvents()


def test_selecting_game_script_does_not_request_variables(tmp_path):
    app = QApplication.instance() or QApplication([])
    source = tmp_path / "Foo.lua"
    source.write_text("a\nb\n", encoding="utf-8")
    window = MainWindow(
        argparse.Namespace(
            host="127.0.0.1",
            port=1234,
            local_port=0,
            client_name=None,
            timeout=5.0,
            source_root=[str(tmp_path)],
        )
    )
    requested = []
    thread_requests = []
    window.table_requested.connect(lambda *args: requested.append(args))
    window.threads_requested.connect(thread_requests.append)
    try:
        window._scripts_loaded([ScriptInfo(7, str(source))])
        window.files.setCurrentItem(window.files.topLevelItem(0))

        assert requested == []
        assert thread_requests == [7]
        assert window.state.current_script_id == 7
        assert window.var_script.value() == 7

        window._threads_loaded(7, [ThreadInfo(3, "main"), ThreadInfo(4, "worker")])

        assert window.threads.topLevelItemCount() == 2
        assert window.threads.topLevelItem(0).text(0) == "3"
        assert window.threads.topLevelItem(0).text(1) == "main"
        assert window.threads.topLevelItem(1).text(0) == "4"
        assert window.threads.topLevelItem(1).text(1) == "worker"
    finally:
        window.close()
        app.processEvents()


def test_five_second_thread_poll_highlights_scripts_with_threads():
    app = QApplication.instance() or QApplication([])
    window = MainWindow(
        argparse.Namespace(
            host="127.0.0.1",
            port=1234,
            local_port=0,
            client_name=None,
            timeout=5.0,
            source_root=[],
        )
    )
    requested = []
    window.poll_threads_requested.connect(requested.append)
    try:
        window.thread_poll_timer.stop()
        window._scripts_loaded([ScriptInfo(7, "A.lua"), ScriptInfo(8, "B.lua")])
        window.is_connected = True

        window._poll_threads()

        assert window.thread_poll_timer.interval() == 5000
        assert requested == [[7, 8]]
        assert window._thread_poll_pending is True

        window._threads_loaded(7, [ThreadInfo(3, "main")])
        active_item = window._file_items[7]
        assert active_item.font(0).bold() is True
        assert active_item.toolTip(1) == "1 thread(s) in latest poll"

        window._threads_loaded(7, [])
        assert active_item.font(0).bold() is False
        assert active_item.toolTip(1) == "No named threads in latest poll"

        window._thread_poll_finished()
        assert window._thread_poll_pending is False
    finally:
        window.close()
        app.processEvents()


def test_files_table_sorts_each_column_and_defaults_active_scripts_first():
    app = QApplication.instance() or QApplication([])
    window = MainWindow(
        argparse.Namespace(
            host="127.0.0.1",
            port=1234,
            local_port=0,
            client_name=None,
            timeout=5.0,
            source_root=[],
        )
    )
    try:
        window.thread_poll_timer.stop()
        window._scripts_loaded(
            [
                ScriptInfo(10, "Beta.lua"),
                ScriptInfo(2, "Alpha.lua"),
                ScriptInfo(3, "Gamma.lua"),
            ]
        )
        window._threads_loaded(3, [ThreadInfo(0, "main")])

        assert window.files.isSortingEnabled() is True
        assert window.files.columnCount() == 3
        assert window.files.topLevelItem(0).text(0) == "3"

        window.files.sortItems(0, Qt.SortOrder.AscendingOrder)
        assert [window.files.topLevelItem(row).text(0) for row in range(3)] == [
            "2",
            "3",
            "10",
        ]

        window.files.sortItems(1, Qt.SortOrder.AscendingOrder)
        assert [window.files.topLevelItem(row).text(1) for row in range(3)] == [
            "Alpha.lua",
            "Beta.lua",
            "Gamma.lua",
        ]

        window.files.sortItems(2, Qt.SortOrder.DescendingOrder)
        assert window.files.topLevelItem(0).text(0) == "3"
        assert window.files.topLevelItem(0).text(2) == "1"
    finally:
        window.close()
        app.processEvents()


def test_suspended_script_does_not_request_variables():
    app = QApplication.instance() or QApplication([])
    window = MainWindow(
        argparse.Namespace(
            host="127.0.0.1",
            port=1234,
            local_port=0,
            client_name=None,
            timeout=5.0,
            source_root=[],
        )
    )
    requested = []
    thread_requests = []
    window.table_requested.connect(lambda *args: requested.append(args))
    window.threads_requested.connect(thread_requests.append)
    message = LuaMessage(
        LuaMessageId.SCRIPT_SUSPENDED,
        {
            "script_id": 7,
            "current_thread_id": 0,
            "full_path_name": "Data/Scripts/Foo.lua",
            "callstack": [],
            "threads": [],
        },
        raw_payload=None,
    )
    try:
        window.state.current_script_id = 7

        window._message_received(message)
        window._message_received(message)

        assert requested == []
        assert thread_requests == []
        assert window.state.current_script_id == 7
        assert window.var_script.value() == 7
    finally:
        window.close()
        app.processEvents()


def test_debug_output_appends_fragments_once_without_protocol_prefix():
    app = QApplication.instance() or QApplication([])
    window = MainWindow(
        argparse.Namespace(
            host="127.0.0.1",
            port=1234,
            local_port=0,
            client_name=None,
            timeout=5.0,
            source_root=[],
        )
    )
    try:
        window._message_received(
            LuaMessage(
                LuaMessageId.OUTPUT,
                {"output_type": 0, "message": "Lu"},
                raw_payload=None,
            )
        )
        window._message_received(LuaMessage(LuaMessageId.HEARTBEAT, {}, raw_payload=None))
        window._message_received(
            LuaMessage(
                LuaMessageId.OUTPUT,
                {"output_type": 0, "message": "a message"},
                raw_payload=None,
            )
        )

        assert window.output.toPlainText() == "Lua message"
    finally:
        window.close()
        app.processEvents()


def test_callstack_tab_shows_selected_script_callstack():
    app = QApplication.instance() or QApplication([])
    window = MainWindow(
        argparse.Namespace(
            host="127.0.0.1",
            port=1234,
            local_port=0,
            client_name=None,
            timeout=5.0,
            source_root=[],
        )
    )
    requested = []
    window.callstack_requested.connect(lambda *args: requested.append(args))
    try:
        window._message_received(
            LuaMessage(
                LuaMessageId.SCRIPT_SUSPENDED,
                {
                    "script_id": 7,
                    "current_thread_id": 0,
                    "full_path_name": "Data/Scripts/Foo.lua",
                    "callstack": ["Foo.lua:10", "Bar.lua:20"],
                    "threads": [],
                },
                raw_payload=None,
            )
        )

        assert window.callstack.topLevelItemCount() == 2
        first_frame = window.callstack.topLevelItem(0)
        second_frame = window.callstack.topLevelItem(1)
        assert [first_frame.text(0), first_frame.text(1)] == [
            "0",
            "Foo.lua:10",
        ]
        assert [second_frame.text(0), second_frame.text(1)] == [
            "1",
            "Bar.lua:20",
        ]
        assert window.callstack.currentItem() is second_frame
        assert requested == [(7, 1)]

        window._callstack_frame_selected(7, 0)
        window._render_callstack(7)

        assert window.callstack.currentItem().text(0) == "0"

        window.state.scripts[8] = ScriptInfo(8, "Data/Scripts/Other.lua")
        window._select_game_script(8, open_source=False, request_threads=False)

        assert window.callstack.topLevelItemCount() == 0
    finally:
        window.close()
        app.processEvents()


def test_active_callstack_frame_highlights_and_centers_its_source_line(tmp_path):
    app = QApplication.instance() or QApplication([])
    source = tmp_path / "Data" / "Scripts" / "Foo.lua"
    source.parent.mkdir(parents=True)
    source.write_text("\n".join(f"line_{line}" for line in range(1, 201)), encoding="utf-8")
    window = MainWindow(
        argparse.Namespace(
            host="127.0.0.1",
            port=1234,
            local_port=0,
            client_name=None,
            timeout=5.0,
            source_root=[str(tmp_path)],
        )
    )
    try:
        window._message_received(
            LuaMessage(
                LuaMessageId.SCRIPT_SUSPENDED,
                {
                    "script_id": 7,
                    "current_thread_id": 0,
                    "full_path_name": "Data/Scripts/Foo.lua",
                    "callstack": [
                        "Data/Scripts/Foo.lua:150:CurrentFunction",
                        "Foo.lua:25:CallingFunction",
                    ],
                    "threads": [],
                },
                raw_payload=None,
            )
        )

        editor = window.source_editors[7]
        assert editor.active_line == 25
        assert editor.textCursor().blockNumber() == 24
        assert editor.extraSelections()[0].cursor.blockNumber() == 24

        window._callstack_frame_selected(7, 0)

        assert editor.active_line == 150
        assert editor.textCursor().blockNumber() == 149
        assert editor.extraSelections()[0].cursor.blockNumber() == 149
    finally:
        window.close()
        app.processEvents()


def test_callstack_library_frame_opens_local_source_in_same_script_context(tmp_path):
    app = QApplication.instance() or QApplication([])
    main_source = tmp_path / "Data" / "Scripts" / "AI" / "Plan.lua"
    library_source = tmp_path / "Data" / "Scripts" / "Library" / "PGBase.lua"
    main_source.parent.mkdir(parents=True)
    library_source.parent.mkdir(parents=True)
    main_source.write_text("main = true\n", encoding="utf-8")
    library_source.write_text(
        "\n".join(f"line_{line}" for line in range(1, 151)), encoding="utf-8"
    )
    window = MainWindow(
        argparse.Namespace(
            host="127.0.0.1",
            port=1234,
            local_port=0,
            client_name=None,
            timeout=5.0,
            source_root=[str(tmp_path)],
        )
    )
    try:
        window._message_received(
            LuaMessage(
                LuaMessageId.SCRIPT_SUSPENDED,
                {
                    "script_id": 395,
                    "current_thread_id": 0,
                    "full_path_name": "Data/Scripts/AI/Plan.lua",
                    "callstack": [
                        "Data/Scripts/AI/Plan.lua:1:Plan",
                        "Data/Scripts/Library/PGBase.lua:84:Lua::global:BlockOnCommand",
                    ],
                    "threads": [],
                },
                raw_payload=None,
            )
        )

        key = (395, "data/scripts/library/pgbase.lua")
        editor = window.frame_source_editors[key]
        assert editor.source.path == library_source
        assert editor.active_line == 84
        assert window.source_tabs.currentWidget() is editor
        assert window.source_tabs.tabText(window.source_tabs.indexOf(editor)) == (
            "[395] PGBase.lua"
        )
        assert window.state.current_script_id == 395
        assert window.var_script.value() == 395
    finally:
        window.close()
        app.processEvents()


def test_local_source_open_does_not_request_game_variables(tmp_path):
    app = QApplication.instance() or QApplication([])
    source = tmp_path / "Local.lua"
    source.write_text("a\nb\n", encoding="utf-8")
    window = MainWindow(
        argparse.Namespace(
            host="127.0.0.1",
            port=1234,
            local_port=0,
            client_name=None,
            timeout=5.0,
            source_root=[str(tmp_path)],
        )
    )
    requested = []
    window.table_requested.connect(lambda *args: requested.append(args))
    try:
        window._open_local_path(str(source))

        assert requested == []
    finally:
        window.close()
        app.processEvents()


def test_local_source_breakpoints_replay_when_matching_game_script_loads(tmp_path):
    app = QApplication.instance() or QApplication([])
    source = tmp_path / "Local.lua"
    source.write_text("a\nb\n", encoding="utf-8")
    window = MainWindow(
        argparse.Namespace(
            host="127.0.0.1",
            port=1234,
            local_port=0,
            client_name=None,
            timeout=5.0,
            source_root=[str(tmp_path)],
        )
    )
    sent = []
    window.add_breakpoint_requested.connect(sent.append)
    try:
        window._open_local_path(str(source))
        editor = window._current_editor()
        assert editor is not None
        local_script_id = editor.source.script.script_id
        assert local_script_id <= -2

        window._toggle_source_breakpoint(local_script_id, 2)

        assert sent == []
        assert window.state.breakpoints[0].script_id == local_script_id
        assert window.breakpoints.item(0, 0).text() == str(local_script_id)
        assert editor.toPlainText().splitlines()[1].startswith("  2 \u25cf")

        window._scripts_loaded([ScriptInfo(7, str(source))])

        assert sent == [BreakpointSpec(7, -1, str(source), 2)]
        assert window.state.breakpoints[0].script_id == 7
        assert editor.toPlainText().splitlines()[1].startswith("  2 \u25cf")

        window._toggle_global_breakpoint()

        assert len(sent) == 1
        assert len(window.state.breakpoints) == 1
        assert "game-reported source" in window.statusBar().currentMessage()
    finally:
        window.close()
        app.processEvents()
