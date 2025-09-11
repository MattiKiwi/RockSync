import os
import io
from logging_utils import ui_log
from PySide6.QtCore import Qt, QTimer, QPoint
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QLineEdit, QPushButton,
    QSplitter, QTreeWidget, QTreeWidgetItem, QTextEdit, QFileDialog, QMenu,
    QDialog, QFormLayout, QComboBox, QMessageBox, QInputDialog
)


class ExplorerPane(QWidget):
    def __init__(self, controller, parent):
        super().__init__(parent)
        self.controller = controller
        self.cover_pixmap = None
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)

        top = QHBoxLayout()
        top.addWidget(QLabel("Path:"))
        self.explorer_path = QLineEdit(self.controller.settings.get("music_root", ""))
        top.addWidget(self.explorer_path, 1)
        use_btn = QPushButton("Use Music Root")
        use_btn.clicked.connect(lambda: self._set_path(self.controller.settings.get('music_root')))
        top.addWidget(use_btn)
        browse_btn = QPushButton("Browse")
        browse_btn.clicked.connect(self._browse)
        top.addWidget(browse_btn)
        up_btn = QPushButton("Up")
        up_btn.clicked.connect(self.go_up)
        top.addWidget(up_btn)
        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(lambda: self.navigate(self.explorer_path.text()))
        top.addWidget(refresh_btn)
        import_btn = QPushButton("Import…")
        import_btn.clicked.connect(self._on_import_music)
        top.addWidget(import_btn)
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
        from PySide6.QtWidgets import QTreeWidget as _QTreeWidget, QTreeWidgetItem as _QTreeWidgetItem
        self.playlist_list = _QTreeWidget(); self.playlist_list.setColumnCount(2)
        self.playlist_list.setHeaderLabels(["#", "Track"])
        self.playlist_list.setAlternatingRowColors(True)
        self.playlist_list.itemDoubleClicked.connect(self._on_playlist_open)
        pl_v.addWidget(self.playlist_list, 1)
        rlayout.addWidget(self.playlist_panel, 1)
        splitter.addWidget(right)

        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)

        self.navigate(self.explorer_path.text())

    # ----- Import dialog -----
    def _on_import_music(self):
        dlg = ImportDialog(self)
        if dlg.exec_() != QDialog.Accepted:
            return
        params = dlg.get_values()
        files = params.get('files') or []
        if not files:
            return
        music_root = self.controller.settings.get('music_root', '')
        if not music_root:
            QMessageBox.warning(self, "No Music Root", "Please set Music root in Settings first.")
            return
        try:
            if params['mode'] == 'Album':
                # Import each file into its own Artist/Album based on its tags
                fallback_artist = params.get('artist', '').strip()
                fallback_album = params.get('album', '').strip()
                dests = set()
                total = 0
                for src in files:
                    a, al = self._extract_artist_album(src)
                    artist = a or fallback_artist or 'Unknown Artist'
                    album = al or fallback_album or 'Unknown Album'
                    artist = self._safe_part(artist)
                    album = self._safe_part(album)
                    dest = os.path.join(music_root, 'Albums', artist, album)
                    os.makedirs(dest, exist_ok=True)
                    copied = self._copy_files([src], dest)
                    total += len(copied)
                    if copied:
                        dests.add(dest)
                # Finalize
                if total == 0:
                    QMessageBox.warning(self, "Import", "No files were imported.")
                else:
                    if len(dests) == 1:
                        dest = list(dests)[0]
                        QMessageBox.information(self, "Import Complete", f"Imported {total} files to\n{dest}")
                        self.navigate(dest)
                    else:
                        QMessageBox.information(self, "Import Complete", f"Imported {total} files across {len(dests)} album folders under\n{os.path.join(music_root, 'Albums')}")
                        self.navigate(os.path.join(music_root, 'Albums'))
            elif params['mode'] == 'Playlist':
                name = params.get('playlist', '').strip()
                sub = params.get('subfolder', '').strip()
                base = os.path.join(music_root, 'Playlists')
                # Copy files into Playlists[/subfolder]/name/
                dest_dir = os.path.join(base, sub, name) if sub else os.path.join(base, name)
                os.makedirs(dest_dir, exist_ok=True)
                copied = self._copy_files(files, dest_dir)
                QMessageBox.information(self, "Import Complete", f"Imported {len(copied)} files to\n{dest_dir}")
                self.navigate(dest_dir)
            else:  # Track
                dest = os.path.join(music_root, 'Tracks')
                os.makedirs(dest, exist_ok=True)
                copied = self._copy_files(files, dest)
                QMessageBox.information(self, "Import Complete", f"Imported {len(copied)} files to\n{dest}")
                self.navigate(dest)
        except Exception as e:
            QMessageBox.critical(self, "Import Error", f"Failed to import: {e}")

    def _extract_artist_album(self, file_path):
        """Return (artist, album) from tags; tries albumartist then artist."""
        try:
            from mutagen import File as MFile
            easy = MFile(file_path, easy=True)
            tags = getattr(easy, 'tags', None) or {}
            if hasattr(tags, 'get'):
                def pick(v):
                    if isinstance(v, list) and v:
                        return str(v[0]).strip()
                    if isinstance(v, str):
                        return v.strip()
                    return ''
                artist = pick(tags.get('albumartist')) or pick(tags.get('artist'))
                album = pick(tags.get('album'))
                return artist, album
        except Exception:
            pass
        return '', ''

    @staticmethod
    def _safe_part(name: str) -> str:
        # Sanitize path components to avoid separator issues
        bad = ['/', '\\', ':']
        s = name.strip() or 'Unknown'
        for b in bad:
            s = s.replace(b, '_')
        return s

    def _copy_files(self, files, dest_dir):
        import shutil
        copied = []
        for src in files:
            try:
                base = os.path.basename(src)
                name, ext = os.path.splitext(base)
                target = os.path.join(dest_dir, base)
                i = 1
                while os.path.exists(target):
                    target = os.path.join(dest_dir, f"{name}_{i}{ext}")
                    i += 1
                shutil.copy2(src, target)
                copied.append(target)
            except Exception:
                continue
        return copied

    def _write_m3u8(self, m3u_path, files):
        root = os.path.dirname(m3u_path)
        lines = []
        for f in files:
            try:
                rel = os.path.relpath(f, start=root)
            except Exception:
                rel = f
            lines.append(rel.replace('\\', '/'))
        with open(m3u_path, 'w', encoding='utf-8') as fh:
            fh.write("\n".join(lines))

    # Navigation helpers
    def _browse(self):
        path = QFileDialog.getExistingDirectory(self, "Select folder", self.explorer_path.text() or os.getcwd())
        if path:
            ui_log('explorer_browse', selected=path)
            self._set_path(path)

    def _set_path(self, path):
        if not path:
            return
        self.explorer_path.setText(path)
        self.navigate(path)

    def go_up(self):
        cur = self.explorer_path.text().strip()
        parent = os.path.dirname(cur.rstrip(os.sep)) or cur
        if parent and os.path.isdir(parent):
            ui_log('explorer_up', from_path=cur, to_path=parent)
            self._set_path(parent)

    def navigate(self, path):
        path = os.path.abspath(path)
        if not os.path.isdir(path):
            return
        ui_log('explorer_navigate', path=path)
        self.explorer_path.setText(path)
        self.tree.clear()
        try:
            with os.scandir(path) as it:
                dirs, files = [], []
                for entry in it:
                    try:
                        st = entry.stat()
                        info = (entry.name, 'Folder' if entry.is_dir() else 'File', st.st_size, st.st_mtime, entry.path)
                        (dirs if entry.is_dir() else files).append(info)
                    except Exception:
                        continue
            dirs.sort(key=lambda x: x[0].lower()); files.sort(key=lambda x: x[0].lower())
            for name, typ, size, mtime, full in dirs + files:
                item = QTreeWidgetItem([
                    name,
                    typ,
                    self._fmt_size(size),
                    self._fmt_mtime(mtime),
                    '…' if typ == 'Folder' else ''
                ])
                item.setData(0, Qt.UserRole, full)
                self.tree.addTopLevelItem(item)
        except Exception:
            pass

    # Events
    def _on_item_open(self, item, column):
        full = item.data(0, Qt.UserRole)
        if os.path.isdir(full):
            ui_log('explorer_open_folder', path=full)
            self.navigate(full)
        else:
            ui_log('explorer_show_file', path=full)
            self.show_info(full)

    def _on_item_select(self):
        items = self.tree.selectedItems()
        if not items:
            return
        full = items[0].data(0, Qt.UserRole)
        if os.path.isfile(full):
            self.show_info(full)

    def _on_context_menu(self, pos: QPoint):
        item = self.tree.itemAt(pos)
        if not item:
            return
        typ = item.text(1)
        if typ != 'Folder':
            return
        folder_path = item.data(0, Qt.UserRole)
        menu = QMenu(self)
        any_added = False
        for task in self.controller.tasks:
            if self.controller.task_accepts_folder(task):
                any_added = True
                action = menu.addAction(f"Use: {task['label']}")
                action.triggered.connect(lambda _, t=task: self.controller.open_quick_task(t, folder_path))
        if not any_added:
            a = menu.addAction("No folder tasks found")
            a.setEnabled(False)
        menu.exec_(self.tree.viewport().mapToGlobal(pos))
        ui_log('explorer_right_click', folder_path=folder_path)

    # Info panel
    def show_info(self, path):
        # Reset views and toggle depending on selection type
        self._toggle_playlist_mode(False)
        self.cover_label.setText("No cover")
        self.cover_label.setPixmap(QPixmap())
        self.meta_text.clear()
        self.lyrics_text.clear()

        ext = os.path.splitext(path)[1].lower()
        if ext in {'.m3u8', '.m3u'}:
            self._show_playlist(path)
            return
        supported = {'.flac', '.mp3', '.m4a', '.alac', '.aac', '.ogg', '.opus', '.wav'}
        if ext not in supported:
            self.meta_text.setPlainText(f"Selected: {os.path.basename(path)}\nNot a supported audio file.")
            return
        try:
            from mutagen import File as MFile
            audio = MFile(path)
        except Exception as e:
            self.meta_text.setPlainText(f"Error reading file: {e}")
            return

        # Collect metadata rows as (label, value)
        meta_rows = []
        try:
            try:
                easy = MFile(path, easy=True)
                tags = getattr(easy, 'tags', None) or {}
            except Exception:
                tags = getattr(audio, 'tags', None) or {}
            def is_skip_key(kstr):
                kl = str(kstr).lower()
                if ('lyric' in kl) or ('uslt' in kl) or kl.endswith('©lyr'):
                    return True
                # Skip embedded artwork and pictures
                if ('apic' in kl) or ('covr' in kl) or ('cover' in kl) or ('picture' in kl) or ('pics' in kl):
                    return True
                return False
            # Preferred ordering of common music tags
            preferred_order = [
                'title','artist','album','albumartist','tracknumber','discnumber',
                'date','year','genre','composer','comment'
            ]
            seen_keys = set()
            def norm_val(v):
                if isinstance(v, list):
                    v = "; ".join(str(x) for x in v)
                v = str(v)
                return (v[:500] + '…') if len(v) > 500 else v
            # If we have easy tags, they use human-friendly keys
            if hasattr(tags, 'get'):
                for key in preferred_order:
                    if key in tags and not is_skip_key(key):
                        meta_rows.append((key.title(), norm_val(tags.get(key))))
                        seen_keys.add(key)
                # Add remaining non-lyrics, non-duplicate tags
                for k, v in tags.items():
                    kl = str(k).lower()
                    if kl in seen_keys or is_skip_key(kl):
                        continue
                    meta_rows.append((k.title(), norm_val(v)))
            else:
                # Fallback to raw tags mapping
                for k, v in (tags.items() if hasattr(tags, 'items') else []):
                    if is_skip_key(k):
                        continue
                    meta_rows.append((str(k), norm_val(v)))
        except Exception:
            pass
        # Technical info
        try:
            if getattr(audio, 'info', None):
                info = audio.info
                # Duration
                if getattr(info, 'length', None):
                    secs = int(info.length)
                    meta_rows.insert(0, ("Duration", f"{secs//60}:{secs%60:02d}"))
                # Bitrate (kbps)
                br = getattr(info, 'bitrate', None)
                if isinstance(br, (int, float)) and br > 0:
                    meta_rows.append(("Bitrate", f"{int(br)//1000} kbps"))
                # Sample rate
                sr = getattr(info, 'sample_rate', getattr(info, 'samplerate', None))
                if isinstance(sr, (int, float)) and sr > 0:
                    meta_rows.append(("Sample Rate", f"{int(sr)} Hz"))
                # Channels
                ch = getattr(info, 'channels', None)
                if isinstance(ch, int) and ch > 0:
                    meta_rows.append(("Channels", str(ch)))
                # Bits per sample (lossless)
                bps = getattr(info, 'bits_per_sample', getattr(info, 'bits_per_sample', None))
                if isinstance(bps, int) and bps > 0:
                    meta_rows.append(("Bits/Sample", str(bps)))
        except Exception:
            pass

        # Codec/container class
        try:
            cname = audio.__class__.__name__
            if cname:
                meta_rows.append(("Format", cname))
        except Exception:
            pass

        # Render as a simple HTML table for nicer display
        if not meta_rows:
            self.meta_text.setPlainText("No tags found.")
        else:
            html = [
                '<html><head><style>'
                'table{border-collapse:collapse; width:100%;}'
                'th,td{padding:4px 6px; vertical-align:top;}'
                'th{width:28%; text-align:right; color:#555;}'
                'tr:nth-child(even){background:#f6f6f6;}'
                '</style></head><body>'
                '<table>'
            ]
            for label, value in meta_rows:
                safe_label = self._escape_html(label)
                safe_value = self._escape_html(value).replace('\n', '<br>')
                html.append(f'<tr><th>{safe_label}</th><td><div>{safe_value}</div></td></tr>')
            html.append('</table></body></html>')
            self.meta_text.setHtml("".join(html))

        # Lyrics
        lyrics_text = self._extract_lyrics_text(audio, path)
        if lyrics_text:
            if len(lyrics_text) > 5000:
                lyrics_text = lyrics_text[:5000] + '\n…'
            self.lyrics_text.setPlainText(lyrics_text)
        else:
            self.lyrics_text.setPlainText("No lyrics found.")

        # Cover
        img_bytes = self._extract_cover_bytes(audio)
        if not img_bytes:
            cpath = os.path.join(os.path.dirname(path), 'cover.jpg')
            if os.path.exists(cpath):
                try:
                    with open(cpath, 'rb') as f:
                        img_bytes = f.read()
                except Exception:
                    img_bytes = None
        if img_bytes:
            if self._set_cover_from_pillow(img_bytes):
                return
            pix = QPixmap()
            if pix.loadFromData(img_bytes):
                self.cover_label.setPixmap(pix.scaled(300, 300, Qt.KeepAspectRatio, Qt.SmoothTransformation))
                self.cover_label.setText("")
            else:
                self.cover_label.setText("Cover present (install Pillow to display)")

    # Playlist helpers
    def _toggle_playlist_mode(self, on: bool):
        self.info_panel.setVisible(not on)
        self.playlist_panel.setVisible(on)

    def _show_playlist(self, m3u_path: str):
        self._toggle_playlist_mode(True)
        self.playlist_list.clear()
        base_dir = os.path.dirname(m3u_path)
        entries = []
        titles = {}
        try:
            with open(m3u_path, 'r', encoding='utf-8', errors='ignore') as fh:
                last_title = None
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    if line.startswith('#'):
                        if line.upper().startswith('#EXTINF:'):
                            # Format: #EXTINF:duration,Artist - Title
                            parts = line.split(',', 1)
                            if len(parts) == 2:
                                last_title = parts[1].strip()
                        continue
                    # Non-comment line: a file path (relative or absolute)
                    p = line
                    if not os.path.isabs(p):
                        p = os.path.normpath(os.path.join(base_dir, p))
                    entries.append(p)
                    if last_title:
                        titles[p] = last_title
                        last_title = None
        except Exception as e:
            self.playlist_list.setHeaderLabels(["#", f"Error reading playlist: {e}"])
            return
        # Populate list
        for idx, p in enumerate(entries, start=1):
            label = titles.get(p) or os.path.basename(p)
            it = QTreeWidgetItem([str(idx), label])
            it.setData(0, Qt.UserRole, p)
            self.playlist_list.addTopLevelItem(it)
        if not entries:
            it = QTreeWidgetItem(["", "(Empty playlist)"])
            self.playlist_list.addTopLevelItem(it)

    def _on_playlist_open(self, item, column):
        p = item.data(0, Qt.UserRole)
        if p and os.path.isfile(p):
            # Switch back to info view and show file metadata
            self._toggle_playlist_mode(False)
            self.show_info(p)

    @staticmethod
    def _escape_html(s: str) -> str:
        try:
            return (
                s.replace('&', '&amp;')
                 .replace('<', '&lt;')
                 .replace('>', '&gt;')
                 .replace('"', '&quot;')
                 .replace("'", '&#39;')
            )
        except Exception:
            return str(s)

    def _set_cover_from_pillow(self, img_bytes: bytes) -> bool:
        try:
            from PIL import Image
            im = Image.open(io.BytesIO(img_bytes)).convert('RGB')
            im.thumbnail((300, 300))
            data = io.BytesIO()
            im.save(data, format='PNG')
            data.seek(0)
            pix = QPixmap()
            if pix.loadFromData(data.getvalue()):
                self.cover_label.setPixmap(pix)
                self.cover_label.setText("")
                return True
        except Exception:
            pass
        return False

    def _extract_cover_bytes(self, audio):
        try:
            cname = audio.__class__.__name__.lower()
            if 'flac' in cname and hasattr(audio, 'pictures') and audio.pictures:
                pics = sorted(audio.pictures, key=lambda p: 0 if getattr(p, 'type', None) == 3 else 1)
                return pics[0].data if pics else None
            if 'mp3' in cname and getattr(audio, 'tags', None):
                for k, v in audio.tags.items():
                    if str(k).startswith('APIC'):
                        return getattr(v, 'data', None)
            if ('mp4' in cname or 'm4a' in cname) and hasattr(audio, 'tags') and 'covr' in audio.tags:
                covr = audio.tags['covr']
                if isinstance(covr, list) and covr:
                    return bytes(covr[0])
        except Exception:
            return None
        return None

    def _extract_lyrics_text(self, audio, path):
        try:
            if getattr(audio, 'tags', None):
                for k, v in audio.tags.items():
                    key = str(k).lower()
                    if 'lyric' in key or 'uslt' in key or key.endswith('©lyr'):
                        try:
                            return v.text if hasattr(v, 'text') else (v[0] if isinstance(v, list) else str(v))
                        except Exception:
                            return str(v)
        except Exception:
            pass
        try:
            stem = os.path.splitext(os.path.basename(path))[0]
            base_dir = os.path.dirname(path)
            candidates = [
                os.path.join(base_dir, f"{stem}{self.controller.settings.get('lyrics_ext', '.lrc')}"),
                os.path.join(base_dir, self.controller.settings.get('lyrics_subdir', 'Lyrics'), f"{stem}{self.controller.settings.get('lyrics_ext', '.lrc')}")
            ]
            for p in candidates:
                if os.path.exists(p):
                    with open(p, 'r', encoding='utf-8', errors='ignore') as f:
                        return f.read()
        except Exception:
            pass
        return ''

    @staticmethod
    def _fmt_size(n):
        for unit in ['B','KB','MB','GB','TB']:
            if n < 1024.0:
                return f"{n:.0f} {unit}"
            n /= 1024.0
        return f"{n:.0f} PB"

    @staticmethod
    def _fmt_mtime(ts):
        import datetime as _dt
        try:
            return _dt.datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M')
        except Exception:
            return ''

class ImportDialog(QDialog):
    def __init__(self, parent: ExplorerPane):
        super().__init__(parent)
        self.setWindowTitle("Import Music into Library")
        self.files = []
        self._build_ui()

    def _build_ui(self):
        from PySide6.QtWidgets import QDialogButtonBox
        v = QVBoxLayout(self)
        form = QFormLayout()
        v.addLayout(form)

        # Files/folder selector
        files_row = QWidget(); h = QHBoxLayout(files_row); h.setContentsMargins(0,0,0,0)
        self.files_edit = QLineEdit(); self.files_edit.setReadOnly(True)
        b_files = QPushButton("Select Files…"); b_files.clicked.connect(self._pick_files)
        b_folder = QPushButton("Select Folder…"); b_folder.clicked.connect(self._pick_folder)
        h.addWidget(self.files_edit, 1); h.addWidget(b_files); h.addWidget(b_folder)
        form.addRow("Files/Folder", files_row)

        # Mode
        self.mode = QComboBox(); self.mode.addItems(["Album", "Playlist", "Track"])
        self.mode.currentTextChanged.connect(self._on_mode_changed)
        form.addRow("Import as", self.mode)

        # Album fields
        self.album_artist = QLineEdit(); self.album_artist.setPlaceholderText("Auto-detected if possible")
        form.addRow("Artist", self.album_artist)
        self.album_title = QLineEdit(); self.album_title.setPlaceholderText("Auto-detected if possible")
        form.addRow("Album", self.album_title)

        # Playlist fields
        self.playlist_name = QLineEdit(); form.addRow("Playlist name", self.playlist_name)
        self.playlist_sub = QLineEdit(); form.addRow("Subfolder (optional)", self.playlist_sub)

        # Buttons
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self._on_accept)
        btns.rejected.connect(self.reject)
        v.addWidget(btns)

        self._update_visibility()

    def _pick_files(self):
        exts = ['*.flac','*.mp3','*.m4a','*.alac','*.aac','*.ogg','*.opus','*.wav']
        files, _ = QFileDialog.getOpenFileNames(self, "Select music files", os.getcwd(), f"Audio Files ({' '.join(exts)})")
        if files:
            ui_log('import_select_files', count=len(files))
            self.files = files
            self.files_edit.setText(f"{len(files)} file(s) selected")
            # Try to auto-fill album/artist when importing as Album
            if self.mode.currentText() == 'Album':
                self._autofill_album_fields()

    def _pick_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Select folder with music", os.getcwd())
        if not folder:
            return
        ui_log('import_select_folder', folder=folder)
        files = self._collect_audio_files(folder)
        self.files = files
        self.files_edit.setText(f"{len(files)} file(s) from folder")
        if self.mode.currentText() == 'Album':
            self._autofill_album_fields()

    def _collect_audio_files(self, root_dir):
        exts = {'.flac','.mp3','.m4a','.alac','.aac','.ogg','.opus','.wav'}
        out = []
        for base, _dirs, fnames in os.walk(root_dir):
            for fn in fnames:
                try:
                    if os.path.splitext(fn)[1].lower() in exts:
                        out.append(os.path.join(base, fn))
                except Exception:
                    continue
        return out

    def _update_visibility(self):
        mode = self.mode.currentText()
        show_album = (mode == 'Album')
        show_playlist = (mode == 'Playlist')
        self.album_artist.setVisible(show_album)
        self.album_title.setVisible(show_album)
        self.playlist_name.setVisible(show_playlist)
        self.playlist_sub.setVisible(show_playlist)

    def _on_mode_changed(self, _):
        self._update_visibility()
        if self.mode.currentText() == 'Album' and self.files:
            self._autofill_album_fields()

    def _autofill_album_fields(self):
        try:
            from mutagen import File as MFile
        except Exception:
            return
        artists = []
        albums = []
        for p in (self.files or []):
            try:
                easy = MFile(p, easy=True)
                tags = getattr(easy, 'tags', None) or {}
                if hasattr(tags, 'get'):
                    a = tags.get('albumartist') or tags.get('artist')
                    al = tags.get('album')
                    def pick(v):
                        if isinstance(v, list) and v:
                            return str(v[0]).strip()
                        if isinstance(v, str):
                            return v.strip()
                        return ''
                    a = pick(a)
                    al = pick(al)
                    if a:
                        artists.append(a)
                    if al:
                        albums.append(al)
            except Exception:
                continue
        def most_common(lst):
            if not lst:
                return ''
            from collections import Counter
            return Counter(lst).most_common(1)[0][0]
        if not self.album_artist.text().strip() and artists:
            self.album_artist.setText(most_common(artists))
        if not self.album_title.text().strip() and albums:
            self.album_title.setText(most_common(albums))

    def _on_accept(self):
        mode = self.mode.currentText()
        if not self.files:
            QMessageBox.warning(self, "No files", "Please select one or more audio files.")
            return
        if mode == 'Album':
            # Try auto-fill once more if empty
            if not self.album_artist.text().strip() or not self.album_title.text().strip():
                self._autofill_album_fields()
            # If still missing, prompt using first file as context
            if not self.album_artist.text().strip() or not self.album_title.text().strip():
                for p in self.files:
                    base = os.path.basename(p)
                    if not self.album_artist.text().strip():
                        txt, ok = QInputDialog.getText(self, "Missing Artist", f"Enter Artist for {base}:")
                        if ok and txt.strip():
                            self.album_artist.setText(txt.strip())
                    if not self.album_title.text().strip():
                        txt, ok = QInputDialog.getText(self, "Missing Album", f"Enter Album for {base}:")
                        if ok and txt.strip():
                            self.album_title.setText(txt.strip())
                    if self.album_artist.text().strip() and self.album_title.text().strip():
                        break
            if not self.album_artist.text().strip() or not self.album_title.text().strip():
                QMessageBox.warning(self, "Missing info", "Please provide Artist and Album names.")
                return
        if mode == 'Playlist':
            if not self.playlist_name.text().strip():
                QMessageBox.warning(self, "Missing name", "Please provide a playlist name.")
                return
        self.accept()
        try:
            ui_log('import_accept', mode=mode, files=len(self.files or []),
                   artist=self.album_artist.text().strip(), album=self.album_title.text().strip(),
                   playlist=self.playlist_name.text().strip(), subfolder=self.playlist_sub.text().strip())
        except Exception:
            pass

    def get_values(self):
        mode = self.mode.currentText()
        return {
            'mode': mode,
            'files': list(self.files),
            'artist': self.album_artist.text().strip(),
            'album': self.album_title.text().strip(),
            'playlist': self.playlist_name.text().strip(),
            'subfolder': self.playlist_sub.text().strip(),
        }
