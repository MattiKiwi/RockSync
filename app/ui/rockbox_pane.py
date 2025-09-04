import os
import sys
from typing import Dict
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTreeWidget, QTreeWidgetItem,
    QGroupBox, QFormLayout, QLineEdit, QCheckBox
)
from rockbox_utils import list_rockbox_devices


def _fmt_size(n: int) -> str:
    try:
        f = float(n)
    except Exception:
        return str(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if f < 1024.0:
            return f"{f:.1f} {unit}"
        f /= 1024.0
    return f"{f:.1f} PB"


class RockboxPane(QWidget):
    """Rockbox device detection UI with future settings placeholder."""
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self._timer = QTimer(self)
        self._timer.setInterval(2000)
        self._timer.timeout.connect(self.scan_now)
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)

        # Header + controls
        hdr = QHBoxLayout()
        self.status = QLabel("Idle")
        hdr.addWidget(self.status)
        hdr.addStretch(1)
        self.scan_btn = QPushButton("Scan Now"); self.scan_btn.clicked.connect(self.scan_now); hdr.addWidget(self.scan_btn)
        self.auto_cb = QCheckBox("Auto refresh"); self.auto_cb.stateChanged.connect(self._toggle_auto); hdr.addWidget(self.auto_cb)
        root.addLayout(hdr)

        # Devices list
        self.tree = QTreeWidget()
        self.tree.setColumnCount(8)
        self.tree.setHeaderLabels(["Mountpoint", "Name", "Label", "Model", "FS", "Device", "Capacity", "Free"])
        self.tree.setAlternatingRowColors(True)
        root.addWidget(self.tree, 1)

        # Future settings placeholder
        grp = QGroupBox("Rockbox Settings (coming soon)")
        form = QFormLayout(grp)
        self.db_path = QLineEdit("/.rockbox")
        self.db_path.setEnabled(False)
        form.addRow("Config root on device", self.db_path)
        self.transcode_preset = QLineEdit("mp3 192k aac he")
        self.transcode_preset.setEnabled(False)
        form.addRow("Transcode preset", self.transcode_preset)
        root.addWidget(grp)

        # Initial scan
        self.scan_now()

    def _toggle_auto(self, state):
        if self.auto_cb.isChecked():
            self._timer.start()
            self.status.setText("Auto-refreshing…")
        else:
            self._timer.stop()
            self.status.setText("Idle")

    def scan_now(self):
        try:
            devices = list_rockbox_devices()
            self._populate(devices)
            if devices:
                self.status.setText(f"Found {len(devices)} device(s)")
            else:
                self.status.setText("No Rockbox devices found")
        except Exception:
            self.status.setText("Detection error (see console/logs)")
            self.tree.clear()

    def _populate(self, devices):
        self.tree.clear()
        for dev in devices:
            # Accept both dicts and objects
            if isinstance(dev, dict):
                mountpoint = dev.get('mountpoint', '')
                name = dev.get('name') or ''
                label = dev.get('label') or ''
                model = dev.get('display_model') or dev.get('model') or dev.get('target') or ''
                fstype = dev.get('fstype', '')
                device = dev.get('device', '')
                total = dev.get('total_bytes', 0)
                free = dev.get('free_bytes', 0)
            else:
                mountpoint = getattr(dev, 'mountpoint', '')
                name = getattr(dev, 'name', '')
                label = getattr(dev, 'label', '') or ''
                model = getattr(dev, 'display_model', '') or getattr(dev, 'target', '')
                fstype = getattr(dev, 'fstype', '')
                device = getattr(dev, 'device', '')
                total = getattr(dev, 'total_bytes', 0)
                free = getattr(dev, 'free_bytes', 0)
            item = QTreeWidgetItem([
                mountpoint,
                str(name or ''),
                str(label),
                str(model or ''),
                fstype,
                device,
                _fmt_size(int(total) if total else 0),
                _fmt_size(int(free) if free else 0),
            ])
            self.tree.addTopLevelItem(item)
