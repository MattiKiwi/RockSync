import os
import shutil
import threading
import queue
from pathlib import Path
from PySide6.QtCore import QTimer
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QCheckBox, QPlainTextEdit, QFileDialog, QComboBox
)
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
        r4.addStretch(1)
        root.addLayout(r4)

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
        self._append(f"Starting sync\n  src: {src}\n  dst: {dst}\n")
        self.timer.start()

        def worker():
            try:
                inc_exts = {e.lower() for e in self.ext_edit.text().split() if e.startswith('.')}
                srcp = Path(src); dstp = Path(dst)
                copied = 0; skipped = 0; updated = 0
                # Build source map
                src_files = []
                for rootd, _, files in os.walk(src):
                    if self._stop_flag:
                        break
                    for name in files:
                        ext = os.path.splitext(name)[1].lower()
                        if inc_exts and ext not in inc_exts:
                            continue
                        full = Path(rootd) / name
                        rel = full.relative_to(srcp)
                        src_files.append((full, rel))
                # Copy/update
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
                    src_set = {rel.as_posix() for _, rel in src_files}
                    for rootd, _, files in os.walk(dst):
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

                self._queue.put(("log", f"Done. copied={copied}, updated={updated}, skipped={skipped}\n"))
            finally:
                self._queue.put(("end", None))

        self._worker = threading.Thread(target=worker, daemon=True)
        self._worker.start()

    def stop_sync(self):
        self._stop_flag = True

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
                elif kind == 'end':
                    self.run_btn.setEnabled(True)
                    self.timer.stop()
                    break
        except queue.Empty:
            pass
