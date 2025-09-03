import os
import threading
import queue
from logging_utils import ui_log
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QFileDialog, QTableWidget, QTableWidgetItem
)


class TracksPane(QWidget):
    def __init__(self, controller, parent):
        super().__init__(parent)
        self.controller = controller
        self._queue = queue.Queue()
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        top = QHBoxLayout()
        top.addWidget(QLabel("Folder:"))
        self.path_entry = QLineEdit(self.controller.settings.get("music_root", ""))
        top.addWidget(self.path_entry, 1)
        b = QPushButton("Browse"); b.clicked.connect(self._browse); top.addWidget(b)
        b2 = QPushButton("Use Music Root"); b2.clicked.connect(self._use_root); top.addWidget(b2)
        b3 = QPushButton("Scan"); b3.clicked.connect(self.scan); top.addWidget(b3)
        root.addLayout(top)

        self.cols = ("artist", "album", "title", "track", "format", "lyrics", "cover", "duration", "path")
        self.table = QTableWidget(0, len(self.cols))
        self.table.setHorizontalHeaderLabels([c.title() for c in self.cols])
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setStretchLastSection(True)
        root.addWidget(self.table, 1)

        self.status_label = QLabel("")
        root.addWidget(self.status_label)

        # Timer to flush background queue to UI
        self.flush_timer = QTimer(self)
        self.flush_timer.setInterval(100)
        self.flush_timer.timeout.connect(self._drain_queue)

    def _browse(self):
        path = QFileDialog.getExistingDirectory(self, "Select folder", self.path_entry.text() or os.getcwd())
        if path:
            self.path_entry.setText(path)

    def _use_root(self):
        self.path_entry.setText(self.controller.settings.get('music_root', ''))

    def scan(self):
        folder = self.path_entry.text().strip()
        if not folder or not os.path.isdir(folder):
            return
        self.table.setRowCount(0)
        self.status_label.setText("Scanning...")
        ui_log('tracks_scan_start', folder=folder)

        def worker():
            try:
                from mutagen import File as MFile  # noqa: F401
            except Exception as e:
                self._queue.put(("status", f"mutagen not installed: {e}"))
                return
            exts = {".flac", ".mp3", ".m4a"}
            count = 0
            for rootd, _, files in os.walk(folder):
                for name in files:
                    if os.path.splitext(name)[1].lower() not in exts:
                        continue
                    path = os.path.join(rootd, name)
                    info = self._extract_info(path)
                    self._queue.put(("row", info))
                    count += 1
            self._queue.put(("status", f"Done. {count} files."))
            self._queue.put(("end", count))

        threading.Thread(target=worker, daemon=True).start()
        self.flush_timer.start()

    def _drain_queue(self):
        try:
            while True:
                kind, payload = self._queue.get_nowait()
                if kind == 'row':
                    self._insert_row(payload)
                elif kind == 'status':
                    self.status_label.setText(str(payload))
                elif kind == 'end':
                    self.flush_timer.stop()
                    ui_log('tracks_scan_end', folder=self.path_entry.text().strip(), count=int(payload))
        except queue.Empty:
            pass

    def _extract_info(self, path):
        artist = album = title = track = ""
        fmt = os.path.splitext(path)[1].lower().lstrip(".")
        has_lyrics = False
        has_cover = False
        duration = ""
        try:
            from mutagen import File as MFile
            audio = MFile(path)
            if audio is not None:
                try:
                    from mutagen.easyid3 import EasyID3  # noqa
                    easy = MFile(path, easy=True)
                except Exception:
                    easy = None
                tags = getattr(easy, 'tags', None) or getattr(audio, 'tags', None) or {}
                def first(key, default=""):
                    v = tags.get(key)
                    return (v[0] if isinstance(v, list) and v else v) or default
                artist = first('artist', artist)
                album = first('album', album)
                title = first('title', os.path.basename(path))
                track = str(first('tracknumber', "")).split('/')[0]
                try:
                    if getattr(audio, 'info', None) and getattr(audio.info, 'length', None):
                        secs = int(audio.info.length)
                        duration = f"{secs//60}:{secs%60:02d}"
                except Exception:
                    pass
                try:
                    cname = audio.__class__.__name__.lower()
                    if 'flac' in cname and hasattr(audio, 'pictures'):
                        has_cover = any(getattr(p, 'type', None) == 3 for p in audio.pictures)
                    elif 'mp3' in cname and getattr(audio, 'tags', None):
                        has_cover = any(str(k).startswith('APIC') for k in audio.tags.keys())
                    elif ('mp4' in cname or 'm4a' in cname) and hasattr(audio, 'tags'):
                        has_cover = 'covr' in audio.tags
                except Exception:
                    pass
                if not has_cover:
                    if os.path.exists(os.path.join(os.path.dirname(path), 'cover.jpg')):
                        has_cover = True
                try:
                    if getattr(audio, 'tags', None):
                        for k in getattr(audio, 'tags', {}).keys():
                            key = str(k).lower()
                            if 'lyric' in key or 'uslt' in key:
                                has_lyrics = True
                                break
                    stem = os.path.splitext(os.path.basename(path))[0]
                    base_dir = os.path.dirname(path)
                    lyrics_paths = [
                        os.path.join(base_dir, f"{stem}{self.controller.settings.get('lyrics_ext', '.lrc')}"),
                        os.path.join(base_dir, self.controller.settings.get('lyrics_subdir', 'Lyrics'), f"{stem}{self.controller.settings.get('lyrics_ext', '.lrc')}")
                    ]
                    if any(os.path.exists(p) for p in lyrics_paths):
                        has_lyrics = True
                except Exception:
                    pass
        except Exception:
            pass
        return {
            'artist': artist, 'album': album, 'title': title, 'track': track,
            'format': fmt, 'lyrics': 'Yes' if has_lyrics else 'No', 'cover': 'Yes' if has_cover else 'No',
            'duration': duration, 'path': path
        }

    def _insert_row(self, info):
        row = self.table.rowCount()
        self.table.insertRow(row)
        vals = [info['artist'], info['album'], info['title'], info['track'], info['format'], info['lyrics'], info['cover'], info['duration'], info['path']]
        for col, val in enumerate(vals):
            self.table.setItem(row, col, QTableWidgetItem(str(val)))
