import os
import sqlite3
import time
import random
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QComboBox, QSpinBox, QFileDialog, QMessageBox, QCheckBox, QGroupBox,
    QTableWidget, QTableWidgetItem
)

from core import CONFIG_PATH
from rockbox_utils import list_rockbox_devices


class DailyMixPane(QWidget):
    """Create Daily Mix playlists using the indexed DB (Library or Device)."""

    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self._genres: List[str] = []
        self._build_ui()
        self._refresh_sources()
        self._on_source_changed()

    # ---------- UI ----------
    def _build_ui(self):
        root = QVBoxLayout(self)

        # Shared source row (used for auto and default output)
        src_row = QHBoxLayout()
        src_row.addWidget(QLabel("Source:"))
        self.source_combo = QComboBox(); self.source_combo.currentIndexChanged.connect(lambda _: self._on_source_changed())
        src_row.addWidget(self.source_combo, 1)
        b_refresh_src = QPushButton("Refresh"); b_refresh_src.clicked.connect(self._refresh_sources)
        src_row.addWidget(b_refresh_src)
        root.addLayout(src_row)

        # Shared output row
        out_row = QHBoxLayout()
        out_row.addWidget(QLabel("Save to:"))
        self.out_dir = QLineEdit("")
        out_row.addWidget(self.out_dir, 1)
        b_browse = QPushButton("Browse"); b_browse.clicked.connect(self._browse_out_dir)
        out_row.addWidget(b_browse)
        self.use_src_default = QCheckBox("Use source default (Playlists/Mood Mixes)")
        self.use_src_default.setChecked(True)
        self.use_src_default.toggled.connect(lambda _: self._apply_default_out_dir())
        out_row.addWidget(self.use_src_default)
        root.addLayout(out_row)

        # Auto Generator group
        auto_group = QGroupBox("Auto Generator")
        auto_v = QVBoxLayout(auto_group)
        # Mix options row 1
        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Mix name:"))
        self.mix_name = QLineEdit("Daily Mix")
        row1.addWidget(self.mix_name, 1)
        row1.addWidget(QLabel("Target (min):"))
        self.target_min = QSpinBox(); self.target_min.setRange(10, 300); self.target_min.setValue(75)
        row1.addWidget(self.target_min)
        row1.addWidget(QLabel("Count:"))
        self.mix_count = QSpinBox(); self.mix_count.setRange(1, 20); self.mix_count.setValue(1)
        row1.addWidget(self.mix_count)
        auto_v.addLayout(row1)

        # Mix options row 2
        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Per-artist max:"))
        self.per_artist_max = QSpinBox(); self.per_artist_max.setRange(1, 10); self.per_artist_max.setValue(2)
        row2.addWidget(self.per_artist_max)
        row2.addWidget(QLabel("Fresh days:"))
        self.fresh_days = QSpinBox(); self.fresh_days.setRange(0, 365); self.fresh_days.setValue(0)
        row2.addWidget(self.fresh_days)
        row2.addWidget(QLabel("Genre mode:"))
        self.genre_mode = QComboBox(); self.genre_mode.addItems(["Random", "Pick"]) 
        self.genre_mode.currentIndexChanged.connect(self._on_genre_mode_changed)
        row2.addWidget(self.genre_mode)
        self.anchor_count = QSpinBox(); self.anchor_count.setRange(1, 6); self.anchor_count.setValue(3)
        row2.addWidget(QLabel("Anchors:"))
        row2.addWidget(self.anchor_count)
        self.genre_pick = QComboBox(); self.genre_pick.setEnabled(False)
        row2.addWidget(QLabel("Genre:"))
        row2.addWidget(self.genre_pick, 1)
        auto_v.addLayout(row2)

        # Actions row
        act_row = QHBoxLayout()
        self.run_btn = QPushButton("Generate Mix")
        self.run_btn.clicked.connect(self._on_generate)
        act_row.addWidget(self.run_btn)
        self.status = QLineEdit(""); self.status.setReadOnly(True)
        act_row.addWidget(self.status, 1)
        auto_v.addLayout(act_row)

        root.addWidget(auto_group)

        # Manual Playlists group
        manual_group = QGroupBox("Manual Playlists")
        man_v = QVBoxLayout(manual_group)

        # Manual source row
        man_src = QHBoxLayout()
        man_src.addWidget(QLabel("Source:"))
        self.manual_source_combo = QComboBox(); self.manual_source_combo.currentIndexChanged.connect(lambda _: self._manual_perform_search())
        man_src.addWidget(self.manual_source_combo, 1)
        b_man_refresh = QPushButton("Refresh"); b_man_refresh.clicked.connect(self._refresh_manual_sources)
        man_src.addWidget(b_man_refresh)
        b_reload = QPushButton("Reload DB"); b_reload.clicked.connect(self._manual_perform_search)
        man_src.addWidget(b_reload)
        man_v.addLayout(man_src)

        # Search controls
        man_search = QHBoxLayout()
        man_search.addWidget(QLabel("Search:"))
        self.manual_query = QLineEdit(); self.manual_query.setPlaceholderText("Type to search…")
        man_search.addWidget(self.manual_query, 1)
        self.manual_query.textChanged.connect(lambda _: self._manual_trigger_search())
        man_search.addWidget(QLabel("Field:"))
        self.manual_field = QComboBox(); self.manual_field.addItems(["Any", "Title", "Artist", "Album", "Genre"]) 
        self.manual_field.currentIndexChanged.connect(lambda _: self._manual_trigger_search())
        man_search.addWidget(self.manual_field)
        man_v.addLayout(man_search)

        # Results table
        self._manual_search_timer = QTimer(self)
        self._manual_search_timer.setInterval(250)
        self._manual_search_timer.setSingleShot(True)
        self._manual_search_timer.timeout.connect(self._manual_perform_search)

        self.manual_cols = ("artist", "album", "title", "genre", "duration", "path")
        self.manual_results = QTableWidget(0, len(self.manual_cols))
        self.manual_results.setHorizontalHeaderLabels([c.title() for c in self.manual_cols])
        self.manual_results.setAlternatingRowColors(True)
        self.manual_results.setSelectionBehavior(QTableWidget.SelectRows)
        self.manual_results.setSelectionMode(QTableWidget.ExtendedSelection)
        self.manual_results.horizontalHeader().setStretchLastSection(True)
        self.manual_results.verticalHeader().setDefaultSectionSize(30)
        self.manual_results.verticalHeader().setMinimumSectionSize(26)
        man_v.addWidget(self.manual_results, 1)
        # Give more vertical space to the results list
        man_v.setStretchFactor(self.manual_results, 2)

        # Selected playlist table + buttons
        sel_row = QHBoxLayout()
        b_add = QPushButton("Add Selected →"); b_add.clicked.connect(self._manual_add_selected)
        b_remove = QPushButton("Remove Selected"); b_remove.clicked.connect(self._manual_remove_selected)
        b_clear = QPushButton("Clear"); b_clear.clicked.connect(self._manual_clear_selected)
        sel_row.addWidget(b_add); sel_row.addWidget(b_remove); sel_row.addWidget(b_clear)
        sel_row.addStretch(1)
        man_v.addLayout(sel_row)

        self.manual_selected = QTableWidget(0, len(self.manual_cols))
        self.manual_selected.setHorizontalHeaderLabels([c.title() for c in self.manual_cols])
        self.manual_selected.setAlternatingRowColors(True)
        self.manual_selected.setSelectionBehavior(QTableWidget.SelectRows)
        self.manual_selected.setSelectionMode(QTableWidget.ExtendedSelection)
        self.manual_selected.horizontalHeader().setStretchLastSection(True)
        self.manual_selected.verticalHeader().setDefaultSectionSize(30)
        self.manual_selected.verticalHeader().setMinimumSectionSize(26)
        man_v.addWidget(self.manual_selected, 1)
        man_v.setStretchFactor(self.manual_selected, 1)

        # Footer: name + save
        man_row1 = QHBoxLayout()
        man_row1.addWidget(QLabel("Name:"))
        self.manual_name = QLineEdit("")
        self.manual_name.setPlaceholderText("New Playlist")
        man_row1.addWidget(self.manual_name, 1)
        b_create = QPushButton("Save Playlist"); b_create.clicked.connect(self._on_create_manual_playlist)
        man_row1.addWidget(b_create)
        man_v.addLayout(man_row1)

        root.addWidget(manual_group, 1)

        # Storage for manual selection
        self._manual_files: List[str] = []
        self._manual_selected_paths: List[str] = []
        # Populate manual sources
        self._refresh_manual_sources()

    # ---------- Helpers ----------
    def _refresh_sources(self):
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

    def _selected_base_folder(self) -> str:
        data = self.source_combo.currentData()
        if not isinstance(data, dict):
            return ''
        if data.get('type') == 'library':
            return (self.controller.settings.get('music_root') or '').strip()
        if data.get('type') == 'device':
            mp = (data.get('mount') or '').rstrip('/\\')
            return mp
        return ''

    def _current_db_path(self) -> str:
        data = self.source_combo.currentData()
        if isinstance(data, dict) and data.get('type') == 'device':
            mp = (data.get('mount') or '').rstrip('/\\')
            if mp:
                return str(Path(mp) / '.rocksync' / 'music_index.sqlite3')
        return str(CONFIG_PATH.with_name('music_index.sqlite3'))

    def _apply_default_out_dir(self):
        if not self.use_src_default.isChecked():
            return
        base = self._selected_base_folder()
        if not base:
            self.out_dir.setText("")
            return
        data = self.source_combo.currentData()
        if isinstance(data, dict) and data.get('type') == 'device':
            # Device default: <mount>/Music/Playlists/Mood Mixes
            self.out_dir.setText(str(Path(base) / 'Music' / 'Playlists' / 'Mood Mixes'))
        else:
            # Library default: <music_root>/Playlists/Mood Mixes
            music_root_str = (self.controller.settings.get('music_root') or base)
            music_root = Path(music_root_str)
            self.out_dir.setText(str(music_root / 'Playlists' / 'Mood Mixes'))

    def _on_source_changed(self):
        self._apply_default_out_dir()
        self._load_genres()

    def _on_genre_mode_changed(self):
        pick = (self.genre_mode.currentText().lower() == 'pick')
        self.genre_pick.setEnabled(pick)
        self.anchor_count.setEnabled(not pick)

    def _browse_out_dir(self):
        path = QFileDialog.getExistingDirectory(self, "Select output folder", self.out_dir.text() or self._selected_base_folder() or "")
        if path:
            self.out_dir.setText(path)
            self.use_src_default.setChecked(False)

    def _manual_trigger_search(self):
        self._manual_search_timer.start()

    def _manual_perform_search(self):
        db_path = self._manual_current_db_path()
        self.manual_results.setRowCount(0)
        if not db_path or not os.path.isfile(db_path):
            return
        query = (self.manual_query.text() or '').strip()
        field = (self.manual_field.currentText() or 'Any').lower()
        try:
            with sqlite3.connect(db_path) as conn:
                if not query:
                    sql = "SELECT artist, album, title, genre, duration_seconds, path FROM tracks ORDER BY artist, album, track, title LIMIT 1000"
                    cur = conn.execute(sql)
                else:
                    like = f"%{query}%"
                    if field == 'any':
                        where = "(IFNULL(title,'') LIKE ? OR IFNULL(artist,'') LIKE ? OR IFNULL(album,'') LIKE ? OR IFNULL(genre,'') LIKE ?)"
                        params = [like, like, like, like]
                    else:
                        col = {'title':'title','artist':'artist','album':'album','genre':'genre'}.get(field, 'title')
                        where = f"IFNULL({col},'') LIKE ?"
                        params = [like]
                    sql = f"SELECT artist, album, title, genre, duration_seconds, path FROM tracks WHERE {where} ORDER BY artist, album, track, title LIMIT 1000"
                    cur = conn.execute(sql, params)
                rows = cur.fetchall()
        except Exception:
            rows = []
        for (artist, album, title, genre, dur, path) in rows:
            info = {
                'artist': artist or '',
                'album': album or '',
                'title': title or '',
                'genre': genre or '',
                'duration': self._fmt_duration(dur or 0),
                'path': path or '',
            }
            self._manual_insert_row(self.manual_results, info)

    # ---------- DB ops ----------
    def _load_genres(self):
        db_path = self._current_db_path()
        genres: List[str] = []
        if db_path and os.path.isfile(db_path):
            try:
                with sqlite3.connect(db_path) as conn:
                    cur = conn.execute("SELECT DISTINCT IFNULL(genre,'') FROM tracks")
                    for (g,) in cur.fetchall():
                        gs = str(g or '')
                        # Split combined genres into individual tokens
                        tokens = self._split_genre_tokens(gs)
                        for t in tokens:
                            if self._is_valid_genre(t):
                                genres.append(t)
            except Exception:
                pass
        genres = sorted(set(genres), key=lambda s: s.lower())
        self._genres = genres
        self.genre_pick.blockSignals(True)
        self.genre_pick.clear()
        self.genre_pick.addItems(self._genres)
        self.genre_pick.blockSignals(False)

    @staticmethod
    def _fmt_duration(secs):
        try:
            secs = int(secs)
            return f"{secs//60}:{secs%60:02d}"
        except Exception:
            return ''

    @staticmethod
    def _is_valid_genre(g: str) -> bool:
        bad = {"", "unknown", "(unknown)", "undef", "undefined", "n/a", "none", "genre:"}
        return (g or '').strip().lower() not in bad

    @staticmethod
    def _split_genre_tokens(genre: str) -> List[str]:
        if not genre:
            return []
        raw = [genre]
        seps = [';', '|', '/', ',']
        for sep in seps:
            tmp = []
            for item in raw:
                tmp.extend(item.split(sep))
            raw = tmp
        return [t.strip() for t in raw if t.strip()]

    def _load_tracks(self) -> List[Dict]:
        db_path = self._current_db_path()
        rows: List[Dict] = []
        if not db_path or not os.path.isfile(db_path):
            return rows
        try:
            with sqlite3.connect(db_path) as conn:
                cur = conn.execute(
                    "SELECT path, IFNULL(artist,''), IFNULL(album,''), IFNULL(title,''), IFNULL(genre,''), IFNULL(duration_seconds,0), IFNULL(mtime,0) FROM tracks"
                )
                for (path, artist, album, title, genre, dur, mtime) in cur.fetchall():
                    if not self._is_valid_genre(genre):
                        continue
                    rows.append({
                        'path': path,
                        'artist': artist,
                        'album': album,
                        'title': title or Path(path).stem,
                        'genre': genre,
                        'seconds': int(dur) if dur else 0,
                        'mtime': int(mtime) if mtime else 0,
                    })
        except Exception:
            return []
        return rows

    # ---------- Generate ----------
    def _on_generate(self):
        out_dir = (self.out_dir.text() or '').strip()
        if not out_dir:
            QMessageBox.warning(self, "Daily Mix", "Please choose an output folder.")
            return
        tracks = self._load_tracks()
        if not tracks:
            QMessageBox.warning(self, "Daily Mix", "No tracks found in the index for the selected source.")
            return

        # Determine anchors
        anchors: List[str] = []
        if self.genre_mode.currentText().lower() == 'pick':
            g = self.genre_pick.currentText().strip()
            if not g:
                QMessageBox.warning(self, "Daily Mix", "Please pick a genre or select Random mode.")
                return
            anchors = [g]
        else:
            anchors = self._choose_anchor_genres(tracks, self.anchor_count.value())

        per_artist_max = self.per_artist_max.value()
        fresh_days = self.fresh_days.value() or None
        total_min = self.target_min.value()
        mix_count = self.mix_count.value()
        name = self.mix_name.text().strip() or "Daily Mix"

        base = Path(out_dir)
        base.mkdir(parents=True, exist_ok=True)

        wrote = 0
        for i in range(mix_count):
            mix = self._build_mix(tracks, anchors, total_min, per_artist_max, fresh_days)
            if not mix:
                break
            mix_name = name if mix_count == 1 else f"{name} #{i+1}"
            out = self._write_m3u8(base, mix_name, mix)
            wrote += 1
            self.status.setText(f"Wrote {out}")
        if wrote == 0:
            QMessageBox.warning(self, "Daily Mix", "Could not build a mix. Try adjusting options.")
        else:
            QMessageBox.information(self, "Daily Mix", f"Created {wrote} playlist(s).")

    # ---------- Manual playlist ----------
    def _manual_insert_row(self, table: QTableWidget, info: Dict):
        row = table.rowCount()
        table.insertRow(row)
        vals = [info.get('artist',''), info.get('album',''), info.get('title',''), info.get('genre',''), info.get('duration',''), info.get('path','')]
        for col, val in enumerate(vals):
            table.setItem(row, col, QTableWidgetItem(str(val)))

    def _manual_add_selected(self):
        rows = sorted(set([i.row() for i in self.manual_results.selectedIndexes()]))
        for r in rows:
            path_item = self.manual_results.item(r, 5)
            if not path_item:
                continue
            path = path_item.text()
            if path in self._manual_selected_paths:
                continue
            # Build info dict from results row
            info = { c: (self.manual_results.item(r, idx).text() if self.manual_results.item(r, idx) else '')
                     for idx, c in enumerate(self.manual_cols) }
            self._manual_insert_row(self.manual_selected, info)
            self._manual_selected_paths.append(path)

    def _manual_remove_selected(self):
        rows = sorted(set([i.row() for i in self.manual_selected.selectedIndexes()]), reverse=True)
        for r in rows:
            path_item = self.manual_selected.item(r, 5)
            path = path_item.text() if path_item else ''
            if 0 <= r < self.manual_selected.rowCount():
                self.manual_selected.removeRow(r)
            if path in self._manual_selected_paths:
                try:
                    self._manual_selected_paths.remove(path)
                except ValueError:
                    pass

    def _manual_clear_selected(self):
        self.manual_selected.setRowCount(0)
        self._manual_selected_paths.clear()
    def _on_create_manual_playlist(self):
        out_dir = (self.out_dir.text() or '').strip()
        if not out_dir:
            QMessageBox.warning(self, "Playlists", "Please choose an output folder.")
            return
        name = (self.manual_name.text() or '').strip()
        if not name:
            QMessageBox.warning(self, "Playlists", "Please enter a playlist name.")
            return
        if not self._manual_selected_paths:
            QMessageBox.warning(self, "Playlists", "Please add one or more tracks.")
            return
        try:
            out = self._write_manual_m3u8(Path(out_dir), name, self._manual_selected_paths)
            self.status.setText(f"Wrote {out}")
            QMessageBox.information(self, "Playlists", f"Created playlist: {out}")
        except Exception as e:
            QMessageBox.critical(self, "Playlists", f"Failed to write playlist: {e}")
    
    def _refresh_manual_sources(self):
        self.manual_source_combo.blockSignals(True)
        self.manual_source_combo.clear()
        self.manual_source_combo.addItem("Library", { 'type': 'library' })
        try:
            devices = list_rockbox_devices()
        except Exception:
            devices = []
        for d in devices:
            label = d.get('name') or d.get('label') or d.get('mountpoint')
            mp = d.get('mountpoint')
            if not mp:
                continue
            self.manual_source_combo.addItem(f"{label}", { 'type': 'device', 'mount': mp })
        self.manual_source_combo.blockSignals(False)
        self._manual_perform_search()

    def _manual_current_db_path(self) -> str:
        data = self.manual_source_combo.currentData()
        if not isinstance(data, dict):
            return ''
        if data.get('type') == 'device':
            mp = (data.get('mount') or '').rstrip('/\\')
            if mp:
                return str(Path(mp) / '.rocksync' / 'music_index.sqlite3')
            return ''
        return str(CONFIG_PATH.with_name('music_index.sqlite3'))

    # ---------- Mix utilities (local) ----------
    @staticmethod
    def _choose_anchor_genres(rows: List[Dict], n: int) -> List[str]:
        freq: Dict[str, int] = {}
        for r in rows:
            g = (r.get('genre') or '').strip()
            toks = DailyMixPane._split_genre_tokens(g)
            for t in toks:
                if not DailyMixPane._is_valid_genre(t):
                    continue
                freq[t] = freq.get(t, 0) + 1
        ranked = sorted(freq.items(), key=lambda kv: kv[1], reverse=True)
        top = [g for g, _ in ranked[:max(2, n + 2)]]
        random.shuffle(top)
        return list(dict.fromkeys(top[:n]))

    @staticmethod
    def _weight_rows(rows: List[Dict], anchors: List[str], fresh_days: Optional[int]) -> List[Tuple[Dict, float]]:
        now = time.time()
        window = (fresh_days or 0) * 86400
        anchors_lc = {a.strip().lower() for a in anchors}
        out: List[Tuple[Dict, float]] = []
        for r in rows:
            w = 1.0
            toks = DailyMixPane._split_genre_tokens(r.get('genre',''))
            if any(t.strip().lower() in anchors_lc for t in toks):
                w += 1.0
            if fresh_days and (now - float(r.get('mtime') or 0)) <= window:
                w += 0.5
            out.append((r, w))
        return out

    @staticmethod
    def _pick_next(pool: List[Tuple[Dict, float]], used: set, last_artist: Optional[str], per_artist: Dict[str, int], cap: int) -> Optional[Dict]:
        filtered = [(r, w) for (r, w) in pool
                    if r.get('path') not in used
                    and per_artist.get(r.get('artist',''), 0) < cap
                    and (last_artist is None or r.get('artist','') != last_artist)]
        if not filtered:
            filtered = [(r, w) for (r, w) in pool
                        if r.get('path') not in used
                        and per_artist.get(r.get('artist',''), 0) < cap]
        if not filtered:
            return None
        weights = [w for _, w in filtered]
        return random.choices(filtered, weights=weights, k=1)[0][0]

    def _build_mix(self, rows: List[Dict], anchors: List[str], target_min: int, per_artist_max: int, fresh_days: Optional[int]) -> List[Dict]:
        pool = self._weight_rows(rows, anchors, fresh_days)
        target_sec = target_min * 60
        used = set()
        per_artist: Dict[str, int] = {}
        out: List[Dict] = []
        last_artist: Optional[str] = None
        total = 0
        approx_count = max(10, int(target_min * 0.24)) if not any(r.get('seconds') for r, _w in pool) else None

        while True:
            nxt = self._pick_next(pool, used, last_artist, per_artist, per_artist_max)
            if not nxt:
                break
            dur = int(nxt.get('seconds') or 240)
            if any(r.get('seconds') for r, _w in pool):
                if total > 0 and total + dur > target_sec + 120:
                    break
                total += dur
            else:
                if approx_count is not None and len(out) >= approx_count:
                    break
            out.append(nxt)
            used.add(nxt.get('path'))
            art = nxt.get('artist','')
            per_artist[art] = per_artist.get(art, 0) + 1
            last_artist = art
            if len(out) >= 200:
                break
        return out

    @staticmethod
    def _write_m3u8(out_dir: Path, name: str, rows: List[Dict]) -> Path:
        out_dir.mkdir(parents=True, exist_ok=True)
        safe = "".join(c for c in name if c not in r'<>:"/\\|?*').strip() or "Daily Mix"
        ts = time.strftime("%Y-%m-%d")
        fp = out_dir / f"{safe} - {ts}.m3u8"
        lines = ["#EXTM3U"]
        for r in rows:
            secs = int(r.get('seconds') or 0)
            if secs:
                lines.append(f"#EXTINF:{secs},{r.get('artist','')} - {r.get('title','')}")
            try:
                rp = os.path.relpath(str(Path(r.get('path')).resolve()), str(out_dir.resolve())).replace("\\", "/")
            except Exception:
                rp = r.get('path')
            lines.append(rp)
        fp.write_text("\n".join(lines), encoding="utf-8")
        return fp

    @staticmethod
    def _write_manual_m3u8(out_dir: Path, name: str, files: List[str]) -> Path:
        out_dir.mkdir(parents=True, exist_ok=True)
        safe = "".join(c for c in name if c not in r'<>:"/\\|?*').strip() or "New Playlist"
        fp = out_dir / f"{safe}.m3u8"
        lines = ["#EXTM3U"]
        for p in files:
            try:
                rp = os.path.relpath(str(Path(p).resolve()), str(out_dir.resolve())).replace("\\", "/")
            except Exception:
                rp = p
            lines.append(rp)
        fp.write_text("\n".join(lines), encoding="utf-8")
        return fp
