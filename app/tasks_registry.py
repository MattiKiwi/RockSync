"""Registry for built-in and user-provided automation scripts.

This module exposes the list of tasks displayed in the Advanced tab.  Built-in
tasks are defined statically so they retain tight coupling with the repository.
User-provided scripts are discovered dynamically from a directory configured in
settings (default: `<app root>/user_scripts`).

Each task is a dictionary containing at least:

* `id`: stable identifier (string)
* `label`: human-readable label
* `script`: Path to the script (if applicable)
* `args`: list describing UI controls, following the existing schema
* `py_deps`/`bin_deps`: optional dependency hints

User scripts can ship an optional metadata file `<name>.rocksync.json` (or
`<name>.json` as fallback) that mirrors the built-in schema.  If no metadata is
present, RockSync falls back to a minimal specification with a single free-form
arguments field so scripts remain runnable via the UI.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence

from core import ROOT, SCRIPTS_DIR, USER_SCRIPTS_DIR
from settings_store import load_settings


LOGGER = logging.getLogger(__name__)


def _builtin_tasks() -> List[Dict[str, Any]]:
    """Return the built-in task specifications."""

    return [
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
            "id": "tag_genres",
            "label": "Tag Genres (MusicBrainz)",
            "script": SCRIPTS_DIR / "tag_genres.py",
            "args": [
                {"key": "--library", "label": "Library Root", "type": "path", "default": str(ROOT)},
                {"key": "--dry-run", "label": "Dry run (no write)", "type": "bool", "default": True},
                {"key": "--only-missing", "label": "Only fill missing genres", "type": "bool", "default": True},
                {"key": "--overwrite", "label": "Overwrite existing genres", "type": "bool", "default": False},
                {"key": "--use-tag-search", "label": "Use MusicBrainz tag search", "type": "bool", "default": False},
                {"key": "--folder-fallback", "label": "Fallback to folder name", "type": "bool", "default": False},
                {"key": "--max-genres", "label": "Max genres to write", "type": "int", "default": 5},
            ],
            "py_deps": ["mutagen", "musicbrainzngs"],
            "bin_deps": [],
        },
        {
            "id": "prune_genres",
            "label": "Keep First Genre",
            "script": SCRIPTS_DIR / "prune_genres.py",
            "args": [
                {"key": "--folder", "label": "Folder", "type": "path", "default": str(ROOT)},
                {"key": "--ext", "label": "Extensions (space-separated)", "type": "text", "default": ".mp3 .flac .m4a .aac .ogg .opus .wav .wv .aiff .ape .mpc"},
                {"key": "--dry-run", "label": "Dry Run", "type": "bool", "default": True},
            ],
            "py_deps": ["mutagen"],
            "bin_deps": [],
        },
        {
            "id": "sort_by_artist",
            "label": "Sort Folders by Artist",
            "script": SCRIPTS_DIR / "sort_by_artist.py",
            "args": [
                {"key": "--source", "label": "Source folder", "type": "path", "default": str(ROOT)},
                {"key": "--separator", "label": "Separator (Artist - Album)", "type": "text", "default": " - "},
                {"key": "--dry-run", "label": "Dry run", "type": "bool", "default": False},
            ],
            "py_deps": [],
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
            "py_deps": ["mutagen"],
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


def _resolve_user_scripts_dir(settings: Dict[str, Any] | None) -> Path:
    """Return the directory that should be scanned for user scripts."""

    base = (settings or {}).get("user_scripts_dir") or str(USER_SCRIPTS_DIR)
    try:
        path = Path(base).expanduser()
    except Exception:
        path = USER_SCRIPTS_DIR

    if not path.is_absolute():
        # Treat relative paths as relative to the application root
        path = (ROOT / path).resolve()
    return path


def _metadata_candidates(script_path: Path) -> Iterable[Path]:
    stem = script_path.stem
    parent = script_path.parent
    yield parent / f"{stem}.rocksync.json"
    yield parent / f"{stem}.json"


def _load_metadata(script_path: Path) -> Dict[str, Any]:
    for candidate in _metadata_candidates(script_path):
        if not candidate.exists():
            continue
        try:
            with open(candidate, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, dict):
                return data
            LOGGER.warning("Metadata for %s is not a JSON object", script_path)
        except Exception as exc:  # pragma: no cover - defensive
            LOGGER.warning("Could not load metadata for %s: %s", script_path, exc)
    return {}


def _normalise_sequence(value: Any) -> List[str]:
    if not value:
        return []
    if isinstance(value, str):
        return value.split()
    if isinstance(value, Sequence):
        return [str(v) for v in value]
    return [str(value)]


def _infer_runner(script_path: Path, metadata: Dict[str, Any]) -> Dict[str, Any]:
    """Determine how the script should be executed."""

    task_flags: Dict[str, Any] = {}
    command = metadata.get("command")
    if command:
        task_flags["command"] = _normalise_sequence(command)
        return task_flags

    interpreter = metadata.get("interpreter")
    if interpreter:
        task_flags["interpreter"] = _normalise_sequence(interpreter)
        return task_flags

    runner = metadata.get("runner")
    if runner:
        task_flags["runner"] = str(runner)
        return task_flags

    # Default behaviour: Python scripts via interpreter, others as executables
    if script_path.suffix.lower() == ".py":
        task_flags["runner"] = "python"
    else:
        task_flags["runner"] = "executable"
    return task_flags


def _ensure_default_args(metadata: Dict[str, Any]) -> List[Dict[str, Any]]:
    args = metadata.get("args")
    if isinstance(args, list):
        filtered = [a for a in args if isinstance(a, dict)]
        if filtered:
            return filtered
    # Fallback to a single free-form text field for CLI arguments
    return [
        {
            "key": "__argline__",
            "label": "Argument string",
            "type": "text",
            "default": "",
            "placeholder": "Example: --flag value --path /tmp",
        }
    ]


def _build_user_task(script_path: Path, metadata: Dict[str, Any]) -> Dict[str, Any]:
    label = metadata.get("label") or script_path.stem.replace("_", " ")
    task = {
        "id": metadata.get("id") or f"user:{script_path.stem}",
        "label": str(label),
        "display_label": metadata.get("display_label") or f"★ {label}",
        "description": metadata.get("description", ""),
        "script": script_path,
        "args": _ensure_default_args(metadata),
        "py_deps": metadata.get("py_deps", []),
        "bin_deps": metadata.get("bin_deps", []),
        "is_user_script": True,
    }
    task.update(_infer_runner(script_path, metadata))
    return task


def _collect_user_tasks(settings: Dict[str, Any] | None) -> List[Dict[str, Any]]:
    directory = _resolve_user_scripts_dir(settings)
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass  # directory creation is best-effort

    if not directory.exists() or not directory.is_dir():
        return []

    tasks: List[Dict[str, Any]] = []
    for script_path in sorted(directory.iterdir()):
        if not script_path.is_file():
            continue
        if script_path.suffix.lower() in {".json", ".yaml", ".yml"}:
            continue
        metadata = _load_metadata(script_path)
        task = _build_user_task(script_path, metadata)
        tasks.append(task)
    return tasks


def get_tasks(settings: Dict[str, Any] | None = None) -> List[Dict[str, Any]]:
    """Return the combined list of built-in and user-defined tasks."""

    settings = settings or load_settings()
    tasks = _builtin_tasks()
    tasks.extend(_collect_user_tasks(settings))
    return tasks

