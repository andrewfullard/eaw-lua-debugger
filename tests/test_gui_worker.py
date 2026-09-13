import pytest

pytest.importorskip("PySide6")

import argparse

from PySide6.QtWidgets import QApplication

from eaw_lua_debugger import gui
from eaw_lua_debugger.client import ScriptInfo, ThreadInfo


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
