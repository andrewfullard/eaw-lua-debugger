import pytest

pytest.importorskip("PySide6")

import argparse

from PySide6.QtWidgets import QApplication

from eaw_lua_debugger.debugger.types import ScriptInfo, TableMember, ThreadInfo
from eaw_lua_debugger.gui import DebuggerWorker, MainWindow
from eaw_lua_debugger.protocol.lua_messages import LuaMessage, LuaMessageId


class FakeClient:
    def __init__(self):
        self.calls = []

    def select_script(self, script_id):
        self.calls.append(("select_script", script_id))

    def select_thread(self, thread_id):
        self.calls.append(("select_thread", thread_id))

    def attach_script(self, script_id):
        self.calls.append(("attach_script", script_id))
        return []

    def request_threads(self, script_id):
        self.calls.append(("request_threads", script_id))
        return [ThreadInfo(3, "main")]

    def service_available(self):
        self.calls.append(("service_available",))
        return []

    def dump_table(self, script_id, context_id, name, path):
        self.calls.append(("dump_table", script_id, context_id, name, path))
        return [TableMember(4, "GlobalName", 2, "GlobalValue")]


def test_gui_loading_a_script_does_not_send_context_or_break_commands():
    worker = DebuggerWorker()
    client = FakeClient()
    worker.client = client

    worker.load_script(7)

    assert client.calls == [("request_threads", 7)]


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


def test_gui_worker_drains_available_packets():
    worker = DebuggerWorker()
    client = FakeClient()
    worker.client = client

    worker.service_once()

    assert client.calls == [("service_available",)]


def test_gui_worker_table_dump_reports_script_context_and_members():
    worker = DebuggerWorker()
    client = FakeClient()
    worker.client = client
    loaded = []
    worker.table_loaded.connect(lambda *args: loaded.append(args))

    worker.dump_table(7, 99, "_G", [])

    assert client.calls == [("dump_table", 7, 99, "_G", [])]
    assert loaded == [(7, 99, "_G", [TableMember(4, "GlobalName", 2, "GlobalValue")])]


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
        assert window.right_tabs.maximumWidth() == 360
        assert window.top_splitter.sizes()[0] > window.top_splitter.sizes()[1]
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
        window.bp_script.setValue(7)
        window.bp_source.setText(str(source))
        window.bp_line.setValue(2)

        window._add_breakpoint()

        editor = window.source_editors[7]
        assert window.breakpoints.rowCount() == 1
        assert window.output.toPlainText() == ""
        assert editor.toPlainText().splitlines()[1].startswith("  2 \u25cf")
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

        window.state.scripts[8] = ScriptInfo(8, "Data/Scripts/Other.lua")
        window._select_game_script(8, open_source=False, request_threads=False)

        assert window.callstack.topLevelItemCount() == 0
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


def test_local_source_breakpoints_keep_local_script_id_and_render_gutter(tmp_path):
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
        assert local_script_id < 0

        window._toggle_source_breakpoint(local_script_id, 2)

        assert sent == []
        assert window.state.breakpoints[0].script_id == local_script_id
        assert window.breakpoints.item(0, 0).text() == str(local_script_id)
        assert editor.toPlainText().splitlines()[1].startswith("  2 \u25cf")
    finally:
        window.close()
        app.processEvents()
