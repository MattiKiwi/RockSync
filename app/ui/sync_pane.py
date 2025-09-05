import os
import sys
import subprocess
import shutil
import threading
import queue
from pathlib import Path
from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QCheckBox, QPlainTextEdit, QFileDialog, QComboBox, QListWidget, QListWidgetItem, QMessageBox
)
from core import SCRIPTS_DIR
from rockbox_utils import list_rockbox_devices


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
        self.quality_box = QComboBox(); self.quality_box.addItems([
            "Original (no downsample)",
            "16-bit 44.1 kHz (downsample FLAC)"
        ])
        qrow.addWidget(self.quality_box)
        help_btn = QPushButton("?"); help_btn.setFixedWidth(24); help_btn.setToolTip("Why downsample?")
        help_btn.clicked.connect(self._show_quality_help)
        qrow.addWidget(help_btn)
        qrow.addStretch(1)
        root.addLayout(qrow)

        # Mode selector
        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("Mode:"))
        self.mode_combo = QComboBox(); self.mode_combo.addItems(["Full Sync", "Partial Sync (Selected)"])
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
            "Choosing '16-bit 44.1 kHz' will downsample supported formats (FLAC) after syncing on the device to improve playback stability.")

    def _show_cleanup_help(self):
        QMessageBox.information(self, "Post-sync Clean Up",
            "Rockbox has a few quirks that this option fixes:\n\n"
            "- Cover art: Rockbox reliably shows only 'front cover' (type 3) images and prefers small sizes (<= 100x100).\n"
            "  This step resizes existing front covers to 100x100 and, if a front cover is missing, promotes another embedded image to front cover (resized).\n\n"
            "- Lyrics: Rockbox does not use embedded lyrics for many formats. It expects plain files (.lrc/.txt) next to the music.\n"
            "  This step exports embedded lyrics to sidecar .lrc files under a 'Lyrics' subfolder beside each track.")

    def _refresh_devices(self):
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
    def _add_folder(self):
        base = self.src_edit.text().strip()
        path = QFileDialog.getExistingDirectory(self, "Select folder to sync", base or os.getcwd())
        if not path:
            return
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

    def _clear_selected(self):
        self.sel_list.clear()

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
                # Copy/update
                if not self._stop_flag:
                    self._queue.put(("status", "Sync: copying files..."))
                for full, rel in src_files:
                    if self._stop_flag:
                        break
                    dst_file = dstp / rel
                    dst_file.parent.mkdir(parents=True, exist_ok=True)
                    try:
                        if not dst_file.exists():
                            shutil.copy2(full, dst_file)
                            copied += 1
                            self._queue.put(("log", f"+ {rel}\n"))
                        else:
                            if self.skip_existing_cb.isChecked():
                                skipped += 1
                            else:
                                sst = full.stat(); dstst = dst_file.stat()
                                if sst.st_size != dstst.st_size or int(sst.st_mtime) > int(dstst.st_mtime):
                                    shutil.copy2(full, dst_file)
                                    updated += 1
                                    self._queue.put(("log", f"~ {rel}\n"))
                                else:
                                    skipped += 1
                    except Exception as e:
                        self._queue.put(("log", f"! {rel} : {e}\n"))

                # Delete extras if requested
                if self.delete_extras_cb.isChecked() and not self._stop_flag:
                    self._queue.put(("status", "Sync: deleting extras..."))
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
                if not self._stop_flag and self.quality_box.currentIndex() == 1:
                    self._queue.put(("status", "Sync: downsampling audio..."))
                    self._queue.put(("log", "Downsampling FLAC to 16-bit/44.1kHz on device...\n"))
                    script = str(SCRIPTS_DIR / 'downsampler.py')
                    jobs = 0
                    try:
                        jobs = int(self.controller.settings.get('jobs', os.cpu_count() or 4))
                    except Exception:
                        jobs = os.cpu_count() or 4
                    try:
                        proc = subprocess.Popen(
                            [sys.executable, script, "--source", str(dstp), "-j", str(jobs)],
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
                    # 1) Resize existing front covers to 100x100
                    _run_script([sys.executable, str(SCRIPTS_DIR / 'embedd_resize.py'), '--folder', str(dstp), '--size', '100x100'], 'Cover resize')
                    if self._stop_flag:
                        pass
                    else:
                        # 2) Export lyrics to sidecar files
                        _run_script([sys.executable, str(SCRIPTS_DIR / 'lyrics_local.py'), '--music-dir', str(dstp), '--lyrics-subdir', 'Lyrics', '--ext', '.lrc'], 'Lyrics export')
                    if not self._stop_flag:
                        # 3) Promote/resize image to cover where no type 3 exists
                        _run_script([sys.executable, str(SCRIPTS_DIR / 'embed_resize_no_cover.py'), '--folder', str(dstp), '--max-size', '100'], 'Promote cover')

                self._queue.put(("log", f"Done. copied={copied}, updated={updated}, skipped={skipped}\n"))
            finally:
                self._queue.put(("end", None))

        self._worker = threading.Thread(target=worker, daemon=True)
        self._worker.start()

    def stop_sync(self):
        self._stop_flag = True
        try:
            self.controller._set_action_status("Sync: stopping...", True)
        except Exception:
            pass

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
                elif kind == 'end':
                    self.run_btn.setEnabled(True)
                    self.timer.stop()
                    try:
                        self.controller._set_action_status("Idle", False)
                    except Exception:
                        pass
                    break
        except queue.Empty:
            pass
