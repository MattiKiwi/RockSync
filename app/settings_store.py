import json
from pathlib import Path
from core import CONFIG_PATH

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
    "lyrics_subdir": "Lyrics",
    "lyrics_ext": ".lrc",
    "cover_size": "100x100",
    "cover_max": 100,
    "jobs": 4,
    "genius_token": "",
    "lastfm_key": "",
    "debug": False,
    "theme_file": "modern-light.css",
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
    try:
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2)
        return True
    except Exception as e:
        # UI layer is responsible for showing errors
        return False
