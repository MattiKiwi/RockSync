import os
import sys
import shlex
import uuid
from PySide6.QtCore import Qt, QProcess
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QTabWidget, QListWidget, QListWidgetItem,
    QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QGroupBox, QFormLayout, QLineEdit,
    QSpinBox, QCheckBox, QComboBox, QPlainTextEdit, QFileDialog, QMessageBox, QDialog
)

from core import ROOT, cmd_exists
from settings_store import load_settings, save_settings
from logging_utils import setup_logging, ui_log
from tasks_registry import get_tasks
from ui.explorer_pane import ExplorerPane
from ui.tracks_pane import TracksPane
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
        layout = QVBoxLayout(central)

        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)

        # Tasks tab
        self.run_tab = QWidget()
        self.tabs.addTab(self.run_tab, "Tasks")
        self._build_run_tab(self.run_tab)

        # Explorer tab
        self.explore_tab = QWidget()
        self.tabs.addTab(self.explore_tab, "Explorer")
        ex_layout = QVBoxLayout(self.explore_tab)
        self.explorer = ExplorerPane(self, self.explore_tab)
        ex_layout.addWidget(self.explorer)

        # Tracks tab
        self.tracks_tab = QWidget()
        self.tabs.addTab(self.tracks_tab, "Tracks")
        tr_layout = QVBoxLayout(self.tracks_tab)
        self.tracks = TracksPane(self, self.tracks_tab)
        tr_layout.addWidget(self.tracks)

        # Settings tab
        self.settings_tab = QWidget()
        self.tabs.addTab(self.settings_tab, "Settings")
        self._build_settings_tab(self.settings_tab)

        self.statusBar().showMessage(f"Music root: {self.settings.get('music_root')}")

        # Apply theme after UI exists
        apply_theme(QApplication.instance(), self.settings.get('theme_file', 'system'))

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

        self.debug_cb = QCheckBox("Enable verbose debug logging (writes to app/debug.log)")
        self.debug_cb.setChecked(bool(self.settings.get("debug", False)))
        form.addRow("Debug", self.debug_cb)

        # Theme selector
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
        self.settings["music_root"] = self.set_music_root.text()
        self.settings["lyrics_subdir"] = self.set_lyrics_subdir.text()
        self.settings["lyrics_ext"] = self.set_lyrics_ext.text()
        self.settings["cover_size"] = self.set_cover_size.text()
        self.settings["cover_max"] = int(self.set_cover_max.value())
        self.settings["jobs"] = int(self.set_jobs.value())
        self.settings["genius_token"] = self.set_genius.text()
        self.settings["lastfm_key"] = self.set_lastfm.text()
        self.settings["debug"] = bool(self.debug_cb.isChecked())
        self.settings["theme_file"] = self.theme_box.currentText()
        if save_settings(self.settings):
            self.statusBar().showMessage(f"Music root: {self.settings.get('music_root')}")
            QMessageBox.information(self, "Settings", "Settings saved.")
            self._reconfigure_logging()
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
        self.theme_box.setCurrentText(self.settings.get('theme_file', 'system'))
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

    # --------------- Tasks tab ---------------
    def _build_run_tab(self, parent: QWidget):
        layout = QHBoxLayout(parent)

        left = QVBoxLayout()
        layout.addLayout(left, 0)
        left.addWidget(QLabel("Tasks"))
        self.task_list = QListWidget(); left.addWidget(self.task_list, 1)
        self.tasks = get_tasks()
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
        self.run_btn = QPushButton("Run"); self.run_btn.clicked.connect(self.run_task); actions_row.addWidget(self.run_btn)
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
        parts = [py, script]
        for spec in task.get('args', []):
            key = spec.get('key')
            typ = spec.get('type')
            w = self.form_widgets.get(key)
            val = ''
            if typ == 'bool':
                val = w.isChecked()
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
        self.proc.finished.connect(on_finished)

        # Start process
        self.proc.start("/bin/sh", ["-c", cmd])

    def stop_task(self):
        if self.proc is not None and self.proc.state() != QProcess.NotRunning:
            try:
                self.proc.terminate()
                self.append_output("\n[Terminated]\n")
                ui_log('stop_task')
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
            self._start_process(cmd)
            if close_cb.isChecked():
                dlg.accept()

        runb.clicked.connect(do_run)
        cancelb.clicked.connect(dlg.reject)
        dlg.exec()

    def _build_cmd_with_values(self, task, values):
        py = shlex.quote(sys.executable)
        script = shlex.quote(str(task["script"]))
        parts = [py, script]
        for spec in task.get('args', []):
            key = spec.get('key')
            typ = spec.get('type')
            val = values.get(key, '')
            if typ == 'bool':
                if val:
                    parts.append(key)
                continue
            if not str(key).startswith('-'):
                parts.append(shlex.quote(str(val)))
            else:
                parts.extend([key, shlex.quote(str(val))])
        return " ".join(parts)

    def _start_process(self, cmd):
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
        self.proc.finished.connect(on_finished)
        self.proc.start("/bin/sh", ["-c", cmd])


def run():
    app = QApplication.instance() or QApplication(sys.argv)
    win = AppWindow()
    win.show()
    app.exec()
