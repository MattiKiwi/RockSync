import os
import re
from typing import Dict, List, Tuple, Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFormLayout, QLineEdit,
    QSpinBox, QComboBox, QCheckBox, QFileDialog, QColorDialog, QWidget, QTabWidget,
    QScrollArea
)


def _detect_newline(text: str) -> str:
    if "\r\n" in text:
        return "\r\n"
    if "\r" in text and "\n" not in text:
        return "\r"
    return "\n"


class RockboxConfigModel:
    """Parse, edit, and serialize a Rockbox .cfg file while preserving comments and order."""

    def __init__(self, text: str = "") -> None:
        self.newline = _detect_newline(text)
        self.records: List[Dict[str, Any]] = []  # each item: {type: 'raw'|'kv', text?|key,value}
        self._index: Dict[str, int] = {}
        if text:
            self._parse(text)

    def _parse(self, text: str) -> None:
        self.records.clear()
        self._index.clear()
        for line in text.splitlines(keepends=False):
            raw = line
            stripped = raw.strip()
            if not stripped or stripped.startswith('#'):
                self.records.append({'type': 'raw', 'text': raw})
                continue
            if ':' in raw:
                key, val = raw.split(':', 1)
                key = key.strip().lower()
                val = val.strip()
                rec = {'type': 'kv', 'key': key, 'value': val}
                self.records.append(rec)
                # only first occurrence is indexed for updates
                if key not in self._index:
                    self._index[key] = len(self.records) - 1
            else:
                # Fallback to raw preservation
                self.records.append({'type': 'raw', 'text': raw})

    def get(self, key: str, default: str = "") -> str:
        idx = self._index.get(key.lower())
        if idx is None:
            return default
        rec = self.records[idx]
        return str(rec.get('value', default))

    def set(self, key: str, value: Any) -> None:
        key = key.lower()
        s = str(value)
        idx = self._index.get(key)
        if idx is not None and 0 <= idx < len(self.records):
            self.records[idx]['value'] = s
        else:
            # append new entry
            self.records.append({'type': 'kv', 'key': key, 'value': s})
            self._index[key] = len(self.records) - 1

    def serialize(self) -> str:
        out: List[str] = []
        nl = self.newline
        for rec in self.records:
            if rec['type'] == 'raw':
                out.append(rec.get('text', ''))
            else:
                out.append(f"{rec['key']}: {rec.get('value','')}")
        return nl.join(out) + nl

    def remove(self, key: str) -> None:
        key = key.lower()
        idx = self._index.get(key)
        if idx is None:
            return
        # remove record
        try:
            self.records.pop(idx)
        except Exception:
            return
        # rebuild index since positions changed
        self._index.clear()
        for i, rec in enumerate(self.records):
            if rec.get('type') == 'kv' and rec.get('key') not in self._index:
                self._index[rec.get('key')] = i


def _path_row(parent: QWidget, edit: QLineEdit, caption: str) -> QWidget:
    row = QWidget(parent)
    h = QHBoxLayout(row)
    h.setContentsMargins(0, 0, 0, 0)
    h.addWidget(edit, 1)
    b = QPushButton("Browse…", row)
    def _browse():
        # Allow any file; caller can validate
        path, _ = QFileDialog.getOpenFileName(parent, caption)
        if path:
            # Normalize to forward slashes (Rockbox friendly)
            edit.setText(path.replace('\\', '/'))
    b.clicked.connect(_browse)
    h.addWidget(b)
    return row


def _color_row(parent: QWidget, edit: QLineEdit, caption: str) -> QWidget:
    row = QWidget(parent)
    h = QHBoxLayout(row)
    h.setContentsMargins(0, 0, 0, 0)
    h.addWidget(edit, 1)
    b = QPushButton("Pick…", row)
    def _pick():
        txt = edit.text().strip().lstrip('#')
        if len(txt) == 6 and all(c in '0123456789abcdefABCDEF' for c in txt):
            r = int(txt[0:2], 16); g = int(txt[2:4], 16); b = int(txt[4:6], 16)
            current = QColor(r, g, b)
        else:
            current = QColor(255, 255, 255)
        color = QColorDialog.getColor(current, parent, caption)
        if color.isValid():
            edit.setText(f"{color.red():02x}{color.green():02x}{color.blue():02x}")
    b.clicked.connect(_pick)
    h.addWidget(b)
    return row


class RockboxConfiguratorDialog(QDialog):
    """A simple, focused configurator for common Rockbox .cfg options."""

    def __init__(self, path: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Configure {os.path.basename(path) if path else 'config'}")
        self.path = path
        self.model = RockboxConfigModel(self._read_text(path))
        self._build_ui()
        self._load_into_ui()

    # --------------- IO ---------------
    def _read_text(self, p: str) -> str:
        try:
            with open(p, 'r', encoding='utf-8', errors='ignore') as f:
                return f.read()
        except Exception:
            return ""

    def _write_text(self, p: str, text: str) -> bool:
        try:
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, 'w', encoding='utf-8') as f:
                f.write(text)
            return True
        except Exception:
            return False

    # --------------- UI ---------------
    def _build_ui(self) -> None:
        v = QVBoxLayout(self)
        tabs = QTabWidget(self)
        v.addWidget(tabs, 1)

        # Playback tab
        play_w = QWidget(); play_form = QFormLayout(play_w)
        self.in_volume = QSpinBox(); self.in_volume.setRange(-100, 6)
        self.in_volume_limit = QSpinBox(); self.in_volume_limit.setRange(0, 6)
        self.in_shuffle = QCheckBox("Enable shuffle")
        self.in_repeat = QComboBox(); self.in_repeat.addItems(["off", "one", "all", "shuffle"])
        self.in_skip_length = QComboBox(); self.in_skip_length.addItems(["track", "1", "3", "5", "10", "15", "30"])
        self.in_antiskip = QSpinBox(); self.in_antiskip.setRange(0, 30)
        self.in_replaygain = QComboBox(); self.in_replaygain.addItems(["off", "track", "album", "track shuffle"])  # common modes
        # Additional playback
        self.in_pitch = QSpinBox(); self.in_pitch.setRange(5000, 20000)  # Rockbox uses 10000 = 1.0
        self.in_speed = QSpinBox(); self.in_speed.setRange(5000, 20000)
        self.in_balance = QSpinBox(); self.in_balance.setRange(-100, 100)
        self.in_bass = QSpinBox(); self.in_bass.setRange(-24, 24)
        self.in_treble = QSpinBox(); self.in_treble.setRange(-24, 24)
        self.in_channels = QComboBox(); self.in_channels.addItems(["stereo", "mono", "left", "right", "karaoke"])
        self.in_stereo_width = QSpinBox(); self.in_stereo_width.setRange(0, 250)
        self.in_playback_freq = QComboBox(); self.in_playback_freq.addItems(["auto", "44", "48", "88", "96"])  # common rates
        self.in_album_art = QComboBox(); self.in_album_art.addItems(["off", "hide", "prefer embedded", "prefer external"])  # simplified

        play_form.addRow("Volume", self.in_volume)
        play_form.addRow("Volume limit", self.in_volume_limit)
        play_form.addRow("Shuffle", self.in_shuffle)
        play_form.addRow("Repeat", self.in_repeat)
        play_form.addRow("Skip length", self.in_skip_length)
        play_form.addRow("Antiskip (sec)", self.in_antiskip)
        play_form.addRow("ReplayGain type", self.in_replaygain)
        play_form.addRow("Pitch (10000=1x)", self.in_pitch)
        play_form.addRow("Speed (10000=1x)", self.in_speed)
        play_form.addRow("Balance", self.in_balance)
        play_form.addRow("Bass", self.in_bass)
        play_form.addRow("Treble", self.in_treble)
        play_form.addRow("Channels", self.in_channels)
        play_form.addRow("Stereo width", self.in_stereo_width)
        play_form.addRow("Playback frequency", self.in_playback_freq)
        play_form.addRow("Album art", self.in_album_art)
        tabs.addTab(play_w, "Playback")

        # Display tab
        disp_w = QWidget(); disp_form = QFormLayout(disp_w)
        self.in_brightness = QSpinBox(); self.in_brightness.setRange(0, 100)
        self.in_backlight = QSpinBox(); self.in_backlight.setRange(0, 300)
        self.in_backlight_plug = QSpinBox(); self.in_backlight_plug.setRange(0, 300)
        self.in_show_icons = QCheckBox("Show icons in lists")
        self.in_statusbar = QComboBox(); self.in_statusbar.addItems(["off", "top", "bottom"])  # varies by target
        self.in_scrollbar = QCheckBox("Show scrollbar")
        self.in_scrollbar_width = QSpinBox(); self.in_scrollbar_width.setRange(0, 32)
        self.in_fg = QLineEdit(); self.in_bg = QLineEdit()
        self.in_sel_start = QLineEdit(); self.in_sel_end = QLineEdit(); self.in_sel_text = QLineEdit()

        disp_form.addRow("Brightness", self.in_brightness)
        disp_form.addRow("Backlight timeout (s)", self.in_backlight)
        disp_form.addRow("Backlight timeout plugged (s)", self.in_backlight_plug)
        disp_form.addRow("Status bar", self.in_statusbar)
        disp_form.addRow("Scrollbar", self.in_scrollbar)
        disp_form.addRow("Scrollbar width", self.in_scrollbar_width)
        disp_form.addRow("Show icons", self.in_show_icons)
        disp_form.addRow("Foreground color", _color_row(self, self.in_fg, "Foreground color"))
        disp_form.addRow("Background color", _color_row(self, self.in_bg, "Background color"))
        disp_form.addRow("Line sel start", _color_row(self, self.in_sel_start, "Line selector start"))
        disp_form.addRow("Line sel end", _color_row(self, self.in_sel_end, "Line selector end"))
        disp_form.addRow("Line sel text", _color_row(self, self.in_sel_text, "Line selector text"))
        tabs.addTab(disp_w, "Display")

        # Paths tab
        paths_w = QWidget(); paths_form = QFormLayout(paths_w)
        self.in_start_dir = QLineEdit()
        self.in_font = QLineEdit(); self.in_wps = QLineEdit(); self.in_sbs = QLineEdit()
        self.in_iconset = QLineEdit(); self.in_viewer_icons = QLineEdit()
        paths_form.addRow("Start directory", self.in_start_dir)
        paths_form.addRow("Font", _path_row(self, self.in_font, "Choose font (.fnt)"))
        paths_form.addRow("WPS", _path_row(self, self.in_wps, "Choose WPS"))
        paths_form.addRow("SBS", _path_row(self, self.in_sbs, "Choose SBS"))
        paths_form.addRow("Iconset", _path_row(self, self.in_iconset, "Choose iconset"))
        paths_form.addRow("Viewer iconset", _path_row(self, self.in_viewer_icons, "Choose viewer icons"))
        tabs.addTab(paths_w, "Paths")

        # Sound tab (EQ section)
        sound_w = QWidget(); sound_v = QVBoxLayout(sound_w)
        # EQ enable + precut
        eq_form = QFormLayout()
        self.eq_enabled_cb = QCheckBox("Enable equalizer")
        self.eq_precut = QSpinBox(); self.eq_precut.setRange(0, 24)
        eq_form.addRow("EQ", self.eq_enabled_cb)
        eq_form.addRow("EQ precut (dB)", self.eq_precut)

        # Helpers to build triple rows (freq, Q, gain)
        def triple_row() -> Tuple[QWidget, QSpinBox, QSpinBox, QSpinBox]:
            w = QWidget(); h = QHBoxLayout(w); h.setContentsMargins(0,0,0,0)
            f = QSpinBox(); f.setRange(20, 22000); f.setSingleStep(10); f.setSuffix(" Hz")
            q = QSpinBox(); q.setRange(1, 32); q.setSingleStep(1)
            g = QSpinBox(); g.setRange(-24, 24); g.setSingleStep(1); g.setSuffix(" dB")
            for x in (f, q, g):
                x.setMaximumWidth(120)
            h.addWidget(QLabel("F:")); h.addWidget(f)
            h.addWidget(QLabel("Q:")); h.addWidget(q)
            h.addWidget(QLabel("Gain:")); h.addWidget(g)
            h.addStretch(1)
            return w, f, q, g

        # Low shelf
        self.eq_low_w, self.eq_low_f, self.eq_low_q, self.eq_low_g = triple_row()
        eq_form.addRow("Low shelf", self.eq_low_w)

        # Peaks 1..8
        self.eq_peaks: List[Tuple[QSpinBox, QSpinBox, QSpinBox]] = []
        for i in range(1, 9):
            w, f, q, g = triple_row()
            setattr(self, f"eq_p{i}_w", w)
            self.eq_peaks.append((f, q, g))
            eq_form.addRow(f"Peak {i}", w)

        # High shelf
        self.eq_high_w, self.eq_high_f, self.eq_high_q, self.eq_high_g = triple_row()
        eq_form.addRow("High shelf", self.eq_high_w)

        sound_v.addLayout(eq_form)
        sound_v.addStretch(1)
        tabs.addTab(sound_w, "Sound")

        # Advanced tab: all key/value pairs
        adv_w = QWidget(); adv_v = QVBoxLayout(adv_w)
        # Filter row
        filt_row = QHBoxLayout();
        filt_row.addWidget(QLabel("Filter:"))
        self.adv_filter = QLineEdit(); filt_row.addWidget(self.adv_filter, 1)
        self.adv_add_btn = QPushButton("Add…"); filt_row.addWidget(self.adv_add_btn)
        self.adv_reset_btn = QPushButton("Reset"); filt_row.addWidget(self.adv_reset_btn)
        adv_v.addLayout(filt_row)
        # Scrollable form
        self.adv_scroll = QScrollArea(); self.adv_scroll.setWidgetResizable(True)
        self.adv_formw = QWidget(); self.adv_form = QFormLayout(self.adv_formw)
        self.adv_scroll.setWidget(self.adv_formw)
        adv_v.addWidget(self.adv_scroll, 1)
        tabs.addTab(adv_w, "Advanced")

        # Buttons
        row = QHBoxLayout(); row.addStretch(1)
        self.btn_cancel = QPushButton("Cancel"); self.btn_save = QPushButton("Save")
        row.addWidget(self.btn_cancel); row.addWidget(self.btn_save)
        v.addLayout(row)
        self.btn_cancel.clicked.connect(self.reject)
        self.btn_save.clicked.connect(self._on_save)

        # Advanced wiring
        self.adv_rows: Dict[str, Tuple[QLabel, QWidget, QLineEdit]] = {}
        self.adv_filter.textChanged.connect(self._apply_adv_filter)
        self.adv_add_btn.clicked.connect(self._adv_add)
        self.adv_reset_btn.clicked.connect(self._rebuild_adv_form)

    def _load_into_ui(self) -> None:
        m = self.model
        # Playback
        self.in_volume.setValue(self._to_int(m.get('volume', '-50'), -50))
        self.in_volume_limit.setValue(self._to_int(m.get('volume limit', '3'), 3))
        self.in_shuffle.setChecked(self._to_bool(m.get('shuffle', 'off')))
        self._set_combo(self.in_repeat, m.get('repeat', 'off'))
        self._set_combo(self.in_skip_length, m.get('skip length', 'track'))
        self.in_antiskip.setValue(self._to_int(m.get('antiskip', '5'), 5))
        self._set_combo(self.in_replaygain, m.get('replaygain type', 'off'))
        # Additional playback
        self.in_pitch.setValue(self._to_int(m.get('pitch', '10000'), 10000))
        self.in_speed.setValue(self._to_int(m.get('speed', '10000'), 10000))
        self.in_balance.setValue(self._to_int(m.get('balance', '0'), 0))
        self.in_bass.setValue(self._to_int(m.get('bass', '0'), 0))
        self.in_treble.setValue(self._to_int(m.get('treble', '0'), 0))
        self._set_combo(self.in_channels, m.get('channels', 'stereo'))
        self.in_stereo_width.setValue(self._to_int(m.get('stereo_width', '100'), 100))
        self._set_combo(self.in_playback_freq, m.get('playback frequency', 'auto'))
        self._set_combo(self.in_album_art, m.get('album art', 'prefer embedded'))

        # Display
        self.in_brightness.setValue(self._to_int(m.get('brightness', '32'), 32))
        self.in_backlight.setValue(self._to_int(m.get('backlight timeout', '15'), 15))
        self.in_backlight_plug.setValue(self._to_int(m.get('backlight timeout plugged', '15'), 15))
        self._set_combo(self.in_statusbar, m.get('statusbar', 'off'))
        self.in_scrollbar.setChecked(self._to_bool(m.get('scrollbar', 'off')))
        self.in_scrollbar_width.setValue(self._to_int(m.get('scrollbar width', '8'), 8))
        self.in_show_icons.setChecked(self._to_bool(m.get('show icons', 'on')))
        self.in_fg.setText(m.get('foreground color', 'ffffff'))
        self.in_bg.setText(m.get('background color', '000000'))
        self.in_sel_start.setText(m.get('line selector start color', 'ff0000'))
        self.in_sel_end.setText(m.get('line selector end color', 'ffffff'))
        self.in_sel_text.setText(m.get('line selector text color', 'ffffff'))

        # Paths
        self.in_start_dir.setText(m.get('start directory', '/'))
        self.in_font.setText(m.get('font', ''))
        self.in_wps.setText(m.get('wps', ''))
        self.in_sbs.setText(m.get('sbs', ''))
        self.in_iconset.setText(m.get('iconset', ''))
        self.in_viewer_icons.setText(m.get('viewers iconset', ''))

        # Sound / EQ
        self.eq_enabled_cb.setChecked(self._to_bool(m.get('eq enabled', 'off')))
        self.eq_precut.setValue(self._to_int(m.get('eq precut', '0'), 0))
        lf, lq, lg = self._parse_triple(m.get('eq low shelf filter', '32, 7, 0'), (32, 7, 0))
        self.eq_low_f.setValue(lf); self.eq_low_q.setValue(lq); self.eq_low_g.setValue(lg)
        for i, (f, q, g) in enumerate(self.eq_peaks, start=1):
            pf, pq, pg = self._parse_triple(m.get(f'eq peak filter {i}', '0, 0, 0'), (0, 0, 0))
            f.setValue(pf); q.setValue(pq); g.setValue(pg)
        hf, hq, hg = self._parse_triple(m.get('eq high shelf filter', '16000, 7, 0'), (16000, 7, 0))
        self.eq_high_f.setValue(hf); self.eq_high_q.setValue(hq); self.eq_high_g.setValue(hg)

        # Advanced
        self._rebuild_adv_form()

    def _on_save(self) -> None:
        m = self.model
        # Advanced first (so structured values override)
        for key, (_lab, _roww, edit) in self.adv_rows.items():
            m.set(key, edit.text())

        # Playback
        m.set('volume', self.in_volume.value())
        m.set('volume limit', self.in_volume_limit.value())
        m.set('shuffle', 'on' if self.in_shuffle.isChecked() else 'off')
        m.set('repeat', self.in_repeat.currentText())
        m.set('skip length', self.in_skip_length.currentText())
        m.set('antiskip', self.in_antiskip.value())
        m.set('replaygain type', self.in_replaygain.currentText())
        m.set('pitch', self.in_pitch.value())
        m.set('speed', self.in_speed.value())
        m.set('balance', self.in_balance.value())
        m.set('bass', self.in_bass.value())
        m.set('treble', self.in_treble.value())
        m.set('channels', self.in_channels.currentText())
        m.set('stereo_width', self.in_stereo_width.value())
        m.set('playback frequency', self.in_playback_freq.currentText())
        m.set('album art', self.in_album_art.currentText())

        # Display
        m.set('brightness', self.in_brightness.value())
        m.set('backlight timeout', self.in_backlight.value())
        m.set('backlight timeout plugged', self.in_backlight_plug.value())
        m.set('statusbar', self.in_statusbar.currentText())
        m.set('scrollbar', 'on' if self.in_scrollbar.isChecked() else 'off')
        m.set('scrollbar width', self.in_scrollbar_width.value())
        m.set('show icons', 'on' if self.in_show_icons.isChecked() else 'off')
        # colors: ensure 6-hex
        for k, edit in (
            ('foreground color', self.in_fg),
            ('background color', self.in_bg),
            ('line selector start color', self.in_sel_start),
            ('line selector end color', self.in_sel_end),
            ('line selector text color', self.in_sel_text),
        ):
            txt = edit.text().strip().lstrip('#')
            if re.fullmatch(r"[0-9a-fA-F]{6}", txt):
                m.set(k, txt.lower())
        # Paths
        m.set('start directory', self.in_start_dir.text().strip())
        m.set('font', self.in_font.text().strip())
        m.set('wps', self.in_wps.text().strip())
        m.set('sbs', self.in_sbs.text().strip())
        m.set('iconset', self.in_iconset.text().strip())
        m.set('viewers iconset', self.in_viewer_icons.text().strip())

        # Sound / EQ
        m.set('eq enabled', 'on' if self.eq_enabled_cb.isChecked() else 'off')
        m.set('eq precut', self.eq_precut.value())
        m.set('eq low shelf filter', self._format_triple(self.eq_low_f.value(), self.eq_low_q.value(), self.eq_low_g.value()))
        for i, (f, q, g) in enumerate(self.eq_peaks, start=1):
            m.set(f'eq peak filter {i}', self._format_triple(f.value(), q.value(), g.value()))
        m.set('eq high shelf filter', self._format_triple(self.eq_high_f.value(), self.eq_high_q.value(), self.eq_high_g.value()))

        if self._write_text(self.path, m.serialize()):
            self.accept()
        else:
            # Keep dialog open; parent can show status
            self.reject()

    # --------------- helpers ---------------
    @staticmethod
    def _to_int(v: str, default: int) -> int:
        try:
            return int(str(v).strip())
        except Exception:
            return default

    @staticmethod
    def _to_bool(v: str) -> bool:
        return str(v).strip().lower() in ("on", "true", "yes", "1")

    @staticmethod
    def _set_combo(box: QComboBox, value: str) -> None:
        v = (value or '').strip().lower()
        for i in range(box.count()):
            if box.itemText(i).strip().lower() == v:
                box.setCurrentIndex(i)
                return
        # Fallback to first
        if box.count() > 0:
            box.setCurrentIndex(0)

    @staticmethod
    def _parse_triple(s: str, default: Tuple[int, int, int]) -> Tuple[int, int, int]:
        try:
            parts = [p.strip() for p in str(s).split(',')]
            a = int(parts[0]) if len(parts) > 0 else default[0]
            b = int(parts[1]) if len(parts) > 1 else default[1]
            c = int(parts[2]) if len(parts) > 2 else default[2]
            return a, b, c
        except Exception:
            return default

    @staticmethod
    def _format_triple(a: int, b: int, c: int) -> str:
        return f"{a}, {b}, {c}"

    # -------- Advanced helpers --------
    def _rebuild_adv_form(self) -> None:
        # Clear
        while self.adv_form.rowCount() > 0:
            self.adv_form.removeRow(0)
        self.adv_rows.clear()
        # Build unique key list in order
        seen: set[str] = set()
        for rec in self.model.records:
            if rec.get('type') != 'kv':
                continue
            key = rec.get('key')
            if not key or key in seen:
                continue
            seen.add(key)
            lab = QLabel(key)
            roww = QWidget(); h = QHBoxLayout(roww); h.setContentsMargins(0,0,0,0)
            edit = QLineEdit(str(rec.get('value', '')))
            h.addWidget(edit, 1)
            rm = QPushButton('Remove');
            def _mk_remove(k=key, row_widget=roww, lab_widget=lab):
                def _do():
                    # remove from model and UI
                    self.model.remove(k)
                    row_widget.hide(); lab_widget.hide()
                    # Also remove from tracking dict
                    self.adv_rows.pop(k, None)
                return _do
            rm.clicked.connect(_mk_remove())
            h.addWidget(rm)
            self.adv_form.addRow(lab, roww)
            self.adv_rows[key] = (lab, roww, edit)
        self._apply_adv_filter()

    def _apply_adv_filter(self) -> None:
        q = self.adv_filter.text().strip().lower()
        for key, (lab, roww, _edit) in self.adv_rows.items():
            show = (q in key.lower()) if q else True
            lab.setVisible(show)
            roww.setVisible(show)

    def _adv_add(self) -> None:
        # lightweight inline add: creates an empty row; user fills key and value via two edits
        # To keep consistent with existing structure, show an input dialog pair
        from PySide6.QtWidgets import QInputDialog
        key, ok = QInputDialog.getText(self, "Add Setting", "Key (as in cfg):")
        if not ok or not key.strip():
            return
        key = key.strip()
        val, ok = QInputDialog.getText(self, "Add Setting", f"Value for '{key}':")
        if not ok:
            return
        self.model.set(key, val)
        # Rebuild to include new key in order
        self._rebuild_adv_form()
