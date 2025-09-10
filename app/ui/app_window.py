import os
import sys
import shlex
import uuid
from PySide6.QtCore import Qt, QProcess, QTimer
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QListWidget, QListWidgetItem, QStackedWidget,
    QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QGroupBox, QFormLayout, QLineEdit,
    QSpinBox, QCheckBox, QComboBox, QPlainTextEdit, QFileDialog, QMessageBox, QDialog,
    QProgressBar
)

from core import ROOT, cmd_exists
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

        self._init_ui()

    # --------------- UI skeleton ---------------
    def _init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root_v = QVBoxLayout(central)

        # Preload tasks for quick actions and consistency
        try:
            self.tasks = get_tasks()
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
        dg.addWidget(self.action_label)
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

        # TIDAL Playlists (embed tidal-dl-ng GUI)
        self.tidal_tab = QWidget(); td_layout = QVBoxLayout(self.tidal_tab)
        self.tidal = TidalPane(self, self.tidal_tab)
        td_layout.addWidget(self.tidal)
        self.stack.addWidget(self.tidal_tab)

        # YouTube (browse + download)
        self.youtube_tab = QWidget(); yt_layout = QVBoxLayout(self.youtube_tab)
        self.youtube = YouTubePane(self, self.youtube_tab)
        yt_layout.addWidget(self.youtube)
        self.stack.addWidget(self.youtube_tab)

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
        add_page("Settings", self.stack.indexOf(self.settings_tab))
        add_page("Rockbox", self.stack.indexOf(self.rockbox_tab))
        add_page("Advanced", self.stack.indexOf(self.run_tab))
        add_page("Tidal-dl-ng", self.stack.indexOf(self.tidal_tab))
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

        self.nav.currentItemChanged.connect(lambda _c, _p: on_nav_changed())
        # Select first real page
        for i in range(self.nav.count()):
            if self.nav.item(i).data(Qt.UserRole) is not None:
                self.nav.setCurrentRow(i)
                break

        # Lazy-initialize heavy/online pages when shown
        def _on_page_changed(idx: int):
            try:
                if idx == self.stack.indexOf(self.tidal_tab):
                    # Initialize Tidal pane on demand to avoid startup failures
                    if hasattr(self, 'tidal'):
                        self.tidal.activate()
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

        # Advanced block (hidden by default)
        # Toggleable advanced options block
        self.advanced_group = QGroupBox("Advanced Options")
        adv_form = QFormLayout(self.advanced_group)

        self.debug_cb = QCheckBox("Enable verbose debug logging (writes to app/debug.log)")
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
            "theme_file": self.theme_box.currentText(),
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
        self.theme_box.setCurrentText(self.settings.get('theme_file', 'system'))
        try:
            self.quick_theme_box.setCurrentText(self.settings.get('theme_file', 'system'))
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
        path, _ = QFileDialog.getOpenFileName(self, "Select file", str(ROOT), "FLAC (*.flac);;All (*.*)")
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
        super().closeEvent(event)

    # --------------- Tasks tab ---------------
    def _build_run_tab(self, parent: QWidget):
        layout = QHBoxLayout(parent)

        left = QVBoxLayout()
        layout.addLayout(left, 0)
        left.addWidget(QLabel("Tasks"))
        self.task_list = QListWidget(); left.addWidget(self.task_list, 1)
        # Ensure tasks list exists
        try:
            self.tasks = self.tasks if hasattr(self, 'tasks') else get_tasks()
        except Exception:
            self.tasks = []
        for t in self.tasks:
            QListWidgetItem(t["label"], self.task_list)
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

        if self.tasks:
            self.task_list.setCurrentRow(0)
            self.on_task_select(0)

    def on_task_select(self, idx: int):
        if idx < 0 or idx >= len(self.tasks):
            return
        task = self.tasks[idx]
        ui_log('on_task_select', idx=idx, label=task.get('label'))
        self.populate_form(task)

    def default_value_for_spec(self, spec):
        key = spec.get("key", "")
        s = self.settings
        if key in ("--root", "--folder", "--music-dir", "base", "source"):
            return s.get("music_root", spec.get("default"))
        if key == "--library":
            return s.get("music_root", spec.get("default"))
        if key == "--size":
            return s.get("cover_size", spec.get("default"))
        if key == "--max-size":
            return int(s.get("cover_max", spec.get("default", 100)))
        if key == "--genius-token":
            return s.get("genius_token", spec.get("default", ""))
        if key == "--lastfm-key":
            return s.get("lastfm_key", spec.get("default", ""))
        if key == "--jobs":
            return int(s.get("jobs", spec.get("default", 4)))
        if key == "--lyrics-subdir":
            return s.get("lyrics_subdir", spec.get("default", "Lyrics"))
        if key == "--ext":
            return s.get("lyrics_ext", spec.get("default", ".lrc"))
        return spec.get("default", "")

    def populate_form(self, task):
        # clear
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
            lab = QLabel(f"Missing deps: {', '.join(missing)}"); lab.setStyleSheet("color:#b00;")
            self.form.addRow(lab)

        for spec in task["args"]:
            label = spec["label"]
            w = None
            if spec["type"] in ("text", "password"):
                w = QLineEdit()
                if spec["type"] == "password":
                    w.setEchoMode(QLineEdit.Password)
                w.setText(str(self.default_value_for_spec(spec)))
            elif spec["type"] == "int":
                w = QSpinBox(); w.setRange(1, 4096)
                w.setValue(int(self.default_value_for_spec(spec)))
            elif spec["type"] == "bool":
                w = QCheckBox()
                w.setChecked(bool(self.default_value_for_spec(spec)))
            elif spec["type"] == "path":
                roww = QWidget(); h = QHBoxLayout(roww); h.setContentsMargins(0,0,0,0)
                entry = QLineEdit(str(self.default_value_for_spec(spec))); h.addWidget(entry, 1)
                b = QPushButton("Browse"); b.clicked.connect(lambda _, e=entry: self._browse_dir_into(e)); h.addWidget(b)
                w = roww; w.entry = entry
            elif spec["type"] == "file":
                roww = QWidget(); h = QHBoxLayout(roww); h.setContentsMargins(0,0,0,0)
                entry = QLineEdit(str(self.default_value_for_spec(spec))); h.addWidget(entry, 1)
                b = QPushButton("Browse"); b.clicked.connect(lambda _, e=entry: self._browse_file_into(e)); h.addWidget(b)
                w = roww; w.entry = entry
            elif spec["type"] == "choice":
                w = QComboBox();
                for c in spec.get('choices', []):
                    w.addItem(str(c))
                w.setCurrentText(str(self.default_value_for_spec(spec)))
            else:
                w = QLineEdit(str(self.default_value_for_spec(spec)))
            self.form.addRow(label, w)
            self.form_widgets[spec["key"]] = w

    def build_cmd(self, task):
        py = shlex.quote(sys.executable)
        script = shlex.quote(str(task["script"]))
        # Use unbuffered Python so progress prints stream into the UI
        parts = [py, '-u', script]
        # Handle mutually exclusive flags for tag_genres
        flags = {s.get('key'): s for s in task.get('args', [])}
        overwrite_checked = False
        if '--overwrite' in flags and isinstance(self.form_widgets.get('--overwrite'), QCheckBox):
            overwrite_checked = bool(self.form_widgets['--overwrite'].isChecked())

        for spec in task.get('args', []):
            key = spec.get('key')
            typ = spec.get('type')
            w = self.form_widgets.get(key)
            val = ''
            if typ == 'bool':
                val = w.isChecked()
                # Avoid passing both --only-missing and --overwrite together
                if key == '--only-missing' and overwrite_checked:
                    continue
                if val:
                    parts.append(key)
                continue
            if typ in ('path','file'):
                val = w.entry.text()
            elif typ == 'int':
                val = str(w.value())
            elif typ == 'choice':
                val = w.currentText()
            else:
                val = w.text()
            if not str(key).startswith('-'):
                parts.append(shlex.quote(str(val)))
            else:
                parts.extend([key, shlex.quote(str(val))])
        return " ".join(parts)

    def append_output(self, text):
        self.output.moveCursor(QTextCursor.End)
        self.output.insertPlainText(text)
        self.output.moveCursor(QTextCursor.End)

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
                typ = spec.get('type')
                if typ == 'bool':
                    values[key] = bool(w.isChecked())
                elif typ in ('path','file'):
                    values[key] = w.entry.text()
                elif typ == 'int':
                    values[key] = w.value()
                elif typ == 'choice':
                    values[key] = w.currentText()
                else:
                    values[key] = w.text()
            cmd = self._build_cmd_with_values(task, values)
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

    def _build_cmd_with_values(self, task, values):
        py = shlex.quote(sys.executable)
        script = shlex.quote(str(task["script"]))
        # Use unbuffered Python so progress prints stream into the UI
        parts = [py, '-u', script]
        # Handle mutually exclusive flags for tag_genres
        overwrite_checked = bool(values.get('--overwrite', False))

        for spec in task.get('args', []):
            key = spec.get('key')
            typ = spec.get('type')
            val = values.get(key, '')
            if typ == 'bool':
                # Avoid passing both --only-missing and --overwrite together
                if key == '--only-missing' and overwrite_checked:
                    continue
                if val:
                    parts.append(key)
                continue
            if not str(key).startswith('-'):
                parts.append(shlex.quote(str(val)))
            else:
                parts.extend([key, shlex.quote(str(val))])
        return " ".join(parts)

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
