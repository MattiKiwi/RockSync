import os
import threading
import tkinter as tk
from tkinter import ttk, filedialog
from logging_utils import ui_log


class TracksPane(ttk.Frame):
    def __init__(self, controller, parent):
        super().__init__(parent)
        self.controller = controller
        self._build_ui()

    def _build_ui(self):
        self.grid(sticky="nsew")
        self.master.rowconfigure(1, weight=1)
        self.master.columnconfigure(0, weight=1)

        top = ttk.Frame(self.master)
        top.grid(row=0, column=0, sticky="ew", padx=8, pady=8)
        ttk.Label(top, text="Folder:").pack(side="left")
        self.path_entry = ttk.Entry(top, width=70)
        self.path_entry.pack(side="left", padx=4, fill="x", expand=True)
        self.path_entry.insert(0, self.controller.settings.get("music_root"))
        ttk.Button(top, text="Browse", command=self._browse).pack(side="left")
        ttk.Button(top, text="Use Music Root", command=self._use_root).pack(side="left", padx=4)
        ttk.Button(top, text="Scan", command=self.scan).pack(side="left", padx=4)

        cols = ("artist", "album", "title", "track", "format", "lyrics", "cover", "duration", "path")
        self.tree = ttk.Treeview(self.master, columns=cols, show="headings")
        for c in cols:
            self.tree.heading(c, text=c.title())
            self.tree.column(c, width=120 if c != "path" else 400, anchor="w")
        self.tree.grid(row=1, column=0, sticky="nsew")
        yscroll = ttk.Scrollbar(self.master, orient="vertical", command=self.tree.yview)
        yscroll.grid(row=1, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=yscroll.set)

        self.scan_status = tk.StringVar(value="")
        ttk.Label(self.master, textvariable=self.scan_status).grid(row=2, column=0, sticky="w", padx=8, pady=(4, 8))

    def _browse(self):
        path = filedialog.askdirectory()
        if path:
            self.path_entry.delete(0, 'end')
            self.path_entry.insert(0, path)

    def _use_root(self):
        self.path_entry.delete(0, 'end')
        self.path_entry.insert(0, self.controller.settings.get('music_root'))

    def scan(self):
        folder = self.path_entry.get().strip()
        if not folder or not os.path.isdir(folder):
            return
        for i in self.tree.get_children():
            self.tree.delete(i)
        self.scan_status.set("Scanning...")
        ui_log('tracks_scan_start', folder=folder)

        def worker():
            try:
                from mutagen import File as MFile
            except Exception as e:
                self._after_status(f"mutagen not installed: {e}")
                return
            exts = {".flac", ".mp3", ".m4a"}
            count = 0
            for root, _, files in os.walk(folder):
                for name in files:
                    if os.path.splitext(name)[1].lower() not in exts:
                        continue
                    path = os.path.join(root, name)
                    info = self._extract_info(path)
                    self.master.after(0, lambda i=info: self._insert_row(i))
                    count += 1
            self._after_status(f"Done. {count} files.")
            ui_log('tracks_scan_end', folder=folder, count=count)

        threading.Thread(target=worker, daemon=True).start()

    def _after_status(self, text):
        self.master.after(0, lambda: self.scan_status.set(text))

    def _extract_info(self, path):
        artist = album = title = track = ""
        fmt = os.path.splitext(path)[1].lower().lstrip(".")
        has_lyrics = False
        has_cover = False
        duration = ""
        try:
            from mutagen import File as MFile
            audio = MFile(path)
            if audio is not None:
                try:
                    from mutagen.easyid3 import EasyID3  # noqa
                    easy = MFile(path, easy=True)
                except Exception:
                    easy = None
                tags = getattr(easy, 'tags', None) or getattr(audio, 'tags', None) or {}
                def first(key, default=""):
                    v = tags.get(key)
                    return (v[0] if isinstance(v, list) and v else v) or default
                artist = first('artist', artist)
                album = first('album', album)
                title = first('title', os.path.basename(path))
                track = str(first('tracknumber', "")).split('/')[0]
                try:
                    if getattr(audio, 'info', None) and getattr(audio.info, 'length', None):
                        secs = int(audio.info.length)
                        duration = f"{secs//60}:{secs%60:02d}"
                except Exception:
                    pass
                try:
                    cname = audio.__class__.__name__.lower()
                    if 'flac' in cname and hasattr(audio, 'pictures'):
                        has_cover = any(getattr(p, 'type', None) == 3 for p in audio.pictures)
                    elif 'mp3' in cname and getattr(audio, 'tags', None):
                        has_cover = any(str(k).startswith('APIC') for k in audio.tags.keys())
                    elif ('mp4' in cname or 'm4a' in cname) and hasattr(audio, 'tags'):
                        has_cover = 'covr' in audio.tags
                except Exception:
                    pass
                if not has_cover:
                    if os.path.exists(os.path.join(os.path.dirname(path), 'cover.jpg')):
                        has_cover = True
                try:
                    if getattr(audio, 'tags', None):
                        for k in audio.tags.keys():
                            key = str(k).lower()
                            if 'lyric' in key or 'uslt' in key:
                                has_lyrics = True
                                break
                    stem = os.path.splitext(os.path.basename(path))[0]
                    base_dir = os.path.dirname(path)
                    lyrics_paths = [
                        os.path.join(base_dir, f"{stem}{self.controller.settings.get('lyrics_ext', '.lrc')}"),
                        os.path.join(base_dir, self.controller.settings.get('lyrics_subdir', 'Lyrics'), f"{stem}{self.controller.settings.get('lyrics_ext', '.lrc')}")
                    ]
                    if any(os.path.exists(p) for p in lyrics_paths):
                        has_lyrics = True
                except Exception:
                    pass
        except Exception:
            pass
        return {
            'artist': artist, 'album': album, 'title': title, 'track': track,
            'format': fmt, 'lyrics': 'Yes' if has_lyrics else 'No', 'cover': 'Yes' if has_cover else 'No',
            'duration': duration, 'path': path
        }

    def _insert_row(self, info):
        values = (info['artist'], info['album'], info['title'], info['track'], info['format'], info['lyrics'], info['cover'], info['duration'], info['path'])
        self.tree.insert('', 'end', values=values)

