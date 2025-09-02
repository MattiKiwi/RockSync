import os
import sys
import shlex
import json
import threading
import subprocess
import shutil
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"
CONFIG_PATH = ROOT / "app" / "settings.json"

DEFAULT_SETTINGS = {
    "music_root": str(ROOT),
    "lyrics_subdir": "Lyrics",
    "lyrics_ext": ".lrc",
    "cover_size": "100x100",
    "cover_max": 100,
    "jobs": os.cpu_count() or 4,
    "genius_token": "",
    "lastfm_key": "",
}

def load_settings():
    try:
        if CONFIG_PATH.exists():
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                return {**DEFAULT_SETTINGS, **data}
    except Exception:
        pass
    return DEFAULT_SETTINGS.copy()

def save_settings(settings):
    try:
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2)
        return True
    except Exception as e:
        messagebox.showerror("Error", f"Could not save settings: {e}")
        return False


def cmd_exists(cmd):
    return shutil.which(cmd) is not None


TASKS = [
    {
        "id": "covers",
        "label": "Resize cover.jpg",
        "script": SCRIPTS_DIR / "covers.py",
        "args": [
            {"key": "--root", "label": "Root Folder", "type": "path", "default": str(ROOT)},
            {"key": "--size", "label": "Size (WxH)", "type": "text", "default": "100x100"},
        ],
        "py_deps": ["PIL"],
        "bin_deps": [],
    },
    {
        "id": "flac_cover_resize",
        "label": "Resize FLAC Front Covers",
        "script": SCRIPTS_DIR / "embedd_resize.py",
        "args": [
            {"key": "--folder", "label": "Folder", "type": "path", "default": str(ROOT)},
            {"key": "--size", "label": "Size (WxH)", "type": "text", "default": "100x100"},
        ],
        "py_deps": ["mutagen", "PIL"],
        "bin_deps": [],
    },
    {
        "id": "flac_cover_promote",
        "label": "Promote & Resize Non-Cover Image",
        "script": SCRIPTS_DIR / "embed_resize_no_cover.py",
        "args": [
            {"key": "--folder", "label": "Folder", "type": "path", "default": str(ROOT)},
            {"key": "--max-size", "label": "Max Size (px)", "type": "int", "default": 100},
        ],
        "py_deps": ["mutagen", "PIL"],
        "bin_deps": [],
    },
    {
        "id": "downsample",
        "label": "Downsample FLAC (16-bit/44.1kHz)",
        "script": SCRIPTS_DIR / "downsampler.py",
        "args": [
            {"key": "--source", "label": "Source Folder", "type": "path", "default": str(ROOT)},
            {"key": "--jobs", "label": "Parallel Jobs", "type": "int", "default": os.cpu_count() or 4},
        ],
        "py_deps": [],
        "bin_deps": ["ffmpeg"],
    },
    {
        "id": "order_playlist",
        "label": "Prefix Files by Date",
        "script": SCRIPTS_DIR / "order_playlist.py",
        "args": [
            {"key": "--folder", "label": "Folder", "type": "path", "default": str(ROOT)},
            {"key": "--include-subfolders", "label": "Include Subfolders", "type": "bool", "default": False},
            {"key": "--ext", "label": "Extensions (space-separated)", "type": "text", "default": ".flac .m4a .mp3 .wav"},
            {"key": "--dry-run", "label": "Dry Run", "type": "bool", "default": False},
        ],
        "py_deps": [],
        "bin_deps": [],
    },
    {
        "id": "order_renamer",
        "label": "Rename 001 Title -> 01. Title",
        "script": SCRIPTS_DIR / "order_renamer.py",
        "args": [
            {"key": "--base-dir", "label": "Base Folder", "type": "path", "default": str(ROOT)},
        ],
        "py_deps": [],
        "bin_deps": [],
    },
    {
        "id": "m4a2flac",
        "label": "Convert M4A -> FLAC",
        "script": SCRIPTS_DIR / "m4a2flac.py",
        "args": [
            {"key": "base", "label": "Base Folder", "type": "path", "default": str(ROOT)},
        ],
        "py_deps": [],
        "bin_deps": ["ffmpeg"],
    },
    {
        "id": "inspect_flac",
        "label": "Inspect FLAC Tags",
        "script": SCRIPTS_DIR / "inspect_flac.py",
        "args": [
            {"key": "file", "label": "FLAC File", "type": "file", "default": ""},
        ],
        "py_deps": ["mutagen"],
        "bin_deps": [],
    },
    {
        "id": "lyrics_local",
        "label": "Export Lyrics (embedded/optional Genius)",
        "script": SCRIPTS_DIR / "lyrics_local.py",
        "args": [
            {"key": "--music-dir", "label": "Music Root", "type": "path", "default": str(ROOT)},
            {"key": "--lyrics-subdir", "label": "Lyrics Subfolder", "type": "text", "default": "Lyrics"},
            {"key": "--ext", "label": "Lyrics Ext", "type": "text", "default": ".lrc"},
            {"key": "--genius-token", "label": "Genius Token (optional)", "type": "password", "default": ""},
        ],
        "py_deps": ["mutagen"],  # lyricsgenius optional
        "bin_deps": [],
    },
    {
        "id": "flac2alac",
        "label": "Convert FLAC -> ALAC (.m4a)",
        "script": SCRIPTS_DIR / "flac2alac.py",
        "args": [
            {"key": "source", "label": "Source (FLAC root)", "type": "path", "default": str(ROOT)},
            {"key": "output", "label": "Output root", "type": "path", "default": str(ROOT / "alac_out")},
            {"key": "--jobs", "label": "Threads", "type": "int", "default": 4},
        ],
        "py_deps": [],
        "bin_deps": ["ffmpeg"],
    },
    {
        "id": "youtube_organizer",
        "label": "YouTube Organizer (Last.fm optional)",
        "script": SCRIPTS_DIR / "youtube_organizer.py",
        "args": [
            {"key": "--source", "label": "Source folder", "type": "path", "default": str(ROOT)},
            {"key": "--target-format", "label": "Target format", "type": "choice", "choices": ["flac"], "default": "flac"},
            {"key": "--lastfm-key", "label": "Last.fm API key (optional)", "type": "text", "default": ""},
            {"key": "--jobs", "label": "Threads", "type": "int", "default": 4},
        ],
        "py_deps": ["mutagen", "requests"],
        "bin_deps": ["ffmpeg"],
    },
]


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("RockSync GUI")
        self.geometry("1000x650")

        self.proc = None
        self.proc_thread = None
        self.settings = load_settings()

        self._build_ui()

    def _build_ui(self):
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)

        self.tabs = ttk.Notebook(self)
        self.tabs.grid(row=0, column=0, sticky="nsew")

        # Run tab
        self.run_tab = ttk.Frame(self.tabs)
        self.tabs.add(self.run_tab, text="Tasks")
        self._build_run_tab(self.run_tab)

        # Explorer tab
        self.explore_tab = ttk.Frame(self.tabs)
        self.tabs.add(self.explore_tab, text="Explorer")
        self._build_explorer_tab(self.explore_tab)

        # Settings tab
        self.settings_tab = ttk.Frame(self.tabs)
        self.tabs.add(self.settings_tab, text="Settings")
        self._build_settings_tab(self.settings_tab)

        # Status bar
        self.status = tk.StringVar(value=f"Music root: {self.settings.get('music_root')}")
        status_bar = ttk.Label(self, textvariable=self.status, anchor="w")
        status_bar.grid(row=1, column=0, sticky="ew")

    def _build_run_tab(self, parent):
        parent.columnconfigure(0, weight=0)
        parent.columnconfigure(1, weight=1)
        parent.rowconfigure(0, weight=1)

        # Task list
        left = ttk.Frame(parent)
        left.grid(row=0, column=0, sticky="nsw", padx=8, pady=8)
        ttk.Label(left, text="Tasks").pack(anchor="w")
        self.task_list = tk.Listbox(left, height=20)
        self.task_list.pack(fill="both", expand=True)
        for t in TASKS:
            self.task_list.insert("end", t["label"])
        self.task_list.bind("<<ListboxSelect>>", self.on_task_select)

        # Right pane
        right = ttk.Frame(parent)
        right.grid(row=0, column=1, sticky="nsew", padx=8, pady=8)
        right.rowconfigure(2, weight=1)
        right.columnconfigure(0, weight=1)

        self.form_frame = ttk.LabelFrame(right, text="Parameters")
        self.form_frame.grid(row=0, column=0, sticky="ew")
        self.form_widgets = {}

        # Actions
        actions = ttk.Frame(right)
        actions.grid(row=1, column=0, sticky="ew", pady=(8, 8))
        self.run_btn = ttk.Button(actions, text="Run", command=self.run_task)
        self.run_btn.pack(side="left")
        self.stop_btn = ttk.Button(actions, text="Stop", command=self.stop_task)
        self.stop_btn.pack(side="left", padx=(8, 0))

        # Output
        out_frame = ttk.LabelFrame(right, text="Output")
        out_frame.grid(row=2, column=0, sticky="nsew")
        out_frame.rowconfigure(0, weight=1)
        out_frame.columnconfigure(0, weight=1)
        self.output = tk.Text(out_frame, wrap="none")
        self.output.grid(row=0, column=0, sticky="nsew")
        yscroll = ttk.Scrollbar(out_frame, orient="vertical", command=self.output.yview)
        yscroll.grid(row=0, column=1, sticky="ns")
        self.output.configure(yscrollcommand=yscroll.set)

        self.task_list.selection_set(0)
        self.on_task_select()

    def _build_explorer_tab(self, parent):
        parent.rowconfigure(1, weight=1)
        parent.columnconfigure(0, weight=1)

        top = ttk.Frame(parent)
        top.grid(row=0, column=0, sticky="ew", padx=8, pady=8)
        ttk.Label(top, text="Folder:").pack(side="left")
        self.explore_path = ttk.Entry(top, width=70)
        self.explore_path.pack(side="left", padx=4, fill="x", expand=True)
        self.explore_path.insert(0, self.settings.get("music_root", str(ROOT)))
        ttk.Button(top, text="Browse", command=lambda: self.browse_dir(self.explore_path)).pack(side="left")
        ttk.Button(top, text="Use Music Root", command=lambda: self.explore_path.delete(0, 'end') or self.explore_path.insert(0, self.settings.get('music_root', str(ROOT)))).pack(side="left", padx=4)
        ttk.Button(top, text="Scan", command=self.scan_library).pack(side="left", padx=4)

        cols = ("artist", "album", "title", "track", "format", "lyrics", "cover", "duration", "path")
        self.tree = ttk.Treeview(parent, columns=cols, show="headings")
        for c in cols:
            self.tree.heading(c, text=c.title())
            self.tree.column(c, width=120 if c != "path" else 400, anchor="w")
        self.tree.grid(row=1, column=0, sticky="nsew")
        yscroll = ttk.Scrollbar(parent, orient="vertical", command=self.tree.yview)
        yscroll.grid(row=1, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=yscroll.set)

        self.scan_status = tk.StringVar(value="")
        ttk.Label(parent, textvariable=self.scan_status).grid(row=2, column=0, sticky="w", padx=8, pady=(4, 8))

    def _build_settings_tab(self, parent):
        parent.columnconfigure(1, weight=1)
        row = 0
        def add_row(label, widget):
            nonlocal row
            ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=8, pady=6)
            widget.grid(row=row, column=1, sticky="ew", padx=8, pady=6)
            row += 1

        # Music root
        music_frame = ttk.Frame(parent)
        self.set_music_root = ttk.Entry(music_frame)
        self.set_music_root.insert(0, self.settings.get("music_root", str(ROOT)))
        self.set_music_root.pack(side="left", fill="x", expand=True)
        ttk.Button(music_frame, text="Browse", command=lambda: self.browse_dir(self.set_music_root)).pack(side="left", padx=4)
        add_row("Music root", music_frame)

        # Lyrics
        self.set_lyrics_subdir = ttk.Entry(parent)
        self.set_lyrics_subdir.insert(0, self.settings.get("lyrics_subdir", "Lyrics"))
        add_row("Lyrics subfolder", self.set_lyrics_subdir)

        self.set_lyrics_ext = ttk.Entry(parent)
        self.set_lyrics_ext.insert(0, self.settings.get("lyrics_ext", ".lrc"))
        add_row("Lyrics extension", self.set_lyrics_ext)

        # Sizes and jobs
        self.set_cover_size = ttk.Entry(parent)
        self.set_cover_size.insert(0, self.settings.get("cover_size", "100x100"))
        add_row("Cover size (WxH)", self.set_cover_size)

        self.set_cover_max = ttk.Spinbox(parent, from_=50, to=2000)
        self.set_cover_max.set(int(self.settings.get("cover_max", 100)))
        add_row("Cover max (px)", self.set_cover_max)

        self.set_jobs = ttk.Spinbox(parent, from_=1, to=1024)
        self.set_jobs.set(int(self.settings.get("jobs", os.cpu_count() or 4)))
        add_row("Default jobs", self.set_jobs)

        # Tokens
        self.set_genius = ttk.Entry(parent, show="*")
        self.set_genius.insert(0, self.settings.get("genius_token", ""))
        add_row("Genius token", self.set_genius)

        self.set_lastfm = ttk.Entry(parent)
        self.set_lastfm.insert(0, self.settings.get("lastfm_key", ""))
        add_row("Last.fm API key", self.set_lastfm)

        # Save
        btns = ttk.Frame(parent)
        save_btn = ttk.Button(btns, text="Save Settings", command=self.on_save_settings)
        save_btn.pack(side="left")
        ttk.Button(btns, text="Reload", command=self.on_reload_settings).pack(side="left", padx=6)
        btns.grid(row=row, column=0, columnspan=2, sticky="w", padx=8, pady=8)

    def clear_form(self):
        for w in self.form_frame.winfo_children():
            w.destroy()
        self.form_widgets.clear()

    def on_task_select(self, event=None):
        idxs = self.task_list.curselection()
        if not idxs:
            return
        idx = idxs[0]
        task = TASKS[idx]
        self.populate_form(task)

    def default_value_for_spec(self, spec):
        key = spec.get("key", "")
        s = self.settings
        # Map common args to settings
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
        self.clear_form()
        row = 0

        # Dependency warnings
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
            lbl = ttk.Label(self.form_frame, text=f"Missing deps: {', '.join(missing)}", foreground="#b00")
            lbl.grid(row=row, column=0, columnspan=3, sticky="w", padx=8, pady=(8, 4))
            row += 1

        for spec in task["args"]:
            ttk.Label(self.form_frame, text=spec["label"]).grid(row=row, column=0, sticky="w", padx=8, pady=4)
            w = None
            if spec["type"] in ("text", "password"):
                w = ttk.Entry(self.form_frame)
                if spec["type"] == "password":
                    w.configure(show="*")
                w.insert(0, str(self.default_value_for_spec(spec)))
            elif spec["type"] == "int":
                w = ttk.Spinbox(self.form_frame, from_=1, to=1024)
                w.set(int(self.default_value_for_spec(spec)))
            elif spec["type"] == "bool":
                var = tk.BooleanVar(value=bool(self.default_value_for_spec(spec)))
                w = ttk.Checkbutton(self.form_frame, variable=var)
                w.var = var
            elif spec["type"] == "path":
                path_frame = ttk.Frame(self.form_frame)
                entry = ttk.Entry(path_frame, width=60)
                entry.insert(0, str(self.default_value_for_spec(spec)))
                entry.pack(side="left", fill="x", expand=True)
                btn = ttk.Button(path_frame, text="Browse", command=lambda e=entry: self.browse_dir(e))
                btn.pack(side="left", padx=4)
                w = path_frame
                w.entry = entry
            elif spec["type"] == "file":
                path_frame = ttk.Frame(self.form_frame)
                entry = ttk.Entry(path_frame, width=60)
                entry.insert(0, str(self.default_value_for_spec(spec)))
                entry.pack(side="left", fill="x", expand=True)
                btn = ttk.Button(path_frame, text="Browse", command=lambda e=entry: self.browse_file(e))
                btn.pack(side="left", padx=4)
                w = path_frame
                w.entry = entry
            elif spec["type"] == "choice":
                w = ttk.Combobox(self.form_frame, values=spec.get("choices", []))
                w.set(self.default_value_for_spec(spec))
            else:
                w = ttk.Entry(self.form_frame)
            w.grid(row=row, column=1, sticky="ew", padx=8, pady=4)
            self.form_widgets[spec["key"]] = w
            row += 1

    def browse_dir(self, entry):
        path = filedialog.askdirectory()
        if path:
            entry.delete(0, "end")
            entry.insert(0, path)

    def browse_file(self, entry):
        path = filedialog.askopenfilename(filetypes=[("FLAC", "*.flac"), ("All", "*.*")])
        if path:
            entry.delete(0, "end")
            entry.insert(0, path)

    def build_cmd(self, task):
        py = shlex.quote(sys.executable)
        script = shlex.quote(str(task["script"]))
        parts = [py, script]
        for spec in task["args"]:
            w = self.form_widgets[spec["key"]]
            if spec["type"] == "bool":
                if getattr(w, "var", None) and w.var.get():
                    parts.append(spec["key"])  # flag
                continue
            if spec["type"] in ("path", "file"):
                val = w.entry.get()
            else:
                val = w.get()
            if not spec["key"].startswith("-"):
                parts.append(shlex.quote(str(val)))
            else:
                parts.extend([spec["key"], shlex.quote(str(val))])
        return " ".join(parts)

    def append_output(self, text):
        self.output.insert("end", text)
        self.output.see("end")

    def run_task(self):
        idxs = self.task_list.curselection()
        if not idxs:
            messagebox.showwarning("No task", "Please select a task")
            return
        task = TASKS[idxs[0]]

        # Quick deps check
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
            if not messagebox.askyesno("Missing dependencies", f"Missing: {', '.join(missing)}\nRun anyway?"):
                return

        cmd = self.build_cmd(task)
        self.append_output(f"\n$ {cmd}\n")
        self.run_btn.configure(state="disabled")

        def worker():
            try:
                self.proc = subprocess.Popen(cmd, shell=True, cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
                for line in self.proc.stdout:
                    self.append_output(line)
                self.proc.wait()
                rc = self.proc.returncode
                self.append_output(f"\n[Exit {rc}]\n")
            except Exception as e:
                self.append_output(f"\n[Error] {e}\n")
            finally:
                self.proc = None
                self.run_btn.configure(state="normal")

        self.proc_thread = threading.Thread(target=worker, daemon=True)
        self.proc_thread.start()

    def stop_task(self):
        if self.proc and self.proc.poll() is None:
            try:
                self.proc.terminate()
                self.append_output("\n[Terminated]\n")
            except Exception as e:
                self.append_output(f"\n[Error stopping] {e}\n")

    # Settings actions
    def on_save_settings(self):
        self.settings["music_root"] = self.set_music_root.get()
        self.settings["lyrics_subdir"] = self.set_lyrics_subdir.get()
        self.settings["lyrics_ext"] = self.set_lyrics_ext.get()
        self.settings["cover_size"] = self.set_cover_size.get()
        self.settings["cover_max"] = int(self.set_cover_max.get())
        self.settings["jobs"] = int(self.set_jobs.get())
        self.settings["genius_token"] = self.set_genius.get()
        self.settings["lastfm_key"] = self.set_lastfm.get()
        if save_settings(self.settings):
            self.status.set(f"Music root: {self.settings.get('music_root')}")
            messagebox.showinfo("Settings", "Settings saved.")
            # refresh defaults in form
            self.on_task_select()

    def on_reload_settings(self):
        self.settings = load_settings()
        self.set_music_root.delete(0, 'end'); self.set_music_root.insert(0, self.settings.get('music_root', ''))
        self.set_lyrics_subdir.delete(0, 'end'); self.set_lyrics_subdir.insert(0, self.settings.get('lyrics_subdir', 'Lyrics'))
        self.set_lyrics_ext.delete(0, 'end'); self.set_lyrics_ext.insert(0, self.settings.get('lyrics_ext', '.lrc'))
        self.set_cover_size.delete(0, 'end'); self.set_cover_size.insert(0, self.settings.get('cover_size', '100x100'))
        self.set_cover_max.set(int(self.settings.get('cover_max', 100)))
        self.set_jobs.set(int(self.settings.get('jobs', os.cpu_count() or 4)))
        self.set_genius.delete(0, 'end'); self.set_genius.insert(0, self.settings.get('genius_token', ''))
        self.set_lastfm.delete(0, 'end'); self.set_lastfm.insert(0, self.settings.get('lastfm_key', ''))
        self.status.set(f"Music root: {self.settings.get('music_root')}")

    # Explorer actions
    def scan_library(self):
        folder = self.explore_path.get().strip()
        if not folder or not os.path.isdir(folder):
            messagebox.showwarning("Invalid folder", "Please choose a valid folder")
            return
        # Clear current
        for i in self.tree.get_children():
            self.tree.delete(i)
        self.scan_status.set("Scanning...")

        def worker():
            try:
                from mutagen import File as MFile
            except Exception as e:
                self.after(0, lambda: self.scan_status.set(f"mutagen not installed: {e}"))
                return

            exts = {".flac", ".mp3", ".m4a"}
            count = 0
            for root, _, files in os.walk(folder):
                for name in files:
                    if os.path.splitext(name)[1].lower() not in exts:
                        continue
                    path = os.path.join(root, name)
                    info = self._extract_track_info(path)
                    self.after(0, lambda i=info: self._insert_track_row(i))
                    count += 1
            self.after(0, lambda: self.scan_status.set(f"Done. {count} files."))

        threading.Thread(target=worker, daemon=True).start()

    def _extract_track_info(self, path):
        artist = album = title = track = ""
        fmt = os.path.splitext(path)[1].lower().lstrip(".")
        has_lyrics = False
        has_cover = False
        duration = ""
        try:
            from mutagen import File as MFile
            audio = MFile(path)
            if audio is not None:
                # Basic tags (try easy first)
                try:
                    from mutagen.easyid3 import EasyID3  # noqa: F401
                    easy = MFile(path, easy=True)
                except Exception:
                    easy = None
                tags = getattr(easy, 'tags', None) or getattr(audio, 'tags', None) or {}
                def first(key, default=""):
                    v = tags.get(key)
                    return (v[0] if isinstance(v, list) and v else v) or default
                artist = first('artist', artist)
                album = first('album', album)
                title = first('title', Path(path).stem)
                track = str(first('tracknumber', "")).split('/')[0]
                # Duration
                try:
                    if getattr(audio, 'info', None) and getattr(audio.info, 'length', None):
                        secs = int(audio.info.length)
                        duration = f"{secs//60}:{secs%60:02d}"
                except Exception:
                    pass
                # Cover detection
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
                # Lyrics detection
                try:
                    # Tag-based
                    if getattr(audio, 'tags', None):
                        for k in audio.tags.keys():
                            key = str(k).lower()
                            if 'lyric' in key or 'uslt' in key:
                                has_lyrics = True
                                break
                    # Sidecar files
                    stem = os.path.splitext(os.path.basename(path))[0]
                    base_dir = os.path.dirname(path)
                    lyrics_paths = [
                        os.path.join(base_dir, f"{stem}{self.settings.get('lyrics_ext', '.lrc')}"),
                        os.path.join(base_dir, self.settings.get('lyrics_subdir', 'Lyrics'), f"{stem}{self.settings.get('lyrics_ext', '.lrc')}")
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

    def _insert_track_row(self, info):
        values = (info['artist'], info['album'], info['title'], info['track'], info['format'], info['lyrics'], info['cover'], info['duration'], info['path'])
        self.tree.insert('', 'end', values=values)


if __name__ == "__main__":
    app = App()
    app.mainloop()
