from __future__ import annotations
import os
import shlex
import sys
from typing import Any, Dict, List, Optional

from PySide6.QtCore import Qt, QTimer, QProcess
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QComboBox, QTableWidget, QTableWidgetItem, QSpinBox, QFileDialog, QGroupBox,
    QCheckBox, QMessageBox, QDialog, QFormLayout, QAbstractItemView, QPlainTextEdit
)

from core import ROOT, SCRIPTS_DIR
from settings_store import load_settings, save_settings
import json
import re
import subprocess


class YouTubePane(QWidget):
    """Browse YouTube (search, playlists, feeds) and download via yt-dlp.

    - Uses yt-dlp Python API to browse without downloading.
    - Spawns a background process to run the downloader script for selections.
    - Supports cookies from browser or cookies.txt, and download profiles/presets.
    """

    COLS = ("title", "channel", "duration", "upload_date", "url")

    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.proc: Optional[QProcess] = None
        self.settings = load_settings()
        self._build_ui()
        self._load_profiles()

    # ---------- UI ----------
    def _build_ui(self):
        root = QVBoxLayout(self)

        # Top row: search and playlist URL
        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Search:"))
        self.search_edit = QLineEdit(); self.search_edit.setPlaceholderText("e.g. guns n' roses live")
        row1.addWidget(self.search_edit, 1)
        self.limit_spin = QSpinBox(); self.limit_spin.setRange(1, 500); self.limit_spin.setValue(25)
        row1.addWidget(QLabel("Limit:")); row1.addWidget(self.limit_spin)
        btn_search = QPushButton("Search"); btn_search.clicked.connect(self.on_search)
        row1.addWidget(btn_search)

        row1.addSpacing(16)
        row1.addWidget(QLabel("Playlist URL:"))
        self.playlist_edit = QLineEdit(); self.playlist_edit.setPlaceholderText("https://www.youtube.com/playlist?list=…")
        row1.addWidget(self.playlist_edit, 1)
        btn_pl = QPushButton("Open"); btn_pl.clicked.connect(self.on_open_playlist)
        row1.addWidget(btn_pl)
        root.addLayout(row1)

        # Row 2: categories (auth) + cookies
        row2 = QHBoxLayout()
        self.btn_home = QPushButton("Home")
        self.btn_watchlater = QPushButton("Watch Later")
        self.btn_liked = QPushButton("Liked")
        self.btn_subs = QPushButton("Subscriptions")
        self.btn_mypls = QPushButton("My Playlists")
        for b in (self.btn_home, self.btn_watchlater, self.btn_liked, self.btn_subs, self.btn_mypls):
            b.clicked.connect(self.on_category)
            row2.addWidget(b)

        row2.addStretch(1)
        self.cookies_cb = QCheckBox("Use browser cookies")
        self.cookies_cb.setToolTip("Enable to access private feeds like Home, Watch Later, Liked, Subscriptions.")
        self.cookies_cb.setChecked(bool(self.settings.get('youtube_use_cookies', False)))
        row2.addWidget(self.cookies_cb)
        self.browser_combo = QComboBox(); self.browser_combo.addItems(["firefox", "chrome", "edge", "brave"])  # common options
        self.browser_combo.setCurrentText(self.settings.get('youtube_cookie_browser', 'firefox'))
        row2.addWidget(self.browser_combo)
        row2.addWidget(QLabel("or cookies.txt:"))
        self.cookies_path = QLineEdit(self.settings.get('youtube_cookie_file', ''))
        row2.addWidget(self.cookies_path, 1)
        b_cf = QPushButton("Browse"); b_cf.clicked.connect(self._browse_cookie)
        row2.addWidget(b_cf)
        root.addLayout(row2)

        # Results table
        self.table = QTableWidget(0, len(self.COLS))
        self.table.setHorizontalHeaderLabels([c.replace('_', ' ').title() for c in self.COLS])
        self.table.setAlternatingRowColors(True)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        root.addWidget(self.table, 1)

        # Download controls
        dl_group = QGroupBox("Download")
        dl = QHBoxLayout(dl_group)
        dl.addWidget(QLabel("Destination:"))
        self.dest_edit = QLineEdit(self.settings.get('youtube_default_dest', self.controller.settings.get('music_root', '')))
        dl.addWidget(self.dest_edit, 1)
        b_dest = QPushButton("Browse"); b_dest.clicked.connect(self._browse_dest)
        dl.addWidget(b_dest)
        dl.addSpacing(12)
        dl.addWidget(QLabel("Profile/Preset:"))
        self.profile_combo = QComboBox(); self.profile_combo.setMinimumWidth(220)
        dl.addWidget(self.profile_combo)
        b_edit_prof = QPushButton("Edit Profiles…"); b_edit_prof.clicked.connect(self._edit_profiles)
        dl.addWidget(b_edit_prof)
        dl.addStretch(1)
        self.btn_download = QPushButton("Download Selected")
        self.btn_download.setProperty("accent", True)
        self.btn_download.clicked.connect(self.on_download_selected)
        dl.addWidget(self.btn_download)
        root.addWidget(dl_group)

        # Status
        self.status = QLabel("")
        root.addWidget(self.status)

        # Browse process state for yt_browse.py
        self._browse_proc: Optional[QProcess] = None
        self._browse_buf: str = ''

    # ---------- Helpers ----------
    def _cookie_args(self) -> Dict[str, Optional[str]]:
        use = bool(self.cookies_cb.isChecked())
        cfile = (self.cookies_path.text() or '').strip()
        browser = self.browser_combo.currentText().strip()
        return {
            'cookies_from_browser': browser if use and not cfile else None,
            'cookies_file': cfile if use and cfile else None,
        }

    def _browse_cookie(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select cookies.txt", str(ROOT), "cookies.txt (*.txt);;All (*.*)")
        if path:
            self.cookies_path.setText(path)

    def _browse_dest(self):
        path = QFileDialog.getExistingDirectory(self, "Select download folder", self.dest_edit.text() or str(ROOT))
        if path:
            self.dest_edit.setText(path)

    def _set_status(self, text: str):
        self.status.setText(text)

    def _insert_rows(self, rows: List[Dict[str, Any]]):
        for r in rows:
            row = self.table.rowCount()
            self.table.insertRow(row)
            vals = [str(r.get(k, '') or '') for k in self.COLS]
            for col, val in enumerate(vals):
                item = QTableWidgetItem(val)
                if col == len(self.COLS) - 1:
                    # URL column wraps long text less usefully; keep as is
                    pass
                self.table.setItem(row, col, item)

    def _load_profiles(self):
        # Built-in presets
        presets = [
            {"name": "Preset: Best Audio (m4a)", "args": "--extract-audio --audio-format m4a"},
            {"name": "Preset: Best Audio (flac)", "args": "--extract-audio --audio-format flac"},
            {"name": "Preset: Best Video (mp4)", "args": "-f 'bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/best'"},
        ]
        user_profiles: List[Dict[str, str]] = self.settings.get('youtube_profiles', []) or []
        self._profiles = presets + user_profiles
        self.profile_combo.clear()
        for p in self._profiles:
            self.profile_combo.addItem(p.get('name') or '(unnamed)', p)
        # Restore last selection
        last = self.settings.get('youtube_last_profile')
        if isinstance(last, str):
            for i in range(self.profile_combo.count()):
                d = self.profile_combo.itemData(i)
                if isinstance(d, dict) and d.get('name') == last:
                    self.profile_combo.setCurrentIndex(i)
                    break

    def _edit_profiles(self):
        dlg = QDialog(self)
        dlg.setWindowTitle('YouTube Download Profiles')
        v = QVBoxLayout(dlg)
        form = QFormLayout()
        v.addLayout(form)

        select = QComboBox();
        # Only user profiles (exclude built-in presets)
        user_profiles: List[Dict[str, str]] = self.settings.get('youtube_profiles', []) or []
        for p in user_profiles:
            select.addItem(p.get('name') or '(unnamed)', p)
        form.addRow('Select:', select)

        name_edit = QLineEdit();
        args_edit = QPlainTextEdit(); args_edit.setPlaceholderText("e.g. --extract-audio --audio-format flac --embed-metadata")
        form.addRow('Name:', name_edit)
        form.addRow('Args:', args_edit)

        btns = QHBoxLayout(); btns.addStretch(1)
        b_new = QPushButton('New'); b_addopt = QPushButton('Add Option…'); b_save = QPushButton('Save'); b_del = QPushButton('Delete'); b_close = QPushButton('Close')
        btns.addWidget(b_new); btns.addWidget(b_addopt); btns.addWidget(b_save); btns.addWidget(b_del); btns.addWidget(b_close)
        v.addLayout(btns)

        def load_current():
            d = select.currentData()
            if isinstance(d, dict):
                name_edit.setText(d.get('name', ''))
                args_edit.setPlainText(d.get('args', ''))
            else:
                name_edit.setText('')
                args_edit.setPlainText('')

        def refresh_select():
            select.blockSignals(True)
            select.clear()
            for p in (self.settings.get('youtube_profiles', []) or []):
                select.addItem(p.get('name') or '(unnamed)', p)
            select.blockSignals(False)
            load_current()

        def on_new():
            name_edit.setText('My Profile')
            args_edit.setText('--extract-audio --audio-format m4a')
            select.setCurrentIndex(-1)

        def on_save():
            name = (name_edit.text() or '').strip()
            args = (args_edit.toPlainText() or '').strip()
            if not name:
                QMessageBox.warning(dlg, 'Profiles', 'Enter a profile name.')
                return
            profiles = (self.settings.get('youtube_profiles', []) or [])
            # Replace if exists, else append
            replaced = False
            for p in profiles:
                if p.get('name') == name:
                    p['args'] = args
                    replaced = True
                    break
            if not replaced:
                profiles.append({'name': name, 'args': args})
            self.settings['youtube_profiles'] = profiles
            if not save_settings(self.settings):
                QMessageBox.critical(dlg, 'Profiles', 'Could not save settings.')
                return
            refresh_select()
            self._load_profiles()

        def on_delete():
            d = select.currentData()
            if not isinstance(d, dict):
                return
            name = d.get('name')
            profiles = (self.settings.get('youtube_profiles', []) or [])
            profiles = [p for p in profiles if p.get('name') != name]
            self.settings['youtube_profiles'] = profiles
            if not save_settings(self.settings):
                QMessageBox.critical(dlg, 'Profiles', 'Could not save settings.')
                return
            refresh_select()
            self._load_profiles()

        select.currentIndexChanged.connect(lambda _: load_current())
        b_new.clicked.connect(on_new)
        b_save.clicked.connect(on_save)
        b_del.clicked.connect(on_delete)
        b_addopt.clicked.connect(lambda: self._open_option_picker_into(args_edit))
        b_close.clicked.connect(dlg.accept)
        load_current()
        dlg.exec()

    def _open_option_picker_into(self, args_edit: QPlainTextEdit):
        opts = self._load_ytdlp_options()
        # Build dialog
        dlg = QDialog(self)
        dlg.setWindowTitle('Add yt-dlp Option')
        v = QVBoxLayout(dlg)
        search = QLineEdit(); search.setPlaceholderText('Search options…')
        v.addWidget(search)
        table = QTableWidget(0, 2)
        table.setHorizontalHeaderLabels(['Option', 'Description'])
        table.horizontalHeader().setStretchLastSection(True)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        v.addWidget(table, 1)
        form = QFormLayout()
        val_edit = QLineEdit(); val_edit.setPlaceholderText('Value (if required)')
        form.addRow('Value:', val_edit)
        v.addLayout(form)
        btns = QHBoxLayout(); btns.addStretch(1)
        addb = QPushButton('Add'); cancelb = QPushButton('Cancel')
        btns.addWidget(cancelb); btns.addWidget(addb)
        v.addLayout(btns)

        # Populate
        def refresh(filter_text: str = ''):
            ft = filter_text.lower().strip()
            table.setRowCount(0)
            for o in opts:
                text = (o.get('opt','') + ' ' + o.get('metavar','') + ' ' + o.get('desc','')).lower()
                if ft and ft not in text:
                    continue
                r = table.rowCount(); table.insertRow(r)
                table.setItem(r, 0, QTableWidgetItem(o.get('display', o.get('opt', ''))))
                table.setItem(r, 1, QTableWidgetItem(o.get('desc', '')))
                table.setRowHeight(r, 22)
        refresh()

        current_meta = {'has_value': False, 'metavar': ''}

        def update_value_field():
            row = table.currentRow()
            if row < 0:
                val_edit.setEnabled(False); val_edit.setPlaceholderText('Value (if required)'); return
            # Map back to option
            disp = table.item(row, 0).text()
            # Find option by display
            meta = next((o for o in opts if o.get('display') == disp), None)
            hv = bool(meta and meta.get('has_value'))
            current_meta['has_value'] = hv
            current_meta['metavar'] = meta.get('metavar', '') if meta else ''
            val_edit.setEnabled(hv)
            if hv:
                ph = meta.get('metavar') or 'VALUE'
                val_edit.setPlaceholderText(ph)
            else:
                val_edit.setPlaceholderText('No value required')
                val_edit.clear()

        def do_add():
            row = table.currentRow()
            if row < 0:
                return
            disp = table.item(row, 0).text()
            meta = next((o for o in opts if o.get('display') == disp), None)
            if not meta:
                return
            arg = meta.get('opt') or disp.split()[0]
            if meta.get('has_value'):
                val = (val_edit.text() or '').strip()
                if not val:
                    QMessageBox.warning(dlg, 'Option', 'Please enter a value for this option.')
                    return
                part = f"{arg} {val}"
            else:
                part = arg
            existing = (args_edit.toPlainText() or '').strip()
            args_edit.setPlainText((existing + ' ' + part).strip())
            dlg.accept()

        table.currentCellChanged.connect(lambda *_: update_value_field())
        search.textChanged.connect(lambda t: refresh(t))
        addb.clicked.connect(do_add)
        cancelb.clicked.connect(dlg.reject)
        update_value_field()
        dlg.exec()

    def _load_ytdlp_options(self) -> List[Dict[str, str]]:
        if hasattr(self, '_ytdlp_option_cache') and isinstance(self._ytdlp_option_cache, list):
            return self._ytdlp_option_cache
        text = ''
        try:
            cp = subprocess.run(['yt-dlp', '--help'], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=5)
            text = cp.stdout or ''
        except Exception:
            text = ''
        opts: List[Dict[str, str]] = []
        if text:
            # Parse lines like: "  -x, --extract-audio          Convert video files to audio-only"
            # Or:               "      --audio-format FORMAT    Specify audio format: best|aac|flac|mp3|m4a|opus|vorbis|wav"
            lines = text.splitlines()
            current = None
            pat = re.compile(r"^\s*(?:-[\w-],\s*)?(--[\w-]+)(?:[ =]([A-Z][A-Z0-9_-]*))?\s{2,}(.*)$")
            for ln in lines:
                m = pat.match(ln)
                if m:
                    opt, metavar, desc = m.group(1), m.group(2) or '', m.group(3).strip()
                    current = {
                        'opt': opt,
                        'display': (opt + (f" {metavar}" if metavar else '')),
                        'has_value': bool(metavar),
                        'metavar': metavar,
                        'desc': desc,
                    }
                    opts.append(current)
                else:
                    # Continuation of description
                    if current is not None and ln.strip() and not ln.lstrip().startswith('-'):
                        current['desc'] = (current.get('desc','') + ' ' + ln.strip()).strip()
        if not opts:
            # Fallback minimal set if parsing failed
            opts = [
                {'opt':'--extract-audio','display':'--extract-audio','has_value':False,'metavar':'','desc':'Convert video files to audio-only format.'},
                {'opt':'--audio-format','display':'--audio-format FORMAT','has_value':True,'metavar':'FORMAT','desc':'Audio format: best|aac|flac|mp3|m4a|opus|vorbis|wav'},
                {'opt':'-f','display':'-f FORMAT','has_value':True,'metavar':'FORMAT','desc':'Video format selection expression.'},
                {'opt':'--embed-metadata','display':'--embed-metadata','has_value':False,'metavar':'','desc':'Embed metadata in the downloaded files.'},
                {'opt':'--embed-thumbnail','display':'--embed-thumbnail','has_value':False,'metavar':'','desc':'Embed thumbnail in the audio as cover art.'},
                {'opt':'--add-metadata','display':'--add-metadata','has_value':False,'metavar':'','desc':'Write metadata to file.'},
            ]
        self._ytdlp_option_cache = opts
        return opts

    # ---------- Actions ----------
    def on_search(self):
        q = (self.search_edit.text() or '').strip()
        if not q:
            return
        lim = int(self.limit_spin.value())
        args = ["search", q, "--limit", str(lim)]
        self._run_browse(args)

    def on_open_playlist(self):
        url = (self.playlist_edit.text() or '').strip()
        if not url:
            return
        lim = int(self.limit_spin.value())
        args = ["playlist", url, "--limit", str(lim)]
        # playlist may need cookies for private playlists
        cargs = self._cookie_args()
        if cargs.get('cookies_file'):
            args += ["--cookies-file", str(cargs['cookies_file'])]
        elif cargs.get('cookies_from_browser'):
            args += ["--cookies-from-browser", str(cargs['cookies_from_browser'])]
        self._run_browse(args)

    def on_category(self):
        sender = self.sender()
        if not hasattr(sender, 'text'):
            return
        label = str(sender.text()).lower()
        lim = int(self.limit_spin.value())
        cmd_map = {
            'home': 'home',
            'watch later': 'watchlater',
            'liked': 'liked',
            'subscriptions': 'subs',
            'my playlists': 'myplaylists',
        }
        subcmd = cmd_map.get(label)
        if not subcmd:
            return
        args = [subcmd, "--limit", str(lim)]
        cargs = self._cookie_args()
        if cargs.get('cookies_file'):
            args += ["--cookies-file", str(cargs['cookies_file'])]
        elif cargs.get('cookies_from_browser'):
            args += ["--cookies-from-browser", str(cargs['cookies_from_browser'])]
        self._run_browse(args)

    # ---------- Process handling for browse ----------
    def _run_browse(self, args: List[str]):
        # Kill previous browse process
        if self._browse_proc is not None:
            try:
                self._browse_proc.kill()
            except Exception:
                pass
            self._browse_proc = None
        # Clear table and status
        self.table.setRowCount(0)
        self._browse_buf = ''
        py = shlex.quote(sys.executable)
        script = shlex.quote(str(SCRIPTS_DIR / 'yt_browse.py'))
        # Global args must come before subcommand; ensure --format is first
        cmd = " ".join([py, '-u', script, '--format', 'jsonl'] + [shlex.quote(a) for a in args])
        self._set_status('Loading…')
        p = QProcess(self)
        self._browse_proc = p
        p.setWorkingDirectory(str(ROOT))
        p.setProcessChannelMode(QProcess.MergedChannels)
        def on_out():
            data = bytes(p.readAllStandardOutput()).decode('utf-8', errors='ignore')
            if not data:
                return
            self._browse_buf += data
            lines = self._browse_buf.split('\n')
            self._browse_buf = '' if self._browse_buf.endswith('\n') else lines.pop()
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    row = {
                        'title': obj.get('title', ''),
                        'channel': obj.get('channel', ''),
                        'duration': obj.get('duration', ''),
                        'upload_date': obj.get('upload_date', ''),
                        'url': obj.get('url', ''),
                    }
                    self._insert_rows([row])
                except Exception:
                    # non-JSON line: status or error
                    self._set_status(line)
        def on_done(rc, _st):
            if rc != 0 and self.status.text().strip() == 'Loading…':
                self._set_status('No results or failed.')
        p.readyReadStandardOutput.connect(on_out)
        p.finished.connect(on_done)
        p.start("/bin/sh", ["-c", cmd])

    def on_download_selected(self):
        rows = sorted(set(r.row() for r in self.table.selectedIndexes()))
        if not rows:
            QMessageBox.information(self, "YouTube", "Select one or more rows to download.")
            return
        urls = []
        for r in rows:
            it = self.table.item(r, len(self.COLS) - 1)
            if it:
                u = (it.text() or '').strip()
                if u:
                    urls.append(u)
        if not urls:
            QMessageBox.warning(self, "YouTube", "No URLs found in the selected rows.")
            return
        dest = (self.dest_edit.text() or '').strip() or self.controller.settings.get('music_root', '')
        if not dest:
            QMessageBox.warning(self, "YouTube", "Set a download destination.")
            return
        prof = self.profile_combo.currentData()
        args_str = ''
        if isinstance(prof, dict):
            args_str = prof.get('args', '') or ''
            # remember selection
            self.settings['youtube_last_profile'] = prof.get('name')
            self.settings['youtube_default_dest'] = dest
            self.settings['youtube_use_cookies'] = bool(self.cookies_cb.isChecked())
            self.settings['youtube_cookie_browser'] = self.browser_combo.currentText()
            self.settings['youtube_cookie_file'] = self.cookies_path.text()
            save_settings(self.settings)

        # Build command for downloader script
        py = shlex.quote(sys.executable)
        script = shlex.quote(str(SCRIPTS_DIR / 'yt_download.py'))
        parts = [py, '-u', script, '--dest', shlex.quote(dest)]
        # If settings specify an ffmpeg path and profile args don't override, pass it through
        try:
            ffmpeg_path = (self.controller.settings.get('ffmpeg_path') or '').strip()
        except Exception:
            ffmpeg_path = (self.settings.get('ffmpeg_path') or '').strip()
        if ffmpeg_path and ('--ffmpeg-location' not in (args_str or '')):
            parts.extend(['--ffmpeg-location', shlex.quote(ffmpeg_path)])
        if args_str:
            parts.extend(['--args', shlex.quote(args_str)])
        # Cookies
        cargs = self._cookie_args()
        if cargs.get('cookies_file'):
            parts.extend(['--cookies-file', shlex.quote(str(cargs['cookies_file']))])
        elif cargs.get('cookies_from_browser'):
            parts.extend(['--cookies-from-browser', shlex.quote(str(cargs['cookies_from_browser']))])
        # URLs last
        for u in urls:
            parts.append(shlex.quote(u))
        cmd = " ".join(parts)
        # Launch process
        self._start_process(cmd)

    # ---------- Process handling ----------
    def _start_process(self, cmd: str):
        if self.proc is not None:
            try:
                self.proc.kill()
            except Exception:
                pass
            self.proc = None
        self.proc = QProcess(self)
        self.proc.setWorkingDirectory(str(ROOT))
        self.proc.setProcessChannelMode(QProcess.MergedChannels)
        self.proc.readyReadStandardOutput.connect(lambda: self._append_status(bytes(self.proc.readAllStandardOutput()).decode('utf-8', errors='ignore')))
        self.proc.finished.connect(lambda rc, _s: self._append_status(f"\n[Downloader exit {rc}]\n"))
        self._set_status("Starting download…")
        self.proc.start("/bin/sh", ["-c", cmd])

    def _append_status(self, text: str):
        # Keep small last-chunk view in the label; the full output is not displayed to avoid heavy UI
        t = (self.status.text() or '')
        t = (t + "\n" + text).splitlines()[-6:]
        self.status.setText("\n".join(t))
