import os
import sqlite3
import time
import random
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QComboBox, QSpinBox, QFileDialog, QMessageBox, QCheckBox
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

        # Source row
        src_row = QHBoxLayout()
        src_row.addWidget(QLabel("Source:"))
        self.source_combo = QComboBox(); self.source_combo.currentIndexChanged.connect(lambda _: self._on_source_changed())
        src_row.addWidget(self.source_combo, 1)
        b_refresh_src = QPushButton("Refresh"); b_refresh_src.clicked.connect(self._refresh_sources)
        src_row.addWidget(b_refresh_src)
        root.addLayout(src_row)

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
        root.addLayout(row1)

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
        root.addLayout(row2)

        # Output row
        out_row = QHBoxLayout()
        out_row.addWidget(QLabel("Save to:"))
        self.out_dir = QLineEdit("")
        out_row.addWidget(self.out_dir, 1)
        b_browse = QPushButton("Browse"); b_browse.clicked.connect(self._browse_out_dir)
        out_row.addWidget(b_browse)
        self.use_src_default = QCheckBox("Use source default (Playlists)")
        self.use_src_default.setChecked(True)
        self.use_src_default.toggled.connect(lambda _: self._apply_default_out_dir())
        out_row.addWidget(self.use_src_default)
        root.addLayout(out_row)

        # Actions row
        act_row = QHBoxLayout()
        self.run_btn = QPushButton("Generate Mix")
        self.run_btn.clicked.connect(self._on_generate)
        act_row.addWidget(self.run_btn)
        self.status = QLineEdit(""); self.status.setReadOnly(True)
        act_row.addWidget(self.status, 1)
        root.addLayout(act_row)

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
            self.out_dir.setText(str(Path(base) / 'Playlists'))
        else:
            # Library default: Playlists next to music root
            music_root = Path(self.controller.settings.get('music_root') or base)
            if music_root.exists():
                self.out_dir.setText(str(music_root.parent / 'Playlists'))
            else:
                self.out_dir.setText(str(Path(base) / 'Playlists'))

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
