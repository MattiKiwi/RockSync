import os
import sys
from typing import Dict
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QGroupBox, QFormLayout, QLineEdit, QCheckBox, QComboBox, QPlainTextEdit, QDialog,
    QFileDialog, QMessageBox, QInputDialog
)
from rockbox_utils import list_rockbox_devices
# Ensure project root is importable so `scripts.*` resolves when running from app/
try:
    from core import ROOT  # type: ignore
    _root_str = str(ROOT)
    if _root_str not in sys.path:
        sys.path.insert(0, _root_str)
except Exception:
    pass
try:
    from ui.rockbox_configurator import RockboxConfiguratorDialog
except Exception:
    RockboxConfiguratorDialog = None  # type: ignore
try:
    # Optional themes API
    from scripts import themes as themes_api  # type: ignore
except Exception:
    themes_api = None  # type: ignore
try:
    import requests  # type: ignore
except Exception:
    requests = None  # type: ignore
from PySide6.QtGui import QPixmap


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

        # Device selector (dropdown)
        sel_row = QHBoxLayout()
        sel_row.addWidget(QLabel("Device:"))
        self.device_combo = QComboBox()
        sel_row.addWidget(self.device_combo, 1)
        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.clicked.connect(self.scan_now)
        sel_row.addWidget(self.refresh_btn)
        root.addLayout(sel_row)

        # Summary panel
        sum_group = QGroupBox("Device Summary")
        sum_form = QFormLayout(sum_group)
        self.sum_name = QLabel("")
        self.sum_model = QLabel("")
        self.sum_cap = QLabel("")
        self.sum_free = QLabel("")
        self.sum_label = QLabel("")
        sum_form.addRow("Name", self.sum_name)
        sum_form.addRow("Model", self.sum_model)
        sum_form.addRow("Capacity", self.sum_cap)
        sum_form.addRow("Free", self.sum_free)
        sum_form.addRow("Label", self.sum_label)
        root.addWidget(sum_group)

        # Profiles manager
        prof_group = QGroupBox("Profiles (.cfg)")
        pv = QVBoxLayout(prof_group)
        row1 = QHBoxLayout()
        self.cfg_combo = QComboBox()
        row1.addWidget(self.cfg_combo, 1)
        self.cfg_refresh_btn = QPushButton("Refresh")
        self.cfg_refresh_btn.clicked.connect(self._refresh_configs)
        row1.addWidget(self.cfg_refresh_btn)
        pv.addLayout(row1)
        row2 = QHBoxLayout()
        #self.btn_set_active = QPushButton("Set Active")
        self.btn_edit = QPushButton("Configure…")
        self.btn_import = QPushButton("Import…")
        self.btn_export = QPushButton("Export…")
        #self.btn_new_from_current = QPushButton("New from Current")
        #self.btn_duplicate = QPushButton("Duplicate…")
        #self.btn_rename = QPushButton("Rename…")
        #self.btn_delete = QPushButton("Delete…")
        #row2.addWidget(self.btn_set_active)
        row2.addWidget(self.btn_edit)
        #row2.addWidget(self.btn_new_from_current)
        #row2.addWidget(self.btn_duplicate)
        #row2.addWidget(self.btn_rename)
        #row2.addWidget(self.btn_delete)
        row2.addWidget(self.btn_import)
        row2.addWidget(self.btn_export)
        row2.addStretch(1)
        pv.addLayout(row2)

        # Info labels for convenience (used elsewhere)
        info_form = QFormLayout()
        self.db_root = QLabel("/")
        self.active_cfg_label = QLabel("(none)")
        #info_form.addRow("RB dir", self.db_root)
        #info_form.addRow("Active", self.active_cfg_label)
        pv.addLayout(info_form)
        root.addWidget(prof_group)

        # Themes browser
        theme_group = QGroupBox("Themes (themes.rockbox.org)")
        tv = QVBoxLayout(theme_group)
        trow = QHBoxLayout()
        trow.addWidget(QLabel("Target:"))
        self.theme_target = QLineEdit()
        trow.addWidget(self.theme_target)
        trow.addWidget(QLabel("Search:"))
        self.theme_search = QLineEdit()
        trow.addWidget(self.theme_search, 1)
        self.theme_list_btn = QPushButton("Load List")
        trow.addWidget(self.theme_list_btn)
        tv.addLayout(trow)

        # List + preview side by side
        list_row = QHBoxLayout()
        from PySide6.QtWidgets import QListWidget, QListWidgetItem, QSpacerItem, QSizePolicy
        self.theme_list = QListWidget()
        list_row.addWidget(self.theme_list, 2)
        # preview panel
        prev_panel = QVBoxLayout()
        self.theme_preview = QLabel("Preview")
        self.theme_preview.setAlignment(Qt.AlignCenter)
        self.theme_preview.setMinimumSize(200, 150)
        self.theme_preview.setStyleSheet("background: #111; color: #aaa; border: 1px solid #333;")
        prev_panel.addWidget(self.theme_preview, 1)
        # Buttons
        pbtns = QHBoxLayout()
        self.theme_open_btn = QPushButton("Open Page")
        self.theme_install_btn = QPushButton("Install to Device")
        pbtns.addWidget(self.theme_open_btn)
        pbtns.addWidget(self.theme_install_btn)
        pbtns.addStretch(1)
        prev_panel.addLayout(pbtns)
        list_row.addLayout(prev_panel, 3)
        tv.addLayout(list_row)

        # Wire actions
        self.theme_list_btn.clicked.connect(self._themes_refresh)
        self.theme_list.itemSelectionChanged.connect(self._themes_on_select)
        self.theme_open_btn.clicked.connect(self._themes_open_page)
        self.theme_install_btn.clicked.connect(self._themes_install_selected)

        root.addWidget(theme_group)

        # Wire profile actions
        #self.btn_set_active.clicked.connect(self._set_active_config)
        self.btn_edit.clicked.connect(self._edit_selected_config)
        #elf.btn_new_from_current.clicked.connect(self._new_from_current)
        #self.btn_duplicate.clicked.connect(self._duplicate_selected)
        #self.btn_rename.clicked.connect(self._rename_selected)
        #self.btn_delete.clicked.connect(self._delete_selected)
        self.btn_import.clicked.connect(self._import_config)
        self.btn_export.clicked.connect(self._export_selected)

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
            self._devices = devices
            self._populate_dropdown(devices)
            if devices:
                self.status.setText(f"Found {len(devices)} device(s)")
            else:
                self.status.setText("No Rockbox devices found")
        except Exception:
            self.status.setText("Detection error (see console/logs)")
            self._devices = []
            self.device_combo.clear()

    def _populate_dropdown(self, devices):
        self.device_combo.blockSignals(True)
        self.device_combo.clear()
        for idx, dev in enumerate(devices):
            if isinstance(dev, dict):
                name = dev.get('name') or dev.get('label') or 'Device'
                model = dev.get('display_model') or dev.get('model') or dev.get('target') or ''
            else:
                name = getattr(dev, 'name', '') or getattr(dev, 'label', '') or 'Device'
                model = getattr(dev, 'display_model', '') or getattr(dev, 'target', '')
            text = f"{name} — {model}" if model else name
            self.device_combo.addItem(text, idx)
        self.device_combo.blockSignals(False)
        self.device_combo.currentIndexChanged.connect(self._on_device_selected)
        if self.device_combo.count() > 0:
            self.device_combo.setCurrentIndex(0)
            self._on_device_selected(0)

    def _on_device_selected(self, _idx):
        if not getattr(self, '_devices', None):
            return
        idx = self.device_combo.currentData()
        try:
            dev = self._devices[idx]
        except Exception:
            return
        # Extract fields
        if isinstance(dev, dict):
            self._current_mount = dev.get('mountpoint', '')
            name = dev.get('name') or dev.get('label') or ''
            model = dev.get('display_model') or dev.get('model') or dev.get('target') or ''
            total = int(dev.get('total_bytes', 0) or 0)
            free = int(dev.get('free_bytes', 0) or 0)
            label = dev.get('label') or ''
        else:
            self._current_mount = getattr(dev, 'mountpoint', '')
            name = getattr(dev, 'name', '') or getattr(dev, 'label', '') or ''
            model = getattr(dev, 'display_model', '') or getattr(dev, 'target', '')
            total = int(getattr(dev, 'total_bytes', 0) or 0)
            free = int(getattr(dev, 'free_bytes', 0) or 0)
            label = getattr(dev, 'label', '') or ''

        self.sum_name.setText(str(name))
        self.sum_model.setText(str(model))
        self.sum_cap.setText(_fmt_size(total))
        self.sum_free.setText(_fmt_size(free))
        self.sum_label.setText(str(label))
        self.db_root.setText("/.rockbox")
        # Suggest theme target from detection
        try:
            tgt = str(model).strip().lower()
            # If utils gave a target, prefer it
            if isinstance(dev, dict) and dev.get('target'):
                tgt = str(dev.get('target')).strip().lower()
            self.theme_target.setText(tgt or "")
        except Exception:
            pass
        self._refresh_configs()

    # ---------------- Config helpers ----------------
    def _config_path(self) -> str:
        mp = getattr(self, '_current_mount', '')
        return (mp.rstrip('/\\') + '/.rockbox/config.cfg') if mp else ''

    def _backup_config(self):
        import datetime as _dt
        path = self._config_path()
        if not path:
            self.status.setText("Select a device first")
            return
        try:
            if not os.path.isfile(path):
                # Nothing to back up; create empty config as baseline
                os.makedirs(os.path.dirname(path), exist_ok=True)
                open(path, 'a').close()
            ts = _dt.datetime.now().strftime('%Y%m%d-%H%M%S')
            backup = path + f'.bak-{ts}'
            import shutil as _sh
            _sh.copy2(path, backup)
            self.status.setText(f"Backed up config.cfg → {os.path.basename(backup)}")
        except Exception:
            self.status.setText("Backup failed (see logs)")

    def _open_config_editor(self):
        path = self._config_path()
        if not path:
            self.status.setText("Select a device first")
            return
        # Lazy create parent dir
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
        except Exception:
            pass
        # Read existing content
        try:
            try:
                with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
            except FileNotFoundError:
                content = ''
        except Exception:
            content = ''

        dlg = QDialog(self)
        dlg.setWindowTitle("Edit config.cfg")
        v = QVBoxLayout(dlg)
        edit = QPlainTextEdit(); edit.setPlainText(content)
        v.addWidget(edit, 1)
        row = QHBoxLayout(); row.addStretch(1)
        saveb = QPushButton("Save"); cancelb = QPushButton("Cancel")
        row.addWidget(cancelb); row.addWidget(saveb)
        v.addLayout(row)

        def _save():
            try:
                with open(path, 'w', encoding='utf-8') as f:
                    f.write(edit.toPlainText())
                self.status.setText("Saved config.cfg")
                dlg.accept()
            except Exception:
                self.status.setText("Save failed (see logs)")
        saveb.clicked.connect(_save)
        cancelb.clicked.connect(dlg.reject)
        dlg.exec()

    # ---------------- Themes browser ----------------
    def _themes_refresh(self):
        if themes_api is None:
            self.status.setText("Themes module missing. See scripts/themes.py and install requests/bs4.")
            return
        target = self.theme_target.text().strip() or 'ipodvideo'
        search = self.theme_search.text().strip() or None
        self.status.setText("Loading themes…")
        try:
            themes = themes_api.list_themes(target, search=search)
        except Exception:
            self.status.setText("Failed to load themes (network?)")
            return
        self.theme_list.clear()
        for t in themes:
            # t is scripts.themes.Theme dataclass
            name = getattr(t, 'name', None) or f"Theme {getattr(t,'id','')}"
            author = getattr(t, 'author', None)
            did = getattr(t, 'id', '')
            dl = getattr(t, 'downloads', None)
            # Prefer Name — Author (#id) [downloads]
            text = name
            if author:
                text += f" — {author}"
            if did:
                text += f"  (#{did})"
            if dl:
                text += f"  [{dl} dl]"
            from PySide6.QtWidgets import QListWidgetItem
            it = QListWidgetItem(text)
            it.setData(Qt.UserRole, t)
            # Tooltip with URL
            try:
                it.setToolTip(getattr(t, 'page_url', '') or '')
            except Exception:
                pass
            self.theme_list.addItem(it)
        self.status.setText(f"Loaded {self.theme_list.count()} theme(s)")
        self.theme_preview.clear(); self.theme_preview.setText("Preview")

    def _themes_on_select(self):
        self.theme_preview.clear(); self.theme_preview.setText("Preview")
        it = self.theme_list.currentItem()
        if not it:
            return
        t = it.data(Qt.UserRole)
        # Try list previews first; else fetch from page
        urls = list(getattr(t, 'preview_urls', []) or [])
        if (not urls) and themes_api is not None:
            try:
                info = themes_api.show_theme(self.theme_target.text().strip(), getattr(t, 'id', ''))
                pv = info.get('previews') if isinstance(info, dict) else None
                if pv:
                    urls = pv.splitlines()
            except Exception:
                urls = []
        if not urls:
            return
        # Fetch first preview image
        url = urls[0]
        for url in urls:
            if "https://themes.rockbox.org/themes/" in url:
                break
        if requests is None:
            self.theme_preview.setText("Install requests to load previews")
            return
        try:
            # Use same headers as scripts/themes.py to avoid 403
            headers = {}
            try:
                if themes_api is not None and hasattr(themes_api, 'HEADERS'):
                    headers.update(getattr(themes_api, 'HEADERS'))
            except Exception:
                pass
            headers.setdefault('User-Agent', 'RockboxThemeGUI/1.0 (+personal use)')
            ref = None
            try:
                ref = getattr(t, 'page_url', None)
            except Exception:
                ref = None
            headers.setdefault('Referer', ref or 'https://themes.rockbox.org/')

            r = requests.get(url, headers=headers, timeout=20)
            r.raise_for_status()
            pm = QPixmap()
            if pm.loadFromData(r.content):
                # scale while keeping aspect
                w = max(240, self.theme_preview.width())
                h = max(180, self.theme_preview.height())
                self.theme_preview.setPixmap(pm.scaled(w, h, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            else:
                self.theme_preview.setText("Preview unsupported")
        except Exception:
            self.theme_preview.setText("Preview failed")

    def _themes_open_page(self):
        it = self.theme_list.currentItem()
        if not it:
            return
        t = it.data(Qt.UserRole)
        url = getattr(t, 'page_url', None)
        if not url:
            return
        # Best-effort open using OS; fallback to status
        try:
            import webbrowser
            webbrowser.open(url)
        except Exception:
            self.status.setText(url)

    def _themes_install_selected(self):
        if themes_api is None:
            self.status.setText("Themes module missing. See scripts/themes.py and install requests/bs4.")
            return
        it = self.theme_list.currentItem()
        if not it:
            self.status.setText("Select a theme first")
            return
        t = it.data(Qt.UserRole)
        target = self.theme_target.text().strip() or 'ipodvideo'
        mp = getattr(self, '_current_mount', '')
        if not mp:
            self.status.setText("Select a device first")
            return
        # Confirm
        ret = QMessageBox.question(self, "Install Theme", f"Install '{getattr(t,'name','theme')}' to {mp}?\nThis will merge files into /.rockbox.")
        if ret != QMessageBox.Yes:
            return
        try:
            # Download a zip to temp and install
            import tempfile, os as _os
            with tempfile.TemporaryDirectory() as tmp:
                zp = themes_api.download_theme(target, getattr(t, 'id', ''), tmp)
                themes_api.install_theme_zip(zp, mp)
            self.status.setText("Theme installed")
        except Exception:
            self.status.setText("Install failed (see logs)")

    # ---------------- Profiles manager ----------------
    def _rb_path(self) -> str:
        mp = getattr(self, '_current_mount', '')
        return mp.rstrip('/\\') + '/.rockbox' if mp else ''

    def _list_configs(self):
        root = self._rb_path()
        items = []
        if not root:
            return items
        active_path = os.path.join(root, 'config.cfg')
        try:
            # search in /.rockbox and /.rockbox/configs
            search = [root, os.path.join(root, 'configs')]
            for base in search:
                try:
                    for name in os.listdir(base):
                        if not name.lower().endswith('.cfg'):
                            continue
                        # skip theme cfgs under themes directory
                        full = os.path.join(base, name)
                        if os.path.isdir(full):
                            continue
                        rel = os.path.relpath(full, root)
                        # Exclude theme cfgs in themes subdir
                        if rel.replace('\\','/').startswith('themes/'):
                            continue
                        items.append({
                            'name': name,
                            'full': full,
                            'rel': rel,
                            'is_active': os.path.abspath(full) == os.path.abspath(active_path)
                        })
                except Exception:
                    continue
        except Exception:
            pass
        # Ensure config.cfg appears even if directories are odd
        if not any(i['rel'] == 'config.cfg' for i in items) and os.path.isfile(active_path):
            items.insert(0, {
                'name': 'config.cfg', 'full': active_path, 'rel': 'config.cfg', 'is_active': True
            })
        # sort with config.cfg first, then alpha
        items.sort(key=lambda d: (0 if d['rel'] == 'config.cfg' else 1, d['rel'].lower()))
        return items

    def _refresh_configs(self):
        items = self._list_configs()
        self.cfg_combo.blockSignals(True)
        self.cfg_combo.clear()
        active_name = '(none)'
        for idx, it in enumerate(items):
            label = it['rel'] + ('  (active)' if it['is_active'] else '')
            self.cfg_combo.addItem(label, it)
            if it['is_active']:
                active_name = it['rel']
        self.cfg_combo.blockSignals(False)
        self.active_cfg_label.setText(active_name)

    def _current_cfg_item(self):
        it = self.cfg_combo.currentData()
        return it if isinstance(it, dict) else None

    def _set_active_config(self):
        it = self._current_cfg_item()
        if not it:
            return
        root = self._rb_path()
        dst = os.path.join(root, 'config.cfg')
        src = it['full']
        if os.path.abspath(src) == os.path.abspath(dst):
            self.status.setText("Already active")
            return
        # Confirm overwrite
        ret = QMessageBox.question(self, "Set Active Config", f"Replace config.cfg with {it['rel']}?")
        if ret != QMessageBox.Yes:
            return
        try:
            import shutil as _sh
            # backup current config.cfg
            if os.path.isfile(dst):
                _sh.copy2(dst, dst + '.bak')
            _sh.copy2(src, dst)
            self.status.setText(f"Set active: {it['rel']}")
            self._refresh_configs()
        except Exception:
            self.status.setText("Failed to set active (see logs)")

    def _edit_selected_config(self):
        it = self._current_cfg_item()
        if not it:
            return
        # Prefer configurator if available; fallback to raw editor
        path = it['full']
        if RockboxConfiguratorDialog is not None:
            dlg = RockboxConfiguratorDialog(path, self)
            ok = dlg.exec()
            if ok:
                self.status.setText(f"Saved {it['rel']}")
                return
        # Fallback
        #self._open_text_editor(path, title=f"Edit {it['rel']}")

    def _new_from_current(self):
        root = self._rb_path()
        cur = os.path.join(root, 'config.cfg')
        if not os.path.isfile(cur):
            self.status.setText("No current config.cfg to copy")
            return
        name, ok = QInputDialog.getText(self, "New from Current", "New filename (e.g., configs/car.cfg):", text="configs/profile.cfg")
        if not ok or not name.strip():
            return
        dst = os.path.join(root, name.strip())
        try:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            import shutil as _sh
            _sh.copy2(cur, dst)
            self.status.setText(f"Created {name}")
            self._refresh_configs()
        except Exception:
            self.status.setText("Failed to create profile")

    def _duplicate_selected(self):
        it = self._current_cfg_item()
        if not it:
            return
        name, ok = QInputDialog.getText(self, "Duplicate Profile", "New filename:", text=it['rel'])
        if not ok or not name.strip():
            return
        root = self._rb_path()
        dst = os.path.join(root, name.strip())
        try:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            import shutil as _sh
            _sh.copy2(it['full'], dst)
            self.status.setText(f"Duplicated to {name}")
            self._refresh_configs()
        except Exception:
            self.status.setText("Failed to duplicate")

    def _rename_selected(self):
        it = self._current_cfg_item()
        if not it:
            return
        name, ok = QInputDialog.getText(self, "Rename Profile", "New filename:", text=it['rel'])
        if not ok or not name.strip():
            return
        root = self._rb_path()
        dst = os.path.join(root, name.strip())
        try:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            os.replace(it['full'], dst)
            self.status.setText(f"Renamed to {name}")
            self._refresh_configs()
        except Exception:
            self.status.setText("Failed to rename")

    def _delete_selected(self):
        it = self._current_cfg_item()
        if not it:
            return
        # Prevent deleting active config.cfg directly
        if it['rel'] == 'config.cfg' or it['is_active']:
            QMessageBox.information(self, "Delete Profile", "Refusing to delete active config.cfg. Set another active first or delete the copy.")
            return
        ret = QMessageBox.question(self, "Delete Profile", f"Delete {it['rel']}? This cannot be undone.")
        if ret != QMessageBox.Yes:
            return
        try:
            os.remove(it['full'])
            self.status.setText(f"Deleted {it['rel']}")
            self._refresh_configs()
        except Exception:
            self.status.setText("Failed to delete")

    def _import_config(self):
        root = self._rb_path()
        if not root:
            self.status.setText("Select a device first")
            return
        path, _ = QFileDialog.getOpenFileName(self, "Import config (.cfg)", root, "Config (*.cfg)")
        if not path:
            return
        name, ok = QInputDialog.getText(self, "Import As", "Destination filename under /.rockbox:", text="configs/imported.cfg")
        if not ok or not name.strip():
            return
        dst = os.path.join(root, name.strip())
        try:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            import shutil as _sh
            _sh.copy2(path, dst)
            self.status.setText(f"Imported to {name}")
            self._refresh_configs()
        except Exception:
            self.status.setText("Failed to import")

    def _export_selected(self):
        it = self._current_cfg_item()
        if not it:
            return
        dst, _ = QFileDialog.getSaveFileName(self, "Export config", it['name'])
        if not dst:
            return
        try:
            import shutil as _sh
            _sh.copy2(it['full'], dst)
            self.status.setText(f"Exported to {dst}")
        except Exception:
            self.status.setText("Failed to export")

    def _open_text_editor(self, path: str, title: str):
        try:
            try:
                with open(path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
            except FileNotFoundError:
                content = ''
        except Exception:
            content = ''
        dlg = QDialog(self)
        dlg.setWindowTitle(title)
        v = QVBoxLayout(dlg)
        edit = QPlainTextEdit(); edit.setPlainText(content)
        v.addWidget(edit, 1)
        row = QHBoxLayout(); row.addStretch(1)
        saveb = QPushButton("Save"); cancelb = QPushButton("Cancel")
        row.addWidget(cancelb); row.addWidget(saveb)
        v.addLayout(row)
        def _save():
            try:
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, 'w', encoding='utf-8') as f:
                    f.write(edit.toPlainText())
                self.status.setText("Saved")
                dlg.accept()
            except Exception:
                self.status.setText("Save failed (see logs)")
        saveb.clicked.connect(_save)
        cancelb.clicked.connect(dlg.reject)
        dlg.exec()
