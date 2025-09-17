import os
import sqlite3
import hashlib
import threading
import queue
from typing import Dict, List
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QTableWidget, QTableWidgetItem, QComboBox
)

from core import CONFIG_PATH
from rockbox_utils import list_rockbox_devices


class DatabasePane(QWidget):
    """Indexes the local library into a SQLite database and displays results."""

    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.db_path = None  # resolved based on selected source
        self._queue: queue.Queue = queue.Queue()
        self._is_scanning = False
        self._build_ui()
        self._refresh_sources()
        self._update_db_path_and_load()

    # ---------- UI ----------
    def _build_ui(self):
        root = QVBoxLayout(self)

        top = QHBoxLayout()
        top.addWidget(QLabel("Source:"))
        self.source_combo = QComboBox()
        self.source_combo.currentIndexChanged.connect(lambda _: self._update_db_path_and_load())
        top.addWidget(self.source_combo)
        self.refresh_sources_btn = QPushButton("Refresh")
        self.refresh_sources_btn.clicked.connect(self._refresh_sources)
        top.addWidget(self.refresh_sources_btn)

        self.scan_btn = QPushButton("Scan")
        self.scan_btn.clicked.connect(self.scan_library)
        top.addWidget(self.scan_btn)
        self.refresh_btn = QPushButton("Reload DB")
        self.refresh_btn.clicked.connect(self.load_from_db)
        top.addWidget(self.refresh_btn)
        top.addWidget(QLabel("Filter:"))
        self.filter_edit = QLineEdit(); self.filter_edit.setPlaceholderText("Type to filter results…")
        self.filter_edit.textChanged.connect(self._apply_filter)
        top.addWidget(self.filter_edit, 1)
        root.addLayout(top)

        self.cols = ("artist", "album", "title", "genre", "duration", "path")
        self.table = QTableWidget(0, len(self.cols))
        self.table.setHorizontalHeaderLabels([c.title() for c in self.cols])
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setStretchLastSection(True)
        root.addWidget(self.table, 1)

        self.status_label = QLabel("")
        root.addWidget(self.status_label)

        self.flush_timer = QTimer(self)
        self.flush_timer.setInterval(120)
        self.flush_timer.timeout.connect(self._drain_queue)

    # ---------- DB ----------
    def _ensure_schema(self):
        db_path = self._current_db_path()
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS tracks (
                    path TEXT PRIMARY KEY,
                    title TEXT,
                    artist TEXT,
                    album TEXT,
                    albumartist TEXT,
                    genre TEXT,
                    track TEXT,
                    disc TEXT,
                    year TEXT,
                    date TEXT,
                    composer TEXT,
                    comment TEXT,
                    duration_seconds INTEGER,
                    format TEXT,
                    mtime INTEGER,
                    size INTEGER,
                    md5 TEXT
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_tracks_artist ON tracks(artist)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_tracks_album ON tracks(album)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_tracks_title ON tracks(title)")
            # Ensure md5 column exists for older DBs
            try:
                cols = {row[1] for row in conn.execute("PRAGMA table_info(tracks)")}
                if 'md5' not in cols:
                    conn.execute("ALTER TABLE tracks ADD COLUMN md5 TEXT")
            except Exception:
                pass

    # ---------- Actions ----------
    def load_from_db(self):
        db_path = self._current_db_path()
        try:
            with sqlite3.connect(db_path) as conn:
                cur = conn.execute("SELECT artist, album, title, genre, duration_seconds, path FROM tracks ORDER BY artist, album, track, title")
                rows = cur.fetchall()
        except Exception:
            rows = []
        self.table.setRowCount(0)
        for r in rows:
            artist, album, title, genre, dur, path = r
            info = {
                'artist': artist or '',
                'album': album or '',
                'title': title or '',
                'genre': genre or '',
                'duration': self._fmt_duration(dur or 0),
                'path': path or '',
            }
            self._insert_row(info)
        self.status_label.setText(f"Loaded {len(rows)} tracks from index.")

    def _apply_filter(self, _text):
        q = (self.filter_edit.text() or '').strip().lower()
        for row in range(self.table.rowCount()):
            vis = True
            if q:
                hay = []
                for col in range(self.table.columnCount()):
                    it = self.table.item(row, col)
                    hay.append(it.text().lower() if it else '')
                vis = (q in ' '.join(hay))
            self.table.setRowHidden(row, not vis)

    def scan_library(self):
        if self._is_scanning:
            return
        base = self._selected_base_folder()
        if not base or not os.path.isdir(base):
            self.status_label.setText("Select a valid source (Library or Device) and ensure the path exists.")
            return
        source_data = self.source_combo.currentData()
        is_device_scan = isinstance(source_data, dict) and source_data.get('type') == 'device'
        self._is_scanning = True
        self.scan_btn.setEnabled(False)
        self.status_label.setText("Scanning source and updating index…")
        self.flush_timer.start()

        def worker():
            count = 0
            updated = 0
            deleted = 0
            pending_md5: List[str] = []
            try:
                from mutagen import File as MFile  # noqa: F401
            except Exception as e:
                self._queue.put(("status", f"mutagen not installed: {e}"))
                self._queue.put(("end", 0))
                return
            exts = {".flac", ".mp3", ".m4a", ".alac", ".aac", ".ogg", ".opus", ".wav"}
            db_path = self._current_db_path()
            try:
                Path(db_path).parent.mkdir(parents=True, exist_ok=True)
            except Exception:
                pass
            conn = sqlite3.connect(db_path)
            try:
                # Ensure schema exists
                try:
                    conn.execute("SELECT 1 FROM tracks LIMIT 1")
                except Exception:
                    try:
                        self._ensure_schema()
                    except Exception:
                        pass

                for rootd, _, files in os.walk(base):
                    for name in files:
                        if os.path.splitext(name)[1].lower() not in exts:
                            continue
                        path = os.path.join(rootd, name)
                        try:
                            st = os.stat(path)
                        except Exception:
                            continue
                        mtime = int(getattr(st, 'st_mtime', 0))
                        size = int(getattr(st, 'st_size', 0))
                        # Check existing
                        try:
                            row = conn.execute("SELECT mtime, size, md5 FROM tracks WHERE path=?", (path,)).fetchone()
                        except Exception:
                            row = None
                        if row and row[0] == mtime and row[1] == size:
                            count += 1
                            continue  # unchanged
                        info = self._extract_info(path)
                        info['mtime'] = mtime
                        info['size'] = size
                        if is_device_scan:
                            # Defer MD5 hashing for device scans to keep the UI responsive
                            info['md5'] = ''
                            pending_md5.append(path)
                        else:
                            # Compute MD5 for verification, best-effort
                            try:
                                info['md5'] = self._compute_md5(path)
                            except Exception:
                                info['md5'] = None
                        self._upsert_row(conn, info)
                        self._queue.put(("row", info))
                        count += 1
                        updated += 1
                # Remove entries for files that no longer exist under the base
                try:
                    existing = conn.execute("SELECT path FROM tracks").fetchall()
                except Exception:
                    existing = []
                base_norm = os.path.normpath(base)
                for (p,) in existing:
                    try:
                        if not p:
                            continue
                        # Only consider files within the selected source root
                        if not os.path.normpath(p).startswith(base_norm):
                            continue
                        if not os.path.exists(p):
                            conn.execute("DELETE FROM tracks WHERE path=?", (p,))
                            deleted += 1
                    except Exception:
                        # Best-effort; skip problematic rows
                        continue
                conn.commit()
            finally:
                conn.close()
            status_msg = f"Scan complete. {count} files seen; {updated} updated; {deleted} removed."
            if is_device_scan and pending_md5:
                status_msg += f" Hashing {len(pending_md5)} files in background."
                self._schedule_md5_backfill(db_path, pending_md5)
            self._queue.put(("status", status_msg))
            self._queue.put(("end", count))

        threading.Thread(target=worker, daemon=True).start()

    def _upsert_row(self, conn: sqlite3.Connection, info: Dict):
        conn.execute(
            """
            INSERT INTO tracks (path, title, artist, album, albumartist, genre, track, disc, year, date, composer, comment, duration_seconds, format, mtime, size, md5)
            VALUES (:path, :title, :artist, :album, :albumartist, :genre, :track, :disc, :year, :date, :composer, :comment, :duration_seconds, :format, :mtime, :size, :md5)
            ON CONFLICT(path) DO UPDATE SET
                title=excluded.title,
                artist=excluded.artist,
                album=excluded.album,
                albumartist=excluded.albumartist,
                genre=excluded.genre,
                track=excluded.track,
                disc=excluded.disc,
                year=excluded.year,
                date=excluded.date,
                composer=excluded.composer,
                comment=excluded.comment,
                duration_seconds=excluded.duration_seconds,
                format=excluded.format,
                mtime=excluded.mtime,
                size=excluded.size,
                md5=COALESCE(excluded.md5, md5)
            """,
            info,
        )

    def _drain_queue(self):
        try:
            while True:
                kind, payload = self._queue.get_nowait()
                if kind == 'row':
                    info = payload
                    row_info = {
                        'artist': info.get('artist',''),
                        'album': info.get('album',''),
                        'title': info.get('title',''),
                        'genre': info.get('genre',''),
                        'duration': self._fmt_duration(info.get('duration_seconds') or 0),
                        'path': info.get('path',''),
                    }
                    self._insert_row(row_info)
                elif kind == 'status':
                    self.status_label.setText(str(payload))
                elif kind == 'end':
                    self._is_scanning = False
                    self.scan_btn.setEnabled(True)
                    self.flush_timer.stop()
                    # Reload from DB to reflect deletions and ensure table matches DB
                    try:
                        self.load_from_db()
                    except Exception:
                        pass
        except queue.Empty:
            pass

    def _extract_info(self, path: str) -> Dict:
        artist = album = title = track = disc = genre = albumartist = year = date = composer = comment = ""
        duration = 0
        fmt = os.path.splitext(path)[1].lower().lstrip('.')
        try:
            from mutagen import File as MFile
            audio = MFile(path)
            if audio is not None:
                try:
                    easy = MFile(path, easy=True)
                except Exception:
                    easy = None
                tags = getattr(easy, 'tags', None) or getattr(audio, 'tags', None) or {}

                def first(key, default=""):
                    try:
                        v = tags.get(key)
                        return (v[0] if isinstance(v, list) and v else v) or default
                    except Exception:
                        return default

                def all_values(key) -> list:
                    try:
                        v = tags.get(key)
                        if v is None:
                            return []
                        if isinstance(v, list):
                            return [str(x) for x in v if str(x).strip()]
                        s = str(v)
                        return [s] if s.strip() else []
                    except Exception:
                        return []

                artist = first('artist', artist)
                album = first('album', album)
                title = first('title', os.path.basename(path))
                albumartist = first('albumartist', albumartist)
                # Collect all genres and store them joined by '; '
                genres_list = all_values('genre')
                if not genres_list:
                    genre = genre
                else:
                    # normalize whitespace and dedupe while preserving order
                    seen = set()
                    norm = []
                    for g in genres_list:
                        gs = g.strip()
                        if not gs:
                            continue
                        if gs not in seen:
                            seen.add(gs)
                            norm.append(gs)
                    genre = "; ".join(norm)
                track = str(first('tracknumber', "")).split('/')[0]
                disc = str(first('discnumber', "")).split('/')[0]
                year = first('year', year)
                date = first('date', date)
                composer = first('composer', composer)
                comment = first('comment', comment)
                try:
                    if getattr(audio, 'info', None) and getattr(audio.info, 'length', None):
                        duration = int(audio.info.length)
                except Exception:
                    pass
        except Exception:
            pass
        return {
            'path': path,
            'title': title,
            'artist': artist,
            'album': album,
            'albumartist': albumartist,
            'genre': genre,
            'track': track,
            'disc': disc,
            'year': year,
            'date': date,
            'composer': composer,
            'comment': comment,
            'duration_seconds': duration,
            'format': fmt,
        }

    @staticmethod
    def _compute_md5(path: str, chunk_size: int = 2 * 1024 * 1024) -> str | None:
        try:
            h = hashlib.md5()
            with open(path, 'rb') as fh:
                while True:
                    chunk = fh.read(chunk_size)
                    if not chunk:
                        break
                    h.update(chunk)
            return h.hexdigest()
        except Exception:
            return None

    def _insert_row(self, info: Dict):
        row = self.table.rowCount()
        self.table.insertRow(row)
        vals = [info.get('artist',''), info.get('album',''), info.get('title',''), info.get('genre',''), info.get('duration',''), info.get('path','')]
        for col, val in enumerate(vals):
            self.table.setItem(row, col, QTableWidgetItem(str(val)))

    def _schedule_md5_backfill(self, db_path: str, paths: List[str]):
        safe_paths = [p for p in paths if p]
        if not safe_paths:
            return

        def backfill():
            try:
                conn = sqlite3.connect(db_path)
            except Exception:
                return
            try:
                try:
                    conn.execute('BEGIN')
                except Exception:
                    pass
                updated = 0
                for idx, track_path in enumerate(safe_paths, 1):
                    md5_value = self._compute_md5(track_path) or ''
                    try:
                        conn.execute("UPDATE tracks SET md5=? WHERE path=?", (md5_value, track_path))
                        updated += 1
                    except Exception:
                        continue
                    if idx % 25 == 0:
                        try:
                            conn.commit()
                        except Exception:
                            pass
                try:
                    conn.commit()
                except Exception:
                    pass
            finally:
                conn.close()

        threading.Thread(target=backfill, daemon=True).start()

    @staticmethod
    def _fmt_duration(secs: int) -> str:
        try:
            secs = int(secs)
            return f"{secs//60}:{secs%60:02d}"
        except Exception:
            return ""

    # ---------- Sources ----------
    def _refresh_sources(self):
        # Populate source dropdown: Library + detected devices
        self.source_combo.blockSignals(True)
        self.source_combo.clear()
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
            self.source_combo.addItem(f"Device: {label} ({mp})", { 'type': 'device', 'mount': mp })
        self.source_combo.blockSignals(False)
        # Ensure DB reflects current selection
        self._update_db_path_and_load()

    def _selected_base_folder(self) -> str:
        data = self.source_combo.currentData()
        if not isinstance(data, dict):
            return ''
        if data.get('type') == 'library':
            return (self.controller.settings.get('music_root') or '').strip()
        if data.get('type') == 'device':
            mp = (data.get('mount') or '').rstrip('/\\')
            return mp + '/Music' if mp else ''
        return ''

    def _current_db_path(self) -> str:
        data = self.source_combo.currentData()
        if isinstance(data, dict) and data.get('type') == 'device':
            mp = (data.get('mount') or '').rstrip('/\\')
            if mp:
                # Store DB on the device in a hidden folder
                return str(Path(mp) / '.rocksync' / 'music_index.sqlite3')
        # Default: library DB next to settings.json
        return str(CONFIG_PATH.with_name('music_index.sqlite3'))

    def _update_db_path_and_load(self):
        # Create schema if needed for current source and load
        try:
            self._ensure_schema()
        except Exception:
            pass
        self.load_from_db()
