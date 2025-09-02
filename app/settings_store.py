import json
from core import CONFIG_PATH
import tkinter.messagebox as messagebox

DEFAULT_SETTINGS = {
    "music_root": str(CONFIG_PATH.parents[1]),
    "lyrics_subdir": "Lyrics",
    "lyrics_ext": ".lrc",
    "cover_size": "100x100",
    "cover_max": 100,
    "jobs": 4,
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


def save_settings(settings) -> bool:
    try:
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2)
        return True
    except Exception as e:
        try:
            messagebox.showerror("Error", f"Could not save settings: {e}")
        except Exception:
            pass
        return False

