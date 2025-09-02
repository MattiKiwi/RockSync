import os
import sys
import shlex
import threading
import subprocess
import uuid
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from core import ROOT, cmd_exists
from settings_store import load_settings, save_settings
from logging_utils import setup_logging, ui_log
from tasks_registry import get_tasks
from ui.explorer_pane import ExplorerPane
from ui.tracks_pane import TracksPane
from theme import apply_theme
from theme_loader import list_theme_files


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("RockSync GUI")
        self.geometry("1000x650")

        self.proc = None
        self.proc_thread = None
        self.settings = load_settings()
        self.session_id = str(uuid.uuid4())[:8]
        self.logger = setup_logging(self.settings, self.session_id)

        self._build_ui()

    # --------------- UI skeleton ---------------
    def _build_ui(self):
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)

        self.tabs = ttk.Notebook(self)
        self.tabs.grid(row=0, column=0, sticky="nsew")

        # Tasks tab
        self.run_tab = ttk.Frame(self.tabs)
        self.tabs.add(self.run_tab, text="Tasks")
        self._build_run_tab(self.run_tab)

        # Explorer tab
        self.explore_tab = ttk.Frame(self.tabs)
        self.tabs.add(self.explore_tab, text="Explorer")
        # Allow child to expand to full tab area
        self.explore_tab.rowconfigure(0, weight=1)
        self.explore_tab.columnconfigure(0, weight=1)
        self.explorer = ExplorerPane(self, self.explore_tab)

        # Tracks tab
        self.tracks_tab = ttk.Frame(self.tabs)
        self.tabs.add(self.tracks_tab, text="Tracks")
        self.tracks_tab.rowconfigure(0, weight=1)
        self.tracks_tab.columnconfigure(0, weight=1)
        self.tracks = TracksPane(self, self.tracks_tab)

        # Settings tab
        self.settings_tab = ttk.Frame(self.tabs)
        self.tabs.add(self.settings_tab, text="Settings")
        self._build_settings_tab(self.settings_tab)

        # Status bar
        self.status = tk.StringVar(value=f"Music root: {self.settings.get('music_root')}")
        status_bar = ttk.Label(self, textvariable=self.status, anchor="w")
        status_bar.grid(row=1, column=0, sticky="ew")
        # Apply theme after UI exists
        self._apply_theme()

    # --------------- Settings tab ---------------
    def _build_settings_tab(self, parent):
        parent.columnconfigure(1, weight=1)
        row = 0

        def add_row(label, widget):
            nonlocal row
            ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=8, pady=6)
            widget.grid(row=row, column=1, sticky="ew", padx=8, pady=6)
            row += 1

        music_frame = ttk.Frame(parent)
        self.set_music_root = ttk.Entry(music_frame)
        self.set_music_root.insert(0, self.settings.get("music_root", str(ROOT)))
        self.set_music_root.pack(side="left", fill="x", expand=True)
        ttk.Button(music_frame, text="Browse", command=lambda: self.browse_dir(self.set_music_root)).pack(side="left", padx=4)
        add_row("Music root", music_frame)

        self.set_lyrics_subdir = ttk.Entry(parent)
        self.set_lyrics_subdir.insert(0, self.settings.get("lyrics_subdir", "Lyrics"))
        add_row("Lyrics subfolder", self.set_lyrics_subdir)

        self.set_lyrics_ext = ttk.Entry(parent)
        self.set_lyrics_ext.insert(0, self.settings.get("lyrics_ext", ".lrc"))
        add_row("Lyrics extension", self.set_lyrics_ext)

        self.set_cover_size = ttk.Entry(parent)
        self.set_cover_size.insert(0, self.settings.get("cover_size", "100x100"))
        add_row("Cover size (WxH)", self.set_cover_size)

        self.set_cover_max = ttk.Spinbox(parent, from_=50, to=2000)
        self.set_cover_max.set(int(self.settings.get("cover_max", 100)))
        add_row("Cover max (px)", self.set_cover_max)

        self.set_jobs = ttk.Spinbox(parent, from_=1, to=1024)
        self.set_jobs.set(int(self.settings.get("jobs", os.cpu_count() or 4)))
        add_row("Default jobs", self.set_jobs)

        self.set_genius = ttk.Entry(parent, show="*")
        self.set_genius.insert(0, self.settings.get("genius_token", ""))
        add_row("Genius token", self.set_genius)

        self.set_lastfm = ttk.Entry(parent)
        self.set_lastfm.insert(0, self.settings.get("lastfm_key", ""))
        add_row("Last.fm API key", self.set_lastfm)

        self.debug_var = tk.BooleanVar(value=bool(self.settings.get("debug", False)))
        dbg_cb = ttk.Checkbutton(parent, text="Enable verbose debug logging (writes to app/debug.log)", variable=self.debug_var)
        add_row("Debug", dbg_cb)

        # Theme selector
        theme_options = ['system'] + list_theme_files()
        # Back-compat: migrate old 'theme' to 'theme_file' if present
        if 'theme_file' not in self.settings and 'theme' in self.settings:
            self.settings['theme_file'] = self.settings['theme']
        self.theme_box = ttk.Combobox(parent, values=theme_options, state='readonly')
        self.theme_box.set(self.settings.get('theme_file', 'system'))
        add_row("Theme", self.theme_box)

        btns = ttk.Frame(parent)
        ttk.Button(btns, text="Save Settings", command=self.on_save_settings).pack(side="left")
        ttk.Button(btns, text="Reload", command=self.on_reload_settings).pack(side="left", padx=6)
        btns.grid(row=row, column=0, columnspan=2, sticky="w", padx=8, pady=8)

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
        self.settings["theme_file"] = self.theme_box.get()
        if save_settings(self.settings):
            self.status.set(f"Music root: {self.settings.get('music_root')}")
            messagebox.showinfo("Settings", "Settings saved.")
            self._reconfigure_logging()
            self._apply_theme()

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
        self.theme_box.set(self.settings.get('theme_file', 'system'))
        self.status.set(f"Music root: {self.settings.get('music_root')}")
        self._reconfigure_logging()
        self._apply_theme()

    def _reconfigure_logging(self):
        self.logger = setup_logging(self.settings, self.session_id)

    def _apply_theme(self):
        # Persist selected theme into current settings (not saved until Save)
        sel = getattr(self, 'theme_box', None)
        if sel is not None:
            self.settings['theme_file'] = sel.get()
        palette = apply_theme(self, self.settings.get('theme_file', 'system'))
        # Non-ttk widgets coloring
        text_bg = palette.get('surface', '#FFFFFF')
        text_fg = palette.get('text', '#000000')
        try:
            self.output.configure(background=text_bg, foreground=text_fg, insertbackground=text_fg)
        except Exception:
            pass
        try:
            self.explorer.meta_text.configure(background=text_bg, foreground=text_fg, insertbackground=text_fg)
            self.explorer.lyrics_text.configure(background=text_bg, foreground=text_fg, insertbackground=text_fg)
        except Exception:
            pass

    # --------------- Utility helpers ---------------
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

    # --------------- Placeholder tabs ---------------
    # Note: For brevity, this refactor focuses on moving structure; pane internals can be further split next.
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
        self.tasks = get_tasks()
        for t in self.tasks:
            self.task_list.insert("end", t["label"])
        self.task_list.bind("<<ListboxSelect>>", self.on_task_select)

        # Right pane
        right = ttk.Frame(parent)
        right.grid(row=0, column=1, sticky="nsew", padx=8, pady=8)
        right.rowconfigure(2, weight=1)
        right.columnconfigure(0, weight=1)

        self.form_frame = ttk.LabelFrame(right, text="Parameters")
        self.form_frame.grid(row=0, column=0, sticky="ew")
        self.form_frame.columnconfigure(1, weight=1)
        self.form_widgets = {}

        actions = ttk.Frame(right)
        actions.grid(row=1, column=0, sticky="ew", pady=(8, 8))
        actions.columnconfigure(0, weight=1)
        self.run_btn = ttk.Button(actions, text="Run", command=self.run_task)
        self.run_btn.grid(row=0, column=1, sticky="e")
        self.stop_btn = ttk.Button(actions, text="Stop", command=self.stop_task)
        self.stop_btn.grid(row=0, column=2, sticky="e", padx=(8, 0))

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

    def on_task_select(self, event=None):
        idxs = self.task_list.curselection()
        if not idxs:
            return
        idx = idxs[0]
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
        for w in self.form_frame.winfo_children():
            w.destroy()
        self.form_widgets.clear()
        row = 0
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
            ttk.Label(self.form_frame, text=f"Missing deps: {', '.join(missing)}", foreground="#b00").grid(row=row, column=0, columnspan=3, sticky="w", padx=8, pady=(8, 4))
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
        ui_log('build_cmd', cmd=cmd, task=task.get('label'))
        return cmd

    def append_output(self, text):
        self.output.insert("end", text)
        self.output.see("end")

    def run_task(self):
        idxs = self.task_list.curselection()
        if not idxs:
            messagebox.showwarning("No task", "Please select a task")
            return
        task = self.tasks[idxs[0]]
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
                ui_log('run_task_end', rc=rc)
            except Exception as e:
                self.append_output(f"\n[Error] {e}\n")
                self.logger.exception("Process error")
                ui_log('run_task_error', error=str(e))
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
                ui_log('stop_task')
            except Exception as e:
                self.append_output(f"\n[Error stopping] {e}\n")

    # Explorer + Tracks are still in this module for now, but can be split further.
    # For brevity, omit re-implementing those; your current main.py contains the full explorer and tracks logic
    # which can be moved here incrementally. This refactor separates settings/logging/tasks first.

    # Explorer context menu and quick task dialog
    def _show_folder_menu(self, folder_path, event):
        menu = tk.Menu(self, tearoff=0)
        for task in self.tasks:
            if self._task_accepts_folder(task):
                menu.add_command(label=f"Use: {task['label']}", command=lambda t=task: self._open_task_with_folder(t, folder_path))
        if not menu.index('end'):
            menu.add_command(label="No folder tasks found", state='disabled')
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            try:
                menu.grab_release()
            except Exception:
                pass

    def _task_accepts_folder(self, task):
        folder_keys = {"--folder", "--root", "--source", "--base-dir", "base", "source", "--music-dir"}
        for spec in task.get('args', []):
            if spec.get('type') == 'path' and spec.get('key') in folder_keys:
                return True
        return False

    def _open_task_with_folder(self, task, folder_path):
        self.open_quick_task(task, folder_path)

    def open_quick_task(self, task, folder_path):
        dlg = tk.Toplevel(self)
        dlg.title(f"Quick Task: {task.get('label')}")
        dlg.transient(self)
        try:
            dlg.grab_set()
        except Exception:
            pass
        dlg.columnconfigure(1, weight=1)

        row = 0
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
                try:
                    w.set(int(default_val))
                except Exception:
                    w.set(1)
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

        close_var = tk.BooleanVar(value=True)
        add_row('Close this window on Run', ttk.Checkbutton(dlg, variable=close_var))

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
            ui_log('quick_task_run', task=task.get('label'), folder_path=folder_path, cmd=cmd)
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


def run():
    app = App()
    app.mainloop()
