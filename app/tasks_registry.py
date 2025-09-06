import os
from core import ROOT, SCRIPTS_DIR


def get_tasks():
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
            "label": "Tag Genres (AcoustID + MusicBrainz)",
            "script": SCRIPTS_DIR / "tag_genres.py",
            "args": [
                {"key": "--library", "label": "Library Root", "type": "path", "default": str(ROOT)},
                {"key": "--dry-run", "label": "Dry run (no write)", "type": "bool", "default": True},
                {"key": "--only-missing", "label": "Only fill missing genres", "type": "bool", "default": True},
                {"key": "--overwrite", "label": "Overwrite existing genres", "type": "bool", "default": False},
                {"key": "--use-acoustid", "label": "Use AcoustID (fpcalc required)", "type": "bool", "default": False},
                {"key": "--use-tag-search", "label": "Use MusicBrainz tag search", "type": "bool", "default": False},
                {"key": "--folder-fallback", "label": "Fallback to folder name", "type": "bool", "default": False},
                {"key": "--max-genres", "label": "Max genres to write", "type": "int", "default": 5},
            ],
            # 'acoustid' and 'fpcalc' are optional; only needed if --use-acoustid is enabled
            "py_deps": ["mutagen", "musicbrainzngs"],
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
