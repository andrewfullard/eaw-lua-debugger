"""Source editor widgets for the Qt GUI."""

from __future__ import annotations

import re

from .gui_sources import SourceFile, format_source_lines

try:
    from pygments import lex
    from pygments.lexers import LuaLexer
    from pygments.token import Comment, Keyword, Literal, Name, Number, String
    from PySide6.QtCore import Signal
    from PySide6.QtGui import QColor, QFont, QSyntaxHighlighter, QTextCharFormat, QTextCursor
    from PySide6.QtWidgets import (
        QDialog,
        QDialogButtonBox,
        QLineEdit,
        QPlainTextEdit,
        QTableWidget,
        QTableWidgetItem,
        QVBoxLayout,
        QWidget,
    )
except ImportError as exc:  # pragma: no cover
    raise SystemExit(
        "PySide6 and Pygments are required for the GUI. "
        "Run: uv sync"
    ) from exc


class LuaHighlighter(QSyntaxHighlighter):
    def __init__(self, document) -> None:
        super().__init__(document)
        self.lexer = LuaLexer()
        self.formats = {
            Comment: self._format("#008000"),
            Keyword: self._format("#0000aa", bold=True),
            Literal.String: self._format("#aa0000", bold=True),
            Name.Function: self._format("#aa0000", bold=True),
            Number: self._format("#008080"),
            String: self._format("#aa0000", bold=True),
        }

    def highlightBlock(self, text: str) -> None:
        start = source_prefix_length(text)
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


class SourceEditor(QPlainTextEdit):
    breakpoint_toggled = Signal(int)

    def __init__(self, source: SourceFile) -> None:
        super().__init__()
        self.source = source
        self.breakpoint_lines: set[int] = set()
        self.setReadOnly(False)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.setFont(QFont("Consolas", 10))
        self.highlighter = LuaHighlighter(self.document())
        self.render()

    def render(self) -> None:
        cursor = self.textCursor()
        line = cursor.blockNumber()
        self.setPlainText(format_source_lines(self.source_text(), self.breakpoint_lines))
        cursor = QTextCursor(self.document().findBlockByNumber(max(0, line)))
        self.setTextCursor(cursor)

    def set_breakpoints(self, lines: set[int]) -> None:
        self.breakpoint_lines = lines
        self.render()

    def source_line(self) -> int:
        return self.textCursor().blockNumber() + 1

    def source_text(self) -> str:
        text = self.toPlainText()
        if not text:
            return self.source.text
        return "\n".join(strip_source_prefix(line) for line in text.splitlines()) + "\n"

    def mouseDoubleClickEvent(self, event) -> None:
        cursor = self.cursorForPosition(event.position().toPoint())
        self.breakpoint_toggled.emit(cursor.blockNumber() + 1)
        super().mouseDoubleClickEvent(event)


class SmartOpenDialog(QDialog):
    def __init__(self, files, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.files = list(files)
        self.selected_path: str | None = None
        self.setWindowTitle("Open Lua File")
        self.resize(650, 440)
        layout = QVBoxLayout(self)
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Name", "Path"])
        self.table.cellDoubleClicked.connect(lambda _row, _col: self.accept())
        layout.addWidget(self.table)
        self.filter_text = QLineEdit()
        self.filter_text.textChanged.connect(self._populate)
        layout.addWidget(self.filter_text)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._populate()

    def _populate(self) -> None:
        needle = self.filter_text.text().lower()
        matches = [path for path in self.files if needle in str(path).lower()]
        self.table.setRowCount(len(matches))
        for row, path in enumerate(matches):
            self.table.setItem(row, 0, QTableWidgetItem(path.name))
            self.table.setItem(row, 1, QTableWidgetItem(str(path)))
        self.table.resizeColumnsToContents()
        if matches:
            self.table.selectRow(0)

    def accept(self) -> None:
        selected = self.table.selectedItems()
        if selected:
            self.selected_path = selected[1].text()
        super().accept()


def source_prefix_length(line: str) -> int:
    match = re.match(r"^\s*\d+\s[ \u25cf]\s", line)
    return 0 if match is None else match.end()


def strip_source_prefix(line: str) -> str:
    return line[source_prefix_length(line) :]
