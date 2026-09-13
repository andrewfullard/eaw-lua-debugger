import pytest

pytest.importorskip("PySide6")

from eaw_lua_debugger import gui
from eaw_lua_debugger.client import ThreadInfo


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
