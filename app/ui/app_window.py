import os
import sys
import shlex
import uuid
from PySide6.QtCore import Qt, QProcess, QTimer
from PySide6.QtGui import QTextCursor, QColor
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QListWidget, QListWidgetItem, QStackedWidget,
    QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QGroupBox, QFormLayout, QLineEdit,
    QSpinBox, QCheckBox, QComboBox, QPlainTextEdit, QFileDialog, QMessageBox, QDialog,
    QProgressBar
)

from core import ROOT, USER_SCRIPTS_DIR, cmd_exists
import logging
from settings_store import load_settings, save_settings
from logging_utils import setup_logging, ui_log
from tasks_registry import get_tasks
from ui.explorer_pane import ExplorerPane
from ui.search_pane import SearchPane
from ui.database_pane import DatabasePane
from ui.device_pane import DeviceExplorerPane
from ui.sync_pane import SyncPane
from ui.daily_mix_pane import DailyMixPane
from ui.tidal_pane import TidalPane
from ui.youtube_pane import YouTubePane
from ui.rockbox_pane import RockboxPane
from ui.genre_pane import GenreTaggerPane
from theme import apply_theme
from theme_loader import list_theme_files


class AppWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("RockSync GUI")
        self.resize(1100, 700)

        self.proc = None
        self.settings = load_settings()
        self.session_id = str(uuid.uuid4())[:8]
        self.logger = setup_logging(self.settings, self.session_id)
        self._active_task = {}

        self._init_ui()

    # --------------- UI skeleton ---------------
    def _init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root_v = QVBoxLayout(central)

        # Preload tasks for quick actions and consistency
        try:
            self.tasks = get_tasks(self.settings)
        except Exception:
            self.tasks = []

        # Top app bar (Material-ish)
        top_bar = QWidget()
        top_bar.setObjectName("TopAppBar")
        top_h = QHBoxLayout(top_bar)
        title = QLabel("RockSync")
        title.setObjectName("TopAppTitle")
        top_h.addWidget(title)
        top_h.addStretch(1)

        # Device / Status indicator cluster (very visible)
        self.device_group = QWidget(); self.device_group.setObjectName("DeviceIndicator")
        dg = QHBoxLayout(self.device_group); dg.setContentsMargins(8, 4, 8, 4); dg.setSpacing(8)
        # Current action label
        self.action_label = QLabel("Idle")
        self.action_label.setObjectName("ActionStatus")
        self.action_label.setStyleSheet("font-weight: 600; color: #0a7;")
        # Prevent window from resizing on long status strings
        self.action_label.setMinimumWidth(120)
        self.action_label.setMaximumWidth(220)
        dg.addWidget(self.action_label)
        # Action progress bar (overall task progress)
        self.action_progress = QProgressBar()
        self.action_progress.setObjectName("ActionProgress")
        self.action_progress.setMaximumWidth(140)
        self.action_progress.setMinimumWidth(120)
        self.action_progress.setRange(0, 100)
        self.action_progress.setValue(0)
        self.action_progress.setTextVisible(True)
        self.action_progress.setFormat("%p%")
        self.action_progress.setVisible(False)
        dg.addWidget(self.action_progress)
        # Device name + model
        self.device_label = QLabel("No device detected")
        self.device_label.setObjectName("DeviceLabel")
        self.device_label.setStyleSheet("font-weight: 600;")
        dg.addWidget(self.device_label)
        # Storage bar
        self.storage_bar = QProgressBar()
        self.storage_bar.setObjectName("DeviceStorageBar")
        self.storage_bar.setMinimumWidth(220)
        self.storage_bar.setMaximumWidth(300)
        self.storage_bar.setFormat("%p% used")
        self.storage_bar.setToolTip("Storage: unknown")
        self.storage_bar.setTextVisible(True)
        dg.addWidget(self.storage_bar)
        top_h.addWidget(self.device_group)
        # Stretch after indicator to center it between left title and right controls
        top_h.addStretch(1)
        
        # Quick theme switcher
        theme_options = ['system'] + list_theme_files()
        if 'theme_file' not in self.settings and 'theme' in self.settings:
            self.settings['theme_file'] = self.settings['theme']
        self.quick_theme_box = QComboBox()
        self.quick_theme_box.addItems(theme_options)
        self.quick_theme_box.setCurrentText(self.settings.get('theme_file', 'system'))
        self.quick_theme_box.currentTextChanged.connect(lambda t: (apply_theme(QApplication.instance(), t)))
        top_h.addWidget(QLabel("Theme:"))
        top_h.addWidget(self.quick_theme_box)
        root_v.addWidget(top_bar)

        # Content row with Navigation rail + pages
        content_row = QHBoxLayout()
        root_v.addLayout(content_row, 1)

        # Sidebar navigation (Navigation rail)
        self.nav = QListWidget()
        self.nav.setObjectName("NavList")
        self.nav.setAlternatingRowColors(False)
        self.nav.setMaximumWidth(240)
        self.nav.setMinimumWidth(200)
        self.nav.setSpacing(2)
        self.nav.setUniformItemSizes(True)
        content_row.addWidget(self.nav)

        # Stacked pages
        self.stack = QStackedWidget()
        content_row.addWidget(self.stack, 1)

        # Pages: build in preferred user flow order
        # Library (Explorer)
        self.explore_tab = QWidget(); ex_layout = QVBoxLayout(self.explore_tab)
        self.explorer = ExplorerPane(self, self.explore_tab)
        ex_layout.addWidget(self.explorer)
        self.stack.addWidget(self.explore_tab)

        # Search
        self.search_tab = QWidget(); se_layout = QVBoxLayout(self.search_tab)
        self.search = SearchPane(self, self.search_tab)
        se_layout.addWidget(self.search)
        self.stack.addWidget(self.search_tab)

        # Device
        self.device_tab = QWidget(); dv_layout = QVBoxLayout(self.device_tab)
        self.device_explorer = DeviceExplorerPane(self, self.device_tab)
        dv_layout.addWidget(self.device_explorer)
        self.stack.addWidget(self.device_tab)

        # Database
        self.db_tab = QWidget(); db_layout = QVBoxLayout(self.db_tab)
        self.db = DatabasePane(self, self.db_tab)
        db_layout.addWidget(self.db)
        self.stack.addWidget(self.db_tab)

        # Manual Genres
        self.genre_tab = QWidget(); gn_layout = QVBoxLayout(self.genre_tab)
        self.genre = GenreTaggerPane(self, self.genre_tab)
        self.genre_tagger = self.genre
        gn_layout.addWidget(self.genre)
        self.stack.addWidget(self.genre_tab)

        # Sync
        self.sync_tab = QWidget(); sy_layout = QVBoxLayout(self.sync_tab)
        self.sync = SyncPane(self, self.sync_tab)
        sy_layout.addWidget(self.sync)
        self.stack.addWidget(self.sync_tab)

        # Rockbox
        self.rockbox_tab = QWidget(); rb_layout = QVBoxLayout(self.rockbox_tab)
        self.rockbox = RockboxPane(self, self.rockbox_tab)
        rb_layout.addWidget(self.rockbox)
        self.stack.addWidget(self.rockbox_tab)

        # Optional add-ons (created conditionally)
        self.tidal_tab = None
        self.tidal = None
        self.youtube_tab = None
        self.youtube = None
        self._ensure_tidal_tab()  # creates only if enabled in settings
        self._ensure_youtube_tab()  # creates only if enabled in settings

        # Daily Mix (kept as a separate page)
        self.daily_tab = QWidget(); dl_layout = QVBoxLayout(self.daily_tab)
        self.daily = DailyMixPane(self, self.daily_tab)
        dl_layout.addWidget(self.daily)
        self.stack.addWidget(self.daily_tab)

        # Settings
        self.settings_tab = QWidget()
        self._build_settings_tab(self.settings_tab)
        self.stack.addWidget(self.settings_tab)

        # Tasks (Advanced)
        self.run_tab = QWidget()
        self._build_run_tab(self.run_tab)
        self.stack.addWidget(self.run_tab)

        # Populate navigation list
        def add_header(text):
            it = QListWidgetItem(text)
            it.setFlags(Qt.NoItemFlags)
            it.setData(Qt.UserRole, None)
            self.nav.addItem(it)

        def add_page(text, page_index):
            it = QListWidgetItem(text)
            it.setData(Qt.UserRole, int(page_index))
            self.nav.addItem(it)

        # Use actual stack indices to avoid hardcoded mismatch as pages change
        add_page("Library", self.stack.indexOf(self.explore_tab))
        add_page("Device", self.stack.indexOf(self.device_tab))
        add_page("Search", self.stack.indexOf(self.search_tab))
        add_page("Sync", self.stack.indexOf(self.sync_tab))
        add_page("Playlists", self.stack.indexOf(self.daily_tab))
        add_page("Database", self.stack.indexOf(self.db_tab))
        add_page("Genres", self.stack.indexOf(self.genre_tab))
        add_page("Settings", self.stack.indexOf(self.settings_tab))
        add_page("Rockbox", self.stack.indexOf(self.rockbox_tab))
        add_page("Advanced", self.stack.indexOf(self.run_tab))
        if getattr(self, 'tidal_tab', None) is not None:
            add_page("Tidal-dl-ng", self.stack.indexOf(self.tidal_tab))
        if getattr(self, 'youtube_tab', None) is not None:
            add_page("YouTube", self.stack.indexOf(self.youtube_tab))

        def on_nav_changed():
            it = self.nav.currentItem()
            if not it:
                return
            idx = it.data(Qt.UserRole)
            if idx is None:
                # Jump to next selectable item
                ci = self.nav.currentRow()
                # Move down until a selectable item
                for j in range(ci + 1, self.nav.count()):
                    if self.nav.item(j).flags() & Qt.ItemIsEnabled:
                        self.nav.setCurrentRow(j)
                        return
                return
            self.stack.setCurrentIndex(int(idx))
            try:
                from logging_utils import ui_log
                ui_log('nav_change', label=str(it.text()), index=int(idx))
            except Exception:
                pass

        self.nav.currentItemChanged.connect(lambda _c, _p: on_nav_changed())
        # Select first real page
        for i in range(self.nav.count()):
            if self.nav.item(i).data(Qt.UserRole) is not None:
                self.nav.setCurrentRow(i)
                break

        # Lazy-initialize heavy/online pages when shown
        def _on_page_changed(idx: int):
            try:
                if getattr(self, 'tidal_tab', None) is not None and idx == self.stack.indexOf(self.tidal_tab):
                    # Initialize Tidal pane on demand to avoid startup failures
                    if hasattr(self, 'tidal'):
                        self.tidal.activate()
                if hasattr(self, 'genre_tagger'):
                    genre_idx = self.stack.indexOf(self.genre_tab)
                    if idx != genre_idx:
                        self.genre_tagger.disable_autoplay()
            except Exception:
                pass

        self.stack.currentChanged.connect(_on_page_changed)

        self.statusBar().showMessage(f"Music root: {self.settings.get('music_root')}")

        # Apply theme after UI exists
        apply_theme(QApplication.instance(), self.settings.get('theme_file', 'system'))

        # Kick off device indicator updates
        self._update_device_indicator()
        self.device_timer = QTimer(self)
        self.device_timer.setInterval(8000)
        self.device_timer.timeout.connect(self._update_device_indicator)
        self.device_timer.start()

    # --------------- Add-on tabs management ---------------
    def _ensure_tidal_tab(self):
        try:
            enabled = bool(self.settings.get('enable_tidal', False))
        except Exception:
            enabled = False
        if enabled and self.tidal_tab is None:
            try:
                self.tidal_tab = QWidget(); td_layout = QVBoxLayout(self.tidal_tab)
                self.tidal = TidalPane(self, self.tidal_tab)
                td_layout.addWidget(self.tidal)
                self.stack.addWidget(self.tidal_tab)
            except Exception:
                # If creation fails, ensure state remains consistent
                self.tidal_tab = None
                self.tidal = None
        if not enabled and self.tidal_tab is not None:
            try:
                idx = self.stack.indexOf(self.tidal_tab)
                if idx >= 0:
                    self.stack.removeWidget(self.tidal_tab)
                if hasattr(self, 'tidal') and self.tidal is not None:
                    try:
                        self.tidal.shutdown()
                    except Exception:
                        pass
                self.tidal_tab.deleteLater()
            except Exception:
                pass
            finally:
                self.tidal_tab = None
                self.tidal = None

    def _ensure_youtube_tab(self):
        try:
            enabled = bool(self.settings.get('enable_youtube', False))
        except Exception:
            enabled = False
        if enabled and self.youtube_tab is None:
            try:
                self.youtube_tab = QWidget(); yt_layout = QVBoxLayout(self.youtube_tab)
                self.youtube = YouTubePane(self, self.youtube_tab)
                yt_layout.addWidget(self.youtube)
                self.stack.addWidget(self.youtube_tab)
            except Exception:
                self.youtube_tab = None
                self.youtube = None
        if not enabled and self.youtube_tab is not None:
            try:
                idx = self.stack.indexOf(self.youtube_tab)
                if idx >= 0:
                    self.stack.removeWidget(self.youtube_tab)
                self.youtube_tab.deleteLater()
            except Exception:
                pass
            finally:
                self.youtube_tab = None
                self.youtube = None

    def _rebuild_navigation(self):
        try:
            self.nav.clear()
        except Exception:
            return
        def add_page(text, page_index):
            it = QListWidgetItem(text)
            it.setData(Qt.UserRole, int(page_index))
            self.nav.addItem(it)
        add_page("Library", self.stack.indexOf(self.explore_tab))
        add_page("Device", self.stack.indexOf(self.device_tab))
        add_page("Search", self.stack.indexOf(self.search_tab))
        add_page("Sync", self.stack.indexOf(self.sync_tab))
        add_page("Playlists", self.stack.indexOf(self.daily_tab))
        add_page("Database", self.stack.indexOf(self.db_tab))
        add_page("Genres", self.stack.indexOf(self.genre_tab))
        add_page("Settings", self.stack.indexOf(self.settings_tab))
        add_page("Rockbox", self.stack.indexOf(self.rockbox_tab))
        add_page("Advanced", self.stack.indexOf(self.run_tab))
        if getattr(self, 'tidal_tab', None) is not None:
            add_page("Tidal-dl-ng", self.stack.indexOf(self.tidal_tab))
        if getattr(self, 'youtube_tab', None) is not None:
            add_page("YouTube", self.stack.indexOf(self.youtube_tab))
        # Select first real page
        for i in range(self.nav.count()):
            try:
                if self.nav.item(i).data(Qt.UserRole) is not None:
                    self.nav.setCurrentRow(i)
                    break
            except Exception:
                pass

    # --------------- Top bar helpers ---------------
    def _human_bytes(self, n: int) -> str:
        try:
            n = int(n)
        except Exception:
            return "0 B"
        units = ["B", "KB", "MB", "GB", "TB", "PB"]
        i = 0
        f = float(n)
        while f >= 1024 and i < len(units) - 1:
            f /= 1024.0
            i += 1
        if i == 0:
            return f"{int(f)} {units[i]}"
        return f"{f:.1f} {units[i]}"

    def _choose_active_device(self, devices):
        if not devices:
            return None
        # Pick the first detected device (no user-configured preference)
        return devices[0]

    def _update_device_indicator(self):
        try:
            from rockbox_utils import list_rockbox_devices
        except Exception:
            # Could not import util; hide storage
            self.device_label.setText("No device detected")
            self.storage_bar.setValue(0)
            self.storage_bar.setToolTip("Storage: unknown")
            return
        try:
            devices = list_rockbox_devices() or []
        except Exception:
            devices = []
        d = self._choose_active_device(devices)
        if not d:
            self.device_label.setText("No device detected")
            self.storage_bar.setValue(0)
            self.storage_bar.setFormat("No storage")
            self.storage_bar.setToolTip("Connect a Rockbox device to see storage details.")
            return
        name = d.get('name') or d.get('label') or d.get('mountpoint') or 'Device'
        model = d.get('display_model') or d.get('model') or d.get('target') or ''
        mp = d.get('mountpoint') or ''
        total = int(d.get('total_bytes') or 0)
        free = int(d.get('free_bytes') or 0)
        used = max(0, total - free) if total > 0 else 0
        pct_used = int(round((used / total) * 100)) if total > 0 else 0
        self.device_label.setText(f"🔌 {name} — {model}")
        self.storage_bar.setMaximum(100)
        self.storage_bar.setValue(pct_used)
        self.storage_bar.setFormat(f"{pct_used}% used")
        tip = (
            f"Device: {name}\n"
            f"Model: {model}\n"
        )
        if total > 0:
            tip += (
                f"Capacity: {self._human_bytes(total)}\n"
                f"Used: {self._human_bytes(used)}\n"
                f"Free: {self._human_bytes(free)} ({100 - pct_used}% free)"
            )
        else:
            tip += "Capacity: unknown"
        self.storage_bar.setToolTip(tip)

    def _set_action_status(self, text: str, running: bool):
        self.action_label.setText(text)
        if running:
            self.action_label.setStyleSheet("font-weight: 700; color: #b50;")
        else:
            self.action_label.setStyleSheet("font-weight: 600; color: #0a7;")

    def _set_action_progress(self, percent: int | None, tooltip: str | None = None):
        try:
            # Hide when reset, show when active
            if percent is None or (int(percent) <= 0 and not tooltip):
                self.action_progress.setVisible(False)
                self.action_progress.setValue(0)
                self.action_progress.setToolTip("")
                return
            p = max(0, min(100, int(percent)))
            self.action_progress.setValue(p)
            self.action_progress.setVisible(True)
            self.action_progress.setToolTip(str(tooltip) if tooltip else "")
        except Exception:
            pass

    # Trigger a device DB scan by selecting the device in the Database pane
    def _scan_device_db(self, mount_path: str):
        try:
            # Ensure sources include current devices
            self.db._refresh_sources()
            # Find matching device entry
            combo = self.db.source_combo
            target_idx = -1
            for i in range(combo.count()):
                data = combo.itemData(i)
                if isinstance(data, dict) and data.get('type') == 'device':
                    mp = (data.get('mount') or '').rstrip('/\\')
                    if mp == mount_path.rstrip('/\\'):
                        target_idx = i
                        break
            if target_idx >= 0:
                combo.setCurrentIndex(target_idx)
                self.db.scan_library()
        except Exception:
            # Best-effort; ignore UI errors here
            pass

    # --------------- Settings tab ---------------
    def _build_settings_tab(self, parent: QWidget):
        v = QVBoxLayout(parent)
        form_group = QGroupBox("Preferences")
        v.addWidget(form_group)
        form = QFormLayout(form_group)

        # Music root row
        music_row = QWidget(); h = QHBoxLayout(music_row); h.setContentsMargins(0,0,0,0)
        self.set_music_root = QLineEdit(self.settings.get("music_root", str(ROOT)))
        h.addWidget(self.set_music_root, 1)
        b = QPushButton("Browse"); b.clicked.connect(lambda: self._browse_dir_into(self.set_music_root)); h.addWidget(b)
        form.addRow("Music root", music_row)

        # Device root setting removed to avoid confusion

        self.set_lyrics_subdir = QLineEdit(self.settings.get("lyrics_subdir", "Lyrics"))
        form.addRow("Lyrics subfolder", self.set_lyrics_subdir)

        self.set_lyrics_ext = QLineEdit(self.settings.get("lyrics_ext", ".lrc"))
        form.addRow("Lyrics extension", self.set_lyrics_ext)

        self.set_cover_size = QLineEdit(self.settings.get("cover_size", "100x100"))
        form.addRow("Cover size (WxH)", self.set_cover_size)

        self.set_cover_max = QSpinBox(); self.set_cover_max.setRange(50, 2000); self.set_cover_max.setValue(int(self.settings.get("cover_max", 100)))
        form.addRow("Cover max (px)", self.set_cover_max)

        self.set_jobs = QSpinBox(); self.set_jobs.setRange(1, 1024); self.set_jobs.setValue(int(self.settings.get("jobs", os.cpu_count() or 4)))
        form.addRow("Default jobs", self.set_jobs)

        self.set_genius = QLineEdit(self.settings.get("genius_token", "")); self.set_genius.setEchoMode(QLineEdit.Password)
        form.addRow("Genius token", self.set_genius)

        self.set_lastfm = QLineEdit(self.settings.get("lastfm_key", ""))
        form.addRow("Last.fm API key", self.set_lastfm)

        # Add-ons section
        addons_group = QGroupBox("Add-ons")
        addons_form = QFormLayout(addons_group)
        self.enable_youtube_cb = QCheckBox("Show YouTube tab")
        self.enable_youtube_cb.setChecked(bool(self.settings.get('enable_youtube', False)))
        addons_form.addRow("YouTube", self.enable_youtube_cb)
        self.enable_tidal_cb = QCheckBox("Show TIDAL tab")
        self.enable_tidal_cb.setChecked(bool(self.settings.get('enable_tidal', False)))
        addons_form.addRow("TIDAL", self.enable_tidal_cb)
        v.addWidget(addons_group)

        # Advanced block (hidden by default)
        # Toggleable advanced options block
        self.advanced_group = QGroupBox("Advanced Options")
        adv_form = QFormLayout(self.advanced_group)

        self.debug_cb = QCheckBox("Enable verbose debug logging (writes to logs/debug.log)")
        self.debug_cb.setChecked(bool(self.settings.get("debug", False)))
        adv_form.addRow("Debug", self.debug_cb)

        # Dummy Rockbox device (for testing)
        self.set_dummy_device = QLineEdit(self.settings.get("dummy_device_path", ""))
        adv_form.addRow("Dummy device path", self.set_dummy_device)
        self.dummy_enable_cb = QCheckBox("Enable dummy device in selectors")
        self.dummy_enable_cb.setChecked(bool(self.settings.get("dummy_device_enabled", False)))
        adv_form.addRow("Dummy device", self.dummy_enable_cb)

        # FFmpeg location (used by YouTube downloader and other tools)
        ffmpeg_row = QWidget(); ffh = QHBoxLayout(ffmpeg_row); ffh.setContentsMargins(0,0,0,0)
        self.set_ffmpeg_path = QLineEdit(self.settings.get("ffmpeg_path", ""))
        self.set_ffmpeg_path.setPlaceholderText("/path/to/ffmpeg OR folder containing ffmpeg/ffprobe")
        ffh.addWidget(self.set_ffmpeg_path, 1)
        b_ff = QPushButton("Browse")
        b_ff.setToolTip("Select a folder containing ffmpeg/ffprobe (or type a full ffmpeg path)")
        b_ff.clicked.connect(lambda: self._browse_dir_into(self.set_ffmpeg_path))
        ffh.addWidget(b_ff)
        adv_form.addRow("FFmpeg location", ffmpeg_row)

        scripts_row = QWidget(); sr = QHBoxLayout(scripts_row); sr.setContentsMargins(0,0,0,0)
        self.set_user_scripts_dir = QLineEdit(self.settings.get("user_scripts_dir", str(USER_SCRIPTS_DIR)))
        sr.addWidget(self.set_user_scripts_dir, 1)
        scripts_browse = QPushButton("Browse")
        scripts_browse.setToolTip("Select the folder containing RockSync user scripts")
        scripts_browse.clicked.connect(lambda: self._browse_dir_into(self.set_user_scripts_dir))
        sr.addWidget(scripts_browse)
        adv_form.addRow("User scripts folder", scripts_row)
        # Toggle button
        adv_toggle = QPushButton("Show Advanced Options")
        adv_toggle.setCheckable(True)
        adv_toggle.setChecked(False)
        def _toggle_adv():
            vis = adv_toggle.isChecked()
            self.advanced_group.setVisible(vis)
            adv_toggle.setText("Hide Advanced Options" if vis else "Show Advanced Options")
        adv_toggle.toggled.connect(_toggle_adv)
        v.addWidget(adv_toggle)
        self.advanced_group.setVisible(False)
        v.addWidget(self.advanced_group)

        # Theme selector (also mirrored in top bar)
        theme_options = ['system'] + list_theme_files()
        if 'theme_file' not in self.settings and 'theme' in self.settings:
            self.settings['theme_file'] = self.settings['theme']
        self.theme_box = QComboBox(); self.theme_box.addItems(theme_options); self.theme_box.setCurrentText(self.settings.get('theme_file', 'system'))
        form.addRow("Theme", self.theme_box)

        btn_row = QWidget(); hb = QHBoxLayout(btn_row); hb.setContentsMargins(0,0,0,0); hb.addStretch(1)
        sb = QPushButton("Save Settings"); sb.clicked.connect(self.on_save_settings); hb.addWidget(sb)
        rb = QPushButton("Reload"); rb.clicked.connect(self.on_reload_settings); hb.addWidget(rb)
        v.addWidget(btn_row)

    def on_save_settings(self):
        before_youtube = bool(self.settings.get('enable_youtube', False))
        before_tidal = bool(self.settings.get('enable_tidal', False))
        patch = {
            "music_root": self.set_music_root.text(),
            "lyrics_subdir": self.set_lyrics_subdir.text(),
            "lyrics_ext": self.set_lyrics_ext.text(),
            "cover_size": self.set_cover_size.text(),
            "cover_max": int(self.set_cover_max.value()),
            "jobs": int(self.set_jobs.value()),
            "genius_token": self.set_genius.text(),
            "lastfm_key": self.set_lastfm.text(),
            "debug": bool(self.debug_cb.isChecked()),
            "dummy_device_path": self.set_dummy_device.text(),
            "dummy_device_enabled": bool(self.dummy_enable_cb.isChecked()),
            "ffmpeg_path": self.set_ffmpeg_path.text(),
            "user_scripts_dir": self.set_user_scripts_dir.text(),
            "theme_file": self.theme_box.currentText(),
            "enable_youtube": bool(self.enable_youtube_cb.isChecked()),
            "enable_tidal": bool(self.enable_tidal_cb.isChecked()),
        }
        self.settings.update(patch)
        if save_settings(patch):
            self.statusBar().showMessage(f"Music root: {self.settings.get('music_root')}")
            QMessageBox.information(self, "Settings", "Settings saved.")
            self._reconfigure_logging()
            try:
                self.quick_theme_box.setCurrentText(self.settings.get('theme_file', 'system'))
            except Exception:
                pass
            apply_theme(QApplication.instance(), self.settings.get('theme_file', 'system'))
            self._reload_tasks()
            # Apply add-on visibility without restart
            if before_tidal != self.settings.get('enable_tidal', False) or before_youtube != self.settings.get('enable_youtube', False):
                self._ensure_tidal_tab()
                self._ensure_youtube_tab()
                self._rebuild_navigation()
        else:
            QMessageBox.critical(self, "Settings", "Could not save settings. See logs.")

    def on_reload_settings(self):
        self.settings = load_settings()
        self.set_music_root.setText(self.settings.get('music_root', ''))
        self.set_lyrics_subdir.setText(self.settings.get('lyrics_subdir', 'Lyrics'))
        self.set_lyrics_ext.setText(self.settings.get('lyrics_ext', '.lrc'))
        self.set_cover_size.setText(self.settings.get('cover_size', '100x100'))
        self.set_cover_max.setValue(int(self.settings.get('cover_max', 100)))
        self.set_jobs.setValue(int(self.settings.get('jobs', os.cpu_count() or 4)))
        self.set_genius.setText(self.settings.get('genius_token', ''))
        self.set_lastfm.setText(self.settings.get('lastfm_key', ''))
        self.debug_cb.setChecked(bool(self.settings.get('debug', False)))
        self.set_dummy_device.setText(self.settings.get('dummy_device_path', ''))
        self.dummy_enable_cb.setChecked(bool(self.settings.get('dummy_device_enabled', False)))
        try:
            self.set_ffmpeg_path.setText(self.settings.get('ffmpeg_path', ''))
        except Exception:
            pass
        try:
            self.set_user_scripts_dir.setText(self.settings.get('user_scripts_dir', str(USER_SCRIPTS_DIR)))
        except Exception:
            pass
        self.theme_box.setCurrentText(self.settings.get('theme_file', 'system'))
        self._reload_tasks()
        try:
            self.quick_theme_box.setCurrentText(self.settings.get('theme_file', 'system'))
        except Exception:
            pass
        # Reload add-on toggles
        try:
            self.enable_youtube_cb.setChecked(bool(self.settings.get('enable_youtube', False)))
            self.enable_tidal_cb.setChecked(bool(self.settings.get('enable_tidal', False)))
        except Exception:
            pass
        self.statusBar().showMessage(f"Music root: {self.settings.get('music_root')}")
        self._reconfigure_logging()
        apply_theme(QApplication.instance(), self.settings.get('theme_file', 'system'))

    def _reconfigure_logging(self):
        self.logger = setup_logging(self.settings, self.session_id)

    # --------------- Utility helpers ---------------
    def _browse_dir_into(self, line_edit: QLineEdit):
        path = QFileDialog.getExistingDirectory(self, "Select folder", line_edit.text() or str(ROOT))
        if path:
            line_edit.setText(path)

    def _browse_file_into(self, line_edit: QLineEdit):
        path, _ = QFileDialog.getOpenFileName(self, "Select file", str(ROOT), "All files (*.*)")
        if path:
            line_edit.setText(path)

    def _browse_save_into(self, line_edit: QLineEdit):
        path, _ = QFileDialog.getSaveFileName(self, "Select output file", str(ROOT), "All files (*.*)")
        if path:
            line_edit.setText(path)

    # --------------- Lifecycle ---------------
    def closeEvent(self, event):
        # Ensure embedded tidal-dl-ng cleans up background threads
        try:
            if hasattr(self, 'tidal') and hasattr(self.tidal, 'shutdown'):
                self.tidal.shutdown()
        except Exception:
            pass
        try:
            if hasattr(self, 'genre_tagger') and hasattr(self.genre_tagger, 'stop_all_playback'):
                self.genre_tagger.stop_all_playback()
        except Exception:
            pass
        super().closeEvent(event)

    # --------------- Tasks tab ---------------
    def _build_run_tab(self, parent: QWidget):
        layout = QHBoxLayout(parent)

        left = QVBoxLayout()
        layout.addLayout(left, 0)
        left.addWidget(QLabel("Tasks"))
        self.task_list = QListWidget(); left.addWidget(self.task_list, 1)
        self.task_list.currentRowChanged.connect(self.on_task_select)

        right = QVBoxLayout()
        layout.addLayout(right, 1)

        params_group = QGroupBox("Parameters")
        self.form = QFormLayout(params_group)
        right.addWidget(params_group)
        self.form_widgets = {}

        actions_row = QHBoxLayout()
        actions_row.addStretch(1)
        self.run_btn = QPushButton("Run"); self.run_btn.setProperty("accent", True); self.run_btn.clicked.connect(self.run_task); actions_row.addWidget(self.run_btn)
        self.stop_btn = QPushButton("Stop"); self.stop_btn.clicked.connect(self.stop_task); actions_row.addWidget(self.stop_btn)
        right.addLayout(actions_row)

        out_group = QGroupBox("Output")
        out_v = QVBoxLayout(out_group)
        self.output = QPlainTextEdit(); self.output.setReadOnly(True)
        out_v.addWidget(self.output, 1)
        right.addWidget(out_group, 1)

        self._reload_tasks(select_first=True)

    def on_task_select(self, idx: int):
        if idx < 0 or idx >= len(self.tasks):
            return
        task = self.tasks[idx]
        ui_log('on_task_select', idx=idx, label=task.get('label'))
        self.populate_form(task)

    def _task_tooltip(self, task: dict) -> str:
        parts = []
        desc = task.get('description')
        if desc:
            parts.append(str(desc))
        script = task.get('script')
        if script:
            parts.append(str(script))
        if task.get('is_user_script') and not parts:
            parts.append("User script")
        return "\n".join(parts)

    def _reload_tasks(self, select_first: bool = False):
        try:
            self.tasks = get_tasks(self.settings)
        except Exception:
            self.tasks = []
        if not hasattr(self, 'task_list'):
            return
        current_row = self.task_list.currentRow()
        self.task_list.blockSignals(True)
        self.task_list.clear()
        for task in self.tasks:
            text = task.get('display_label') or task.get('label') or 'Task'
            item = QListWidgetItem(text)
            if task.get('is_user_script'):
                item.setForeground(QColor('#0b6ee0'))
                item.setToolTip(self._task_tooltip(task))
            else:
                tooltip = self._task_tooltip(task)
                if tooltip:
                    item.setToolTip(tooltip)
            self.task_list.addItem(item)
        self.task_list.blockSignals(False)

        if not self.tasks:
            while self.form.rowCount():
                self.form.removeRow(0)
            self.form_widgets.clear()
            self._active_task = {}
            return

        if select_first or current_row < 0:
            target = 0
        else:
            target = min(current_row, len(self.tasks) - 1)
        self.task_list.setCurrentRow(target)

    def default_value_for_spec(self, spec):
        task = getattr(self, '_active_task', {}) or {}
        default = spec.get("default", "")
        if task.get('is_user_script'):
            return default

        key = spec.get("key", "")
        s = self.settings
        if key in ("--root", "--folder", "--music-dir", "base", "source"):
            return s.get("music_root", default)
        if key == "--library":
            return s.get("music_root", default)
        if key == "--size":
            return s.get("cover_size", default)
        if key == "--max-size":
            try:
                return int(s.get("cover_max", default if default != "" else 100))
            except Exception:
                return 100
        if key == "--genius-token":
            return s.get("genius_token", default)
        if key == "--lastfm-key":
            return s.get("lastfm_key", default)
        if key == "--jobs":
            try:
                return int(s.get("jobs", default if default != "" else 4))
            except Exception:
                return 4
        if key == "--lyrics-subdir":
            return s.get("lyrics_subdir", default if default != "" else "Lyrics")
        if key == "--ext":
            default_value = default
            if str(default_value).strip().lower() == ".lrc":
                return s.get("lyrics_ext", default_value)
            return default_value
        return default

    def populate_form(self, task):
        self._active_task = task or {}
        while self.form.rowCount():
            self.form.removeRow(0)
        self.form_widgets.clear()

        missing = []
        for mod in task.get("py_deps", []):
            try:
                __import__(mod)
            except Exception:
                missing.append(f"python:{mod}")
        for bin_name in task.get("bin_deps", []):
            if not cmd_exists(bin_name):
                missing.append(f"bin:{bin_name}")
        if missing:
            lab = QLabel(f"Missing deps: {', '.join(missing)}")
            lab.setStyleSheet("color:#b00;")
            self.form.addRow(lab)

        description = task.get('description')
        if description:
            desc_label = QLabel(str(description))
            desc_label.setWordWrap(True)
            desc_label.setStyleSheet("color:#555;")
            self.form.addRow('', desc_label)

        for spec in task.get("args", []):
            label = spec.get("label") or spec.get("key") or "Value"
            spec_type = str(spec.get("type", "text")).lower()
            default = self.default_value_for_spec(spec)
            placeholder = spec.get("placeholder")
            widget = None

            if spec_type in ("text", "password"):
                widget = QLineEdit()
                if spec_type == "password":
                    widget.setEchoMode(QLineEdit.Password)
                if default not in (None, ""):
                    widget.setText(str(default))
                if placeholder:
                    widget.setPlaceholderText(str(placeholder))
            elif spec_type in ("textarea", "multiline"):
                widget = QPlainTextEdit()
                if default not in (None, ""):
                    widget.setPlainText(str(default))
                if placeholder:
                    try:
                        widget.setPlaceholderText(str(placeholder))
                    except Exception:
                        pass
            elif spec_type == "int":
                widget = QSpinBox()
                try:
                    min_val = int(spec.get("min", 0))
                except Exception:
                    min_val = 0
                try:
                    max_val = int(spec.get("max", 4096))
                except Exception:
                    max_val = 4096
                if min_val > max_val:
                    min_val, max_val = 0, 4096
                widget.setRange(min_val, max_val)
                try:
                    widget.setValue(int(default))
                except Exception:
                    widget.setValue(min_val)
            elif spec_type == "bool":
                widget = QCheckBox()
                if isinstance(default, bool):
                    widget.setChecked(default)
                else:
                    widget.setChecked(str(default).strip().lower() in {"1", "true", "yes", "on"})
            elif spec_type == "path":
                roww = QWidget()
                h = QHBoxLayout(roww); h.setContentsMargins(0,0,0,0)
                entry = QLineEdit()
                if default not in (None, ""):
                    entry.setText(str(default))
                if placeholder:
                    entry.setPlaceholderText(str(placeholder))
                h.addWidget(entry, 1)
                b = QPushButton("Browse")
                b.clicked.connect(lambda _, e=entry: self._browse_dir_into(e))
                h.addWidget(b)
                widget = roww
                widget.entry = entry
            elif spec_type == "file":
                roww = QWidget()
                h = QHBoxLayout(roww); h.setContentsMargins(0,0,0,0)
                entry = QLineEdit()
                if default not in (None, ""):
                    entry.setText(str(default))
                if placeholder:
                    entry.setPlaceholderText(str(placeholder))
                h.addWidget(entry, 1)
                b = QPushButton("Browse")
                b.clicked.connect(lambda _, e=entry: self._browse_file_into(e))
                h.addWidget(b)
                widget = roww
                widget.entry = entry
            elif spec_type in ("savefile", "save_file"):
                roww = QWidget()
                h = QHBoxLayout(roww); h.setContentsMargins(0,0,0,0)
                entry = QLineEdit()
                if default not in (None, ""):
                    entry.setText(str(default))
                if placeholder:
                    entry.setPlaceholderText(str(placeholder))
                h.addWidget(entry, 1)
                b = QPushButton("Browse")
                b.clicked.connect(lambda _, e=entry: self._browse_save_into(e))
                h.addWidget(b)
                widget = roww
                widget.entry = entry
            elif spec_type == "choice":
                widget = QComboBox()
                for choice in spec.get('choices', []):
                    widget.addItem(str(choice))
                if default not in (None, ""):
                    widget.setCurrentText(str(default))
            elif spec_type == "device":
                widget = QComboBox()
                widget.addItem("Auto-detect (single device)", "")
                try:
                    from rockbox_utils import list_rockbox_devices
                    devices = list_rockbox_devices() or []
                except Exception:
                    devices = []
                added_any = False
                for dev in devices:
                    try:
                        mount = str(dev.get("mountpoint") or "").strip()
                        if not mount:
                            continue
                        name = str(dev.get("name") or "").strip()
                        display = str(dev.get("display_model") or dev.get("model") or "").strip()
                        label = name or display or mount
                        if display and display.lower() != label.lower():
                            label = f"{label} ({display})"
                        widget.addItem(f"{label} — {mount}", mount)
                        added_any = True
                    except Exception:
                        continue
                if not added_any:
                    widget.addItem("No devices detected", "")
                if default not in (None, ""):
                    idx = widget.findData(str(default))
                    if idx >= 0:
                        widget.setCurrentIndex(idx)
            else:
                widget = QLineEdit()
                if default not in (None, ""):
                    widget.setText(str(default))
                if placeholder:
                    widget.setPlaceholderText(str(placeholder))

            if widget is None:
                continue

            help_text = spec.get('help')
            if help_text:
                widget.setToolTip(str(help_text))

            self.form.addRow(label, widget)
            key = spec.get("key")
            if key is not None:
                self.form_widgets[key] = widget

    def _collect_current_values(self, task):
        values = {}
        for spec in task.get('args', []):
            key = spec.get('key')
            if key is None:
                continue
            widget = self.form_widgets.get(key)
            if widget is None:
                continue
            spec_type = str(spec.get('type', 'text')).lower()
            if spec_type == 'bool':
                values[key] = bool(widget.isChecked())
            elif spec_type in ('path', 'file', 'savefile', 'save_file'):
                values[key] = widget.entry.text()
            elif spec_type == 'int':
                values[key] = widget.value()
            elif spec_type == 'choice':
                values[key] = widget.currentText()
            elif spec_type == 'device':
                data = widget.currentData()
                values[key] = data if data is not None else widget.currentText()
            elif spec_type in ('textarea', 'multiline'):
                values[key] = widget.toPlainText()
            else:
                values[key] = widget.text()
        return values

    def _normalise_command_sequence(self, seq):
        if not seq:
            return []
        if isinstance(seq, str):
            try:
                return shlex.split(seq)
            except ValueError:
                return [seq]
        try:
            return [str(part) for part in seq]
        except TypeError:
            return [str(seq)]

    def _command_base(self, task):
        script = task.get('script')
        command = task.get('command')
        if command:
            parts = self._normalise_command_sequence(command)
            return [shlex.quote(part) for part in parts if str(part).strip()]

        interpreter = task.get('interpreter')
        if interpreter:
            base = self._normalise_command_sequence(interpreter)
        else:
            runner = task.get('runner') or 'python'
            if runner == 'python':
                base = [sys.executable, '-u']
            elif runner == 'python-no-u':
                base = [sys.executable]
            else:
                base = []
        if script and (not command):
            base.append(str(script))
        return [shlex.quote(part) for part in base if str(part).strip()]

    def _compose_command(self, task, values):
        parts = self._command_base(task)
        overwrite_checked = bool(values.get('--overwrite', False))

        for spec in task.get('args', []):
            key = spec.get('key')
            spec_type = str(spec.get('type', 'text')).lower()
            value = values.get(key)

            if spec_type == 'bool':
                if key == '--only-missing' and overwrite_checked:
                    continue
                if value:
                    parts.append(key)
                continue

            if key == '__argline__':
                argline = str(value or '').strip()
                if argline:
                    try:
                        tokens = shlex.split(argline)
                    except ValueError:
                        tokens = [argline]
                    parts.extend(shlex.quote(tok) for tok in tokens if tok)
                continue

            if value is None or value == "":
                continue

            if isinstance(value, (list, tuple)):
                sequence = [str(v) for v in value if str(v).strip()]
                if not sequence:
                    continue
                if not key or not str(key).startswith('-'):
                    parts.extend(shlex.quote(item) for item in sequence)
                else:
                    for item in sequence:
                        parts.extend([key, shlex.quote(item)])
                continue

            text_value = str(value)
            if not key or not str(key).startswith('-'):
                parts.append(shlex.quote(text_value))
            else:
                parts.extend([key, shlex.quote(text_value)])
        return " ".join(parts)

    def build_cmd(self, task):
        values = self._collect_current_values(task)
        return self._compose_command(task, values)

    def append_output(self, text):
        # Append to UI
        self.output.moveCursor(QTextCursor.End)
        self.output.insertPlainText(text)
        self.output.moveCursor(QTextCursor.End)
        # Also log captured process output
        try:
            logger = logging.getLogger("RockSyncGUI.TaskOutput")
            for line in str(text).splitlines():
                line = line.rstrip()
                if line:
                    logger.info(line)
        except Exception:
            pass

    def run_task(self):
        idx = self.task_list.currentRow()
        if idx < 0:
            QMessageBox.warning(self, "No task", "Please select a task")
            return
        task = self.tasks[idx]
        ui_log('run_task_start', task=task.get('label'))

        # Deps check
        missing = []
        for mod in task.get("py_deps", []):
            try:
                __import__(mod)
            except Exception:
                missing.append(f"python:{mod}")
        for bin_name in task.get("bin_deps", []):
            if not cmd_exists(bin_name):
                missing.append(f"bin:{bin_name}")
        if missing:
            ret = QMessageBox.question(self, "Missing dependencies", f"Missing: {', '.join(missing)}\nRun anyway?")
            if ret != QMessageBox.Yes:
                return

        cmd = self.build_cmd(task)
        self.append_output(f"\n$ {cmd}\n")
        self.run_btn.setEnabled(False)
        # Update action indicator (script from registry)
        lbl = task.get('label') or 'Task'
        self._set_action_status(f"Script: {lbl}", True)

        # Use QProcess for async IO
        if self.proc is not None:
            try:
                self.proc.kill()
            except Exception:
                pass
        self.proc = QProcess(self)
        self.proc.setWorkingDirectory(str(ROOT))
        self.proc.setProcessChannelMode(QProcess.MergedChannels)
        self.proc.readyReadStandardOutput.connect(lambda: self.append_output(bytes(self.proc.readAllStandardOutput()).decode('utf-8', errors='ignore')))
        def on_finished(rc, _status):
            self.append_output(f"\n[Exit {rc}]\n")
            self.logger.info("Process exited | rc=%s", rc)
            ui_log('run_task_end', rc=rc)
            self.run_btn.setEnabled(True)
            self._set_action_status("Idle", False)
        self.proc.finished.connect(on_finished)

        # Start process
        self.proc.start("/bin/sh", ["-c", cmd])

    def stop_task(self):
        if self.proc is not None and self.proc.state() != QProcess.NotRunning:
            try:
                self.proc.terminate()
                self.append_output("\n[Terminated]\n")
                ui_log('stop_task')
                self._set_action_status("Idle", False)
            except Exception as e:
                self.append_output(f"\n[Error stopping] {e}\n")

    # Explorer helpers for context menu
    def task_accepts_folder(self, task):
        folder_keys = {"--folder", "--root", "--source", "--base-dir", "base", "source", "--music-dir"}
        for spec in task.get('args', []):
            if spec.get('type') == 'path' and spec.get('key') in folder_keys:
                return True
        return False

    def open_quick_task(self, task, folder_path):
        dlg = QDialog(self)
        dlg.setWindowTitle(f"Quick Task: {task.get('label')}")
        v = QVBoxLayout(dlg)
        form = QFormLayout(); v.addLayout(form)

        info = QLabel(f"Folder: {folder_path}")
        form.addRow(info)

        quick_widgets = {}
        folder_keys = {"--folder", "--root", "--source", "--base-dir", "base", "source", "--music-dir"}
        for spec in task.get('args', []):
            label = spec.get('label')
            key = spec.get('key')
            typ = spec.get('type')
            default_val = self.default_value_for_spec(spec)
            if key in folder_keys:
                default_val = folder_path
            w = None
            if typ in ('text', 'password'):
                w = QLineEdit();
                if typ == 'password':
                    w.setEchoMode(QLineEdit.Password)
                w.setText(str(default_val))
            elif typ == 'int':
                w = QSpinBox(); w.setRange(1, 4096)
                try:
                    w.setValue(int(default_val))
                except Exception:
                    w.setValue(1)
            elif typ == 'bool':
                w = QCheckBox(); w.setChecked(bool(default_val))
            elif typ == 'path':
                roww = QWidget(); h = QHBoxLayout(roww); h.setContentsMargins(0,0,0,0)
                entry = QLineEdit(str(default_val)); h.addWidget(entry, 1)
                b = QPushButton('Browse'); b.clicked.connect(lambda _, e=entry: self._browse_dir_into(e)); h.addWidget(b)
                w = roww; w.entry = entry
            elif typ == 'file':
                roww = QWidget(); h = QHBoxLayout(roww); h.setContentsMargins(0,0,0,0)
                entry = QLineEdit(str(default_val)); h.addWidget(entry, 1)
                b = QPushButton('Browse'); b.clicked.connect(lambda _, e=entry: self._browse_file_into(e)); h.addWidget(b)
                w = roww; w.entry = entry
            elif typ == 'choice':
                w = QComboBox();
                for c in spec.get('choices', []):
                    w.addItem(str(c))
                w.setCurrentText(str(default_val))
            else:
                w = QLineEdit(str(default_val))
            form.addRow(label, w)
            quick_widgets[key] = w

        close_cb = QCheckBox(); close_cb.setChecked(True)
        form.addRow('Close this window on Run', close_cb)

        btns = QHBoxLayout(); btns.addStretch(1)
        runb = QPushButton('Run'); cancelb = QPushButton('Cancel')
        btns.addWidget(cancelb); btns.addWidget(runb)
        v.addLayout(btns)

        def do_run():
            values = {}
            for spec in task.get('args', []):
                key = spec.get('key')
                w = quick_widgets.get(key)
                if w is None:
                    continue
                typ = str(spec.get('type', 'text')).lower()
                if typ == 'bool':
                    values[key] = bool(w.isChecked())
                elif typ in ('path','file'):
                    values[key] = w.entry.text()
                elif typ == 'int':
                    values[key] = w.value()
                elif typ == 'choice':
                    values[key] = w.currentText()
                elif typ in ('textarea', 'multiline'):
                    values[key] = w.toPlainText()
                else:
                    values[key] = w.text()
            cmd = self._compose_command(task, values)
            self.append_output(f"\n$ {cmd}\n")
            ui_log('quick_task_run', task=task.get('label'), folder_path=folder_path, cmd=cmd)
            try:
                self._set_action_status(f"Script: {task.get('label')}", True)
            except Exception:
                pass
            self._start_process(cmd, label=task.get('label'))
            if close_cb.isChecked():
                dlg.accept()

        runb.clicked.connect(do_run)
        cancelb.clicked.connect(dlg.reject)
        dlg.exec()

    def _start_process(self, cmd, label: str | None = None):
        self.run_btn.setEnabled(False)
        if self.proc is not None:
            try:
                self.proc.kill()
            except Exception:
                pass
        self.proc = QProcess(self)
        self.proc.setWorkingDirectory(str(ROOT))
        self.proc.setProcessChannelMode(QProcess.MergedChannels)
        self.proc.readyReadStandardOutput.connect(lambda: self.append_output(bytes(self.proc.readAllStandardOutput()).decode('utf-8', errors='ignore')))
        def on_finished(rc, _status):
            self.append_output(f"\n[Exit {rc}]\n")
            self.logger.info("Process exited | rc=%s", rc)
            self.run_btn.setEnabled(True)
            self._set_action_status("Idle", False)
        self.proc.finished.connect(on_finished)
        self.proc.start("/bin/sh", ["-c", cmd])
        # Update action indicator with a short command preview
        if label and str(label).strip():
            self._set_action_status(f"Script: {label}", True)
        else:
            preview = cmd.strip().split("\n", 1)[0]
            if len(preview) > 120:
                preview = preview[:117] + '...'
            self._set_action_status(f"Script: {preview}", True)


def run():
    app = QApplication.instance() or QApplication(sys.argv)
    win = AppWindow()
    win.show()
    app.exec()
