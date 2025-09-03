import os
import io
from logging_utils import ui_log
from PySide6.QtCore import Qt, QTimer, QPoint
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QLabel, QLineEdit, QPushButton,
    QSplitter, QTreeWidget, QTreeWidgetItem, QTextEdit, QFileDialog, QMenu
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
        self.meta_text = QTextEdit()
        self.meta_text.setReadOnly(True)
        rlayout.addWidget(self.meta_text, 1)
        rlayout.addWidget(QLabel("Lyrics (preview)"))
        self.lyrics_text = QTextEdit()
        self.lyrics_text.setReadOnly(True)
        rlayout.addWidget(self.lyrics_text, 1)
        splitter.addWidget(right)

        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)

        self.navigate(self.explorer_path.text())

    # Navigation helpers
    def _browse(self):
        path = QFileDialog.getExistingDirectory(self, "Select folder", self.explorer_path.text() or os.getcwd())
        if path:
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
            self._set_path(parent)

    def navigate(self, path):
        path = os.path.abspath(path)
        if not os.path.isdir(path):
            return
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
            self.navigate(full)
        else:
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
        self.cover_label.setText("No cover")
        self.cover_label.setPixmap(QPixmap())
        self.meta_text.clear()
        self.lyrics_text.clear()

        ext = os.path.splitext(path)[1].lower()
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

        meta_lines = []
        try:
            try:
                easy = MFile(path, easy=True)
                tags = getattr(easy, 'tags', None) or {}
            except Exception:
                tags = getattr(audio, 'tags', None) or {}
            def is_lyrics_key(kstr):
                kl = str(kstr).lower(); return ('lyric' in kl) or ('uslt' in kl) or kl.endswith('©lyr')
            for k, v in (tags.items() if hasattr(tags, 'items') else []):
                if is_lyrics_key(k):
                    continue
                if isinstance(v, list):
                    val = "; ".join(str(x) for x in v)
                else:
                    val = str(v)
                if len(val) > 500:
                    val = val[:500] + '…'
                meta_lines.append(f"{k}: {val}")
        except Exception:
            pass
        try:
            if getattr(audio, 'info', None) and getattr(audio.info, 'length', None):
                secs = int(audio.info.length)
                meta_lines.insert(0, f"Duration: {secs//60}:{secs%60:02d}")
        except Exception:
            pass
        self.meta_text.setPlainText("\n".join(meta_lines) or "No tags found.")

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
