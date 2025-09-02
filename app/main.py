import os
import sys
import shlex
import json
import logging
import logging.handlers
import uuid
import warnings
import io
import traceback
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
    "debug": False,
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
        # Session + Logging
        self.session_id = str(uuid.uuid4())[:8]
        self._configure_logging()

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

        # Explorer tab (folder navigation)
        self.explore_tab = ttk.Frame(self.tabs)
        self.tabs.add(self.explore_tab, text="Explorer")
        self._build_explorer_tab(self.explore_tab)

        # Tracks tab (full library list)
        self.tracks_tab = ttk.Frame(self.tabs)
        self.tabs.add(self.tracks_tab, text="Tracks")
        self._build_tracks_tab(self.tracks_tab)

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

    def _select_tasks_tab(self):
        """Robustly switch to the Tasks tab across Tk variants."""
        # 1) Try selecting directly by widget
        try:
            self.logger.debug("Selecting Tasks tab by widget")
            self.tabs.select(self.run_tab)
            return True
        except Exception as e:
            self.logger.warning("Select by widget failed: %s", e)

        # 2) Resolve tab id from run_tab widget
        try:
            tabs = self.tabs.tabs()
            for tid in tabs:
                w = self.tabs.nametowidget(tid)
                if w is self.run_tab:
                    self.logger.debug("Selecting Tasks tab by tab id: %s", tid)
                    self.tabs.select(tid)
                    return True
        except Exception as e:
            self.logger.warning("Select by tab id failed: %s", e)

        # 3) Fallback by title text
        try:
            tabs = self.tabs.tabs()
            for tid in tabs:
                if self.tabs.tab(tid, 'text') == 'Tasks':
                    self.logger.debug("Selecting Tasks tab by title")
                    self.tabs.select(tid)
                    return True
        except Exception as e:
            self.logger.warning("Select by title failed: %s", e)

        # 4) Final fallback: first tab
        try:
            tabs = self.tabs.tabs()
            if tabs:
                self.logger.debug("Selecting first tab as fallback: %s", tabs[0])
                self.tabs.select(tabs[0])
                return True
        except Exception as e:
            self.logger.error("Failed to select any tab: %s", e)
        return False

    def _configure_logging(self):
        log_level = logging.DEBUG if self.settings.get("debug") else logging.INFO

        # Root logger setup (capture everything)
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.DEBUG)  # capture all
        for h in list(root_logger.handlers):
            try:
                root_logger.removeHandler(h)
                h.close()
            except Exception:
                pass

        class SessionFilter(logging.Filter):
            def __init__(self, session):
                super().__init__()
                self.session = session
            def filter(self, record):
                record.session = self.session
                return True

        sess_filter = SessionFilter(self.session_id)

        # Formatters
        console_fmt = logging.Formatter("[%(levelname)s] %(message)s")
        file_fmt = logging.Formatter("%(asctime)s [%(levelname)s] [%(name)s] %(module)s:%(lineno)d | %(message)s | session=%(session)s")

        # Handlers
        try:
            # Console
            sh = logging.StreamHandler(sys.stdout)
            sh.setLevel(log_level)
            sh.setFormatter(console_fmt)
            sh.addFilter(sess_filter)
            root_logger.addHandler(sh)

            # latest.log (overwritten each run)
            latest_path = ROOT / "app" / "latest.log"
            latest_path.parent.mkdir(parents=True, exist_ok=True)
            lh = logging.FileHandler(latest_path, mode='w', encoding='utf-8')
            lh.setLevel(logging.DEBUG)
            lh.setFormatter(file_fmt)
            lh.addFilter(sess_filter)
            root_logger.addHandler(lh)

            # debug.log (rotating history)
            debug_path = ROOT / "app" / "debug.log"
            rh = logging.handlers.RotatingFileHandler(debug_path, maxBytes=1_000_000, backupCount=5, encoding='utf-8')
            rh.setLevel(logging.DEBUG)
            rh.setFormatter(file_fmt)
            rh.addFilter(sess_filter)
            root_logger.addHandler(rh)
            # ui_state.log captures detailed UI state snapshots
            ui_state_path = ROOT / "app" / "ui_state.log"
            uh = logging.FileHandler(ui_state_path, mode='w', encoding='utf-8')
            uh.setLevel(logging.DEBUG)
            uh.setFormatter(file_fmt)
            uh.addFilter(sess_filter)
            logging.getLogger("RockSyncGUI.UI").addHandler(uh)
            logging.getLogger("RockSyncGUI.UI").setLevel(logging.DEBUG)
        except Exception:
            pass

        # App logger (for convenience)
        self.logger = logging.getLogger("RockSyncGUI")
        self.logger.setLevel(log_level)

        # Capture Python warnings
        try:
            warnings.captureWarnings(True)
        except Exception:
            pass

        # Redirect stdout/stderr into logging
        class StreamToLogger(io.TextIOBase):
            def __init__(self, logger, level):
                self.logger = logger
                self.level = level
                self._buf = ""
            def write(self, b):
                try:
                    s = str(b)
                except Exception:
                    s = b.decode('utf-8', errors='ignore')
                self._buf += s
                while "\n" in self._buf:
                    line, self._buf = self._buf.split("\n", 1)
                    if line.strip():
                        self.logger.log(self.level, line)
                return len(b) if hasattr(b, '__len__') else 0
            def flush(self):
                if self._buf.strip():
                    self.logger.log(self.level, self._buf.strip())
                self._buf = ""

        try:
            sys.stdout = StreamToLogger(logging.getLogger("stdout"), logging.INFO)
            sys.stderr = StreamToLogger(logging.getLogger("stderr"), logging.ERROR)
        except Exception:
            pass

        # Log unhandled exceptions
        def excepthook(exc_type, exc_value, exc_tb):
            self.logger.error("Uncaught exception", exc_info=(exc_type, exc_value, exc_tb))
        sys.excepthook = excepthook

        self.logger.log(log_level, "Logger initialized | debug=%s | session=%s", self.settings.get("debug"), self.session_id)

    def log(self, level, event, **data):
        try:
            payload = json.dumps(data, ensure_ascii=False, default=str)
        except Exception:
            payload = str(data)
        self.logger.log(level, f"event={event} data={payload}")

    # --- UI State Snapshot ---
    def ui_state(self, event, **extra):
        try:
            st = {
                'event': event,
                'session': self.session_id,
            }
            # Tabs
            try:
                cur_tab = self.tabs.select()
                st['active_tab'] = self.tabs.tab(cur_tab, 'text')
            except Exception:
                st['active_tab'] = None
            # Task selection
            try:
                idxs = self.task_list.curselection()
                st['task_index'] = (idxs[0] if idxs else None)
                st['task_label'] = (self.task_list.get(idxs[0]) if idxs else None)
            except Exception:
                st['task_index'] = st['task_label'] = None
            # Form values
            try:
                vals = {}
                for k, w in self.form_widgets.items():
                    v = None
                    try:
                        if hasattr(w, 'entry'):
                            v = w.entry.get()
                        elif hasattr(w, 'var'):
                            v = w.var.get()
                        else:
                            v = w.get()
                    except Exception:
                        v = None
                    vals[k] = v
                st['form_values'] = vals
            except Exception:
                st['form_values'] = None
            # Explorer
            try:
                st['explorer_path'] = self.explorer_path.get()
                sel = self.explorer_list.focus()
                st['explorer_focus'] = self.explorer_list.item(sel, 'values') if sel else None
            except Exception:
                st['explorer_path'] = st['explorer_focus'] = None
            # Tracks
            try:
                st['tracks_path'] = self.tracks_path.get()
                st['tracks_count'] = len(self.tracks_tree.get_children())
            except Exception:
                st['tracks_path'] = None
            # Settings subset
            st['settings'] = {
                'music_root': self.settings.get('music_root'),
                'lyrics_subdir': self.settings.get('lyrics_subdir'),
                'lyrics_ext': self.settings.get('lyrics_ext'),
                'cover_size': self.settings.get('cover_size'),
                'cover_max': self.settings.get('cover_max'),
                'jobs': self.settings.get('jobs'),
                'debug': self.settings.get('debug'),
            }
            # Process state
            st['proc_running'] = (self.proc is not None and getattr(self.proc, 'poll', lambda: 0)() is None)
            # Extra data
            if extra:
                st.update(extra)
            payload = json.dumps(st, ensure_ascii=False, default=str)
            logging.getLogger("RockSyncGUI.UI").info(payload)
        except Exception:
            try:
                logging.getLogger("RockSyncGUI.UI").exception("snapshot_failed")
            except Exception:
                pass

    def _build_explorer_tab(self, parent):
        # Layout: top bar, main split (list on left, detail on right)
        parent.rowconfigure(1, weight=1)
        parent.columnconfigure(0, weight=1)
        parent.columnconfigure(1, weight=0)

        # Top bar
        top = ttk.Frame(parent)
        top.grid(row=0, column=0, columnspan=2, sticky="ew", padx=8, pady=8)
        ttk.Label(top, text="Path:").pack(side="left")
        self.explorer_path = ttk.Entry(top, width=70)
        self.explorer_path.pack(side="left", padx=4, fill="x", expand=True)
        self.explorer_path.insert(0, self.settings.get("music_root", str(ROOT)))
        ttk.Button(top, text="Use Music Root", command=lambda: self._set_explorer_path(self.settings.get('music_root', str(ROOT)))).pack(side="left", padx=4)
        ttk.Button(top, text="Browse", command=lambda: self.browse_dir(self.explorer_path)).pack(side="left")
        ttk.Button(top, text="Up", command=self.explorer_up).pack(side="left", padx=4)
        ttk.Button(top, text="Refresh", command=lambda: self.explorer_navigate(self.explorer_path.get())).pack(side="left")

        # Directory listing
        self.explorer_cols = ("name", "type", "size", "modified", "actions")
        self.explorer_list = ttk.Treeview(parent, columns=self.explorer_cols, show="headings")
        for c, w in zip(self.explorer_cols, (300, 80, 100, 160, 50)):
            self.explorer_list.heading(c, text=c.title())
            self.explorer_list.column(c, width=w, anchor="w")
        self.explorer_list.grid(row=1, column=0, sticky="nsew", padx=(8, 4), pady=(0, 8))
        yscroll = ttk.Scrollbar(parent, orient="vertical", command=self.explorer_list.yview)
        yscroll.grid(row=1, column=0, sticky="nse", padx=(0, 8), pady=(0, 8))
        self.explorer_list.configure(yscrollcommand=yscroll.set)
        self.explorer_list.bind("<Double-1>", self.explorer_on_open)
        self.explorer_list.bind("<<TreeviewSelect>>", self.explorer_on_select)
        self.explorer_list.bind("<Button-1>", self.explorer_on_click)
        self.explorer_list.bind("<Button-3>", self.explorer_on_right_click)

        # Detail panel
        detail = ttk.Frame(parent)
        detail.grid(row=1, column=1, sticky="ns", padx=(0, 8), pady=(0, 8))
        # Cover art
        self.cover_label = ttk.Label(detail, text="No cover", anchor="center")
        self.cover_label.grid(row=0, column=0, sticky="n", padx=4, pady=4)
        self.cover_image_ref = None
        # Metadata
        ttk.Label(detail, text="Metadata").grid(row=1, column=0, sticky="w", padx=4)
        self.meta_text = tk.Text(detail, width=40, height=12, wrap="word")
        self.meta_text.grid(row=2, column=0, sticky="nsew", padx=4)
        # Lyrics
        ttk.Label(detail, text="Lyrics (preview)").grid(row=3, column=0, sticky="w", padx=4, pady=(8, 0))
        self.lyrics_text = tk.Text(detail, width=40, height=12, wrap="word")
        self.lyrics_text.grid(row=4, column=0, sticky="nsew", padx=4)
        detail.rowconfigure(2, weight=1)
        detail.rowconfigure(4, weight=1)

        # Initial load
        self.explorer_navigate(self.explorer_path.get())

    def _build_tracks_tab(self, parent):
        parent.rowconfigure(1, weight=1)
        parent.columnconfigure(0, weight=1)

        top = ttk.Frame(parent)
        top.grid(row=0, column=0, sticky="ew", padx=8, pady=8)
        ttk.Label(top, text="Folder:").pack(side="left")
        self.tracks_path = ttk.Entry(top, width=70)
        self.tracks_path.pack(side="left", padx=4, fill="x", expand=True)
        self.tracks_path.insert(0, self.settings.get("music_root", str(ROOT)))
        ttk.Button(top, text="Browse", command=lambda: self.browse_dir(self.tracks_path)).pack(side="left")
        ttk.Button(top, text="Use Music Root", command=lambda: self.tracks_path.delete(0, 'end') or self.tracks_path.insert(0, self.settings.get('music_root', str(ROOT)))).pack(side="left", padx=4)
        ttk.Button(top, text="Scan", command=self.scan_library).pack(side="left", padx=4)

        cols = ("artist", "album", "title", "track", "format", "lyrics", "cover", "duration", "path")
        self.tracks_tree = ttk.Treeview(parent, columns=cols, show="headings")
        for c in cols:
            self.tracks_tree.heading(c, text=c.title())
            self.tracks_tree.column(c, width=120 if c != "path" else 400, anchor="w")
        self.tracks_tree.grid(row=1, column=0, sticky="nsew")
        yscroll = ttk.Scrollbar(parent, orient="vertical", command=self.tracks_tree.yview)
        yscroll.grid(row=1, column=1, sticky="ns")
        self.tracks_tree.configure(yscrollcommand=yscroll.set)

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

        # Debug toggle
        self.debug_var = tk.BooleanVar(value=bool(self.settings.get("debug", False)))
        dbg_cb = ttk.Checkbutton(parent, text="Enable verbose debug logging (writes to app/debug.log)", variable=self.debug_var)
        add_row("Debug", dbg_cb)

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
        self.ui_state('on_task_select', idx=idx, label=task.get('label'))
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
        cmd = " ".join(parts)
        self.ui_state('build_cmd', cmd=cmd, task=task.get('label'))
        return cmd

    def append_output(self, text):
        self.output.insert("end", text)
        self.output.see("end")

    def run_task(self):
        idxs = self.task_list.curselection()
        if not idxs:
            messagebox.showwarning("No task", "Please select a task")
            return
        task = TASKS[idxs[0]]
        self.ui_state('run_task_start', task=task.get('label'))

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
                    try:
                        self.logger.info("[proc] %s", line.rstrip())
                    except Exception:
                        pass
                self.proc.wait()
                rc = self.proc.returncode
                self.append_output(f"\n[Exit {rc}]\n")
                self.logger.info("Process exited | rc=%s", rc)
                self.ui_state('run_task_end', rc=rc)
            except Exception as e:
                self.append_output(f"\n[Error] {e}\n")
                self.logger.exception("Process error")
                self.ui_state('run_task_error', error=str(e))
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
                self.ui_state('stop_task')
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
        self.settings["debug"] = bool(self.debug_var.get())
        if save_settings(self.settings):
            self.status.set(f"Music root: {self.settings.get('music_root')}")
            messagebox.showinfo("Settings", "Settings saved.")
            # refresh defaults in form
            self.on_task_select()
            # Reconfigure logging live
            self._configure_logging()
            self.ui_state('settings_saved')

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
        self.debug_var.set(bool(self.settings.get('debug', False)))
        self.status.set(f"Music root: {self.settings.get('music_root')}")
        self._configure_logging()
        self.ui_state('settings_reloaded')

    # Explorer actions
    def scan_library(self):
        folder = self.tracks_path.get().strip()
        if not folder or not os.path.isdir(folder):
            messagebox.showwarning("Invalid folder", "Please choose a valid folder")
            return
        # Clear current
        for i in self.tracks_tree.get_children():
            self.tracks_tree.delete(i)
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
        self.tracks_tree.insert('', 'end', values=values)

    # ===== Explorer helpers =====
    def _set_explorer_path(self, path):
        self.explorer_path.delete(0, 'end')
        self.explorer_path.insert(0, path)
        self.explorer_navigate(path)

    def explorer_up(self):
        cur = self.explorer_path.get().strip()
        parent = os.path.dirname(cur.rstrip(os.sep)) or cur
        if parent and os.path.isdir(parent):
            self._set_explorer_path(parent)

    def explorer_navigate(self, path):
        path = os.path.abspath(path)
        if not os.path.isdir(path):
            messagebox.showwarning("Invalid folder", f"Not a directory:\n{path}")
            return
        self._set_explorer_entry(path)
        # Clear listing
        for i in self.explorer_list.get_children():
            self.explorer_list.delete(i)
        # Populate with entries
        try:
            with os.scandir(path) as it:
                dirs, files = [], []
                for entry in it:
                    try:
                        st = entry.stat()
                        info = (entry.name, 'Folder' if entry.is_dir() else 'File', st.st_size, st.st_mtime, entry.path)
                        if entry.is_dir():
                            dirs.append(info)
                        else:
                            files.append(info)
                    except Exception:
                        continue
            # Sort: directories first, then files by name
            dirs.sort(key=lambda x: x[0].lower())
            files.sort(key=lambda x: x[0].lower())
            for name, typ, size, mtime, full in dirs + files:
                actions = '…' if typ == 'Folder' else ''
                self.explorer_list.insert('', 'end', values=(name, typ, self._fmt_size(size), self._fmt_mtime(mtime), actions), tags=(full,))
        except Exception as e:
            messagebox.showerror("Error", f"Could not list folder:\n{e}")

    def _set_explorer_entry(self, path):
        self.explorer_path.delete(0, 'end')
        self.explorer_path.insert(0, path)

    def explorer_on_open(self, event):
        item = self.explorer_list.focus()
        if not item:
            return
        name = self.explorer_list.item(item, 'values')[0]
        base = self.explorer_path.get().strip()
        full = os.path.join(base, name)
        if os.path.isdir(full):
            self.explorer_navigate(full)
        else:
            self.explorer_show_info(full)

    def explorer_on_select(self, event):
        item = self.explorer_list.focus()
        if not item:
            return
        name = self.explorer_list.item(item, 'values')[0]
        base = self.explorer_path.get().strip()
        full = os.path.join(base, name)
        if os.path.isfile(full):
            self.explorer_show_info(full)

    def explorer_on_click(self, event):
        row_id = self.explorer_list.identify_row(event.y)
        col_id = self.explorer_list.identify_column(event.x)
        if not row_id:
            return
        # If clicking the actions column and it's a folder, open context menu
        try:
            idx = int(col_id.replace('#', '')) - 1
        except Exception:
            return
        if idx != list(self.explorer_cols).index('actions'):
            return
        vals = self.explorer_list.item(row_id, 'values')
        if not vals:
            return
        name, typ = vals[0], vals[1]
        if typ != 'Folder':
            return
        base = self.explorer_path.get().strip()
        folder_path = os.path.join(base, name)
        self.logger.debug("Explorer actions click: row=%s col=%s path=%s", row_id, col_id, folder_path)
        self._show_folder_menu(folder_path, event)
        self.ui_state('explorer_actions_click', folder_path=folder_path)
        return 'break'

    def explorer_on_right_click(self, event):
        row_id = self.explorer_list.identify_row(event.y)
        if not row_id:
            return
        vals = self.explorer_list.item(row_id, 'values')
        if not vals:
            return
        name, typ = vals[0], vals[1]
        if typ != 'Folder':
            return
        base = self.explorer_path.get().strip()
        folder_path = os.path.join(base, name)
        self.logger.debug("Explorer right click: row=%s path=%s", row_id, folder_path)
        self._show_folder_menu(folder_path, event)
        self.ui_state('explorer_right_click', folder_path=folder_path)

    def _show_folder_menu(self, folder_path, event):
        self.logger.debug("Show folder menu for: %s", folder_path)
        # Destroy any existing context menu
        if getattr(self, "_ctx_menu", None):
            try:
                self._ctx_menu.unpost()
                self._ctx_menu.destroy()
            except Exception:
                pass
            self._ctx_menu = None

        menu = tk.Menu(self, tearoff=0)
        # Build task list for folder-accepting tasks
        for task in TASKS:
            if self._task_accepts_folder(task):
                menu.add_command(label=f"Use: {task['label']}", command=lambda t=task: self._open_task_with_folder(t, folder_path))
        if not menu.index('end'):
            menu.add_command(label="No folder tasks found", state='disabled')
        # Keep reference for dismissal and teardown
        self._ctx_menu = menu
        # Only bind Escape to dismiss to avoid stealing the click that should activate menu items
        self.bind_all("<Escape>", self._dismiss_context_menu, add="+")
        # When the menu unposts (user clicked elsewhere or selected), clean up handler and state
        try:
            menu.bind("<Unmap>", lambda e: self._destroy_ctx_menu())
        except Exception:
            pass
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            try:
                menu.grab_release()
            except Exception:
                pass
        self.ui_state('context_menu_opened', folder_path=folder_path)

    def _dismiss_context_menu(self, event=None):
        # Delay unpost slightly to let menu commands fire first
        self.after(10, self._destroy_ctx_menu)

    def _destroy_ctx_menu(self):
        menu = getattr(self, "_ctx_menu", None)
        if menu is None:
            return
        try:
            menu.unpost()
        except Exception:
            pass
        try:
            menu.destroy()
        except Exception:
            pass
        self._ctx_menu = None
        # Remove global bindings
        try:
            self.unbind_all("<Button-1>")
            self.unbind_all("<Button-3>")
            self.unbind_all("<Escape>")
        except Exception:
            pass

    # Tkinter callback exception hook -> log file
    def report_callback_exception(self, exc, val, tb):
        try:
            self.logger.error("Tk callback exception", exc_info=(exc, val, tb))
        except Exception:
            pass

    def _task_accepts_folder(self, task):
        folder_keys = {"--folder", "--root", "--source", "--base-dir", "base", "source", "--music-dir"}
        for spec in task.get('args', []):
            if spec.get('type') == 'path' and spec.get('key') in folder_keys:
                return True
        return False

    def _open_task_with_folder(self, task, folder_path):
        # Close menu if visible
        self._destroy_ctx_menu()
        self.logger.debug("Quick task dialog for folder: %s | task=%s", folder_path, task.get('label'))
        self.ui_state('quick_task_open', folder_path=folder_path, task=task.get('label'))

        dlg = tk.Toplevel(self)
        dlg.title(f"Quick Task: {task.get('label')}")
        dlg.transient(self)
        try:
            dlg.grab_set()
        except Exception:
            pass
        dlg.columnconfigure(1, weight=1)

        row = 0
        # Deps warning
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
            ttk.Label(dlg, text=f"Missing deps: {', '.join(missing)}", foreground="#b00").grid(row=row, column=0, columnspan=2, sticky='w', padx=8, pady=(8,4))
            row += 1

        ttk.Label(dlg, text=f"Folder: {folder_path}").grid(row=row, column=0, columnspan=2, sticky='w', padx=8)
        row += 1

        quick_widgets = {}
        folder_keys = {"--folder", "--root", "--source", "--base-dir", "base", "source", "--music-dir"}

        def add_row(label, widget):
            nonlocal row
            ttk.Label(dlg, text=label).grid(row=row, column=0, sticky='w', padx=8, pady=4)
            widget.grid(row=row, column=1, sticky='ew', padx=8, pady=4)
            row += 1

        for spec in task.get('args', []):
            label = spec.get('label')
            key = spec.get('key')
            typ = spec.get('type')
            default_val = self.default_value_for_spec(spec)
            if key in folder_keys:
                default_val = folder_path
            w = None
            if typ in ('text', 'password'):
                w = ttk.Entry(dlg)
                if typ == 'password':
                    w.configure(show='*')
                w.insert(0, str(default_val))
            elif typ == 'int':
                w = ttk.Spinbox(dlg, from_=1, to=4096)
                w.set(int(default_val) if str(default_val).isdigit() else 1)
            elif typ == 'bool':
                var = tk.BooleanVar(value=bool(default_val))
                w = ttk.Checkbutton(dlg, variable=var)
                w.var = var
            elif typ == 'path':
                frame = ttk.Frame(dlg)
                entry = ttk.Entry(frame)
                entry.insert(0, str(default_val))
                entry.pack(side='left', fill='x', expand=True)
                ttk.Button(frame, text='Browse', command=lambda e=entry: self.browse_dir(e)).pack(side='left', padx=4)
                w = frame
                w.entry = entry
            elif typ == 'file':
                frame = ttk.Frame(dlg)
                entry = ttk.Entry(frame)
                entry.insert(0, str(default_val))
                entry.pack(side='left', fill='x', expand=True)
                ttk.Button(frame, text='Browse', command=lambda e=entry: self.browse_file(e)).pack(side='left', padx=4)
                w = frame
                w.entry = entry
            elif typ == 'choice':
                w = ttk.Combobox(dlg, values=spec.get('choices', []))
                w.set(default_val)
            else:
                w = ttk.Entry(dlg)
                w.insert(0, str(default_val))
            add_row(label, w)
            quick_widgets[key] = w

        # Close on run toggle
        close_var = tk.BooleanVar(value=True)
        add_row('Close this window on Run', ttk.Checkbutton(dlg, variable=close_var))

        # Buttons
        btns = ttk.Frame(dlg)
        btns.grid(row=row, column=0, columnspan=2, sticky='e', padx=8, pady=8)
        def do_run():
            values = {}
            for spec in task.get('args', []):
                key = spec.get('key')
                w = quick_widgets.get(key)
                if w is None:
                    continue
                if spec.get('type') == 'bool':
                    values[key] = bool(getattr(w, 'var', tk.BooleanVar(value=False)).get())
                elif spec.get('type') in ('path','file'):
                    values[key] = w.entry.get()
                else:
                    try:
                        values[key] = w.get()
                    except Exception:
                        values[key] = ''
            cmd = self._build_cmd_with_values(task, values)
            self.append_output(f"\n$ {cmd}\n")
            self.ui_state('quick_task_run', task=task.get('label'), folder_path=folder_path, cmd=cmd)
            self._run_command(cmd)
            if close_var.get():
                dlg.destroy()
        ttk.Button(btns, text='Run', command=do_run).pack(side='right')
        ttk.Button(btns, text='Cancel', command=dlg.destroy).pack(side='right', padx=(0,8))

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

    def _run_command(self, cmd):
        # Reuse output pane; similar to run_task worker
        self.run_btn.configure(state="disabled")
        def worker():
            try:
                self.proc = subprocess.Popen(cmd, shell=True, cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
                for line in self.proc.stdout:
                    self.append_output(line)
                    try:
                        self.logger.info("[proc] %s", line.rstrip())
                    except Exception:
                        pass
                self.proc.wait()
                rc = self.proc.returncode
                self.append_output(f"\n[Exit {rc}]\n")
                self.logger.info("Process exited | rc=%s", rc)
            except Exception:
                self.logger.exception("Process error")
            finally:
                self.proc = None
                self.run_btn.configure(state="normal")
        threading.Thread(target=worker, daemon=True).start()

    def explorer_show_info(self, path):
        # Reset fields
        self.cover_label.configure(text="No cover", image='')
        self.cover_image_ref = None
        self.meta_text.delete('1.0', 'end')
        self.lyrics_text.delete('1.0', 'end')

        # Only parse supported audio files
        ext = os.path.splitext(path)[1].lower()
        supported = {'.flac', '.mp3', '.m4a', '.alac', '.aac', '.ogg', '.opus', '.wav'}
        if ext not in supported:
            self.meta_text.insert('end', f"Selected: {os.path.basename(path)}\nNot an audio file supported for metadata preview.")
            return
        try:
            from mutagen import File as MFile
            audio = MFile(path)
        except Exception as e:
            self.meta_text.insert('end', f"Error reading file: {e}")
            return

        # Metadata dump
        meta_lines = []
        try:
            # Prefer easy tags if available
            try:
                easy = MFile(path, easy=True)
                tags = getattr(easy, 'tags', None) or {}
            except Exception:
                tags = getattr(audio, 'tags', None) or {}
            # Normalize to simple strings, excluding lyrics-related tags
            def is_lyrics_key(kstr):
                kl = kstr.lower()
                return ('lyric' in kl) or ('uslt' in kl) or kl.endswith('©lyr')
            for k, v in (tags.items() if hasattr(tags, 'items') else []):
                kstr = str(k)
                if is_lyrics_key(kstr):
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
        # Basic info
        try:
            if getattr(audio, 'info', None) and getattr(audio.info, 'length', None):
                secs = int(audio.info.length)
                meta_lines.insert(0, f"Duration: {secs//60}:{secs%60:02d}")
        except Exception:
            pass
        self.meta_text.insert('end', "\n".join(meta_lines) or "No tags found.")

        # Lyrics preview (tags + sidecars)
        lyrics_text = self._extract_lyrics_text(audio, path)
        if lyrics_text:
            if len(lyrics_text) > 5000:
                lyrics_text = lyrics_text[:5000] + '\n…'
            self.lyrics_text.insert('end', lyrics_text)
        else:
            self.lyrics_text.insert('end', "No lyrics found.")

        # Cover image
        img_bytes = self._extract_cover_bytes(audio)
        if not img_bytes:
            # fallback to cover.jpg
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
                import io
                im = Image.open(io.BytesIO(img_bytes)).convert('RGB')
                im.thumbnail((300, 300))
                photo = ImageTk.PhotoImage(im)
                self.cover_label.configure(image=photo, text='')
                self.cover_image_ref = photo
            except Exception as e:
                self.cover_label.configure(text=f"Cover present (install Pillow to display)")

    def _extract_cover_bytes(self, audio):
        try:
            cname = audio.__class__.__name__.lower()
            if 'flac' in cname and hasattr(audio, 'pictures') and audio.pictures:
                # Prefer front cover type 3
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
        # From tags
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
        # From sidecar
        try:
            stem = os.path.splitext(os.path.basename(path))[0]
            base_dir = os.path.dirname(path)
            candidates = [
                os.path.join(base_dir, f"{stem}{self.settings.get('lyrics_ext', '.lrc')}"),
                os.path.join(base_dir, self.settings.get('lyrics_subdir', 'Lyrics'), f"{stem}{self.settings.get('lyrics_ext', '.lrc')}")
            ]
            for p in candidates:
                if os.path.exists(p):
                    with open(p, 'r', encoding='utf-8', errors='ignore') as f:
                        return f.read()
        except Exception:
            pass
        return ''

    def _fmt_size(self, n):
        for unit in ['B','KB','MB','GB','TB']:
            if n < 1024.0:
                return f"{n:.0f} {unit}"
            n /= 1024.0
        return f"{n:.0f} PB"

    def _fmt_mtime(self, ts):
        import datetime as _dt
        try:
            return _dt.datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M')
        except Exception:
            return ''


if __name__ == "__main__":
    app = App()
    app.mainloop()
