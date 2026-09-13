import pytest

pytest.importorskip("PySide6")

import argparse

from PySide6.QtWidgets import QApplication

from eaw_lua_debugger import gui
from eaw_lua_debugger.client import ScriptInfo, TableMember, ThreadInfo
from eaw_lua_debugger.lua_messages import LuaMessage, LuaMessageId


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

    def dump_table(self, script_id, context_id, name, path):
        self.calls.append(("dump_table", script_id, context_id, name, path))
        return [TableMember(4, "GlobalName", 2, "GlobalValue")]


def test_gui_loading_a_script_does_not_send_context_or_break_commands():
    worker = gui.DebuggerWorker()
    client = FakeClient()
    worker.client = client

    worker.load_script(7)

    assert client.calls == [("request_threads", 7)]


def test_gui_worker_reports_backend_timeout_without_traceback():
    class TimeoutClient(FakeClient):
        def request_threads(self, script_id):
            raise TimeoutError("boom")

    worker = gui.DebuggerWorker()
    worker.client = TimeoutClient()
    errors = []
    worker.error.connect(errors.append)

    worker.load_script(7)

    assert errors == ["boom"]


def test_gui_worker_table_dump_reports_script_context_and_members():
    worker = gui.DebuggerWorker()
    client = FakeClient()
    worker.client = client
    loaded = []
    worker.table_loaded.connect(lambda *args: loaded.append(args))

    worker.dump_table(7, 99, "_G", [])

    assert client.calls == [("dump_table", 7, 99, "_G", [])]
    assert loaded == [(7, 99, "_G", [TableMember(4, "GlobalName", 2, "GlobalValue")])]


def test_gui_breakpoints_render_in_table_and_source_gutter_not_output(tmp_path):
    app = QApplication.instance() or QApplication([])
    source = tmp_path / "Foo.lua"
    source.write_text("a\nb\n", encoding="utf-8")
    window = gui.MainWindow(
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
    window = gui.MainWindow(
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
        window._scripts_loaded([ScriptInfo(7, str(source))])
        window.files.setCurrentItem(window.files.topLevelItem(0))

        assert requested == []
        assert window.state.current_script_id == 7
        assert window.var_script.value() == 7
    finally:
        window.close()
        app.processEvents()


def test_suspended_script_refreshes_variables_even_when_script_id_is_unchanged():
    app = QApplication.instance() or QApplication([])
    window = gui.MainWindow(
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

        assert requested == [(7, 1, "_G", []), (7, 2, "_G", [])]

        window._table_loaded(7, 2, "_G", [TableMember(4, "GlobalName", 2, "GlobalValue")])

        assert window.variables.topLevelItemCount() == 1
        row = window.variables.topLevelItem(0)
        assert [row.text(0), row.text(1), row.text(2)] == [
            "GlobalName",
            "2",
            "GlobalValue",
        ]
    finally:
        window.close()
        app.processEvents()


def test_local_source_open_does_not_request_game_variables(tmp_path):
    app = QApplication.instance() or QApplication([])
    source = tmp_path / "Local.lua"
    source.write_text("a\nb\n", encoding="utf-8")
    window = gui.MainWindow(
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
    window = gui.MainWindow(
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
