import os
import sqlite3
from pathlib import Path
from typing import Dict, List

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QComboBox, QTableWidget, QTableWidgetItem
)
from rockbox_utils import list_rockbox_devices
from core import CONFIG_PATH
from logging_utils import ui_log


class SearchPane(QWidget):
    """Search the library by title, artist, album, or genre.

    Uses the indexed SQLite database for the selected source (Library or
    Device). Build or refresh the index in the Database tab.
    """

    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self._all_tracks: List[Dict] = []  # kept for backward compatibility
        self._search_debounce = QTimer(self)
        self._search_debounce.setInterval(250)
        self._search_debounce.setSingleShot(True)
        self._search_debounce.timeout.connect(self._perform_search)
        self._build_ui()

    # ---------- UI ----------
    def _build_ui(self):
        root = QVBoxLayout(self)

        # Controls row
        top = QHBoxLayout()
        top.addWidget(QLabel("Search:"))
        self.query_edit = QLineEdit(); self.query_edit.setPlaceholderText("Type to search…")
        self.query_edit.textChanged.connect(self._on_query_changed)
        top.addWidget(self.query_edit, 1)
        top.addWidget(QLabel("Field:"))
        self.field_combo = QComboBox(); self.field_combo.addItems(["Any", "Title", "Artist", "Album", "Genre"])  # case-insensitive
        self.field_combo.currentIndexChanged.connect(lambda _: self._trigger_search())
        top.addWidget(self.field_combo)

        top.addWidget(QLabel("Source:"))
        self.source_combo = QComboBox()
        self.source_combo.currentIndexChanged.connect(lambda _: self._perform_search())
        top.addWidget(self.source_combo)
        b_refresh = QPushButton("Refresh")
        b_refresh.clicked.connect(self._refresh_sources)
        top.addWidget(b_refresh)

        b_reload = QPushButton("Reload DB")
        b_reload.clicked.connect(self._perform_search)
        top.addWidget(b_reload)
        b_clear = QPushButton("Clear")
        b_clear.clicked.connect(self._clear_results)
        top.addWidget(b_clear)
        root.addLayout(top)

        # Results table
        self.cols = ("artist", "album", "title", "genre", "duration", "path")
        self.table = QTableWidget(0, len(self.cols))
        self.table.setHorizontalHeaderLabels([c.title() for c in self.cols])
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setStretchLastSection(True)
        root.addWidget(self.table, 1)

        # Status
        self.status_label = QLabel("")
        root.addWidget(self.status_label)

        # Populate sources initially
        self._refresh_sources()
        self.status_label.setText("Type to search. Use Database tab to build the index.")

    # ---------- Actions ----------
    def _on_query_changed(self, _):
        self._trigger_search()

    def _trigger_search(self):
        # Debounce to avoid excessive filtering on every keystroke
        self._search_debounce.start()

    def _perform_search(self):
        query = (self.query_edit.text() or "").strip()
        field = (self.field_combo.currentText() or "Any").lower()
        try:
            ui_log('search_perform', query=query, field=field, source=str(self.source_combo.currentText()))
        except Exception:
            pass
        self.table.setRowCount(0)
        db_path = self._current_db_path()
        if not db_path or not os.path.isfile(db_path):
            self.status_label.setText("No index found for source. Open Database tab and Scan.")
            return
        if not query:
            # Show all entries when no search is active
            try:
                with sqlite3.connect(db_path) as conn:
                    cur = conn.execute("SELECT artist, album, title, genre, duration_seconds, path FROM tracks ORDER BY artist, album, track, title")
                    rows = cur.fetchall()
            except Exception as e:
                self.status_label.setText(f"DB error: {e}")
                return
            for (artist, album, title, genre, dur, path) in rows:
                info = {
                    'artist': artist or '',
                    'album': album or '',
                    'title': title or '',
                    'genre': genre or '',
                    'duration': self._fmt_duration(dur or 0),
                    'path': path or '',
                }
                self._insert_row(info)
            self.status_label.setText(f"Showing {len(rows)} track(s) from index.")
            return
        like = f"%{query}%"
        if field == 'any':
            where = "(IFNULL(title,'') LIKE ? OR IFNULL(artist,'') LIKE ? OR IFNULL(album,'') LIKE ? OR IFNULL(genre,'') LIKE ?)"
            params = [like, like, like, like]
        else:
            col = {'title':'title','artist':'artist','album':'album','genre':'genre'}.get(field, 'title')
            where = f"IFNULL({col},'') LIKE ?"
            params = [like]
        sql = f"SELECT artist, album, title, genre, duration_seconds, path FROM tracks WHERE {where} ORDER BY artist, album, track, title LIMIT 1000"
        try:
            with sqlite3.connect(db_path) as conn:
                cur = conn.execute(sql, params)
                rows = cur.fetchall()
        except Exception as e:
            self.status_label.setText(f"DB error: {e}")
            return
        for (artist, album, title, genre, dur, path) in rows:
            info = {
                'artist': artist or '',
                'album': album or '',
                'title': title or '',
                'genre': genre or '',
                'duration': self._fmt_duration(dur or 0),
                'path': path or '',
            }
            self._insert_row(info)
        self.status_label.setText(f"Matched {len(rows)} result(s).")

    def _clear_results(self):
        self.table.setRowCount(0)
        self.status_label.setText("")
        try:
            ui_log('search_clear')
        except Exception:
            pass

    def scan_library(self):
        if self._is_scanning:
            return
        base = self._selected_base_folder()
        if not base or not os.path.isdir(base):
            self.status_label.setText("Select a valid source (Library or Device).")
            return
        self._is_scanning = True
        self.status_label.setText("Scanning library…")
        self._all_tracks.clear()
        self.table.setRowCount(0)

    # Background scanning removed; Search queries the DB built by the Database tab.

    # Tag extraction removed; DB holds metadata.

    def _insert_row(self, info: Dict):
        row = self.table.rowCount()
        self.table.insertRow(row)
        vals = [info.get('artist',''), info.get('album',''), info.get('title',''), info.get('genre',''), info.get('duration',''), info.get('path','')]
        for col, val in enumerate(vals):
            self.table.setItem(row, col, QTableWidgetItem(str(val)))

    # ---------- Sources ----------
    def _refresh_sources(self):
        try:
            ui_log('search_refresh_sources')
        except Exception:
            pass
        self.source_combo.blockSignals(True)
        self.source_combo.clear()
        # Library option from settings
        self.source_combo.addItem("Library", { 'type': 'library' })
        try:
            devices = list_rockbox_devices()
        except Exception:
            devices = []
        for d in devices:
            label = d.get('name') or d.get('label') or d.get('mountpoint')
            mp = d.get('mountpoint')
            if not mp:
                continue
            self.source_combo.addItem(f"{label}", { 'type': 'device', 'mount': mp })
        self.source_combo.blockSignals(False)
        self._perform_search()

    def _selected_base_folder(self) -> str:
        data = self.source_combo.currentData()
        if not data or not isinstance(data, dict):
            return ''
        if data.get('type') == 'library':
            return self.controller.settings.get('music_root', '')
        if data.get('type') == 'device':
            mp = (data.get('mount') or '').rstrip('/\\')
            if not mp:
                return ''
            # Convention: Music folder on device
            return mp + '/Music'
        return ''

    def _current_db_path(self) -> str:
        data = self.source_combo.currentData()
        if not isinstance(data, dict):
            return ''
        if data.get('type') == 'device':
            mp = (data.get('mount') or '').rstrip('/\\')
            if mp:
                return str(Path(mp) / '.rocksync' / 'music_index.sqlite3')
            return ''
        return str(CONFIG_PATH.with_name('music_index.sqlite3'))

    @staticmethod
    def _fmt_duration(secs):
        try:
            secs = int(secs)
            return f"{secs//60}:{secs%60:02d}"
        except Exception:
            return ''
