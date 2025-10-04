from __future__ import annotations
import re
from typing import List, Dict, Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QPlainTextEdit, QDialogButtonBox, QMessageBox
)


_TIME_RE = re.compile(
    r"^\s*(?P<start>[0-9]{1,2}:[0-9]{2}(?::[0-9]{2})?|[0-9]+)(?:\s*[-\u2013\u2014~]\s*(?P<end>[0-9]{1,2}:[0-9]{2}(?::[0-9]{2})?|[0-9]+))?\s+(?P<title>.+)$"
)


def _parse_time(token: str) -> float:
    parts = token.strip().split(":")
    if not parts:
        raise ValueError("empty time token")
    # Allow plain seconds without ':'
    if len(parts) == 1:
        return float(parts[0])
    secs = 0.0
    for part in parts:
        part = part.strip()
        if not part:
            raise ValueError("invalid time component")
        secs = secs * 60.0 + float(part)
    return secs


def parse_chapter_text(text: str) -> List[Dict[str, Any]]:
    lines = [ln.strip() for ln in (text or "").splitlines()]
    lines = [ln for ln in lines if ln]
    if not lines:
        raise ValueError("No chapter lines provided.")
    chapters: List[Dict[str, Any]] = []
    for ln in lines:
        m = _TIME_RE.match(ln)
        if not m:
            raise ValueError(f"Could not parse line: '{ln}'")
        start_token = m.group("start") or ""
        end_token = m.group("end")
        title = (m.group("title") or "").strip()
        if not title:
            raise ValueError(f"Missing title for line: '{ln}'")
        start = _parse_time(start_token)
        end = None
        if end_token:
            end = _parse_time(end_token)
            if end <= start:
                raise ValueError(f"End time must be after start time in line: '{ln}'")
        chapters.append({"title": title, "start_time": start, "end_time": end})
    # Ensure strictly increasing start times and fill missing end times
    for idx, cur in enumerate(chapters):
        if idx > 0 and cur['start_time'] <= chapters[idx - 1]['start_time']:
            raise ValueError("Chapter start times must be strictly increasing.")
    for idx, cur in enumerate(chapters):
        if cur.get('end_time') is None and idx + 1 < len(chapters):
            cur['end_time'] = chapters[idx + 1]['start_time']
    return chapters


class ManualChaptersDialog(QDialog):
    """Prompt the user to paste chapter timestamps for a video without chapters."""

    RESULT_CANCEL = 0
    RESULT_ACCEPT = 1
    RESULT_SKIP = 2

    def __init__(self, parent, title: str, url: str, preset_text: str = ""):
        super().__init__(parent)
        self.setWindowTitle("Add Chapters")
        self._result = self.RESULT_CANCEL
        layout = QVBoxLayout(self)

        info = QLabel(f"<b>{title}</b><br>{url}")
        info.setTextFormat(Qt.RichText)
        info.setWordWrap(True)
        layout.addWidget(info)

        layout.addWidget(QLabel(
            "Paste one chapter per line. Formats supported:\n"
            "  0:00 Intro\n  1:23-2:34 Chorus"
        ))

        self.text = QPlainTextEdit()
        if preset_text:
            self.text.setPlainText(preset_text)
        layout.addWidget(self.text, 1)

        btns = QDialogButtonBox()
        self.btn_ok = btns.addButton("Use Chapters", QDialogButtonBox.AcceptRole)
        self.btn_skip = btns.addButton("Skip Video", QDialogButtonBox.DestructiveRole)
        self.btn_cancel = btns.addButton(QDialogButtonBox.Cancel)
        btns.accepted.connect(self._on_accept)
        self.btn_skip.clicked.connect(self._on_skip)
        btns.rejected.connect(self._on_cancel)
        layout.addWidget(btns)

    def _on_accept(self):
        text = self.text.toPlainText()
        try:
            self._chapters = parse_chapter_text(text)
        except ValueError as exc:
            QMessageBox.warning(self, "Chapters", str(exc))
            return
        self._result = self.RESULT_ACCEPT
        self.accept()

    def _on_skip(self):
        self._chapters = []
        self._result = self.RESULT_SKIP
        self.accept()

    def _on_cancel(self):
        self._result = self.RESULT_CANCEL
        self.reject()

    def result_code(self) -> int:
        return getattr(self, "_result", self.RESULT_CANCEL)

    def chapters(self) -> List[Dict[str, Any]]:
        return getattr(self, "_chapters", [])
