import os
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QLineEdit, QPushButton,
    QSplitter, QTreeWidget, QTreeWidgetItem, QTextEdit, QFileDialog, QComboBox
)
from rockbox_utils import list_rockbox_devices
from ui.explorer_pane import ExplorerPane


class DeviceExplorerPane(ExplorerPane):
    """Explorer pane dedicated to the device root.
    Inherits ExplorerPane behavior but defaults to settings['device_root']
    and adds a convenient button to jump there.
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
        self.explorer_path = QLineEdit(self.controller.settings.get("device_root", ""))
        self.explorer_path.setVisible(False)
        dir_refresh.clicked.connect(lambda: self.navigate(self.explorer_path.text()))
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
        self.cover_label = QLabel("No cover")
        self.cover_label.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
        rlayout.addWidget(self.cover_label)
        rlayout.addWidget(QLabel("Metadata"))
        self.meta_text = QTextEdit(); self.meta_text.setReadOnly(True)
        rlayout.addWidget(self.meta_text, 1)
        rlayout.addWidget(QLabel("Lyrics (preview)"))
        self.lyrics_text = QTextEdit(); self.lyrics_text.setReadOnly(True)
        rlayout.addWidget(self.lyrics_text, 1)
        splitter.addWidget(right)

        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)

        self._refresh_devices()
        self.navigate(self.explorer_path.text())

    def _refresh_devices(self):
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

    def _on_device_changed(self, idx):
        # Auto-open Music on selection
        self._use_selected_music()

    def _use_selected_music(self):
        mp = self.device_combo.currentData()
        if not mp:
            mp = self.controller.settings.get('device_root', '')
        if mp:
            path = mp.rstrip('/\\') + '/Music'
            self._set_path(path)
