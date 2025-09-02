import os
import io
import tkinter as tk
from tkinter import ttk
from logging_utils import ui_log


class ExplorerPane(ttk.Frame):
    def __init__(self, controller, parent):
        super().__init__(parent)
        self.controller = controller
        self.cover_image_ref = None
        self._build_ui()

    def _build_ui(self):
        # Make this pane responsive within its tab
        self.grid(sticky="nsew")
        self.rowconfigure(1, weight=1)
        self.columnconfigure(0, weight=1)   # list area grows
        self.columnconfigure(1, weight=0)   # detail panel keeps natural size

        top = ttk.Frame(self)
        top.grid(row=0, column=0, columnspan=2, sticky="ew", padx=8, pady=8)
        ttk.Label(top, text="Path:").pack(side="left")
        self.explorer_path = ttk.Entry(top, width=70)
        self.explorer_path.pack(side="left", padx=4, fill="x", expand=True)
        self.explorer_path.insert(0, self.controller.settings.get("music_root"))
        ttk.Button(top, text="Use Music Root", command=lambda: self._set_path(self.controller.settings.get('music_root'))).pack(side="left", padx=4)
        ttk.Button(top, text="Browse", command=lambda: self.controller.browse_dir(self.explorer_path)).pack(side="left")
        ttk.Button(top, text="Up", command=self.go_up).pack(side="left", padx=4)
        ttk.Button(top, text="Refresh", command=lambda: self.navigate(self.explorer_path.get())).pack(side="left")

        # Horizontal PanedWindow for resizable split
        pw = ttk.Panedwindow(self, orient='horizontal')
        pw.grid(row=1, column=0, columnspan=2, sticky='nsew', padx=8, pady=(0, 8))
        # List frame with its own grid to keep scrollbar aligned
        list_frame = ttk.Frame(pw)
        list_frame.columnconfigure(0, weight=1)
        list_frame.rowconfigure(0, weight=1)
        pw.add(list_frame, weight=3)

        cols = ("name", "type", "size", "modified", "actions")
        self.tree = ttk.Treeview(list_frame, columns=cols, show="headings")
        for c, w in zip(cols, (300, 80, 100, 160, 50)):
            self.tree.heading(c, text=c.title())
            self.tree.column(c, width=w, anchor="w")
        self.tree.grid(row=0, column=0, sticky="nsew")
        yscroll = ttk.Scrollbar(list_frame, orient="vertical", command=self.tree.yview)
        yscroll.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=yscroll.set)
        self.tree.bind("<Double-1>", self.on_open)
        self.tree.bind("<<TreeviewSelect>>", self.on_select)
        self.tree.bind("<Button-1>", self.on_click)
        self.tree.bind("<Button-3>", self.on_right_click)

        detail = ttk.Frame(pw)
        detail.columnconfigure(0, weight=1)
        pw.add(detail, weight=2)
        self.cover_label = ttk.Label(detail, text="No cover", anchor="center")
        self.cover_label.grid(row=0, column=0, sticky="n", padx=4, pady=4)
        ttk.Label(detail, text="Metadata").grid(row=1, column=0, sticky="w", padx=4)
        self.meta_text = tk.Text(detail, width=40, height=12, wrap="word")
        self.meta_text.grid(row=2, column=0, sticky="nsew", padx=4)
        ttk.Label(detail, text="Lyrics (preview)").grid(row=3, column=0, sticky="w", padx=4, pady=(8, 0))
        self.lyrics_text = tk.Text(detail, width=40, height=12, wrap="word")
        self.lyrics_text.grid(row=4, column=0, sticky="nsew", padx=4)
        detail.rowconfigure(2, weight=1)
        detail.rowconfigure(4, weight=1)
        # Auto-adjust name column on resize
        self.tree.bind('<Configure>', self._on_tree_resize)

        self.navigate(self.explorer_path.get())

    def _on_tree_resize(self, event):
        try:
            total = self.tree.winfo_width()
            # Fetch fixed columns current widths
            fixed = sum(self.tree.column(c, width=None) for c in ('type', 'size', 'modified', 'actions'))
            name_w = max(120, total - fixed - 24)
            self.tree.column('name', width=name_w)
        except Exception:
            pass

    # Navigation
    def _set_path(self, path):
        self.explorer_path.delete(0, 'end')
        self.explorer_path.insert(0, path)
        self.navigate(path)

    def go_up(self):
        cur = self.explorer_path.get().strip()
        parent = os.path.dirname(cur.rstrip(os.sep)) or cur
        if parent and os.path.isdir(parent):
            self._set_path(parent)

    def navigate(self, path):
        path = os.path.abspath(path)
        if not os.path.isdir(path):
            return
        self.explorer_path.delete(0, 'end'); self.explorer_path.insert(0, path)
        for i in self.tree.get_children():
            self.tree.delete(i)
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
                actions = '…' if typ == 'Folder' else ''
                self.tree.insert('', 'end', values=(name, typ, self._fmt_size(size), self._fmt_mtime(mtime), actions), tags=(full,))
        except Exception:
            pass

    # Events
    def on_open(self, event):
        item = self.tree.focus()
        if not item:
            return
        name = self.tree.item(item, 'values')[0]
        base = self.explorer_path.get().strip()
        full = os.path.join(base, name)
        if os.path.isdir(full):
            self.navigate(full)
        else:
            self.show_info(full)

    def on_select(self, event):
        item = self.tree.focus()
        if not item:
            return
        name, typ = self.tree.item(item, 'values')[:2]
        base = self.explorer_path.get().strip()
        full = os.path.join(base, name)
        if os.path.isfile(full):
            self.show_info(full)

    def on_click(self, event):
        row_id = self.tree.identify_row(event.y)
        col_id = self.tree.identify_column(event.x)
        if not row_id:
            return
        idx = int(col_id.replace('#', '')) - 1
        if idx != 4:  # actions column
            return
        vals = self.tree.item(row_id, 'values')
        if not vals:
            return
        name, typ = vals[0], vals[1]
        if typ != 'Folder':
            return
        folder_path = os.path.join(self.explorer_path.get().strip(), name)
        self.controller._show_folder_menu(folder_path, event)
        ui_log('explorer_actions_click', folder_path=folder_path)
        return 'break'

    def on_right_click(self, event):
        row_id = self.tree.identify_row(event.y)
        if not row_id:
            return
        vals = self.tree.item(row_id, 'values')
        if not vals:
            return
        name, typ = vals[0], vals[1]
        if typ != 'Folder':
            return
        folder_path = os.path.join(self.explorer_path.get().strip(), name)
        self.controller._show_folder_menu(folder_path, event)
        ui_log('explorer_right_click', folder_path=folder_path)

    # Info panel
    def show_info(self, path):
        self.cover_label.configure(text="No cover", image='')
        self.cover_image_ref = None
        self.meta_text.delete('1.0', 'end')
        self.lyrics_text.delete('1.0', 'end')

        ext = os.path.splitext(path)[1].lower()
        supported = {'.flac', '.mp3', '.m4a', '.alac', '.aac', '.ogg', '.opus', '.wav'}
        if ext not in supported:
            self.meta_text.insert('end', f"Selected: {os.path.basename(path)}\nNot a supported audio file.")
            return
        try:
            from mutagen import File as MFile
            audio = MFile(path)
        except Exception as e:
            self.meta_text.insert('end', f"Error reading file: {e}")
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
        self.meta_text.insert('end', "\n".join(meta_lines) or "No tags found.")

        # Lyrics
        lyrics_text = self._extract_lyrics_text(audio, path)
        if lyrics_text:
            if len(lyrics_text) > 5000:
                lyrics_text = lyrics_text[:5000] + '\n…'
            self.lyrics_text.insert('end', lyrics_text)
        else:
            self.lyrics_text.insert('end', "No lyrics found.")

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
            try:
                from PIL import Image, ImageTk
                im = Image.open(io.BytesIO(img_bytes)).convert('RGB')
                im.thumbnail((300, 300))
                photo = ImageTk.PhotoImage(im)
                self.cover_label.configure(image=photo, text='')
                self.cover_image_ref = photo
            except Exception:
                self.cover_label.configure(text="Cover present (install Pillow to display)")

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
