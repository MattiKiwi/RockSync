import json
from pathlib import Path
try:
    from core import CONFIG_PATH, USER_SCRIPTS_DIR
except ImportError:
    from app.core import CONFIG_PATH, USER_SCRIPTS_DIR


def _default_music_root() -> str:
    """Return a sensible cross-platform default Music folder.
    - Windows/macOS/Linux: use ~/Music
    - If the folder does not exist, still return the path so the user can create it.
    """
    try:
        return str(Path.home() / "Music")
    except Exception:
        # Last-resort fallback to current directory
        return str(Path.cwd())


DEFAULT_SETTINGS = {
    "music_root": _default_music_root(),
    "dummy_device_path": "",
    "dummy_device_enabled": False,
    # Path to ffmpeg (binary or directory containing ffmpeg/ffprobe). Optional.
    # If empty, tools will rely on PATH.
    "ffmpeg_path": "",
    "lyrics_subdir": "Lyrics",
    "lyrics_ext": ".lrc",
    "cover_size": "100x100",
    "cover_max": 100,
    "jobs": 4,
    "genius_token": "",
    "lastfm_key": "",
    "debug": False,
    "theme_file": "modern-light.css",
    "user_scripts_dir": str(USER_SCRIPTS_DIR),
    # Optional add-ons visibility
    "enable_youtube": False,
    "enable_tidal": False,
    # Downsampling presets (user-editable)
    "downsample_presets": [
        {"name": "16-bit 44.1 kHz (lossless)", "bits": 16, "rate": 44100},
        {"name": "16-bit 48 kHz (lossless)", "bits": 16, "rate": 48000},
    ],
    "downsample_last": "16-bit 44.1 kHz (lossless)",
    # YouTube pane defaults (editable presets)
    "youtube_profiles": [
        {"name": "Preset: Best Audio (m4a)", "args": "--extract-audio -f \"ba[ext=m4a]/ba/bestaudio\" --embed-thumbnail --embed-metadata"},
        {"name": "Preset: Best Audio (flac)", "args": "--extract-audio -f \"ba[ext=m4a]/ba/bestaudio\" --audio-format flac --embed-thumbnail --embed-metadata"},
        {"name": "Preset: Best Video (mp4)", "args": "-f 'bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/best' --embed-thumbnail --embed-metadata"},
        {"name": "Preset: Playlist Audio (indexed)",
         "args": "--yes-playlist --extract-audio -f \"ba[ext=m4a]/ba/bestaudio\" -o '%(playlist_title)s/%(playlist_index|02d)s. %(title)s.%(ext)s' --embed-thumbnail --embed-metadata"},
        {"name": "Preset: Video Split Chapters",
         "args": "--split-chapters -f \"ba[ext=m4a]/ba/bestaudio\" --extract-audio -o 'chapter:%(title)s/%(section_number|02d)s. %(section_title)s.%(ext)s' --embed-thumbnail --embed-metadata"},
    ],
    "youtube_last_profile": "",
    "youtube_default_dest": _default_music_root(),
    "youtube_use_cookies": False,
    "youtube_cookie_browser": "firefox",
    "youtube_cookie_file": "",
    # Daily Mix genre presets
    "daily_mix_genre_presets": [],
    "daily_mix_last_preset": "",
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


def save_settings(settings) -> bool:
    """Persist settings without discarding keys written by other parts of the app.

    - Loads the current on-disk JSON (if any)
    - Deep-merges provided settings into it (dict values merged, others replaced)
    - Writes the merged result atomically
    """
    def _deep_merge(dst, src):
        try:
            # Merge src into dst in-place, returning dst
            if isinstance(dst, dict) and isinstance(src, dict):
                for k, v in src.items():
                    if k in dst and isinstance(dst[k], dict) and isinstance(v, dict):
                        _deep_merge(dst[k], v)
                    else:
                        dst[k] = v
                return dst
            # Not both dicts: replace
            return src
        except Exception:
            return src

    try:
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        current = {}
        if CONFIG_PATH.exists():
            try:
                with open(CONFIG_PATH, "r", encoding="utf-8") as rf:
                    current = json.load(rf) or {}
            except Exception:
                current = {}
        merged = _deep_merge(current if isinstance(current, dict) else {}, settings or {})
        tmp_path = CONFIG_PATH.with_suffix(CONFIG_PATH.suffix + ".tmp")
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(merged, f, indent=2)
        tmp_path.replace(CONFIG_PATH)
        return True
    except Exception:
        # UI layer is responsible for showing errors
        return False
