import os
import sys
import shlex
import threading
import subprocess
import shutil
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"


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

        self._build_ui()

    def _build_ui(self):
        self.columnconfigure(0, weight=0)
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)
        self.rowconfigure(1, weight=0)

        # Task list
        left = ttk.Frame(self)
        left.grid(row=0, column=0, sticky="nsw", padx=8, pady=8)
        ttk.Label(left, text="Tasks").pack(anchor="w")
        self.task_list = tk.Listbox(left, height=20)
        self.task_list.pack(fill="both", expand=True)
        for t in TASKS:
            self.task_list.insert("end", t["label"]) 
        self.task_list.bind("<<ListboxSelect>>", self.on_task_select)

        # Right pane
        right = ttk.Frame(self)
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
                w.insert(0, str(spec.get("default", "")))
            elif spec["type"] == "int":
                w = ttk.Spinbox(self.form_frame, from_=1, to=1024)
                w.set(int(spec.get("default", 1)))
            elif spec["type"] == "bool":
                var = tk.BooleanVar(value=bool(spec.get("default", False)))
                w = ttk.Checkbutton(self.form_frame, variable=var)
                w.var = var
            elif spec["type"] == "path":
                path_frame = ttk.Frame(self.form_frame)
                entry = ttk.Entry(path_frame, width=60)
                entry.insert(0, str(spec.get("default", "")))
                entry.pack(side="left", fill="x", expand=True)
                btn = ttk.Button(path_frame, text="Browse", command=lambda e=entry: self.browse_dir(e))
                btn.pack(side="left", padx=4)
                w = path_frame
                w.entry = entry
            elif spec["type"] == "file":
                path_frame = ttk.Frame(self.form_frame)
                entry = ttk.Entry(path_frame, width=60)
                entry.insert(0, str(spec.get("default", "")))
                entry.pack(side="left", fill="x", expand=True)
                btn = ttk.Button(path_frame, text="Browse", command=lambda e=entry: self.browse_file(e))
                btn.pack(side="left", padx=4)
                w = path_frame
                w.entry = entry
            elif spec["type"] == "choice":
                w = ttk.Combobox(self.form_frame, values=spec.get("choices", []))
                w.set(spec.get("default", ""))
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


if __name__ == "__main__":
    app = App()
    app.mainloop()

