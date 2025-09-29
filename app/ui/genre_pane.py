import html
import io
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from PySide6.QtCore import Qt, QUrl, QRunnable, QThreadPool, Signal, QObject
from PySide6.QtGui import QPixmap, QColor, QPalette
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QSizePolicy, QGroupBox, QTableWidget, QTableWidgetItem, QComboBox, QAbstractItemView
)
from PySide6.QtWidgets import QHeaderView

try:  # Optional dependency in some PySide builds
    from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
except Exception:  # pragma: no cover - fallback when QtMultimedia is unavailable
    QAudioOutput = None  # type: ignore
    QMediaPlayer = None  # type: ignore

from core import CONFIG_PATH, ROOT
from logging_utils import ui_log
from rockbox_utils import list_rockbox_devices


class GenreSuggestionWorkerSignals(QObject):
    finished = Signal(int, list, str)


class GenreSuggestionWorker(QRunnable):
    def __init__(self, task_id: int, title: str, artist: str, album: str, limit: int):
        super().__init__()
        self.task_id = task_id
        self.title = title
        self.artist = artist
        self.album = album
        self.limit = max(1, limit)
        self.signals = GenreSuggestionWorkerSignals()

    def run(self):
        genres: List[str] = []
        error = ""
        script_path = ROOT / 'scripts' / 'search_genres.py'
        if not script_path.exists():
            error = "Genre lookup script missing."
            self.signals.finished.emit(self.task_id, genres, error)
            return
        cmd = [sys.executable or 'python3', str(script_path), '--title', self.title, '--max-genres', str(self.limit), '--json']
        if self.artist:
            cmd.extend(['--artist', self.artist])
        if self.album:
            cmd.extend(['--album', self.album])
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
            if result.returncode == 0:
                try:
                    data = json.loads(result.stdout or '{}')
                    genres = [g for g in data.get('genres', []) if isinstance(g, str)]
                except Exception:
                    error = "Failed to parse genre suggestions."
            elif result.returncode == 3:
                genres = []
            else:
                err_text = result.stderr.strip() or result.stdout.strip()
                error = err_text or f"Suggestion lookup failed (code {result.returncode})."
        except subprocess.TimeoutExpired:
            error = "Genre suggestion lookup timed out."
        except Exception as exc:  # pragma: no cover - safeguard against unexpected runtime issues
            error = f"Suggestion lookup error: {exc}"
        self.signals.finished.emit(self.task_id, genres, error)


class GenreTaggerPane(QWidget):
    """Manually assign genres to tracks that are missing them in the library index."""

    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self._queue: List[Dict[str, str]] = []
        self._search_results: List[Dict[str, str]] = []
        self._last_error: Optional[str] = None
        self._last_status: str = ""
        self._last_search_status: str = ""
        self._suppress_source_apply = True
        self._audio_player: Optional["QMediaPlayer"] = None
        self._audio_output: Optional["QAudioOutput"] = None
        self._preview_path: Optional[str] = None
        self._thread_pool = QThreadPool(self)
        self._suggestion_task_id = 0
        self._last_suggestion_source: Optional[str] = None
        self._build_ui()
        self._init_audio()
        self._suppress_source_apply = False
        self._apply_source_change()

    # ---------- UI ----------
    def _build_ui(self):
        root = QVBoxLayout(self)

        source_row = QHBoxLayout()
        source_row.addWidget(QLabel("Source:"))
        self.source_combo = QComboBox()
        self.source_combo.currentIndexChanged.connect(self._on_source_changed)
        self.source_combo.setSizeAdjustPolicy(QComboBox.AdjustToContents)
        source_row.addWidget(self.source_combo, 1)
        self.source_refresh_btn = QPushButton("Refresh")
        self.source_refresh_btn.clicked.connect(self._refresh_sources)
        source_row.addWidget(self.source_refresh_btn)
        source_row.addStretch(1)
        root.addLayout(source_row)

        self.progress_label = QLabel("Loading tracks…")
        self.progress_label.setObjectName("GenreProgressLabel")
        root.addWidget(self.progress_label)

        self.track_label = QLabel("")
        self.track_label.setWordWrap(True)
        self.track_label.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.track_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.track_label.setMinimumWidth(0)
        self.track_label.setTextFormat(Qt.RichText)
        self.track_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        root.addWidget(self.track_label)

        cover_row = QHBoxLayout()
        cover_row.setSpacing(16)
        self.cover_label = QLabel("No cover art")
        self.cover_label.setObjectName("GenreCoverLabel")
        self.cover_label.setAlignment(Qt.AlignCenter)
        self.cover_label.setMinimumSize(160, 160)
        self.cover_label.setMaximumSize(240, 240)
        self.cover_label.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.cover_label.setStyleSheet("border: 1px solid rgba(0,0,0,0.2); padding: 4px;")
        cover_row.addWidget(self.cover_label)

        self.suggest_panel = QWidget()
        self.suggest_panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        suggest_layout = QVBoxLayout(self.suggest_panel)
        suggest_layout.setContentsMargins(0, 0, 0, 0)
        suggest_layout.setSpacing(6)
        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.setSpacing(8)
        self.suggest_header = QLabel("Suggested genres")
        self.suggest_header.setStyleSheet("font-weight: 600;")
        header_row.addWidget(self.suggest_header)
        header_row.addStretch(1)
        self.suggest_refresh_btn = QPushButton("Refresh")
        self.suggest_refresh_btn.setFixedHeight(26)
        self.suggest_refresh_btn.setEnabled(False)
        self.suggest_refresh_btn.clicked.connect(self._refresh_suggestions)
        header_row.addWidget(self.suggest_refresh_btn)
        suggest_layout.addLayout(header_row)

        self.suggest_status = QLabel("Suggestions unavailable")
        self.suggest_status.setWordWrap(True)
        self.suggest_status.setStyleSheet("color: #666;")
        suggest_layout.addWidget(self.suggest_status)

        self.suggest_pill_host = QWidget()
        self.suggest_pill_layout = QHBoxLayout(self.suggest_pill_host)
        self.suggest_pill_layout.setContentsMargins(0, 0, 0, 0)
        self.suggest_pill_layout.setSpacing(8)
        self.suggest_pill_layout.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        suggest_layout.addWidget(self.suggest_pill_host)
        self.suggest_pill_host.setVisible(False)

        cover_row.addWidget(self.suggest_panel)
        root.addLayout(cover_row)

        self.path_label = QLabel("")
        self.path_label.setWordWrap(True)
        self.path_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.path_label.setMinimumWidth(0)
        self.path_label.setTextFormat(Qt.RichText)
        self.path_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.path_label.setStyleSheet("color: #666;")
        root.addWidget(self.path_label)

        self.genre_edit = QLineEdit()
        self.genre_edit.setPlaceholderText("Enter genre and press Enter…")
        self.genre_edit.setClearButtonEnabled(True)
        self.genre_edit.returnPressed.connect(self._apply_current_genre)
        root.addWidget(self.genre_edit)

        buttons = QHBoxLayout()
        self.preview_play_btn = QPushButton("Listen")
        self.preview_play_btn.clicked.connect(self._play_preview)
        self.preview_play_btn.setEnabled(False)
        buttons.addWidget(self.preview_play_btn)

        self.preview_stop_btn = QPushButton("Stop")
        self.preview_stop_btn.clicked.connect(self._stop_preview)
        self.preview_stop_btn.setEnabled(False)
        buttons.addWidget(self.preview_stop_btn)

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

        self._refresh_sources()

    def _init_audio(self):
        if not hasattr(self, 'preview_play_btn'):
            return
        if QMediaPlayer is None or QAudioOutput is None:
            self.preview_play_btn.setToolTip("Audio preview requires QtMultimedia support.")
            self.preview_play_btn.setEnabled(False)
            self.preview_stop_btn.setEnabled(False)
            return
        try:
            self._audio_output = QAudioOutput(self)
            self._audio_player = QMediaPlayer(self)
            self._audio_player.setAudioOutput(self._audio_output)
            self._audio_player.playbackStateChanged.connect(self._on_playback_state_changed)
            self._audio_player.errorOccurred.connect(self._on_audio_error)
        except Exception:
            self._audio_output = None
            self._audio_player = None
            self.preview_play_btn.setEnabled(False)
            self.preview_stop_btn.setEnabled(False)
            self.preview_play_btn.setToolTip("Audio preview failed to initialize.")
        else:
            self.preview_play_btn.setToolTip("")

    # ---------- Data loading ----------
    def _db_path(self) -> Path:
        data = self.source_combo.currentData()
        if isinstance(data, dict) and data.get('type') == 'device':
            mount = (data.get('mount') or '').rstrip('/\\')
            if mount:
                return Path(mount) / '.rocksync' / 'music_index.sqlite3'
        return CONFIG_PATH.with_name('music_index.sqlite3')

    def _refresh_sources(self):
        previous = self.source_combo.currentData()
        self.source_combo.blockSignals(True)
        self.source_combo.clear()
        self.source_combo.addItem("Library", {'type': 'library'})
        try:
            devices = list_rockbox_devices()
        except Exception:
            devices = []
        target_index = 0
        for offset, device in enumerate(devices, start=1):
            label = device.get('name') or device.get('label') or device.get('mountpoint')
            mount = device.get('mountpoint')
            if not mount:
                continue
            data = {'type': 'device', 'mount': mount}
            self.source_combo.addItem(f"Device: {label}", data)
            if previous and isinstance(previous, dict):
                if previous.get('type') == data.get('type') == 'device' and previous.get('mount') == mount:
                    target_index = self.source_combo.count() - 1
        if target_index >= self.source_combo.count():
            target_index = 0
        self.source_combo.setCurrentIndex(target_index)
        self.source_combo.blockSignals(False)
        try:
            ui_log('genre_sources_refreshed', selected=self.source_combo.currentText())
        except Exception:
            pass
        if not getattr(self, '_suppress_source_apply', False):
            self._apply_source_change()

    def _on_source_changed(self):
        self._apply_source_change()

    def _apply_source_change(self):
        if getattr(self, '_suppress_source_apply', False):
            return
        self.reload_queue()
        # Keep search results aligned with source
        if self.search_query_edit.text() or self.search_table.rowCount():
            self._perform_search()
        else:
            self._clear_search_results()
            self._set_search_status("")

    def reload_queue(self):
        self._stop_preview()
        db_path = self._db_path()
        self._queue.clear()
        self.genre_edit.clear()
        source_name = self.source_combo.currentText() or "Library"
        if not db_path.exists():
            self._set_status(f"{source_name}: Library index not found. Open Database tab and scan this source.")
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
                    self._queue.append({
                        'path': path,
                        'artist': row[1] or '',
                        'album': row[2] or '',
                        'title': row[3] or '',
                        'track': row[4] or '',
                        'format': row[5] or '',
                    })
        except Exception as exc:
            self._set_status(f"{source_name}: DB error: {exc}")
            self._update_display()
            return

        if self._queue:
            self._set_status(f"{source_name}: Loaded {len(self._queue)} track(s) without genre.")
        else:
            self._set_status(f"{source_name}: All indexed tracks already have a genre.")
        self._update_display()

    # ---------- Actions ----------
    def _current_entry(self) -> Optional[Dict[str, str]]:
        return self._queue[0] if self._queue else None

    def _apply_current_genre(self):
        self._stop_preview()
        entry = self._current_entry()
        if not entry:
            return
        genre = (self.genre_edit.text() or "").strip()
        if not genre:
            self._set_status("Enter a genre or use Skip to move on.")
            return
        path = entry['path']
        ok, msg = self._update_genre_for_path(path, genre)
        if not ok:
            self._set_status(msg or "Failed to update genre.")
            readable = self._format_error_message(path, msg)
            self._report_error(readable)
            self.genre_edit.setText(genre)
            try:
                ui_log('genre_update_failed', path=path, genre=genre, zone='manual', source=self.source_combo.currentText() or "Library", error=msg)
            except Exception:
                pass
            return

        title = entry['title'] or Path(path).name
        self._queue.pop(0)
        self.genre_edit.clear()
        self._update_search_entry(path, genre)
        self._clear_error()
        if not self._queue:
            self.reload_queue()
        else:
            self._update_display()
        self._set_status(f"Set genre to '{genre}' for {title}.")
        try:
            ui_log('genre_manual_update', path=path, genre=genre)
            ui_log('genre_update_completed', path=path, genre=genre, zone='manual', source=self.source_combo.currentText() or "Library")
        except Exception:
            pass

    def _skip_current(self):
        self._stop_preview()
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
            self.track_label.setToolTip("")
            self.path_label.setToolTip("")
            self._set_cover_placeholder()
            self.genre_edit.setEnabled(False)
            self.apply_btn.setEnabled(False)
            self.skip_btn.setEnabled(False)
            self.preview_play_btn.setEnabled(False)
            self.preview_stop_btn.setEnabled(False)
            self.suggest_refresh_btn.setEnabled(False)
            self._clear_suggestions(status="Suggestions unavailable")
            self._last_suggestion_source = None
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
        self.track_label.setText(self._render_track_label(parts[0], details))
        self.track_label.setToolTip(f"{parts[0]}" + (f"\n{details}" if details else ""))
        display_path = entry['path']
        self.path_label.setText(self._render_wrapped_path(display_path))
        self.path_label.setToolTip(display_path)
        self._update_cover(display_path)
        self.genre_edit.setEnabled(True)
        self.apply_btn.setEnabled(True)
        self.skip_btn.setEnabled(True)
        self.preview_play_btn.setEnabled(self._audio_player is not None and os.path.isfile(display_path))
        self.preview_stop_btn.setEnabled(False)
        self.suggest_refresh_btn.setEnabled(True)
        self._schedule_suggestions(entry)
        self.genre_edit.setFocus(Qt.OtherFocusReason)

    def _play_preview(self):
        if self._audio_player is None:
            self._set_status("Audio preview not available on this system.")
            return
        entry = self._current_entry()
        if not entry:
            return
        path = entry.get('path') or ''
        if not path or not os.path.isfile(path):
            self._set_status("Audio file not found for preview.")
            return
        self._stop_preview()
        try:
            self._audio_player.setSource(QUrl.fromLocalFile(path))
            self._audio_player.play()
            self._preview_path = path
            btn = getattr(self, 'preview_stop_btn', None)
            if btn is not None:
                btn.setEnabled(True)
            try:
                ui_log('genre_preview_play', path=path)
            except Exception:
                pass
        except Exception as exc:
            self._report_error(f"Preview error: {exc}")
            btn = getattr(self, 'preview_stop_btn', None)
            if btn is not None:
                btn.setEnabled(False)

    def _stop_preview(self, *_):
        if self._audio_player is not None:
            try:
                if self._audio_player.playbackState() != QMediaPlayer.StoppedState:
                    self._audio_player.stop()
            except Exception:
                pass
        self._preview_path = None
        btn = getattr(self, 'preview_stop_btn', None)
        if btn is not None:
            btn.setEnabled(False)

    def _on_playback_state_changed(self, state):
        if QMediaPlayer is None:
            return
        playing = state == QMediaPlayer.PlayingState
        btn = getattr(self, 'preview_stop_btn', None)
        if btn is not None:
            btn.setEnabled(playing)
        if not playing:
            self._preview_path = None

    def _on_audio_error(self, error, error_string=''):
        if not error:
            return
        message = error_string or "Audio preview failed."
        self._report_error(f"Preview error: {message}")
        btn = getattr(self, 'preview_stop_btn', None)
        if btn is not None:
            btn.setEnabled(False)
        self._preview_path = None

    def _update_cover(self, path: str):
        if not path or not os.path.isfile(path):
            self._set_cover_placeholder()
            return
        img_bytes = self._extract_cover_bytes(path)
        if img_bytes and self._set_cover_from_bytes(img_bytes):
            self.cover_label.setToolTip("Embedded artwork")
            return
        cover_file = self._find_cover_file(path)
        if cover_file:
            pix = QPixmap(cover_file)
            if not pix.isNull():
                self._set_cover_pixmap(pix, cover_file)
                return
        self._set_cover_placeholder()

    def _set_cover_placeholder(self):
        if hasattr(self, 'cover_label'):
            self.cover_label.setPixmap(QPixmap())
            self.cover_label.setText("No cover art")
            self.cover_label.setToolTip("")

    def _set_cover_from_bytes(self, img_bytes: bytes) -> bool:
        pix = QPixmap()
        if pix.loadFromData(img_bytes):
            self._set_cover_pixmap(pix, "Embedded artwork")
            return True
        try:
            from PIL import Image
            data = io.BytesIO(img_bytes)
            im = Image.open(data).convert('RGB')
            buf = io.BytesIO()
            im.save(buf, format='PNG')
            buf.seek(0)
            pix_alt = QPixmap()
            if pix_alt.loadFromData(buf.getvalue()):
                self._set_cover_pixmap(pix_alt, "Embedded artwork")
                return True
        except Exception:
            pass
        return False

    @staticmethod
    def _find_cover_file(path: str) -> Optional[str]:
        base_dir = os.path.dirname(path)
        for name in ("cover.jpg", "folder.jpg", "front.jpg", "cover.png", "folder.png", "front.png"):
            candidate = os.path.join(base_dir, name)
            if os.path.isfile(candidate):
                return candidate
        return None

    def _extract_cover_bytes(self, path: str) -> Optional[bytes]:
        try:
            from mutagen import File as MFile
            audio = MFile(path)
        except Exception:
            return None
        if audio is None:
            return None
        try:
            if hasattr(audio, 'pictures') and getattr(audio, 'pictures'):
                pics = sorted(audio.pictures, key=lambda p: 0 if getattr(p, 'type', None) == 3 else 1)
                if pics:
                    return getattr(pics[0], 'data', None)
            tags = getattr(audio, 'tags', None)
            if tags:
                items_iter = []
                try:
                    items_iter = list(tags.items())  # type: ignore[arg-type]
                except Exception:
                    try:
                        keys = list(getattr(tags, 'keys')())  # type: ignore[call-arg]
                        items_iter = [(k, tags[k]) for k in keys]
                    except Exception:
                        items_iter = []
                for key, value in items_iter:
                    try:
                        k = str(key).lower()
                    except Exception:
                        k = ''
                    if k.startswith('apic'):
                        data = getattr(value, 'data', None)
                        if data:
                            return data
                covr = None
                try:
                    if hasattr(tags, 'get'):
                        covr = tags.get('covr')  # type: ignore[index]
                    elif hasattr(tags, '__contains__') and 'covr' in tags:  # type: ignore[operator]
                        covr = tags['covr']  # type: ignore[index]
                except Exception:
                    covr = None
                if covr:
                    if isinstance(covr, list) and covr:
                        return bytes(covr[0])
                    data = getattr(covr, 'data', None)
                    if data:
                        return bytes(data)
        except Exception:
            return None
        return None

    def _set_cover_pixmap(self, pixmap: QPixmap, source: str = ""):
        if pixmap.isNull():
            self._set_cover_placeholder()
            return
        scaled = pixmap.scaled(220, 220, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.cover_label.setPixmap(scaled)
        self.cover_label.setText("")
        self.cover_label.setToolTip(source)

    def _clear_suggestions(self, status: str = ""):
        self._set_suggestion_status(status or "")
        while self.suggest_pill_layout.count():
            item = self.suggest_pill_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        if hasattr(self, 'suggest_pill_host'):
            self.suggest_pill_host.setVisible(False)

    def _set_suggestion_status(self, text: str, *, is_error: bool = False):
        if not text:
            self.suggest_status.hide()
            return
        self.suggest_status.show()
        self.suggest_status.setText(text)
        if is_error:
            self.suggest_status.setStyleSheet("color: #b33;")
        else:
            self.suggest_status.setStyleSheet("color: #666;")

    def _refresh_suggestions(self):
        entry = self._current_entry()
        if not entry:
            return
        self._schedule_suggestions(entry, force=True)

    def _schedule_suggestions(self, entry: Dict[str, str], force: bool = False):
        path = entry.get('path') or ''
        source_key = f"{path}::{entry.get('title','')}::{entry.get('artist','')}::{entry.get('album','')}"
        if not force and source_key == self._last_suggestion_source:
            return
        title = entry.get('title') or Path(path).stem
        artist = entry.get('artist') or ''
        album = entry.get('album') or ''
        if not title:
            self._clear_suggestions("Metadata missing for genre suggestions.")
            self.suggest_refresh_btn.setEnabled(False)
            self._last_suggestion_source = None
            return
        self._last_suggestion_source = source_key
        self._suggestion_task_id += 1
        task_id = self._suggestion_task_id
        self._clear_suggestions()
        self._set_suggestion_status("Fetching suggestions…")
        self.suggest_refresh_btn.setEnabled(False)
        limit = 5
        worker = GenreSuggestionWorker(task_id, title, artist, album, limit)
        worker.signals.finished.connect(self._on_suggestions_ready)
        self._thread_pool.start(worker)

    def _on_suggestions_ready(self, task_id: int, genres: List[str], error: str):
        if task_id != self._suggestion_task_id:
            return
        self.suggest_refresh_btn.setEnabled(True)
        if error:
            self._clear_suggestions()
            self._set_suggestion_status(error, is_error=True)
            try:
                entry = self._current_entry()
                if entry:
                    ui_log('genre_suggestions_error', path=entry.get('path'), error=error)
            except Exception:
                pass
            return
        if not genres:
            self._clear_suggestions("No suggestions found.")
            try:
                entry = self._current_entry()
                if entry:
                    ui_log('genre_suggestions_empty', path=entry.get('path'))
            except Exception:
                pass
            return
        self._clear_suggestions()
        self.suggest_status.hide()
        for genre in genres:
            self._add_suggestion_pill(genre)
        try:
            entry = self._current_entry()
            if entry:
                ui_log('genre_suggestions_ready', path=entry.get('path'), genres=genres)
        except Exception:
            pass

    def _add_suggestion_pill(self, genre: str):
        pill = QPushButton(genre)
        pill.setCursor(Qt.PointingHandCursor)
        pill.setStyleSheet(self._pill_style_sheet())
        pill.clicked.connect(lambda _=False, g=genre: self.genre_edit.setText(g))
        self.suggest_pill_layout.addWidget(pill)
        self.suggest_pill_host.setVisible(True)

    def _pill_style_sheet(self) -> str:
        palette = self.suggest_panel.palette() if hasattr(self, 'suggest_panel') else self.palette()
        accent = palette.color(QPalette.Highlight)
        if not accent.isValid():
            accent = palette.color(QPalette.ButtonText)
        if not accent.isValid():
            accent = QColor(30, 100, 220)

        accent_hsv = accent.toHsv()
        base = QColor(accent)
        base.setHsv(accent_hsv.hue(), max(90, int(accent_hsv.saturation() * 0.7)), min(255, int(accent_hsv.value() * 0.85)))

        window = palette.color(QPalette.Window)
        luminance = 0.299 * window.red() + 0.587 * window.green() + 0.114 * window.blue()
        is_dark = luminance < 110

        if is_dark:
            bg = QColor(accent.lighter(190))
            text = QColor(248, 248, 255)
        else:
            bg = QColor(base)
            text = QColor(accent.darker(140))

        bg.setAlpha(220 if is_dark else 245)
        border = QColor(bg)
        border.setAlpha(210 if is_dark else 160)
        hover = QColor(bg.lighter(112 if not is_dark else 125))
        hover.setAlpha(min(255, bg.alpha() + 20))
        pressed = QColor(bg.darker(120))
        pressed.setAlpha(min(255, bg.alpha() + 30))


        def rgba(c: QColor) -> str:
            return f"{c.red()},{c.green()},{c.blue()},{c.alpha()}"

        return (
            "QPushButton {"
            f"background-color: rgba({rgba(bg)});"
            f"border: 1px solid rgba({rgba(border)});"
            "border-radius: 22px;"
            "padding: 6px 18px;"
            "font-weight: 600;"
            "min-height: 32px;"
            f"color: rgb({text.red()},{text.green()},{text.blue()});"
            "}"
            "QPushButton:hover {"
            f"background-color: rgba({rgba(hover)});"
            "}"
            "QPushButton:pressed {"
            f"background-color: rgba({rgba(pressed)});"
            "}"
        )

    # ---------- Search helpers ----------
    def _perform_search(self):
        db_path = self._db_path()
        source_name = self.source_combo.currentText() or "Library"
        if not db_path.exists():
            self._set_search_status(f"{source_name}: Library index not found. Open Database tab to scan.")
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
            self._set_search_status(f"{source_name}: DB error: {exc}")
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
            self._set_search_status(f"{source_name}: Matched {len(self._search_results)} track(s).")
        else:
            self._set_search_status(f"{source_name}: Showing first {len(self._search_results)} track(s) from index.")

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
        self.search_apply_btn.setEnabled(bool(path))

    def _apply_search_genre(self):
        row = self.search_table.currentRow()
        if row < 0 or row >= len(self._search_results):
            self._set_search_status("Select a track first.")
            return
        entry = self._search_results[row]
        genre = (self.search_genre_edit.text() or "").strip()
        path = entry.get('path', '')
        if not path:
            self._set_search_status("Missing track path.")
            return

        ok, msg = self._update_genre_for_path(path, genre)
        if not ok:
            self._set_search_status(msg or "Failed to update genre.")
            readable = self._format_error_message(path, msg)
            self._report_error(readable)
            try:
                ui_log('genre_update_failed', path=path, genre=genre, zone='search', source=self.source_combo.currentText() or "Library", error=msg)
            except Exception:
                pass
            return

        entry['genre'] = genre
        item = self.search_table.item(row, self.search_cols.index('genre'))
        if item is not None:
            item.setText(genre)
        title = entry.get('title') or Path(path).name
        if genre:
            self._set_search_status(f"Updated genre for {title}.")
        else:
            self._set_search_status(f"Cleared genre for {title}.")
        self._remove_queue_entry(path)
        self._clear_error()
        self.search_apply_btn.setEnabled(False)
        try:
            ui_log('genre_search_update', path=path, genre=genre)
            ui_log('genre_update_completed', path=path, genre=genre, zone='search', source=self.source_combo.currentText() or "Library")
        except Exception:
            pass

    def _remove_queue_entry(self, path: str):
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

    def _update_genre_for_path(self, path: str, genre: str) -> Tuple[bool, str]:
        """Write the genre to disk and update the matching index row."""
        try:
            db_path = str(self._db_path())
        except Exception:
            db_path = ""

        ok, msg = self._write_genre_to_file(path, genre)
        if not ok:
            return False, msg

        db_ok, db_msg = self._update_database(path, genre, db_path)
        if not db_ok:
            return False, db_msg

        return True, "ok"

    @staticmethod
    def _render_track_label(title: str, details: str) -> str:
        safe_title = html.escape(title or '')
        if details:
            safe_details = html.escape(details)
            return f"<span>{safe_title}</span><br/><small>{safe_details}</small>"
        return safe_title

    @staticmethod
    def _render_wrapped_path(path: str) -> str:
        if not path:
            return ''
        safe = html.escape(path)
        safe = safe.replace('/', '/<wbr>')
        safe = safe.replace(chr(92), f"{chr(92)}<wbr>")
        return f"<span style='white-space:normal;'>{safe}</span>"

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

    def _update_database(self, path: str, genre: str, override: Optional[str]) -> Tuple[bool, str]:
        if override:
            db_path = Path(override)
        else:
            db_path = CONFIG_PATH.with_name('music_index.sqlite3')
        if not db_path.exists():
            return False, "Library index not found."
        try:
            with sqlite3.connect(str(db_path)) as conn:
                conn.execute("UPDATE tracks SET genre = ? WHERE path = ?", (genre, path))
                conn.commit()
        except Exception as exc:
            return False, f"DB update failed: {exc}"
        return True, "ok"

    def _set_status(self, text: str):
        self._last_status = text or ""
        self.status_label.setText(self._last_status)

    def _set_search_status(self, text: str):
        self._last_search_status = text or ""
        self.search_status_label.setText(self._last_search_status)

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
