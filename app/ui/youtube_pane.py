from __future__ import annotations
import os
import shlex
import sys
from typing import Any, Dict, List, Optional
import tempfile
import shutil

from PySide6.QtCore import Qt, QTimer, QProcess, QUrl, QSize, QEvent
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QComboBox, QListWidget, QListWidgetItem, QSpinBox, QFileDialog, QGroupBox,
    QCheckBox, QMessageBox, QDialog, QFormLayout, QAbstractItemView, QPlainTextEdit,
    QScroller, QScrollerProperties, QToolButton
)
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest

from core import ROOT, SCRIPTS_DIR
from settings_store import load_settings, save_settings
from ui.explorer_pane import ImportDialog
import json
import re
import subprocess


class YouTubePane(QWidget):
    """Browse YouTube (search, playlists, feeds) and download via yt-dlp.

    - Uses yt-dlp Python API to browse without downloading.
    - Spawns a background process to run the downloader script for selections.
    - Supports cookies from browser or cookies.txt, and download profiles/presets.
    """

    # Data keys provided by yt_browse.py
    COLS = ("title", "channel", "duration", "upload_date", "url", "thumbnail")

    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.proc: Optional[QProcess] = None
        self.settings = load_settings()
        # Browse pagination state
        self._browse_kind: Optional[str] = None  # 'search'|'playlist'|'home'|'watchlater'|'liked'|'myplaylists'|'subs'
        self._browse_params: Dict[str, Any] = {}
        self._page_size: int = 25
        self._next_start: int = 1
        self._loading_more: bool = False
        self._seen_urls: set[str] = set()
        self._selected_urls: set[str] = set()
        self._url_to_card_button: Dict[str, QPushButton] = {}
        self._post_download: Optional[Dict[str, Any]] = None
        self._build_ui()
        self._load_profiles()

    # ---------- UI ----------
    def _build_ui(self):
        root = QVBoxLayout(self)

        # Top row: search and playlist URL
        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Search:"))
        self.search_edit = QLineEdit(); self.search_edit.setPlaceholderText("e.g. guns n' roses live")
        row1.addWidget(self.search_edit, 1)
        self.limit_spin = QSpinBox(); self.limit_spin.setRange(1, 500); self.limit_spin.setValue(25)
        row1.addWidget(QLabel("Limit:")); row1.addWidget(self.limit_spin)
        btn_search = QPushButton("Search"); btn_search.clicked.connect(self.on_search)
        row1.addWidget(btn_search)

        row1.addSpacing(16)
        row1.addWidget(QLabel("Playlist URL:"))
        self.playlist_edit = QLineEdit(); self.playlist_edit.setPlaceholderText("https://www.youtube.com/playlist?list=…")
        row1.addWidget(self.playlist_edit, 1)
        btn_pl = QPushButton("Open"); btn_pl.clicked.connect(self.on_open_playlist)
        row1.addWidget(btn_pl)
        root.addLayout(row1)

        # Row 2: categories (auth) + cookies
        row2 = QHBoxLayout()
        self.btn_home = QPushButton("Home")
        self.btn_watchlater = QPushButton("Watch Later")
        self.btn_liked = QPushButton("Liked")
        #self.btn_subs = QPushButton("Subscriptions")
        self.btn_mypls = QPushButton("My Playlists")
        for b in (self.btn_home, self.btn_watchlater, self.btn_liked, self.btn_mypls):
            b.clicked.connect(self.on_category)
            row2.addWidget(b)

        row2.addStretch(1)
        self.cookies_cb = QCheckBox("Use browser cookies")
        self.cookies_cb.setToolTip("Enable to access private feeds like Home, Watch Later, Liked, Subscriptions.")
        self.cookies_cb.setChecked(bool(self.settings.get('youtube_use_cookies', False)))
        row2.addWidget(self.cookies_cb)
        self.browser_combo = QComboBox(); self.browser_combo.addItems(["firefox", "chrome", "edge", "brave"])  # common options
        self.browser_combo.setCurrentText(self.settings.get('youtube_cookie_browser', 'firefox'))
        row2.addWidget(self.browser_combo)
        row2.addWidget(QLabel("or cookies.txt:"))
        self.cookies_path = QLineEdit(self.settings.get('youtube_cookie_file', ''))
        row2.addWidget(self.cookies_path, 1)
        b_cf = QPushButton("Browse"); b_cf.clicked.connect(self._browse_cookie)
        row2.addWidget(b_cf)
        root.addLayout(row2)

        # Results view (YouTube-like cards with thumbnails)
        self.list = QListWidget()
        self.list.setViewMode(QListWidget.IconMode)
        self.list.setFlow(QListWidget.LeftToRight)
        self.list.setWrapping(True)
        self.list.setResizeMode(QListWidget.Adjust)
        self.list.setSpacing(12)
        self.list.setUniformItemSizes(False)
        self.list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        # Smooth scrolling instead of snapping per item
        self.list.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.list.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        # Responsive card metrics
        self._min_card_width = 260
        self._thumb_size = QSize(320, 180)
        self._card_size = QSize(self._thumb_size.width() + 16, self._thumb_size.height() + 80)
        self.list.installEventFilter(self)
        try:
            # Detect near-bottom scrolling and auto-load next page
            self.list.verticalScrollBar().valueChanged.connect(self._on_scroll_value_changed)
        except Exception:
            pass

        # Selected videos section (collapsible)
        self.sel_toggle = QToolButton()
        self.sel_toggle.setText("Selected Videos")
        self.sel_toggle.setCheckable(True)
        self.sel_toggle.setChecked(True)
        self.sel_toggle.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.sel_toggle.setArrowType(Qt.DownArrow)

        self.sel_container = QWidget()
        sel_layout = QVBoxLayout(self.sel_container)
        sel_layout.setContentsMargins(9, 0, 9, 9)
        # Manual URL add row
        manual_row = QHBoxLayout()
        self.manual_url = QLineEdit(); self.manual_url.setPlaceholderText("Paste a YouTube video or playlist URL…")
        btn_add_url = QPushButton("Add URL")
        manual_row.addWidget(self.manual_url, 1)
        manual_row.addWidget(btn_add_url)
        sel_layout.addLayout(manual_row)
        self.selected_list = QListWidget()
        self.selected_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.selected_list.setMaximumHeight(140)
        sel_layout.addWidget(self.selected_list)
        sel_btns = QHBoxLayout()
        self.btn_remove_sel = QPushButton("Remove Selected")
        self.btn_clear_sel = QPushButton("Clear")
        sel_btns.addWidget(self.btn_remove_sel)
        sel_btns.addWidget(self.btn_clear_sel)
        sel_btns.addStretch(1)
        sel_layout.addLayout(sel_btns)

        # Layout: results above, then collapsible header + content
        root.addWidget(self.list, 1)
        root.addWidget(self.sel_toggle)
        root.addWidget(self.sel_container)

        # Kinetic (inertial) scrolling with smooth per-pixel deltas and no snapping
        try:
            self.list.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
            self.list.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
            scroller = QScroller.scroller(self.list.viewport())
            props = scroller.scrollerProperties()
            props.setScrollMetric(QScrollerProperties.FrameRate, QScrollerProperties.Fps60)
            props.setScrollMetric(QScrollerProperties.DecelerationFactor, 0.06)
            props.setScrollMetric(QScrollerProperties.DragVelocitySmoothingFactor, 0.15)
            props.setScrollMetric(QScrollerProperties.MaximumVelocity, 0.6)
            props.setScrollMetric(QScrollerProperties.MinimumVelocity, 0.0)
            props.setScrollMetric(QScrollerProperties.AxisLockThreshold, 0.12)
            props.setScrollMetric(QScrollerProperties.OvershootPolicy, QScrollerProperties.OvershootAlwaysOff)
            scroller.setScrollerProperties(props)
            QScroller.grabGesture(self.list.viewport(), QScroller.LeftMouseButtonGesture)
            # Smaller pixel steps for wheel/keys to avoid jumpy feel
            self.list.verticalScrollBar().setSingleStep(12)
            self.list.horizontalScrollBar().setSingleStep(12)
        except Exception:
            pass

        # Download controls
        dl_group = QGroupBox("Download")
        dl = QHBoxLayout(dl_group)
        # Destination input removed; will ask on download
        dl.addSpacing(12)
        dl.addWidget(QLabel("Profile/Preset:"))
        self.profile_combo = QComboBox(); self.profile_combo.setMinimumWidth(220)
        dl.addWidget(self.profile_combo)
        b_edit_prof = QPushButton("Edit Profiles…"); b_edit_prof.clicked.connect(self._edit_profiles)
        dl.addWidget(b_edit_prof)
        dl.addStretch(1)
        self.btn_download = QPushButton("Download Selected")
        self.btn_download.setProperty("accent", True)
        self.btn_download.clicked.connect(self.on_download_selected)
        dl.addWidget(self.btn_download)
        self.btn_download_import = QPushButton("Download && Import…")
        self.btn_download_import.clicked.connect(self.on_download_and_import)
        dl.addWidget(self.btn_download_import)
        root.addWidget(dl_group)

        # Status
        self.status = QLabel("")
        root.addWidget(self.status)

        # Browse process state for yt_browse.py
        self._browse_proc: Optional[QProcess] = None
        self._browse_buf: str = ''
        # Network for thumbnails
        self._net = QNetworkAccessManager(self)
        # Initial layout sizing
        QTimer.singleShot(0, self._recompute_grid)

        # Wire selected list controls
        self.btn_remove_sel.clicked.connect(self._remove_selected_from_queue)
        self.btn_clear_sel.clicked.connect(self._clear_selected_queue)
        self.sel_toggle.toggled.connect(self._toggle_selected_section)
        btn_add_url.clicked.connect(self._add_manual_url)

    def eventFilter(self, obj, ev):
        if obj is self.list and ev.type() in (QEvent.Resize, QEvent.Show, QEvent.LayoutRequest):
            QTimer.singleShot(0, self._recompute_grid)
        return super().eventFilter(obj, ev)

    def _recompute_grid(self):
        try:
            vpw = max(1, self.list.viewport().width())
            spacing = self.list.spacing() or 0
            # Compute columns to use most width with minimal leftover
            minw = self._min_card_width
            cols = max(1, (vpw + spacing) // (minw + spacing))
            # Card width uses available width minus inter-column spacing (no outer spacing)
            cw = max(minw, (vpw - spacing * max(0, cols - 1)) // cols)
            # Account for card internal margins (6 left/right)
            thumb_w = max(120, cw - 16)
            thumb_h = int(thumb_w * 9 / 16)
            self._thumb_size = QSize(thumb_w, thumb_h)
            self._card_size = QSize(cw, thumb_h + 80)
            self.list.setGridSize(self._card_size)
            # Update existing items/widgets
            for i in range(self.list.count()):
                it = self.list.item(i)
                if it:
                    it.setSizeHint(self._card_size)
                    w = self.list.itemWidget(it)
                    if w:
                        thumb = w.findChild(QLabel, "VideoThumb")
                        if thumb:
                            thumb.setFixedSize(self._thumb_size)
                            # Rescale if we have original pixmap
                            raw = getattr(thumb, "_raw_pixmap", None)
                            if isinstance(raw, QPixmap) and not raw.isNull():
                                thumb.setPixmap(raw.scaled(self._thumb_size, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation))
        except Exception:
            pass

    # ---------- Helpers ----------
    def _cookie_args(self) -> Dict[str, Optional[str]]:
        use = bool(self.cookies_cb.isChecked())
        cfile = (self.cookies_path.text() or '').strip()
        browser = self.browser_combo.currentText().strip()
        return {
            'cookies_from_browser': browser if use and not cfile else None,
            'cookies_file': cfile if use and cfile else None,
        }

    def _browse_cookie(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select cookies.txt", str(ROOT), "cookies.txt (*.txt);;All (*.*)")
        if path:
            self.cookies_path.setText(path)

    # Destination is chosen at download time via dialog now

    def _set_status(self, text: str):
        self.status.setText(text)

    def _insert_rows(self, rows: List[Dict[str, Any]]):
        for data in rows:
            it = QListWidgetItem()
            # Keep URL + all metadata on the item
            it.setData(Qt.UserRole, data)
            it.setSizeHint(self._card_size)
            self.list.addItem(it)
            w = self._make_card_widget(data)
            self.list.setItemWidget(it, w)

    def _make_card_widget(self, data: Dict[str, Any]) -> QWidget:
        card = QWidget(); card.setObjectName("VideoCard")
        v = QVBoxLayout(card); v.setContentsMargins(6, 6, 6, 6); v.setSpacing(6)
        # Thumbnail with big plus overlay
        thumb_container = QWidget(card)
        thumb_layout = QVBoxLayout(thumb_container)
        thumb_layout.setContentsMargins(0, 0, 0, 0)
        thumb_layout.setSpacing(0)
        thumb = QLabel(thumb_container); thumb.setObjectName("VideoThumb"); thumb.setFixedSize(self._thumb_size); thumb.setAlignment(Qt.AlignCenter)
        thumb.setStyleSheet("background:#222; border-radius:4px;")
        thumb_layout.addWidget(thumb)
        # Big '+' overlay button centered
        plus_btn = QPushButton("+", thumb_container)
        plus_btn.setCheckable(True)
        plus_btn.setCursor(Qt.PointingHandCursor)
        plus_btn.setToolTip("Add to download list")
        # Visual prominence
        plus_btn.setStyleSheet(
            "QPushButton { font-size: 36px; font-weight: 800; color: white;"
            " background-color: rgba(0,0,0,140); border: 2px solid rgba(255,255,255,180);"
            " border-radius: 28px; padding: 6px; }"
            "QPushButton:checked { background-color: rgba(46, 204, 113, 210); border-color: rgba(255,255,255,220); }"
        )
        # Position overlay by placing it after thumb in same layout cell using manual geometry on resize
        def _position_plus():
            try:
                # Center over the thumbnail area
                tw, th = thumb.width(), thumb.height()
                bw, bh = 56, 56
                x = max(0, (tw - bw) // 2)
                y = max(0, (th - bh) // 2)
                plus_btn.setGeometry(x, y, bw, bh)
                plus_btn.raise_()
            except Exception:
                pass
        _position_plus()
        thumb_container.resizeEvent = lambda ev: (_position_plus())
        v.addWidget(thumb_container)
        # Title
        title = QLabel(str(data.get('title') or ''))
        title.setWordWrap(True)
        title.setStyleSheet("font-weight:600;")
        v.addWidget(title)
        # Meta: channel + duration
        meta = QLabel(" · ".join([x for x in [str(data.get('channel') or ''), str(data.get('duration') or '')] if x]))
        meta.setStyleSheet("color:#888;")
        v.addWidget(meta)
        # Load thumbnail async
        url = str(data.get('thumbnail') or '')
        if url and url.startswith('http'):
            try:
                req = QNetworkRequest(QUrl(url))
                reply = self._net.get(req)
                def _on_done():
                    try:
                        ba = reply.readAll()
                        px = QPixmap()
                        if px.loadFromData(ba):
                            # Scale/crop to fit
                            thumb._raw_pixmap = px  # store original for rescale
                            scaled = px.scaled(self._thumb_size, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
                            thumb.setPixmap(scaled)
                    finally:
                        reply.deleteLater()
                reply.finished.connect(_on_done)
            except Exception:
                pass
        # Hook overlay button logic
        url = str(data.get('url') or '')
        if url:
            # sync state if already in selected queue
            plus_btn.setChecked(url in self._selected_urls)
            self._url_to_card_button[url] = plus_btn

            def on_toggle(checked: bool):
                if checked:
                    self._queue_add(data)
                else:
                    self._queue_remove(url)
            plus_btn.toggled.connect(on_toggle)

        return card

    # ---------- Selected queue management ----------
    def _queue_add(self, data: Dict[str, Any]):
        url = str(data.get('url') or '').strip()
        if not url or url in self._selected_urls:
            return
        self._selected_urls.add(url)
        it = QListWidgetItem(str(data.get('title') or url))
        it.setData(Qt.UserRole, data)
        self.selected_list.addItem(it)

    def _queue_remove(self, url: str):
        u = (url or '').strip()
        if not u:
            return
        # Remove from set and list widget
        if u in self._selected_urls:
            self._selected_urls.remove(u)
        # Update overlay button if present
        btn = self._url_to_card_button.get(u)
        if btn and btn.isChecked():
            try:
                btn.blockSignals(True)
                btn.setChecked(False)
            finally:
                btn.blockSignals(False)
        # Remove items from the selected list
        i = 0
        while i < self.selected_list.count():
            it = self.selected_list.item(i)
            d = it.data(Qt.UserRole) or {}
            if str(d.get('url') or '') == u:
                self.selected_list.takeItem(i)
                continue
            i += 1

    def _remove_selected_from_queue(self):
        items = self.selected_list.selectedItems()
        if not items:
            return
        for it in items:
            d = it.data(Qt.UserRole) or {}
            self._queue_remove(str(d.get('url') or ''))

    def _clear_selected_queue(self):
        # Clear all and uncheck overlays
        urls = list(self._selected_urls)
        for u in urls:
            self._queue_remove(u)

    def _toggle_selected_section(self, expanded: bool):
        try:
            self.sel_container.setVisible(bool(expanded))
            self.sel_toggle.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)
        except Exception:
            pass

    def _load_profiles(self):
        # Ensure default presets exist in settings (non-destructive merge by name)
        defaults: List[Dict[str, str]] = [
            {"name": "Preset: Best Audio (m4a)", "args": "--extract-audio -f \"ba[ext=m4a]/ba/bestaudio\""},
            {"name": "Preset: Best Audio (flac)", "args": "--extract-audio -f \"ba[ext=m4a]/ba/bestaudio\" --audio-format flac"},
            {"name": "Preset: Best Video (mp4)", "args": "-f 'bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/best'"},
            {"name": "Preset: Playlist Audio (indexed)",
             "args": "--yes-playlist --extract-audio -f \"ba[ext=m4a]/ba/bestaudio\" -o '%(playlist_title)s/%(playlist_index|02d)s. %(title)s.%(ext)s'"},
            {"name": "Preset: Best Audio Split Chapters",
             "args": "--split-chapters -f \"ba[ext=m4a]/ba/bestaudio\" --extract-audio -o 'chapter:%(title)s/%(section_number|02d)s. %(section_title)s.%(ext)s'"},
        ]
        profiles: List[Dict[str, str]] = self.settings.get('youtube_profiles', []) or []
        existing = { (p.get('name') or ''): p for p in profiles }
        changed = False
        for d in defaults:
            nm = d.get('name') or ''
            if not nm:
                continue
            if nm not in existing:
                profiles.append(d.copy())
                changed = True
            else:
                # Migrate old split-chapters template to use chapter-specific output
                if 'Split Chapters' in nm:
                    cur = existing[nm]
                    args = str(cur.get('args') or '')
                    if ' - %(section_number' in args and 'chapter:' not in args:
                        cur['args'] = d['args']
                        changed = True
        if changed:
            self.settings['youtube_profiles'] = profiles
            save_settings({'youtube_profiles': profiles})
        # Load profiles solely from settings so users can edit built-ins too
        self._profiles = profiles
        self.profile_combo.clear()
        for p in profiles:
            self.profile_combo.addItem(p.get('name') or '(unnamed)', p)
        # Restore last selection
        last = self.settings.get('youtube_last_profile')
        if isinstance(last, str):
            for i in range(self.profile_combo.count()):
                d = self.profile_combo.itemData(i)
                if isinstance(d, dict) and d.get('name') == last:
                    self.profile_combo.setCurrentIndex(i)
                    break

    def _edit_profiles(self):
        dlg = QDialog(self)
        dlg.setWindowTitle('YouTube Download Profiles')
        v = QVBoxLayout(dlg)
        form = QFormLayout()
        v.addLayout(form)

        select = QComboBox();
        # Only user profiles (exclude built-in presets)
        user_profiles: List[Dict[str, str]] = self.settings.get('youtube_profiles', []) or []
        for p in user_profiles:
            select.addItem(p.get('name') or '(unnamed)', p)
        form.addRow('Select:', select)

        name_edit = QLineEdit();
        args_edit = QPlainTextEdit(); args_edit.setPlaceholderText("e.g. --extract-audio --audio-format flac --embed-metadata")
        form.addRow('Name:', name_edit)
        form.addRow('Args:', args_edit)

        btns = QHBoxLayout(); btns.addStretch(1)
        b_new = QPushButton('New'); b_addopt = QPushButton('Add Option…'); b_save = QPushButton('Save'); b_del = QPushButton('Delete'); b_close = QPushButton('Close')
        btns.addWidget(b_new); btns.addWidget(b_addopt); btns.addWidget(b_save); btns.addWidget(b_del); btns.addWidget(b_close)
        v.addLayout(btns)

        def load_current():
            d = select.currentData()
            if isinstance(d, dict):
                name_edit.setText(d.get('name', ''))
                args_edit.setPlainText(d.get('args', ''))
            else:
                name_edit.setText('')
                args_edit.setPlainText('')

        def refresh_select():
            select.blockSignals(True)
            select.clear()
            for p in (self.settings.get('youtube_profiles', []) or []):
                select.addItem(p.get('name') or '(unnamed)', p)
            select.blockSignals(False)
            load_current()

        def on_new():
            name_edit.setText('My Profile')
            args_edit.setText('--extract-audio --audio-format m4a')
            select.setCurrentIndex(-1)

        def on_save():
            name = (name_edit.text() or '').strip()
            args = (args_edit.toPlainText() or '').strip()
            if not name:
                QMessageBox.warning(dlg, 'Profiles', 'Enter a profile name.')
                return
            profiles = (self.settings.get('youtube_profiles', []) or [])
            # Replace if exists, else append
            replaced = False
            for p in profiles:
                if p.get('name') == name:
                    p['args'] = args
                    replaced = True
                    break
            if not replaced:
                profiles.append({'name': name, 'args': args})
            self.settings['youtube_profiles'] = profiles
            if not save_settings({'youtube_profiles': profiles}):
                QMessageBox.critical(dlg, 'Profiles', 'Could not save settings.')
                return
            refresh_select()
            self._load_profiles()

        def on_delete():
            d = select.currentData()
            if not isinstance(d, dict):
                return
            name = d.get('name')
            profiles = (self.settings.get('youtube_profiles', []) or [])
            profiles = [p for p in profiles if p.get('name') != name]
            self.settings['youtube_profiles'] = profiles
            if not save_settings({'youtube_profiles': profiles}):
                QMessageBox.critical(dlg, 'Profiles', 'Could not save settings.')
                return
            refresh_select()
            self._load_profiles()

        select.currentIndexChanged.connect(lambda _: load_current())
        b_new.clicked.connect(on_new)
        b_save.clicked.connect(on_save)
        b_del.clicked.connect(on_delete)
        b_addopt.clicked.connect(lambda: self._open_option_picker_into(args_edit))
        b_close.clicked.connect(dlg.accept)
        load_current()
        dlg.exec()

    def _open_option_picker_into(self, args_edit: QPlainTextEdit):
        opts = self._load_ytdlp_options()
        # Build dialog
        dlg = QDialog(self)
        dlg.setWindowTitle('Add yt-dlp Option')
        v = QVBoxLayout(dlg)
        search = QLineEdit(); search.setPlaceholderText('Search options…')
        v.addWidget(search)
        table = QTableWidget(0, 2)
        table.setHorizontalHeaderLabels(['Option', 'Description'])
        table.horizontalHeader().setStretchLastSection(True)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        v.addWidget(table, 1)
        form = QFormLayout()
        val_edit = QLineEdit(); val_edit.setPlaceholderText('Value (if required)')
        form.addRow('Value:', val_edit)
        v.addLayout(form)
        btns = QHBoxLayout(); btns.addStretch(1)
        addb = QPushButton('Add'); cancelb = QPushButton('Cancel')
        btns.addWidget(cancelb); btns.addWidget(addb)
        v.addLayout(btns)

        # Populate
        def refresh(filter_text: str = ''):
            ft = filter_text.lower().strip()
            table.setRowCount(0)
            for o in opts:
                text = (o.get('opt','') + ' ' + o.get('metavar','') + ' ' + o.get('desc','')).lower()
                if ft and ft not in text:
                    continue
                r = table.rowCount(); table.insertRow(r)
                table.setItem(r, 0, QTableWidgetItem(o.get('display', o.get('opt', ''))))
                table.setItem(r, 1, QTableWidgetItem(o.get('desc', '')))
                table.setRowHeight(r, 22)
        refresh()

        current_meta = {'has_value': False, 'metavar': ''}

        def update_value_field():
            row = table.currentRow()
            if row < 0:
                val_edit.setEnabled(False); val_edit.setPlaceholderText('Value (if required)'); return
            # Map back to option
            disp = table.item(row, 0).text()
            # Find option by display
            meta = next((o for o in opts if o.get('display') == disp), None)
            hv = bool(meta and meta.get('has_value'))
            current_meta['has_value'] = hv
            current_meta['metavar'] = meta.get('metavar', '') if meta else ''
            val_edit.setEnabled(hv)
            if hv:
                ph = meta.get('metavar') or 'VALUE'
                val_edit.setPlaceholderText(ph)
            else:
                val_edit.setPlaceholderText('No value required')
                val_edit.clear()

        def do_add():
            row = table.currentRow()
            if row < 0:
                return
            disp = table.item(row, 0).text()
            meta = next((o for o in opts if o.get('display') == disp), None)
            if not meta:
                return
            arg = meta.get('opt') or disp.split()[0]
            if meta.get('has_value'):
                val = (val_edit.text() or '').strip()
                if not val:
                    QMessageBox.warning(dlg, 'Option', 'Please enter a value for this option.')
                    return
                part = f"{arg} {val}"
            else:
                part = arg
            existing = (args_edit.toPlainText() or '').strip()
            args_edit.setPlainText((existing + ' ' + part).strip())
            dlg.accept()

        table.currentCellChanged.connect(lambda *_: update_value_field())
        search.textChanged.connect(lambda t: refresh(t))
        addb.clicked.connect(do_add)
        cancelb.clicked.connect(dlg.reject)
        update_value_field()
        dlg.exec()

    def _load_ytdlp_options(self) -> List[Dict[str, str]]:
        if hasattr(self, '_ytdlp_option_cache') and isinstance(self._ytdlp_option_cache, list):
            return self._ytdlp_option_cache
        text = ''
        try:
            cp = subprocess.run(['yt-dlp', '--help'], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=5)
            text = cp.stdout or ''
        except Exception:
            text = ''
        opts: List[Dict[str, str]] = []
        if text:
            # Parse lines like: "  -x, --extract-audio          Convert video files to audio-only"
            # Or:               "      --audio-format FORMAT    Specify audio format: best|aac|flac|mp3|m4a|opus|vorbis|wav"
            lines = text.splitlines()
            current = None
            pat = re.compile(r"^\s*(?:-[\w-],\s*)?(--[\w-]+)(?:[ =]([A-Z][A-Z0-9_-]*))?\s{2,}(.*)$")
            for ln in lines:
                m = pat.match(ln)
                if m:
                    opt, metavar, desc = m.group(1), m.group(2) or '', m.group(3).strip()
                    current = {
                        'opt': opt,
                        'display': (opt + (f" {metavar}" if metavar else '')),
                        'has_value': bool(metavar),
                        'metavar': metavar,
                        'desc': desc,
                    }
                    opts.append(current)
                else:
                    # Continuation of description
                    if current is not None and ln.strip() and not ln.lstrip().startswith('-'):
                        current['desc'] = (current.get('desc','') + ' ' + ln.strip()).strip()
        if not opts:
            # Fallback minimal set if parsing failed
            opts = [
                {'opt':'--extract-audio','display':'--extract-audio','has_value':False,'metavar':'','desc':'Convert video files to audio-only format.'},
                {'opt':'--audio-format','display':'--audio-format FORMAT','has_value':True,'metavar':'FORMAT','desc':'Audio format: best|aac|flac|mp3|m4a|opus|vorbis|wav'},
                {'opt':'-f','display':'-f FORMAT','has_value':True,'metavar':'FORMAT','desc':'Video format selection expression.'},
                {'opt':'--embed-metadata','display':'--embed-metadata','has_value':False,'metavar':'','desc':'Embed metadata in the downloaded files.'},
                {'opt':'--embed-thumbnail','display':'--embed-thumbnail','has_value':False,'metavar':'','desc':'Embed thumbnail in the audio as cover art.'},
                {'opt':'--add-metadata','display':'--add-metadata','has_value':False,'metavar':'','desc':'Write metadata to file.'},
            ]
        self._ytdlp_option_cache = opts
        return opts

    # ---------- Actions ----------
    def on_search(self):
        q = (self.search_edit.text() or '').strip()
        if not q:
            return
        self._begin_browse('search', {'query': q})

    def on_open_playlist(self):
        url = (self.playlist_edit.text() or '').strip()
        if not url:
            return
        # Save cookies context in params
        cargs = self._cookie_args()
        params = {'url': url, **cargs}
        self._begin_browse('playlist', params)

    def on_category(self):
        sender = self.sender()
        if not hasattr(sender, 'text'):
            return
        label = str(sender.text()).lower()
        cmd_map = {
            'home': 'home',
            'watch later': 'watchlater',
            'liked': 'liked',
            'subscriptions': 'subs',
            'my playlists': 'myplaylists',
        }
        subcmd = cmd_map.get(label)
        if not subcmd:
            return
        cargs = self._cookie_args()
        self._begin_browse(subcmd, {**cargs})

    # ---------- Process handling for browse ----------
    def _begin_browse(self, kind: str, params: Dict[str, Any]):
        # Reset list and paging state, then load first page
        self._browse_kind = kind
        self._browse_params = params or {}
        self._page_size = int(self.limit_spin.value()) or 25
        self._next_start = 1
        self._seen_urls.clear()
        self.list.clear()
        self._set_status('Loading…')
        self._load_page(self._next_start, self._page_size)

    def _make_args_for_page(self, start: int, limit: int) -> List[str]:
        kind = self._browse_kind or ''
        p = self._browse_params or {}
        args: List[str] = []
        if kind == 'search':
            args = ["search", str(p.get('query', '')), "--start", str(start), "--limit", str(limit)]
        elif kind == 'playlist':
            args = ["playlist", str(p.get('url', '')), "--start", str(start), "--limit", str(limit)]
        elif kind in ('home', 'watchlater', 'liked', 'subs', 'myplaylists'):
            args = [kind, "--start", str(start), "--limit", str(limit)]
        else:
            args = []
        # Cookies if present
        if p.get('cookies_file'):
            args += ["--cookies-file", str(p['cookies_file'])]
        elif p.get('cookies_from_browser'):
            args += ["--cookies-from-browser", str(p['cookies_from_browser'])]
        return args

    def _load_page(self, start: int, limit: int):
        if self._loading_more:
            return
        args = self._make_args_for_page(start, limit)
        if not args:
            return
        # Kill previous browse process if still running
        if self._browse_proc is not None:
            try:
                self._browse_proc.kill()
            except Exception:
                pass
            self._browse_proc = None
        self._browse_buf = ''
        self._loading_more = True
        py = shlex.quote(sys.executable)
        script = shlex.quote(str(SCRIPTS_DIR / 'yt_browse.py'))
        cmd = " ".join([py, '-u', script, '--format', 'jsonl'] + [shlex.quote(a) for a in args])
        p = QProcess(self)
        self._browse_proc = p
        p.setWorkingDirectory(str(ROOT))
        p.setProcessChannelMode(QProcess.MergedChannels)

        def on_out():
            data = bytes(p.readAllStandardOutput()).decode('utf-8', errors='ignore')
            if not data:
                return
            self._browse_buf += data
            lines = self._browse_buf.split('\n')
            self._browse_buf = '' if self._browse_buf.endswith('\n') else lines.pop()
            new_rows: List[Dict[str, Any]] = []
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    # non-JSON line: status or error
                    self._set_status(line)
                    continue
                row = {
                    'title': obj.get('title', ''),
                    'channel': obj.get('channel', ''),
                    'duration': obj.get('duration', ''),
                    'upload_date': obj.get('upload_date', ''),
                    'url': obj.get('url', ''),
                    'thumbnail': obj.get('thumbnail', ''),
                }
                u = (row.get('url') or '').strip()
                if u and u not in self._seen_urls:
                    self._seen_urls.add(u)
                    new_rows.append(row)
            if new_rows:
                self._insert_rows(new_rows)
                self._recompute_grid()

        def on_done(rc, _st):
            self._loading_more = False
            if rc != 0 and self.status.text().strip() == 'Loading…':
                self._set_status('No results or failed.')
            else:
                # Advance next start; be robust to partial pages
                self._next_start = max(self._next_start, start + limit)
                if self.list.count() > 0 and self.status.text().strip().startswith('Loading'):
                    self._set_status('')

        p.readyReadStandardOutput.connect(on_out)
        p.finished.connect(on_done)
        p.start("/bin/sh", ["-c", cmd])

    def _on_scroll_value_changed(self, value: int):
        try:
            bar = self.list.verticalScrollBar()
            if not bar:
                return
            # Trigger when within 3 item-heights from bottom
            threshold = max(120, self._card_size.height() * 3)
            if value >= (bar.maximum() - threshold):
                # Load next page if not already loading
                if not self._loading_more and self._browse_kind:
                    self._set_status('Loading more…')
                    self._load_page(self._next_start, self._page_size)
        except Exception:
            pass

    def on_download_selected(self):
        # Use the selected queue (small list)
        if self.selected_list.count() <= 0:
            QMessageBox.information(self, "YouTube", "No videos queued. Click + on videos to add.")
            return
        urls: List[str] = []
        for i in range(self.selected_list.count()):
            it = self.selected_list.item(i)
            d = it.data(Qt.UserRole) or {}
            u = str((d.get('url') or '')).strip()
            if u:
                urls.append(u)
        if not urls:
            QMessageBox.warning(self, "YouTube", "No URLs found in the selected rows.")
            return

        # Ask user for destination each time (starting in last used or music root)
        start_dir = (self.settings.get('youtube_default_dest')
                     or self.controller.settings.get('music_root', '')
                     or str(ROOT))
        dest = QFileDialog.getExistingDirectory(self, "Select download folder", start_dir)
        if not dest:
            # User canceled
            return

        prof = self.profile_combo.currentData()
        args_str = ''
        if isinstance(prof, dict):
            args_str = prof.get('args', '') or ''
            # remember selection
            patch = {
                'youtube_last_profile': prof.get('name'),
                'youtube_default_dest': dest,  # remember last for next start dir
                'youtube_use_cookies': bool(self.cookies_cb.isChecked()),
                'youtube_cookie_browser': self.browser_combo.currentText(),
                'youtube_cookie_file': self.cookies_path.text(),
            }
            self.settings.update(patch)
            save_settings(patch)

        # Build command for downloader script
        py = shlex.quote(sys.executable)
        script = shlex.quote(str(SCRIPTS_DIR / 'yt_download.py'))
        parts = [py, '-u', script, '--dest', shlex.quote(dest)]
        # If settings specify an ffmpeg path and profile args don't override, pass it through
        try:
            ffmpeg_path = (self.controller.settings.get('ffmpeg_path') or '').strip()
        except Exception:
            ffmpeg_path = (self.settings.get('ffmpeg_path') or '').strip()
        if ffmpeg_path and ('--ffmpeg-location' not in (args_str or '')):
            parts.extend(['--ffmpeg-location', shlex.quote(ffmpeg_path)])
        if args_str:
            parts.extend(['--args', shlex.quote(args_str)])
        # Cookies
        cargs = self._cookie_args()
        if cargs.get('cookies_file'):
            parts.extend(['--cookies-file', shlex.quote(str(cargs['cookies_file']))])
        elif cargs.get('cookies_from_browser'):
            parts.extend(['--cookies-from-browser', shlex.quote(str(cargs['cookies_from_browser']))])
        # URLs last
        for u in urls:
            parts.append(shlex.quote(u))
        cmd = " ".join(parts)
        # Launch process
        self._post_download = None
        self._start_process(cmd)

    def on_download_and_import(self):
        # Gather URLs
        if self.selected_list.count() <= 0:
            QMessageBox.information(self, "YouTube", "No videos queued. Click + on videos to add.")
            return
        urls: List[str] = []
        for i in range(self.selected_list.count()):
            it = self.selected_list.item(i)
            d = it.data(Qt.UserRole) or {}
            u = str((d.get('url') or '')).strip()
            if u:
                urls.append(u)
        if not urls:
            QMessageBox.warning(self, "YouTube", "No URLs found in the selected rows.")
            return
        # Create temp directory for download
        tmpdir = tempfile.mkdtemp(prefix='rocksync_ytdl_')

        prof = self.profile_combo.currentData()
        args_str = ''
        if isinstance(prof, dict):
            args_str = prof.get('args', '') or ''
            patch = {
                'youtube_last_profile': prof.get('name'),
                'youtube_use_cookies': bool(self.cookies_cb.isChecked()),
                'youtube_cookie_browser': self.browser_combo.currentText(),
                'youtube_cookie_file': self.cookies_path.text(),
            }
            self.settings.update(patch)
            save_settings(patch)

        py = shlex.quote(sys.executable)
        script = shlex.quote(str(SCRIPTS_DIR / 'yt_download.py'))
        parts = [py, '-u', script, '--dest', shlex.quote(tmpdir)]
        try:
            ffmpeg_path = (self.controller.settings.get('ffmpeg_path') or '').strip()
        except Exception:
            ffmpeg_path = (self.settings.get('ffmpeg_path') or '').strip()
        if ffmpeg_path and ('--ffmpeg-location' not in (args_str or '')):
            parts.extend(['--ffmpeg-location', shlex.quote(ffmpeg_path)])
        if args_str:
            parts.extend(['--args', shlex.quote(args_str)])
        cargs = self._cookie_args()
        if cargs.get('cookies_file'):
            parts.extend(['--cookies-file', shlex.quote(str(cargs['cookies_file']))])
        elif cargs.get('cookies_from_browser'):
            parts.extend(['--cookies-from-browser', shlex.quote(str(cargs['cookies_from_browser']))])
        for u in urls:
            parts.append(shlex.quote(u))
        cmd = " ".join(parts)
        # Record post action and start
        self._post_download = { 'kind': 'import', 'tmpdir': tmpdir }
        self._start_process(cmd)

    def _add_manual_url(self):
        url = (self.manual_url.text() or '').strip()
        if not url:
            return
        # Basic validation: require URL scheme and host
        if not (url.startswith('http://') or url.startswith('https://')):
            QMessageBox.warning(self, 'Add URL', 'Please enter a valid video or playlist URL (http/https).')
            return
        # Avoid duplicates
        if url in self._selected_urls:
            QMessageBox.information(self, 'Add URL', 'This URL is already in the selected list.')
            return
        # Add minimal metadata; downloader handles both video and playlist URLs
        data = {
            'url': url,
            'title': url,
            'channel': '',
            'duration': '',
            'upload_date': '',
            'thumbnail': '',
        }
        self._queue_add(data)
        self.manual_url.clear()

    # ---------- Process handling ----------
    def _start_process(self, cmd: str):
        if self.proc is not None:
            try:
                self.proc.kill()
            except Exception:
                pass
            self.proc = None
        self.proc = QProcess(self)
        self.proc.setWorkingDirectory(str(ROOT))
        self.proc.setProcessChannelMode(QProcess.MergedChannels)
        self.proc.readyReadStandardOutput.connect(lambda: self._append_status(bytes(self.proc.readAllStandardOutput()).decode('utf-8', errors='ignore')))
        self.proc.finished.connect(self._on_downloader_finished)
        self._set_status("Starting download…")
        self.proc.start("/bin/sh", ["-c", cmd])

    def _append_status(self, text: str):
        # Keep small last-chunk view in the label; the full output is not displayed to avoid heavy UI
        t = (self.status.text() or '')
        t = (t + "\n" + text).splitlines()[-6:]
        self.status.setText("\n".join(t))

    def _on_downloader_finished(self, rc: int, _status):
        try:
            self._append_status(f"\n[Downloader exit {rc}]\n")
            if int(rc) == 0:
                # Clear queue on success
                self._clear_selected_queue()
                # If an import is pending, run it
                if self._post_download and self._post_download.get('kind') == 'import':
                    tmp = self._post_download.get('tmpdir')
                    self._post_download = None
                    if tmp and os.path.isdir(tmp):
                        self._do_import_from_temp(tmp)
            else:
                # Clean up temp dir if any pending import
                if self._post_download and self._post_download.get('kind') == 'import':
                    tmp = self._post_download.get('tmpdir')
                    self._post_download = None
                    try:
                        if tmp and os.path.isdir(tmp):
                            shutil.rmtree(tmp)
                    except Exception:
                        pass
        except Exception:
            pass

    # ---------- Import integration ----------
    def _do_import_from_temp(self, tmpdir: str):
        try:
            files = self._collect_audio_files(tmpdir)
            if not files:
                QMessageBox.information(self, "Import", "No audio files were downloaded.")
                try:
                    shutil.rmtree(tmpdir)
                except Exception:
                    pass
                return
            # Open Import dialog with preloaded files
            dlg = ImportDialog(self)
            dlg.files = files
            try:
                dlg.files_edit.setText(f"{len(files)} file(s) selected")
            except Exception:
                pass
            if dlg.exec() != QDialog.Accepted:
                try:
                    shutil.rmtree(tmpdir)
                except Exception:
                    pass
                return
            params = dlg.get_values()
            music_root = self.controller.settings.get('music_root', '')
            if not music_root:
                QMessageBox.warning(self, "Import", "Set your Music Root in Settings first.")
                return
            os.makedirs(music_root, exist_ok=True)
            # Modes copied from Explorer import logic
            if params['mode'] == 'Album':
                artist, album = params.get('artist',''), params.get('album','')
                if not artist or not album:
                    # Try simple inference from first file
                    a, al = self._extract_artist_album(files[0])
                    artist = artist or a
                    album = album or al
                base = os.path.join(music_root, 'Albums', self._safe_part(artist), self._safe_part(album))
                os.makedirs(base, exist_ok=True)
                # Copy and split into album folder
                copied = self._copy_files(files, base)
                if copied:
                    QMessageBox.information(self, "Import Complete", f"Imported {len(copied)} files to\n{base}")
            elif params['mode'] == 'Playlist':
                name = params.get('playlist', '').strip()
                sub = params.get('subfolder', '').strip()
                base = os.path.join(music_root, 'Playlists')
                dest_dir = os.path.join(base, sub, name) if sub else os.path.join(base, name)
                os.makedirs(dest_dir, exist_ok=True)
                copied = self._copy_files(files, dest_dir)
                QMessageBox.information(self, "Import Complete", f"Imported {len(copied)} files to\n{dest_dir}")
            else:
                dest = os.path.join(music_root, 'Tracks')
                os.makedirs(dest, exist_ok=True)
                copied = self._copy_files(files, dest)
                QMessageBox.information(self, "Import Complete", f"Imported {len(copied)} files to\n{dest}")
        except Exception as e:
            QMessageBox.critical(self, "Import Error", f"Failed to import: {e}")
        finally:
            try:
                shutil.rmtree(tmpdir)
            except Exception:
                pass

    def _collect_audio_files(self, root_dir: str) -> List[str]:
        exts = {'.flac','.mp3','.m4a','.alac','.aac','.ogg','.opus','.wav'}
        out: List[str] = []
        for base, _dirs, fnames in os.walk(root_dir):
            for fn in fnames:
                try:
                    if os.path.splitext(fn)[1].lower() in exts:
                        out.append(os.path.join(base, fn))
                except Exception:
                    continue
        return out

    def _copy_files(self, files: List[str], dest_dir: str) -> List[str]:
        copied: List[str] = []
        for src in files:
            try:
                base = os.path.basename(src)
                name, ext = os.path.splitext(base)
                target = os.path.join(dest_dir, base)
                i = 1
                while os.path.exists(target):
                    target = os.path.join(dest_dir, f"{name}_{i}{ext}")
                    i += 1
                shutil.copy2(src, target)
                copied.append(target)
            except Exception:
                continue
        return copied

    def _safe_part(self, name: str) -> str:
        bad = ['/', '\\', ':']
        s = (name or '').strip() or 'Unknown'
        for b in bad:
            s = s.replace(b, '_')
        return s

    def _extract_artist_album(self, file_path: str):
        try:
            from mutagen import File as MFile
            easy = MFile(file_path, easy=True)
            tags = getattr(easy, 'tags', None) or {}
            def pick(v):
                if isinstance(v, list) and v:
                    return str(v[0]).strip()
                if isinstance(v, str):
                    return v.strip()
                return ''
            artist = pick(tags.get('albumartist')) or pick(tags.get('artist'))
            album = pick(tags.get('album'))
            return artist, album
        except Exception:
            return '', ''
