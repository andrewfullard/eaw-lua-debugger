"""Qt GUI application entry point."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication
except ImportError as exc:  # pragma: no cover
    raise SystemExit("PySide6 is required for the GUI. Run: uv sync") from exc

from .main_window import MainWindow


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="eaw-lua-debugger-gui")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=1234)
    parser.add_argument("--local-port", type=int, default=0)
    parser.add_argument("--client-name", default=None)
    parser.add_argument("--timeout", type=float, default=5.0)
    parser.add_argument(
        "--breakpoint-file",
        default=str(Path.home() / ".eaw_lua_debugger_breakpoints.json"),
        help="file used to persist GUI breakpoints",
    )
    parser.add_argument(
        "--source-root-file",
        default=str(Path.home() / ".eaw_lua_debugger_source_roots.json"),
        help="file used to persist GUI source roots",
    )
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
