import os
import sys
import subprocess
import shutil
import threading
import queue
import sqlite3
import time
import hashlib
from pathlib import Path
from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QCheckBox, QPlainTextEdit, QFileDialog, QComboBox, QListWidget, QListWidgetItem, QMessageBox
)
from core import SCRIPTS_DIR
from rockbox_utils import list_rockbox_devices
from logging_utils import ui_log


class SyncPane(QWidget):
    """Simple one-way mirror: copy missing/newer files from source to device.
    Supports include extension filter and optional delete of extras on device.
    """
    def __init__(self, controller, parent):
        super().__init__(parent)
        self.controller = controller
        self._queue = queue.Queue()
        self._worker = None
        self._stop_flag = False
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        # Source row
        r1 = QHBoxLayout(); r1.addWidget(QLabel("Source (Library):"))
        self.src_edit = QLineEdit(self.controller.settings.get('music_root', ''))
        r1.addWidget(self.src_edit, 1)
        b = QPushButton("Browse"); b.clicked.connect(lambda: self._pick_dir(self.src_edit)); r1.addWidget(b)
        root.addLayout(r1)
        # Device row
        r2 = QHBoxLayout(); r2.addWidget(QLabel("Device:"))
        self.device_combo = QComboBox(); r2.addWidget(self.device_combo)
        rb = QPushButton("Refresh"); rb.clicked.connect(self._refresh_devices); r2.addWidget(rb)
        r2.addWidget(QLabel("Target:"))
        self.target_label = QLabel("")
        r2.addWidget(self.target_label, 1)
        root.addLayout(r2)
        # Options
        r3 = QHBoxLayout(); r3.addWidget(QLabel("Include ext (space-separated):"))
        self.ext_edit = QLineEdit(".mp3 .m4a .flac .ogg .opus")
        r3.addWidget(self.ext_edit, 1)
        root.addLayout(r3)
        r4 = QHBoxLayout()
        self.delete_extras_cb = QCheckBox("Delete extras on device (DANGEROUS)")
        r4.addWidget(self.delete_extras_cb)
        self.skip_existing_cb = QCheckBox("Only copy missing (skip if exists)")
        self.skip_existing_cb.setChecked(True)
        r4.addWidget(self.skip_existing_cb)
        self.cleanup_cb = QCheckBox("Clean up after sync (covers + lyrics)")
        self.cleanup_cb.setToolTip("Resize front covers to 100x100, export embedded lyrics, and promote a non-cover image to front cover if missing.")
        r4.addWidget(self.cleanup_cb)
        cleanup_help = QPushButton("?")
        cleanup_help.setFixedWidth(24)
        cleanup_help.setToolTip("Why clean up after sync?")
        cleanup_help.clicked.connect(self._show_cleanup_help)
        r4.addWidget(cleanup_help)
        r4.addStretch(1)
        root.addLayout(r4)

        # Audio quality row
        qrow = QHBoxLayout(); qrow.addWidget(QLabel("Audio Quality:"))
        self.quality_box = QComboBox()
        self._build_quality_dropdown()
        self.quality_box.currentIndexChanged.connect(self._on_quality_changed)
        qrow.addWidget(self.quality_box)
        help_btn = QPushButton("?"); help_btn.setFixedWidth(24); help_btn.setToolTip("Why downsample?")
        help_btn.clicked.connect(self._show_quality_help)
        qrow.addWidget(help_btn)
        qrow.addStretch(1)
        root.addLayout(qrow)

        # Mode selector
        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("Mode:"))
        self.mode_combo = QComboBox(); self.mode_combo.addItems(["Full Sync", "Partial Sync (Selected)", "Add Missing (DB)"])
        self.mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        mode_row.addWidget(self.mode_combo)
        mode_row.addStretch(1)
        root.addLayout(mode_row)

        # Partial selection controls and list (hidden by default)
        sel_controls = QHBoxLayout()
        self.add_sel_btn = QPushButton("Add Folder")
        self.add_sel_btn.clicked.connect(self._add_folder)
        sel_controls.addWidget(self.add_sel_btn)
        self.remove_sel_btn = QPushButton("Remove")
        self.remove_sel_btn.clicked.connect(self._remove_selected)
        sel_controls.addWidget(self.remove_sel_btn)
        self.clear_sel_btn = QPushButton("Clear")
        self.clear_sel_btn.clicked.connect(self._clear_selected)
        sel_controls.addWidget(self.clear_sel_btn)
        sel_controls.addStretch(1)
        root.addLayout(sel_controls)

        self.sel_list = QListWidget(); self.sel_list.setSelectionMode(QListWidget.ExtendedSelection)
        root.addWidget(self.sel_list, 1)

        # Buttons
        controls = QHBoxLayout(); controls.addStretch(1)
        self.run_btn = QPushButton("Start Sync"); self.run_btn.clicked.connect(self.start_sync); controls.addWidget(self.run_btn)
        self.stop_btn = QPushButton("Stop"); self.stop_btn.clicked.connect(self.stop_sync); controls.addWidget(self.stop_btn)
        # Verify device row
        self.verify_btn = QPushButton("Verify Device (MD5)")
        self.verify_btn.setToolTip("Checks the entire device against the library using MD5; optionally auto-repairs mismatches.")
        self.verify_btn.clicked.connect(self._verify_device_clicked)
        controls.addWidget(self.verify_btn)
        self.verify_fix_cb = QCheckBox("Auto-repair corrupted")
        controls.addWidget(self.verify_fix_cb)
        root.addLayout(controls)

        # Log
        self.log = QPlainTextEdit(); self.log.setReadOnly(True)
        root.addWidget(self.log, 1)

        # Timer to process queue
        self.timer = QTimer(self); self.timer.setInterval(100)
        self.timer.timeout.connect(self._drain_queue)
        self._refresh_devices()
        # Start in Full mode, hide partial widgets
        self._on_mode_changed(self.mode_combo.currentIndex())

    def _show_quality_help(self):
        QMessageBox.information(self, "Audio Quality",
            "Some devices have slow storage or limited CPU. High-bitrate or high-resolution files can stutter.\n\n"
            "Choosing a preset will downsample supported lossless formats (e.g., FLAC, WAV/AIFF, ALAC) on the device to improve playback stability.\n\n"
            "You can also add a custom preset with specific bit-depth and sample rate.")

    def _build_quality_dropdown(self):
        self.quality_box.clear()
        # First item is always Original / no downsample
        self.quality_box.addItem("Original (no downsample)", None)
        presets = []
        try:
            presets = list(self.controller.settings.get('downsample_presets') or [])
        except Exception:
            presets = []
        # Add defined presets with dict as userData
        for p in presets:
            name = str(p.get('name') or '')
            if not name:
                continue
            self.quality_box.addItem(name, {
                'bits': int(p.get('bits') or 16),
                'rate': int(p.get('rate') or 44100),
            })
        # Custom option
        self.quality_box.addItem("Custom…", { 'custom': True })
        # Select last used preset if available
        last = str(self.controller.settings.get('downsample_last') or '')
        if last:
            idx = self.quality_box.findText(last)
            if idx >= 0:
                self.quality_box.setCurrentIndex(idx)

    def _on_quality_changed(self, idx: int):
        data = self.quality_box.currentData()
        # Handle Custom… selection
        if isinstance(data, dict) and data.get('custom'):
            from PySide6.QtWidgets import QInputDialog
            # Prompt: "bit-depth, sample-rate" e.g. "16,44100"
            text, ok = QInputDialog.getText(self, "Custom Downsample Preset", "Enter bit-depth and sample-rate (e.g. 16,44100):")
            if not ok or not text:
                # Revert to Original
                self.quality_box.setCurrentIndex(0)
                return
            try:
                parts = [p.strip() for p in str(text).split(',')]
                bits = int(parts[0])
                rate = int(parts[1]) if len(parts) > 1 else 44100
                if bits not in (16, 24):
                    raise ValueError("bits must be 16 or 24")
                if rate < 8000 or rate > 192000:
                    raise ValueError("invalid sample-rate")
            except Exception as e:
                QMessageBox.warning(self, "Invalid Preset", f"Could not parse: {e}")
                self.quality_box.setCurrentIndex(0)
                return
            name = f"Custom: {bits}-bit {rate/1000:.1f} kHz"
            # Save to settings list and select
            try:
                from settings_store import save_settings
                presets = list(self.controller.settings.get('downsample_presets') or [])
                presets.append({ 'name': name, 'bits': bits, 'rate': rate })
                self.controller.settings['downsample_presets'] = presets
                self.controller.settings['downsample_last'] = name
                save_settings({ 'downsample_presets': presets, 'downsample_last': name })
            except Exception:
                pass
            self._build_quality_dropdown()
            j = self.quality_box.findText(name)
            self.quality_box.setCurrentIndex(j if j >= 0 else 0)
        else:
            # Persist last used
            try:
                from settings_store import save_settings
                save_settings({ 'downsample_last': self.quality_box.currentText() })
                self.controller.settings['downsample_last'] = self.quality_box.currentText()
            except Exception:
                pass

    def _show_cleanup_help(self):
        QMessageBox.information(self, "Post-sync Clean Up",
            "Rockbox has a few quirks that this option fixes:\n\n"
            "- Cover art: Rockbox reliably shows only 'front cover' (type 3) images and prefers small sizes (<= 100x100).\n"
            "  This step resizes existing front covers to 100x100 and, if a front cover is missing, promotes another embedded image to front cover (resized).\n\n"
            "- Lyrics: Rockbox does not use embedded lyrics for many formats. It expects plain files (.lrc/.txt) next to the music.\n"
            "  This step exports embedded lyrics to sidecar .lrc files under a 'Lyrics' subfolder beside each track.")

    def _refresh_devices(self):
        try:
            ui_log('sync_refresh_devices')
        except Exception:
            pass
        self.device_combo.blockSignals(True)
        self.device_combo.clear()
        devices = list_rockbox_devices()
        for d in devices:
            label = d.get('label') or d.get('mountpoint')
            mp = d.get('mountpoint')
            self.device_combo.addItem(f"{label} ({mp})", mp)
        self.device_combo.blockSignals(False)
        self.device_combo.currentIndexChanged.connect(self._on_device_selected)
        if self.device_combo.count() > 0:
            self._on_device_selected(self.device_combo.currentIndex())

    def _on_device_selected(self, idx: int):
        mp = self.device_combo.currentData()
        if mp:
            self.target_label.setText(mp.rstrip('/\\') + '/Music')
        try:
            ui_log('sync_device_selected', index=int(idx), mount=mp)
        except Exception:
            pass

    def _pick_dir(self, edit: QLineEdit):
        from PySide6.QtWidgets import QFileDialog
        path = QFileDialog.getExistingDirectory(self, "Select folder", edit.text() or os.getcwd())
        if path:
            edit.setText(path)
            # No-op; partial selections are manual via Add Folder

    def _on_mode_changed(self, idx: int):
        is_partial = (idx == 1)
        # Show/hide partial controls and list
        self.add_sel_btn.setVisible(is_partial)
        self.remove_sel_btn.setVisible(is_partial)
        self.clear_sel_btn.setVisible(is_partial)
        self.sel_list.setVisible(is_partial)
        try:
            ui_log('sync_mode_changed', mode=self.mode_combo.currentText())
        except Exception:
            pass
    def _add_folder(self):
        base = self.src_edit.text().strip()
        path = QFileDialog.getExistingDirectory(self, "Select folder to sync", base or os.getcwd())
        if not path:
            return
        try:
            ui_log('sync_add_folder', path=path)
        except Exception:
            pass
        try:
            # Ensure selection is inside source base
            basep = Path(base).resolve()
            pp = Path(path).resolve()
            pp.relative_to(basep)
        except Exception:
            self._append("Selection must be inside source base.\n")
            return
        # Avoid duplicates
        existing = {self.sel_list.item(i).text() for i in range(self.sel_list.count())}
        if path not in existing:
            QListWidgetItem(path, self.sel_list)

    def _remove_selected(self):
        for it in self.sel_list.selectedItems():
            row = self.sel_list.row(it)
            self.sel_list.takeItem(row)
        try:
            ui_log('sync_remove_selected')
        except Exception:
            pass

    def _clear_selected(self):
        self.sel_list.clear()
        try:
            ui_log('sync_clear_selected')
        except Exception:
            pass

    def start_sync(self):
        if self._worker and self._worker.is_alive():
            return
        src = self.src_edit.text().strip()
        mp = self.device_combo.currentData()
        if not (os.path.isdir(src) and mp and os.path.isdir(mp)):
            self._append("Select valid source and a connected device.\n")
            return
        dst = mp.rstrip('/\\') + '/Music'
        try:
            os.makedirs(dst, exist_ok=True)
        except Exception:
            pass
        self._stop_flag = False
        self.run_btn.setEnabled(False)
        # Inform top bar indicator
        try:
            self.controller._set_action_status("Sync: preparing...", True)
        except Exception:
            pass
        try:
            ui_log('sync_start', src=src, mount=mp)
        except Exception:
            pass
        mode = self.mode_combo.currentText()
        sel_info = ""
        if self.mode_combo.currentIndex() == 1:
            cnt = self.sel_list.count()
            if cnt == 0:
                self._append("No folders selected for partial sync.\n")
                self.run_btn.setEnabled(True)
                return
            sel_info = f"  selections: {cnt}\n"
        self._append(f"Starting sync ({mode})\n  src: {src}\n  dst: {dst}\n{sel_info}")
        self.timer.start()

        def worker():
            try:
                inc_exts = {e.lower() for e in self.ext_edit.text().split() if e.startswith('.')}
                srcp = Path(src); dstp = Path(dst)
                copied = 0; skipped = 0; updated = 0
                touched: list[Path] = []  # files newly copied/updated on device
                src_for_dst: dict[str, Path] = {}  # map rel key -> source full path

                def _md5_of_file(path: Path, chunk_size: int = 2 * 1024 * 1024) -> str | None:
                    try:
                        h = hashlib.md5()
                        with open(path, 'rb') as fh:
                            while True:
                                b = fh.read(chunk_size)
                                if not b:
                                    break
                                h.update(b)
                        return h.hexdigest()
                    except Exception:
                        return None

                def _load_md5_map(db_path: str, base: Path | None) -> dict[str, str]:
                    m = {}
                    if not db_path or not os.path.exists(db_path):
                        return m
                    try:
                        with sqlite3.connect(db_path) as conn:
                            cur = conn.execute("SELECT path, md5 FROM tracks")
                            for p, h in cur.fetchall():
                                if not p or not h:
                                    continue
                                try:
                                    pp = Path(p)
                                    rel = pp.relative_to(base) if base else pp
                                except Exception:
                                    rel = Path(p)
                                key = str(rel).replace('\\', '/').lower()
                                m[key] = str(h)
                    except Exception:
                        return {}
                    return m

                def _human(n: int) -> str:
                    for unit in ['B','KB','MB','GB','TB']:
                        if n < 1024 or unit == 'TB':
                            return f"{n:.1f} {unit}" if unit != 'B' else f"{n} {unit}"
                        n /= 1024
                    return f"{n:.1f} TB"

                def _copy_with_resume(src_file: Path, dst_file: Path, overall_start: float, totals: dict):
                    nonlocal updated, copied
                    src_size = src_file.stat().st_size
                    dst_exists = dst_file.exists()
                    dst_size = dst_file.stat().st_size if dst_exists else 0
                    mode = 'ab' if dst_exists and dst_size < src_size and dst_size > 0 else 'wb'
                    resumed = (mode == 'ab')
                    # Update overall totals if not accounted yet (in case of resume)
                    remaining = max(0, src_size - dst_size)
                    # Stream copy with per-file progress and overall ETA
                    chunk = 1024 * 1024
                    last_update = 0.0
                    file_done = dst_size
                    try:
                        with open(src_file, 'rb') as s, open(dst_file, mode) as d:
                            if resumed:
                                s.seek(dst_size)
                            while not self._stop_flag:
                                buf = s.read(chunk)
                                if not buf:
                                    break
                                d.write(buf)
                                file_done += len(buf)
                                totals['done'] += len(buf)
                                now = time.time()
                                if now - last_update >= 0.25:
                                    elapsed = max(0.001, now - overall_start)
                                    speed = totals['done'] / elapsed
                                    remain = max(0, totals['total'] - totals['done'])
                                    eta = int(remain / speed) if speed > 0 else 0
                                    overall_pct = (totals['done'] / totals['total'] * 100) if totals['total'] > 0 else 100
                                    file_pct = (file_done / src_size * 100) if src_size > 0 else 100
                                    tip = f"{src_file.name} — file {file_pct:.0f}% • overall {_human(totals['done'])}/{_human(totals['total'])} @ {_human(int(speed))}/s • ETA {eta}s"
                                    self._queue.put(("progress", { 'pct': int(overall_pct), 'tip': tip }))
                                    last_update = now
                    except Exception as e:
                        self._queue.put(("log", f"! Copy error: {src_file} -> {dst_file} : {e}\n"))
                        return False
                    # Set times and metadata
                    try:
                        shutil.copystat(src_file, dst_file, follow_symlinks=True)
                    except Exception:
                        pass
                    if resumed:
                        updated += 1
                        self._queue.put(("log", f"~ resumed {src_file.relative_to(srcp)}\n"))
                    else:
                        copied += 1
                        self._queue.put(("log", f"+ {src_file.relative_to(srcp)}\n"))
                    return True
                # Determine selection roots for partial mode
                selected_roots: list[Path] = []
                if self.mode_combo.currentIndex() == 1:
                    # From selected list
                    tmp = []
                    for i in range(self.sel_list.count()):
                        try:
                            tmp.append(Path(self.sel_list.item(i).text()))
                        except Exception:
                            continue
                    # Deduplicate nested selections by keeping highest-level items
                    tmp = sorted(set(tmp), key=lambda p: len(p.as_posix()))
                    for p in tmp:
                        if not any(str(p).startswith(str(other) + os.sep) for other in selected_roots):
                            selected_roots.append(p)
                mode_idx = self.mode_combo.currentIndex()

                if mode_idx in (0, 1):
                    # Build source map according to selection
                    self._queue.put(("status", "Sync: scanning source..."))
                    src_files: list[tuple[Path, Path]] = []
                    def add_from_root(root_dir: Path):
                        for rootd, _, files in os.walk(root_dir):
                            if self._stop_flag:
                                break
                            for name in files:
                                ext = os.path.splitext(name)[1].lower()
                                if inc_exts and ext not in inc_exts:
                                    continue
                                full = Path(rootd) / name
                                try:
                                    rel = full.relative_to(srcp)
                                except ValueError:
                                    continue
                                src_files.append((full, rel))

                    if selected_roots:
                        for r in selected_roots:
                            add_from_root(r)
                    else:
                        add_from_root(srcp)
                    # Attempt to load MD5 maps from DBs for verification
                    lib_db = self._resolve_db_path('library', None)
                    dev_db = self._resolve_db_path('device', dstp.parent)
                    lib_md5 = _load_md5_map(lib_db, srcp) if lib_db else {}
                    dev_md5 = _load_md5_map(dev_db, dstp) if dev_db else {}

                    # Compute total bytes to copy for ETA
                    total_bytes = 0
                    files_plan: list[tuple[Path, Path, int]] = []  # (full, rel, remaining_bytes)
                    for full, rel in src_files:
                        if self._stop_flag:
                            break
                        dst_file = dstp / rel
                        src_size = 0
                        try:
                            src_size = full.stat().st_size
                        except Exception:
                            continue
                        key = str(rel).replace('\\', '/').lower()
                        lmd5 = lib_md5.get(key)
                        dmd5 = dev_md5.get(key)
                        if dst_file.exists():
                            if lmd5 and dmd5 and lmd5 == dmd5:
                                continue  # already identical
                            try:
                                dst_size = dst_file.stat().st_size
                            except Exception:
                                dst_size = 0
                            if self.skip_existing_cb.isChecked() and dst_size >= src_size:
                                # existing but cannot verify; skip
                                continue
                            remaining = max(0, src_size - max(0, dst_size))
                        else:
                            remaining = src_size
                        if remaining > 0:
                            total_bytes += remaining
                            files_plan.append((full, rel, remaining))

                    totals = { 'total': total_bytes, 'done': 0 }
                    overall_start = time.time()
                    if not self._stop_flag:
                        self._queue.put(("status", f"Sync: copying…"))
                        # Initialize progress bar
                        self._queue.put(("progress", { 'pct': 0, 'tip': f"Planning {_human(total_bytes)} to copy" }))

                    # Copy/Resume
                    for full, rel, _remaining in files_plan:
                        if self._stop_flag:
                            break
                        dst_file = dstp / rel
                        dst_file.parent.mkdir(parents=True, exist_ok=True)
                        try:
                            ok = _copy_with_resume(full, dst_file, overall_start, totals)
                            if ok:
                                # Verify hash if available
                                key = str(rel).replace('\\', '/').lower()
                                src_hash = lib_md5.get(key) or _md5_of_file(full)
                                dst_hash = _md5_of_file(dst_file)
                                if src_hash and dst_hash and src_hash != dst_hash:
                                    self._queue.put(("log", f"! Hash mismatch: {rel}\n"))
                                else:
                                    touched.append(dst_file)
                                    # record source mapping
                                    try:
                                        src_for_dst[key] = full
                                    except Exception:
                                        pass
                            else:
                                skipped += 1
                        except Exception as e:
                            self._queue.put(("log", f"! {rel} : {e}\n"))
                else:
                    # Mode 2: Add Missing (DB)
                    self._queue.put(("status", "Sync: loading DBs…"))
                    lib_db = self._resolve_db_path('library', None)
                    dev_db = self._resolve_db_path('device', dstp.parent)
                    if not lib_db or not os.path.exists(lib_db):
                        self._queue.put(("log", "! Library DB not found. Ensure music_index.sqlite3 exists.\n"))
                        return
                    if not dev_db or not os.path.exists(dev_db):
                        self._queue.put(("log", "! Device DB not found. Ensure the device has been indexed.\n"))
                        return
                    lib_rows = self._load_db_rows(lib_db)
                    dev_keys = self._load_db_keys(dev_db)
                    if self._stop_flag:
                        return
                    self._queue.put(("status", "Sync: comparing libraries…"))
                    # Build relative path for copy based on source base
                    for (path, artist, album, title, seconds) in lib_rows:
                        if self._stop_flag:
                            break
                        k = self._make_key(artist, album, title, seconds)
                        if k in dev_keys:
                            continue
                        try:
                            full = Path(path)
                        except Exception:
                            continue
                        # Only copy if under source base and extension allowed
                        ext = full.suffix.lower()
                        if inc_exts and ext not in inc_exts:
                            continue
                        try:
                            rel = full.relative_to(srcp)
                        except Exception:
                            # Not under source base; place under Tracks
                            rel = Path('Tracks') / full.name
                        dst_file = dstp / rel
                        dst_file.parent.mkdir(parents=True, exist_ok=True)
                        try:
                            # Resume/Copy with progress for DB mode as well
                            # Build minimal totals context for ETA per file only
                            src_size = full.stat().st_size if full.exists() else 0
                            totals = { 'total': src_size, 'done': 0 }
                            _copy_with_resume(full, dst_file, time.time(), totals)
                            # Verify hash when possible (only if library DB has md5)
                            try:
                                with sqlite3.connect(lib_db) as conn:
                                    row = conn.execute("SELECT md5 FROM tracks WHERE path=?", (str(full),)).fetchone()
                                    src_hash = row[0] if row else None
                            except Exception:
                                src_hash = None
                            dst_hash = _md5_of_file(dst_file)
                            if src_hash and dst_hash and src_hash != dst_hash:
                                self._queue.put(("log", f"! Hash mismatch: {rel}\n"))
                            else:
                                touched.append(dst_file)
                            # record source mapping
                            try:
                                key = str(rel).replace('\\', '/').lower()
                                src_for_dst[key] = full
                            except Exception:
                                pass
                        except Exception as e:
                            self._queue.put(("log", f"! {rel} : {e}\n"))

                # Delete extras if requested (only applicable to Full/Partial modes)
                if self.delete_extras_cb.isChecked() and not self._stop_flag and mode_idx in (0, 1):
                    self._queue.put(("status", "Sync: deleting extras…"))
                    src_set = {rel.as_posix() for _, rel in src_files}
                    # Scope deletions: if partial, only under selected roots; otherwise whole dst
                    scopes: list[Path] = []
                    if selected_roots:
                        for r in selected_roots:
                            try:
                                rel_root = r.relative_to(srcp)
                            except ValueError:
                                continue
                            scopes.append(dstp / rel_root)
                    else:
                        scopes = [dstp]
                    for scope in scopes:
                        for rootd, _, files in os.walk(scope):
                            if self._stop_flag:
                                break
                            for name in files:
                                dst_full = Path(rootd) / name
                                try:
                                    rel = dst_full.relative_to(dstp)
                                except ValueError:
                                    continue
                                ext = dst_full.suffix.lower()
                                if inc_exts and ext not in inc_exts:
                                    continue
                                if rel.as_posix() not in src_set:
                                    try:
                                        os.remove(dst_full)
                                        self._queue.put(("log", f"- {rel}\n"))
                                    except Exception as e:
                                        self._queue.put(("log", f"! del {rel}: {e}\n"))

                # Optional downsample step
                preset = self.quality_box.currentData()
                if not self._stop_flag and isinstance(preset, dict) and ('bits' in preset and 'rate' in preset):
                    bits = int(preset.get('bits') or 16)
                    rate = int(preset.get('rate') or 44100)
                    self._queue.put(("status", "Sync: downsampling audio..."))
                    self._queue.put(("log", f"Downsampling lossless audio to {bits}-bit/{rate/1000:.1f}kHz on device...\n"))
                    script = str(SCRIPTS_DIR / 'downsampler.py')
                    jobs = 0
                    try:
                        jobs = int(self.controller.settings.get('jobs', os.cpu_count() or 4))
                    except Exception:
                        jobs = os.cpu_count() or 4
                    # Build list of touched audio files (supported lossless extensions)
                    touched_candidates = [
                        str(p) for p in touched if p.suffix.lower() in {'.flac', '.wav', '.aif', '.aiff', '.m4a'}
                    ]
                    list_file = None
                    if touched_candidates:
                        try:
                            list_file = dstp / ".sync_touched_audio.txt"
                            with open(list_file, 'w', encoding='utf-8') as fh:
                                fh.write("\n".join(touched_candidates))
                        except Exception:
                            list_file = None
                    try:
                        cmd = [sys.executable, script, "-j", str(jobs), "--bits", str(bits), "--rate", str(rate)]
                        if list_file:
                            cmd.extend(["--files-from", str(list_file)])
                        else:
                            cmd.extend(["--source", str(dstp)])
                        proc = subprocess.Popen(
                            cmd,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
                        )
                        assert proc.stdout is not None
                        for line in proc.stdout:
                            if self._stop_flag:
                                try:
                                    proc.terminate()
                                except Exception:
                                    pass
                                break
                            self._queue.put(("log", line))
                        rc = proc.wait()
                        if rc != 0:
                            self._queue.put(("log", f"Downsampler exited with code {rc}.\n"))
                        else:
                            self._queue.put(("log", "Downsampling complete.\n"))
                        # Cleanup temp list file
                        try:
                            if list_file and os.path.exists(list_file):
                                os.remove(list_file)
                        except Exception:
                            pass
                    except FileNotFoundError:
                        self._queue.put(("log", "Downsampler script not found. Skipping.\n"))
                    except Exception as e:
                        self._queue.put(("log", f"Downsampler error: {e}\n"))

                # Optional clean-up step (covers + lyrics)
                if not self._stop_flag and self.cleanup_cb.isChecked():
                    self._queue.put(("log", "Running Rockbox clean up (covers + lyrics)...\n"))

                    def _run_script(cmd, label: str):
                        # Announce specific cleanup step
                        self._queue.put(("status", f"Sync: {label.lower()}..."))
                        try:
                            proc = subprocess.Popen(
                                cmd,
                                stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT,
                                text=True,
                            )
                            assert proc.stdout is not None
                            for line in proc.stdout:
                                if self._stop_flag:
                                    try:
                                        proc.terminate()
                                    except Exception:
                                        pass
                                    break
                                self._queue.put(("log", line))
                            rc = proc.wait()
                            if rc != 0:
                                self._queue.put(("log", f"{label} exited with code {rc}.\n"))
                            else:
                                self._queue.put(("log", f"{label} complete.\n"))
                        except FileNotFoundError:
                            self._queue.put(("log", f"{label} script not found. Skipping.\n"))
                        except Exception as e:
                            self._queue.put(("log", f"{label} error: {e}\n"))

                    dstp = Path(dst)
                    # Write touched file list for targeted cleanup
                    touched_list = None
                    if touched:
                        try:
                            touched_list = dstp / ".sync_touched.txt"
                            with open(touched_list, 'w', encoding='utf-8') as fh:
                                for p in touched:
                                    fh.write(str(p) + "\n")
                        except Exception:
                            touched_list = None
                    # 1) Resize existing front covers to 100x100 (only new files)
                    cmd1 = [sys.executable, str(SCRIPTS_DIR / 'embedd_resize.py'), '--folder', str(dstp), '--size', '100x100']
                    if touched_list:
                        cmd1.extend(['--files-from', str(touched_list)])
                    _run_script(cmd1, 'Cover resize')
                    if self._stop_flag:
                        pass
                    else:
                        # 2) Export lyrics to sidecar files (only new files)
                        cmd2 = [sys.executable, str(SCRIPTS_DIR / 'lyrics_local.py'), '--music-dir', str(dstp), '--lyrics-subdir', 'Lyrics', '--ext', '.lrc']
                        if touched_list:
                            cmd2.extend(['--files-from', str(touched_list)])
                        _run_script(cmd2, 'Lyrics export')
                    if not self._stop_flag:
                        # 3) Promote/resize image to cover where no type 3 exists (only new files)
                        cmd3 = [sys.executable, str(SCRIPTS_DIR / 'embed_resize_no_cover.py'), '--folder', str(dstp), '--max-size', '100']
                        if touched_list:
                            cmd3.extend(['--files-from', str(touched_list)])
                        _run_script(cmd3, 'Promote cover')
                    # Cleanup temp list
                    try:
                        if touched_list and os.path.exists(touched_list):
                            os.remove(touched_list)
                    except Exception:
                        pass

                # Post-sync: verify copied files against library MD5 where applicable
                try:
                    preset = None
                    try:
                        preset = self.quality_box.currentData()
                    except Exception:
                        preset = None
                    downsample_enabled = isinstance(preset, dict) and ('bits' in preset and 'rate' in preset)
                    lossless_exts = {'.flac', '.wav', '.aif', '.aiff', '.m4a'}
                    # Load library MD5s once
                    lib_db = self._resolve_db_path('library', None)
                    lib_md5 = _load_md5_map(lib_db, srcp) if lib_db else {}
                    mismatches = []
                    fixed = []
                    failed = []
                    for dst_path in touched:
                        try:
                            rel = dst_path.relative_to(dstp)
                        except Exception:
                            continue
                        # Skip verification for potentially transformed lossless files
                        if downsample_enabled and dst_path.suffix.lower() in lossless_exts:
                            continue
                        key = str(rel).replace('\\', '/').lower()
                        src_hash = lib_md5.get(key)
                        if not src_hash:
                            continue
                        dst_hash = _md5_of_file(dst_path)
                        if dst_hash and dst_hash != src_hash:
                            mismatches.append(rel)
                            # Attempt automatic replacement from source
                            try:
                                src_full = src_for_dst.get(key) or (srcp / rel)
                                # Overwrite destination with fresh copy
                                shutil.copy2(str(src_full), str(dst_path))
                                # Re-verify
                                new_hash = _md5_of_file(dst_path)
                                if new_hash == src_hash:
                                    fixed.append(rel)
                                else:
                                    failed.append(rel)
                            except Exception:
                                failed.append(rel)
                    if mismatches:
                        msg = []
                        msg.append(f"Detected {len(mismatches)} corrupted files (MD5 mismatch).")
                        if fixed:
                            msg.append(f"Replaced {len(fixed)} successfully.")
                        if failed:
                            msg.append(f"Failed to replace {len(failed)} file(s). See log for details.")
                        self._queue.put(("log", "! " + " ".join(msg) + "\n"))
                        # Detailed list limited in log
                        for r in mismatches[:50]:
                            self._queue.put(("log", f"  - {r}\n"))
                        if len(mismatches) > 50:
                            self._queue.put(("log", f"  … and {len(mismatches)-50} more\n"))
                        # Popup on UI thread
                        try:
                            self._queue.put(("popup", {
                                'title': 'Corrupted files detected',
                                'text': "\n".join(msg)
                            }))
                        except Exception:
                            pass
                    else:
                        self._queue.put(("log", "MD5 verification passed for all copied files.\n"))
                except Exception as e:
                    self._queue.put(("log", f"MD5 verification skipped: {e}\n"))

                # Trigger device DB re-scan on UI thread (after any downsampling/cleanup)
                try:
                    self._queue.put(("status", "Sync: indexing device…"))
                    self._queue.put(("index_device", { 'mount': str(dstp.parent) }))
                except Exception:
                    pass

                self._queue.put(("log", f"Done. copied={copied}, updated={updated}, skipped={skipped}\n"))
            finally:
                self._queue.put(("end", None))

        self._worker = threading.Thread(target=worker, daemon=True)
        self._worker.start()

    # ---- DB helpers for Add Missing mode ----
    def _resolve_db_path(self, which: str, device_mount: Path | None) -> str | None:
        try:
            from core import CONFIG_PATH
            cfg = Path(CONFIG_PATH)
            if which == 'library':
                return str(cfg.with_name('music_index.sqlite3'))
            if which == 'device' and device_mount:
                return str(Path(device_mount) / '.rocksync' / 'music_index.sqlite3')
        except Exception:
            return None
        return None

    def _load_db_rows(self, db_path: str):
        rows = []
        try:
            with sqlite3.connect(db_path) as conn:
                cur = conn.execute("SELECT path, artist, album, title, IFNULL(duration_seconds,0) FROM tracks")
                rows = [(p, a or '', al or '', t or '', int(d or 0)) for (p,a,al,t,d) in cur.fetchall()]
        except Exception:
            rows = []
        return rows

    def _make_key(self, artist: str, album: str, title: str, seconds: int) -> tuple:
        return (artist.strip().lower(), album.strip().lower(), title.strip().lower(), int(seconds or 0))

    def _load_db_keys(self, db_path: str):
        keys = set()
        try:
            with sqlite3.connect(db_path) as conn:
                cur = conn.execute("SELECT artist, album, title, IFNULL(duration_seconds,0) FROM tracks")
                for a, al, t, d in cur.fetchall():
                    keys.add(self._make_key(a or '', al or '', t or '', int(d or 0)))
        except Exception:
            return set()
        return keys

    def stop_sync(self):
        self._stop_flag = True
        try:
            self.controller._set_action_status("Sync: stopping...", True)
        except Exception:
            pass
        try:
            ui_log('sync_stop')
        except Exception:
            pass

    # ---- Full-device verification ----
    def _verify_device_clicked(self):
        mp = self.device_combo.currentData()
        if not (mp and os.path.isdir(mp)):
            self._append("Select a connected device.\n")
            return
        dst = mp.rstrip('/\\') + '/Music'
        if not os.path.isdir(dst):
            self._append("Device has no Music folder.\n")
            return
        auto_fix = self.verify_fix_cb.isChecked()
        self._append(f"Starting device verification (auto-repair={'on' if auto_fix else 'off'})…\n")
        self.controller._set_action_status("Verify: preparing…", True)
        self.timer.start()

        def worker():
            try:
                src_base = Path(self.src_edit.text().strip() or '')
                dstp = Path(dst)
                lib_db = self._resolve_db_path('library', None)
                if not (lib_db and os.path.exists(lib_db)):
                    self._queue.put(("log", "! Library DB not found. Run a library scan first.\n"))
                    return
                self._queue.put(("status", "Verify: loading library index…"))
                # Build library maps: by relative path (under src base) and by basename fallback
                lib_rel_md5: dict[str, tuple[str, str]] = {}
                lib_name_map: dict[str, list[tuple[str, str]]] = {}
                try:
                    with sqlite3.connect(lib_db) as conn:
                        cur = conn.execute("SELECT path, IFNULL(md5,'') FROM tracks")
                        for p, h in cur.fetchall():
                            if not p:
                                continue
                            ap = str(p)
                            md5v = (h or '').strip()
                            base = os.path.basename(ap).lower()
                            lib_name_map.setdefault(base, []).append((ap, md5v))
                            # add relative if within src base
                            try:
                                rel = str(Path(ap).resolve().relative_to(src_base.resolve())).replace('\\','/').lower()
                                if rel:
                                    lib_rel_md5[rel] = (ap, md5v)
                            except Exception:
                                pass
                except Exception:
                    pass
                if not lib_name_map:
                    self._queue.put(("log", "! Library DB has no MD5/path data. Re-scan the library.\n"))
                    return
                # Walk entire device filesystem
                self._queue.put(("status", "Verify: scanning device files…"))
                inc_exts = {e.lower() for e in self.ext_edit.text().split() if e.startswith('.')}
                all_files: list[Path] = []
                for rootd, _, files in os.walk(dstp):
                    for name in files:
                        ext = os.path.splitext(name)[1].lower()
                        if inc_exts and ext not in inc_exts:
                            continue
                        all_files.append(Path(rootd) / name)
                bad = 0; fixed = 0; failed = 0; missing_src = 0
                total_rows = len(all_files)
                processed = 0
                last_tick = 0.0
                last_log = 0.0
                start_ts = time.time()
                self._queue.put(("progress", { 'pct': 0, 'tip': f"Preparing… {total_rows} files" }))
                # Helper to compute source MD5 on the fly when DB lacks it
                def _md5_file(p: Path) -> str | None:
                    try:
                        h = hashlib.md5()
                        with open(p, 'rb') as fh:
                            while True:
                                b = fh.read(2 * 1024 * 1024)
                                if not b:
                                    break
                                h.update(b)
                        return h.hexdigest()
                    except Exception:
                        return None
                for dfile in all_files:
                    if self._stop_flag:
                        break
                    processed += 1
                    try:
                        if not dfile.exists():
                            continue
                        # Compute md5 of device file
                        try:
                            dh = hashlib.md5()
                            with open(dfile, 'rb') as fh:
                                while True:
                                    buf = fh.read(2 * 1024 * 1024)
                                    if not buf:
                                        break
                                    dh.update(buf)
                            dmd5 = dh.hexdigest()
                        except Exception:
                            dmd5 = None
                        # Match by relative path or basename fallback
                        try:
                            rel = str(dfile.resolve().relative_to(dstp.resolve())).replace('\\','/').lower()
                        except Exception:
                            rel = dfile.name.lower()
                        src_path = None; src_md5 = None
                        if rel in lib_rel_md5:
                            src_path, src_md5 = lib_rel_md5.get(rel) or (None, None)
                        if not src_md5 and src_path and Path(src_path).exists():
                            # Compute expected MD5 from library file when missing in DB
                            try:
                                src_md5 = _md5_file(Path(src_path))
                            except Exception:
                                src_md5 = None
                        if not src_md5:
                            candidates = lib_name_map.get(dfile.name.lower()) or []
                            if candidates:
                                src_path, src_md5 = candidates[0]
                                if (not src_md5) and src_path and Path(src_path).exists():
                                    try:
                                        src_md5 = _md5_file(Path(src_path))
                                    except Exception:
                                        src_md5 = None
                        if not dmd5 or not src_md5 or dmd5 == src_md5:
                            # periodic progress update
                            now = time.time()
                            if now - last_tick >= 0.25:
                                pct = int((processed / total_rows) * 100) if total_rows else 100
                                tip = f"{dfile.name} — {processed}/{total_rows} • corrupted {bad} • fixed {fixed}"
                                self._queue.put(("progress", { 'pct': pct, 'tip': tip }))
                                # Also write a concise progress line to the log occasionally
                                if now - last_log >= 2.0:
                                    elapsed = max(0.001, now - start_ts)
                                    rate = processed / elapsed
                                    remaining = max(0, total_rows - processed)
                                    eta_s = int(remaining / rate) if rate > 0 else 0
                                    self._queue.put(("log", f"… {processed}/{total_rows} ({pct}%) verified; corrupted={bad}, fixed={fixed}; ETA ~{eta_s}s\n"))
                                    last_log = now
                                last_tick = now
                            continue
                        # Mismatch
                        bad += 1
                        self._queue.put(("log", f"! Corrupted: {dfile} (device md5 {dmd5}); expecting {src_md5 or 'unknown'}\n"))
                        if auto_fix:
                            # Try to copy from library
                            sp = Path(src_path) if src_path else None
                            if not (sp and sp.exists()) and rel:
                                try:
                                    sp = (src_base / rel)
                                except Exception:
                                    sp = None
                            if sp.exists():
                                try:
                                    shutil.copy2(str(sp), str(dfile))
                                    # Recompute md5
                                    nh = hashlib.md5()
                                    with open(dfile, 'rb') as fh:
                                        while True:
                                            buf = fh.read(2 * 1024 * 1024)
                                            if not buf:
                                                break
                                            nh.update(buf)
                                    if nh.hexdigest() == src_md5:
                                        fixed += 1
                                        self._queue.put(("log", f"  → Replaced OK from {sp}\n"))
                                    else:
                                        failed += 1
                                        self._queue.put(("log", f"  → Replace failed (md5 mismatch after copy)\n"))
                                except Exception as e:
                                    failed += 1
                                    self._queue.put(("log", f"  → Replace error: {e}\n"))
                            else:
                                missing_src += 1
                                self._queue.put(("log", f"  → Source not found for {dfile.name}\n"))
                        # Notify for this corrupted file
                        try:
                            detail = f"Corrupted file: {dfile.name}"
                            if auto_fix:
                                detail += "\nAuto-repair attempted."
                            self._queue.put(("popup", { 'title': 'Corruption detected', 'text': detail }))
                        except Exception:
                            pass
                        # progress tick after handling corruption
                        try:
                            pct = int((processed / total_rows) * 100) if total_rows else 100
                            tip = f"{dfile.name} — {processed}/{total_rows} • corrupted {bad} • fixed {fixed}"
                            self._queue.put(("progress", { 'pct': pct, 'tip': tip }))
                        except Exception:
                            pass
                    except Exception:
                        continue
                summary = f"Verify complete. scanned={total_rows}, corrupted={bad}, fixed={fixed}, failed={failed}, missing_source={missing_src}\n"
                self._queue.put(("log", summary))
                # Popup summary
                self._queue.put(("popup", { 'title': 'Device Verification', 'text': summary.strip() }))
            finally:
                self._queue.put(("end", None))

        self._worker = threading.Thread(target=worker, daemon=True)
        self._worker.start()

    def _append(self, text: str):
        self.log.moveCursor(QTextCursor.End)
        self.log.insertPlainText(text)
        self.log.moveCursor(QTextCursor.End)

    def _drain_queue(self):
        try:
            while True:
                kind, payload = self._queue.get_nowait()
                if kind == 'log':
                    self._append(payload)
                elif kind == 'status':
                    try:
                        self.controller._set_action_status(str(payload), True)
                    except Exception:
                        pass
                elif kind == 'popup':
                    try:
                        title = 'Notice'
                        text = ''
                        if isinstance(payload, dict):
                            title = str(payload.get('title') or title)
                            text = str(payload.get('text') or '')
                        QMessageBox.warning(self, title, text)
                    except Exception:
                        pass
                elif kind == 'index_device':
                    try:
                        mount = None
                        if isinstance(payload, dict):
                            mount = payload.get('mount')
                        if mount:
                            self.controller._scan_device_db(str(mount))
                    except Exception:
                        pass
                elif kind == 'progress':
                    try:
                        pct = 0
                        tip = None
                        if isinstance(payload, dict):
                            pct = int(payload.get('pct') or 0)
                            tip = payload.get('tip')
                        elif isinstance(payload, (tuple, list)) and payload:
                            pct = int(payload[0])
                            tip = payload[1] if len(payload) > 1 else None
                        self.controller._set_action_progress(pct, tip)
                    except Exception:
                        pass
                elif kind == 'end':
                    self.run_btn.setEnabled(True)
                    self.timer.stop()
                    try:
                        self.controller._set_action_status("Idle", False)
                        # Hide and reset the top-bar progress bar
                        self.controller._set_action_progress(None, None)
                    except Exception:
                        pass
                    break
        except queue.Empty:
            pass
