import os
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QLineEdit, QPushButton,
    QSplitter, QTreeWidget, QTreeWidgetItem, QTextEdit, QFileDialog, QComboBox
)
from rockbox_utils import list_rockbox_devices
from logging_utils import ui_log
from ui.explorer_pane import ExplorerPane


class DeviceExplorerPane(ExplorerPane):
    """Explorer pane dedicated to a connected Rockbox device.
    When no device is connected, the explorer remains empty.
    """
    def _build_ui(self):
        root = QVBoxLayout(self)

        top = QHBoxLayout()
        top.addWidget(QLabel("Device:"))
        self.device_combo = QComboBox()
        top.addWidget(self.device_combo)
        dev_refresh = QPushButton("Refresh")
        dev_refresh.clicked.connect(self._refresh_devices)
        top.addWidget(dev_refresh)
        up_btn = QPushButton("Up")
        up_btn.clicked.connect(self.go_up)
        top.addWidget(up_btn)
        dir_refresh = QPushButton("Refresh Folder")
        # Hidden path field retained to integrate with base ExplorerPane helpers
        self.explorer_path = QLineEdit("")
        self.explorer_path.setVisible(False)
        dir_refresh.clicked.connect(self._refresh_folder)
        top.addWidget(dir_refresh)
        root.addLayout(top)

        splitter = QSplitter(Qt.Horizontal)
        root.addWidget(splitter, 1)

        self.tree = QTreeWidget()
        self.tree.setColumnCount(5)
        self.tree.setHeaderLabels(["Name", "Type", "Size", "Modified", "Actions"])
        self.tree.setAlternatingRowColors(True)
        self.tree.itemDoubleClicked.connect(self._on_item_open)
        self.tree.itemSelectionChanged.connect(self._on_item_select)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._on_context_menu)
        splitter.addWidget(self.tree)

        right = QWidget()
        rlayout = QVBoxLayout(right)
        # Info panel (cover + metadata + lyrics)
        self.info_panel = QWidget(); info_v = QVBoxLayout(self.info_panel)
        self.cover_label = QLabel("No cover")
        self.cover_label.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
        info_v.addWidget(self.cover_label)
        info_v.addWidget(QLabel("Metadata"))
        self.meta_text = QTextEdit(); self.meta_text.setReadOnly(True); self.meta_text.setAcceptRichText(True)
        info_v.addWidget(self.meta_text, 1)
        info_v.addWidget(QLabel("Lyrics (preview)"))
        self.lyrics_text = QTextEdit(); self.lyrics_text.setReadOnly(True)
        info_v.addWidget(self.lyrics_text, 1)
        rlayout.addWidget(self.info_panel, 1)
        # Playlist panel
        self.playlist_panel = QWidget(); self.playlist_panel.setVisible(False)
        pl_v = QVBoxLayout(self.playlist_panel)
        pl_v.addWidget(QLabel("Playlist Tracks"))
        self.playlist_list = QTreeWidget(); self.playlist_list.setColumnCount(2)
        self.playlist_list.setHeaderLabels(["#", "Track"])
        self.playlist_list.setAlternatingRowColors(True)
        self.playlist_list.itemDoubleClicked.connect(self._on_playlist_open)
        pl_v.addWidget(self.playlist_list, 1)
        rlayout.addWidget(self.playlist_panel, 1)
        splitter.addWidget(right)

        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)

        self._refresh_devices()

    def _refresh_devices(self):
        ui_log('device_refresh_click')
        self.device_combo.blockSignals(True)
        self.device_combo.clear()
        devices = list_rockbox_devices()
        for d in devices:
            label = d.get('label') or d.get('mountpoint')
            mp = d.get('mountpoint')
            self.device_combo.addItem(f"{label} ({mp})", mp)
        self.device_combo.blockSignals(False)
        self.device_combo.currentIndexChanged.connect(self._on_device_changed)
        if self.device_combo.count() > 0:
            self._use_selected_music()
        else:
            # No device connected: clear view and path
            try:
                self.tree.clear()
            except Exception:
                pass
            self.explorer_path.setText("")

    def _refresh_folder(self):
        path = (self.explorer_path.text() or '').strip()
        if path and os.path.isdir(path):
            ui_log('device_refresh_folder', path=path)
            self.navigate(path)

    def _on_device_changed(self, idx):
        # Auto-open Music on selection
        try:
            data = self.device_combo.itemData(idx)
            ui_log('device_select', index=int(idx), mount=data)
        except Exception:
            pass
        self._use_selected_music()

    def _use_selected_music(self):
        mp = self.device_combo.currentData()
        if not mp:
            # No device selected/available: keep view empty
            return
        path = mp.rstrip('/\\') + '/Music'
        ui_log('device_use_music', mount=mp, path=path)
        self._set_path(path)
