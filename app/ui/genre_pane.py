import os
import queue
import sqlite3
import threading
from functools import partial
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QSizePolicy, QGroupBox, QTableWidget, QTableWidgetItem, QComboBox, QAbstractItemView
)
from PySide6.QtWidgets import QHeaderView

from core import CONFIG_PATH
from logging_utils import ui_log


class GenreTaggerPane(QWidget):
    """Manually assign genres to tracks that are missing them in the library index."""

    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self._queue: List[Dict[str, str]] = []
        self._search_results: List[Dict[str, str]] = []
        self._pending_paths: Set[str] = set()
        self._job_queue: "queue.Queue[Dict[str, object]]" = queue.Queue()
        self._last_error: Optional[str] = None
        self._last_status: str = ""
        self._last_search_status: str = ""
        self._last_pending_count: int = 0
        self._worker_thread = threading.Thread(target=self._tag_worker_loop, daemon=True)
        self._worker_thread.start()
        self._build_ui()
        self._update_pending_indicator()
        self.reload_queue()

    # ---------- UI ----------
    def _build_ui(self):
        root = QVBoxLayout(self)

        self.progress_label = QLabel("Loading tracks…")
        self.progress_label.setObjectName("GenreProgressLabel")
        root.addWidget(self.progress_label)

        self.track_label = QLabel("")
        self.track_label.setWordWrap(True)
        self.track_label.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.track_label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.track_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        root.addWidget(self.track_label)

        self.path_label = QLabel("")
        self.path_label.setWordWrap(True)
        self.path_label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        self.path_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.path_label.setStyleSheet("color: #666;")
        root.addWidget(self.path_label)

        self.genre_edit = QLineEdit()
        self.genre_edit.setPlaceholderText("Enter genre and press Enter…")
        self.genre_edit.setClearButtonEnabled(True)
        self.genre_edit.returnPressed.connect(self._apply_current_genre)
        root.addWidget(self.genre_edit)

        buttons = QHBoxLayout()
        self.apply_btn = QPushButton("Save & Next")
        self.apply_btn.setProperty("accent", True)
        self.apply_btn.clicked.connect(self._apply_current_genre)
        buttons.addWidget(self.apply_btn)

        self.skip_btn = QPushButton("Skip")
        self.skip_btn.clicked.connect(self._skip_current)
        buttons.addWidget(self.skip_btn)

        self.reload_btn = QPushButton("Reload")
        self.reload_btn.clicked.connect(self.reload_queue)
        buttons.addWidget(self.reload_btn)

        buttons.addStretch(1)
        root.addLayout(buttons)

        self.status_label = QLabel("")
        self.status_label.setObjectName("GenreStatusLabel")
        root.addWidget(self.status_label)

        self.error_label = QLabel("")
        self.error_label.setObjectName("GenreErrorLabel")
        self.error_label.setWordWrap(True)
        self.error_label.setStyleSheet("color: #b33; font-style: italic;")
        root.addWidget(self.error_label)

        self.pending_label = QLabel("")
        self.pending_label.setObjectName("GenrePendingLabel")
        self.pending_label.setStyleSheet("color: #555;")
        root.addWidget(self.pending_label)

        # ---------- Search & edit section ----------
        search_group = QGroupBox("Search & Edit")
        search_layout = QVBoxLayout(search_group)

        search_row = QHBoxLayout()
        search_row.addWidget(QLabel("Field:"))
        self.search_field_combo = QComboBox()
        self.search_field_combo.addItems(["Any", "Title", "Artist", "Album", "Path"])
        search_row.addWidget(self.search_field_combo)

        search_row.addWidget(QLabel("Query:"))
        self.search_query_edit = QLineEdit()
        self.search_query_edit.setPlaceholderText("Type search text and press Enter…")
        self.search_query_edit.returnPressed.connect(self._perform_search)
        search_row.addWidget(self.search_query_edit, 1)

        self.search_btn = QPushButton("Search")
        self.search_btn.clicked.connect(self._perform_search)
        search_row.addWidget(self.search_btn)
        search_layout.addLayout(search_row)

        self.search_cols = ("artist", "album", "title", "genre", "path")
        self.search_table = QTableWidget(0, len(self.search_cols))
        self.search_table.setHorizontalHeaderLabels([c.title() for c in self.search_cols])
        self.search_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.search_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.search_table.setAlternatingRowColors(True)
        self.search_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.search_table.horizontalHeader().setStretchLastSection(True)
        self.search_table.verticalHeader().setVisible(False)
        self.search_table.itemSelectionChanged.connect(self._on_search_selection)
        search_layout.addWidget(self.search_table)

        edit_row = QHBoxLayout()
        edit_row.addWidget(QLabel("Genre:"))
        self.search_genre_edit = QLineEdit()
        self.search_genre_edit.setPlaceholderText("Update genre for selected track…")
        self.search_genre_edit.returnPressed.connect(self._apply_search_genre)
        edit_row.addWidget(self.search_genre_edit, 1)
        self.search_apply_btn = QPushButton("Apply")
        self.search_apply_btn.clicked.connect(self._apply_search_genre)
        self.search_apply_btn.setEnabled(False)
        edit_row.addWidget(self.search_apply_btn)
        search_layout.addLayout(edit_row)

        self.search_status_label = QLabel("")
        search_layout.addWidget(self.search_status_label)

        root.addWidget(search_group)
        root.addStretch(1)

    # ---------- Data loading ----------
    def _db_path(self) -> Path:
        return CONFIG_PATH.with_name('music_index.sqlite3')

    def reload_queue(self):
        db_path = self._db_path()
        self._queue.clear()
        self.genre_edit.clear()
        if not db_path.exists():
            self._set_status("Library index not found. Open Database tab and scan your library.")
            self._update_display()
            return
        try:
            with sqlite3.connect(str(db_path)) as conn:
                cursor = conn.execute(
                    """
                    SELECT path, IFNULL(artist,''), IFNULL(album,''), IFNULL(title,''), IFNULL(track,''), IFNULL(format,'')
                    FROM tracks
                    WHERE TRIM(IFNULL(genre,'')) = ''
                    ORDER BY artist, album, track, title
                    """
                )
                for row in cursor.fetchall():
                    path = row[0]
                    if not path:
                        continue
                    if path in self._pending_paths:
                        continue
                    self._queue.append({
                        'path': path,
                        'artist': row[1] or '',
                        'album': row[2] or '',
                        'title': row[3] or '',
                        'track': row[4] or '',
                        'format': row[5] or '',
                    })
        except Exception as exc:
            self._set_status(f"DB error: {exc}")
            self._update_display()
            return

        if self._queue:
            self._set_status(f"Loaded {len(self._queue)} track(s) without genre.")
        else:
            self._set_status("All indexed tracks already have a genre.")
        self._update_display()

    # ---------- Actions ----------
    def _current_entry(self) -> Optional[Dict[str, str]]:
        return self._queue[0] if self._queue else None

    def _apply_current_genre(self):
        entry = self._current_entry()
        if not entry:
            return
        genre = (self.genre_edit.text() or "").strip()
        if not genre:
            self._set_status("Enter a genre or use Skip to move on.")
            return
        context = {
            'zone': 'manual',
            'path': entry['path'],
            'genre': genre,
            'entry': dict(entry),
        }
        if not self._start_tag_update(context):
            return
        self._queue.pop(0)
        self.genre_edit.clear()
        title = entry['title'] or Path(entry['path']).name
        if genre:
            self._set_status(f"Queued genre '{genre}' for {title}.")
        else:
            self._set_status(f"Queued genre clearance for {title}.")
        self._update_display()
        self._clear_error()

    def _skip_current(self):
        entry = self._current_entry()
        if not entry:
            return
        skipped = self._queue.pop(0)
        try:
            ui_log('genre_manual_skip', path=skipped['path'])
        except Exception:
            pass
        title = skipped['title'] or Path(skipped['path']).name
        self.genre_edit.clear()
        self._set_status(f"Skipped {title}.")
        self._update_display()

    # ---------- Helpers ----------
    def _update_display(self):
        if not self._queue:
            self.progress_label.setText("No tracks pending.")
            self.track_label.setText("")
            self.path_label.setText("")
            self.genre_edit.setEnabled(False)
            self.apply_btn.setEnabled(False)
            self.skip_btn.setEnabled(False)
            return

        total = len(self._queue)
        entry = self._queue[0]
        title = entry['title'] or Path(entry['path']).stem
        artist = entry['artist']
        album = entry['album']
        track_no = entry['track']
        fmt = entry['format']

        parts = [title]
        sub = []
        if artist:
            sub.append(artist)
        if album:
            sub.append(album)
        if track_no:
            sub.append(f"Track {track_no}")
        if fmt:
            sub.append(fmt.upper())
        details = " • ".join(sub)

        self.progress_label.setText(f"Track 1 of {total}")
        self.track_label.setText(f"{parts[0]}" + (f"\n{details}" if details else ""))
        self.path_label.setText(entry['path'])
        self.genre_edit.setEnabled(True)
        self.apply_btn.setEnabled(True)
        self.skip_btn.setEnabled(True)
        self.genre_edit.setFocus(Qt.OtherFocusReason)

    # ---------- Search helpers ----------
    def _perform_search(self):
        db_path = self._db_path()
        if not db_path.exists():
            self._set_search_status("Library index not found. Open Database tab to scan.")
            self._clear_search_results()
            return
        field = (self.search_field_combo.currentText() or "Any").strip().lower()
        query = (self.search_query_edit.text() or "").strip()
        like = f"%{query}%"
        params: List[str] = []
        where = ""
        if query:
            if field == "any":
                where = "WHERE (IFNULL(title,'') LIKE ? OR IFNULL(artist,'') LIKE ? OR IFNULL(album,'') LIKE ? OR IFNULL(genre,'') LIKE ? OR IFNULL(path,'') LIKE ?)"
                params = [like, like, like, like, like]
            else:
                col = {
                    'title': 'title',
                    'artist': 'artist',
                    'album': 'album',
                    'path': 'path',
                }.get(field, 'title')
                where = f"WHERE IFNULL({col},'') LIKE ?"
                params = [like]
        sql = (
            "SELECT IFNULL(artist,''), IFNULL(album,''), IFNULL(title,''), IFNULL(genre,''), path "
            "FROM tracks "
            f"{where} ORDER BY artist, album, track, title LIMIT 200"
        )
        try:
            with sqlite3.connect(str(db_path)) as conn:
                cur = conn.execute(sql, params)
                rows = cur.fetchall()
        except Exception as exc:
            self._set_search_status(f"DB error: {exc}")
            self._clear_search_results()
            return

        self._search_results = [
            {
                'artist': r[0] or '',
                'album': r[1] or '',
                'title': r[2] or '',
                'genre': r[3] or '',
                'path': r[4] or '',
            }
            for r in rows
        ]
        self._populate_search_results()
        if query:
            self._set_search_status(f"Matched {len(self._search_results)} track(s).")
        else:
            self._set_search_status(f"Showing first {len(self._search_results)} track(s) from index.")

    def _populate_search_results(self):
        self.search_table.setRowCount(0)
        for info in self._search_results:
            row = self.search_table.rowCount()
            self.search_table.insertRow(row)
            for col, key in enumerate(self.search_cols):
                text = info.get(key, '')
                item = QTableWidgetItem(text)
                item.setFlags(Qt.ItemIsSelectable | Qt.ItemIsEnabled)
                self.search_table.setItem(row, col, item)
        self.search_table.resizeRowsToContents()
        self.search_table.clearSelection()
        self.search_genre_edit.clear()
        self.search_apply_btn.setEnabled(False)

    def _clear_search_results(self):
        self._search_results = []
        self.search_table.setRowCount(0)
        self.search_genre_edit.clear()
        self.search_apply_btn.setEnabled(False)

    def _on_search_selection(self):
        row = self.search_table.currentRow()
        if row < 0 or row >= len(self._search_results):
            self.search_genre_edit.clear()
            self.search_apply_btn.setEnabled(False)
            return
        info = self._search_results[row]
        self.search_genre_edit.setText(info.get('genre', ''))
        path = info.get('path', '')
        if path and path in self._pending_paths:
            self.search_apply_btn.setEnabled(False)
            self._set_search_status("Update pending for this track. Please wait.")
        else:
            self.search_apply_btn.setEnabled(True)

    def _apply_search_genre(self):
        row = self.search_table.currentRow()
        if row < 0 or row >= len(self._search_results):
            self._set_search_status("Select a track first.")
            return
        entry = self._search_results[row]
        genre = (self.search_genre_edit.text() or "").strip()
        context = {
            'zone': 'search',
            'row': row,
            'path': entry['path'],
            'genre': genre,
            'entry': dict(entry),
        }
        if not self._start_tag_update(context):
            return
        title = entry.get('title') or Path(entry.get('path', '')).name
        if genre:
            self._set_search_status(f"Queued genre update for {title} -> '{genre}'.")
        else:
            self._set_search_status(f"Queued genre clearance for {title}.")
        self.search_apply_btn.setEnabled(False)
        self._clear_error()

    def _remove_pending_entry(self, path: str):
        if not path:
            return
        removed = False
        for idx, info in enumerate(list(self._queue)):
            if info.get('path') == path:
                self._queue.pop(idx)
                removed = True
                break
        if removed:
            self._update_display()

    def _update_search_entry(self, path: str, genre: str):
        if not path:
            return
        for idx, info in enumerate(self._search_results):
            if info.get('path') == path:
                info['genre'] = genre
                item = self.search_table.item(idx, self.search_cols.index('genre'))
                if item is not None:
                    item.setText(genre)
                break

    def _start_tag_update(self, context: Dict[str, object]) -> bool:
        path = str(context.get('path', '')).strip()
        zone = str(context.get('zone', '')) or 'manual'
        if not path:
            message = "Missing file path."
            if zone == 'search':
                self._set_search_status(message)
            else:
                self._set_status(message)
            return False
        if path in self._pending_paths:
            message = "Already updating this track. Please wait."
            if zone == 'search':
                self._set_search_status(message)
            else:
                self._set_status(message)
            return False
        self._pending_paths.add(path)
        self._job_queue.put(dict(context))
        self._update_pending_indicator()
        genre = str(context.get('genre', ''))
        action = genre or '<clear>'
        print(f"[genre-pane] Queued {Path(path).name} -> {action}")
        return True

    def _tag_worker_loop(self):
        while True:
            context = self._job_queue.get()
            if context is None:
                break
            path = str(context.get('path', ''))
            genre = str(context.get('genre', ''))
            try:
                ok, msg = self._write_genre_to_file(path, genre)
                if ok:
                    db_ok, db_msg = self._update_database(path, genre)
                    if not db_ok:
                        ok = False
                        msg = db_msg
            except Exception as exc:
                ok = False
                msg = str(exc)
            QTimer.singleShot(0, partial(self._finish_tag_update, context, ok, msg))

    def _finish_tag_update(self, context: Dict[str, object], success: bool, message: str):
        zone = str(context.get('zone', '')) or 'manual'
        path = str(context.get('path', ''))
        genre = str(context.get('genre', ''))

        if path:
            self._pending_paths.discard(path)
        self._update_pending_indicator()

        if success:
            if zone == 'manual':
                entry = dict(context.get('entry', {}))
                title = entry.get('title') or Path(path).name
                try:
                    ui_log('genre_manual_update', path=path, genre=genre)
                except Exception:
                    pass
                if genre:
                    self._set_status(f"Set genre to '{genre}' for {title}.")
                else:
                    self._set_status(f"Cleared genre for {title}.")
                self._update_search_entry(path, genre)
                self._remove_pending_entry(path)
                self._update_display()
                self._clear_error()
            elif zone == 'search':
                row = int(context.get('row', -1))
                if 0 <= row < len(self._search_results):
                    entry = self._search_results[row]
                    entry['genre'] = genre
                    item = self.search_table.item(row, self.search_cols.index('genre'))
                    if item is not None:
                        item.setText(genre)
                    title = entry.get('title') or Path(entry.get('path', '')).name
                    self._set_search_status(f"Updated genre for {title}.")
                else:
                    self._set_search_status("Genre updated.")
                try:
                    ui_log('genre_search_update', path=path, genre=genre)
                except Exception:
                    pass
                self._remove_pending_entry(path)
            else:
                self._set_status("Genre updated.")
            if path:
                action = genre or '<clear>'
                print(f"[genre-pane] Completed {Path(path).name} -> {action}")
            self._clear_error()
        else:
            fallback = message or "Failed to update genre."
            if zone == 'manual':
                entry = dict(context.get('entry', {}))
                if entry:
                    self._queue.insert(0, entry)
                self._set_status(fallback)
                self._update_display()
                self.genre_edit.setText(genre)
            else:
                self._set_search_status(fallback)
            readable = self._format_error_message(path, message)
            print(f"[genre-pane] {readable}")
            self._report_error(readable)

        if not self._pending_paths and not self._queue:
            self.reload_queue()

        self._on_search_selection()


    def _write_genre_to_file(self, path: str, genre: str) -> Tuple[bool, str]:
        if not os.path.isfile(path):
            return False, "File not found on disk."
        try:
            from mutagen import File as MFile
        except Exception as exc:  # pragma: no cover - mutagen missing in dev envs
            return False, f"mutagen not installed: {exc}"
        try:
            audio = MFile(path, easy=True)
        except Exception as exc:
            return False, f"Could not read tags: {exc}"
        if audio is None:
            return False, "Unsupported audio file for tagging."

        tags = getattr(audio, 'tags', None)
        ext = Path(path).suffix.lower()

        if tags is None:
            if ext == '.mp3':
                try:
                    from mutagen.easyid3 import EasyID3  # type: ignore
                    try:
                        easy = EasyID3(path)
                    except Exception:
                        easy = EasyID3()
                    if genre:
                        easy['genre'] = [genre]
                        easy.save(path)
                    else:
                        easy.pop('genre', None)
                        if list(easy.keys()):
                            easy.save(path)
                    return True, "ok"
                except Exception as exc:
                    return False, f"Could not initialize ID3 tags: {exc}"
            else:
                try:
                    full = MFile(path)
                except Exception:
                    full = None
                if full is not None and getattr(full, 'tags', None) is None and hasattr(full, 'add_tags'):
                    try:
                        full.add_tags()
                        full.save()
                        audio = MFile(path, easy=True)
                        tags = getattr(audio, 'tags', None)
                    except Exception:
                        tags = None

        if tags is None:
            return False, "File has no editable tags."

        try:
            if genre:
                tags['genre'] = [genre]
            else:
                tags.pop('genre', None)
            audio.save()
        except Exception as exc:
            return False, f"Could not save tags: {exc}"
        return True, "ok"

    def _update_database(self, path: str, genre: str) -> Tuple[bool, str]:
        db_path = self._db_path()
        if not db_path.exists():
            return False, "Library index not found."
        try:
            with sqlite3.connect(str(db_path)) as conn:
                conn.execute("UPDATE tracks SET genre = ? WHERE path = ?", (genre, path))
                conn.commit()
        except Exception as exc:
            return False, f"DB update failed: {exc}"
        return True, "ok"

    def _status_suffix(self) -> str:
        count = len(self._pending_paths)
        return f" (pending: {count})" if count else ""

    def _set_status(self, text: str):
        self._last_status = text or ""
        self.status_label.setText(self._compose_status_text(self._last_status))

    def _set_search_status(self, text: str):
        self._last_search_status = text or ""
        self.search_status_label.setText(self._compose_status_text(self._last_search_status))

    def _compose_status_text(self, base: str) -> str:
        suffix = self._status_suffix()
        if base:
            return f"{base}{suffix}"
        return suffix.lstrip() if suffix else ""

    def _report_error(self, message: str):
        self._last_error = message
        self.error_label.setText(message)

    def _clear_error(self):
        self._last_error = None
        self.error_label.setText("")

    @staticmethod
    def _format_error_message(path: str, message: str) -> str:
        details = message or "Unknown error while writing tags."
        basename = Path(path).name if path else "<unknown>"
        return f"Error updating {basename}: {details}"

    def _update_pending_indicator(self):
        count = len(self._pending_paths)
        just_cleared = self._last_pending_count > 0 and count == 0

        if count:
            self.pending_label.setText(f"Pending updates: {count}")
        else:
            self.pending_label.setText("Pending updates: 0 (idle)")

        if just_cleared:
            print("[genre-pane] All pending genre updates completed.")
            if not self._last_status:
                self._last_status = "All pending updates completed."

        self.status_label.setText(self._compose_status_text(self._last_status))
        self.search_status_label.setText(self._compose_status_text(self._last_search_status))

        self._last_pending_count = count
