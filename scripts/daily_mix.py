#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
daily_mix.py — Auto-generate genre-weighted "Daily Mix" playlists.

Now supports reading from the indexed SQLite database for either the
local Library or a connected Device, and ignores empty/unknown genres.

Features
- Anchor genres to shape the mix (auto or user-specified).
- Weighted random selection with diversity constraints.
- Avoids back-to-back same artist; per-artist cap.
- Target duration (minutes) using audio lengths when available.
- Freshness boost for recently added tracks.
- Writes UTF-8 .m3u8 with relative paths (good for Rockbox).

Dependencies
- Optional: mutagen (pip install mutagen) for robust tags+durations.
  Without mutagen, script infers tags from folders and estimates duration.

Usage examples
--------------
Using the Library DB and saving to device Playlists:
    python daily_mix.py --db-source library --out-dir /media/ROCKBOX/Playlists \
        --target-min 75 --mix-name "Daily Mix"

Using a device DB (detected at MOUNTPOINT/.rocksync/music_index.sqlite3):
    python daily_mix.py --db-source device --device-mount /media/ROCKBOX \
        --out-dir /media/ROCKBOX/Playlists --target-min 60

Fallback (no DB): scan a directory directly:
    python daily_mix.py --library ~/Music --out-dir ./Playlists --target-min 70
"""

from __future__ import annotations
import argparse
import os
import sqlite3
import sys
from pathlib import Path
import random
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

# ---------- Config ----------
AUDIO_EXTS = {".mp3", ".flac", ".ogg", ".opus", ".aac", ".m4a", ".wav", ".wv", ".aiff", ".ape", ".mpc"}

try:
    from mutagen import File as MutagenFile  # type: ignore
    _HAS_MUTAGEN = True
except Exception:
    _HAS_MUTAGEN = False

# Try to load CONFIG_PATH to locate the default Library DB
_CONFIG_PATH: Optional[Path] = None
try:
    here = Path(__file__).resolve()
    app_dir = here.parents[1] / 'app'
    if str(app_dir) not in sys.path:
        sys.path.append(str(app_dir))
    from core import CONFIG_PATH as _CP  # type: ignore
    _CONFIG_PATH = Path(_CP)
except Exception:
    _CONFIG_PATH = None

# ---------- Models ----------

@dataclass
class Track:
    path: Path
    artist: str
    album: str
    title: str
    genre: str
    seconds: Optional[int]  # None if unknown
    mtime: float            # for freshness (file modified time)

# ---------- Helpers ----------

def is_audio(p: Path) -> bool:
    return p.is_file() and p.suffix.lower() in AUDIO_EXTS

def relpath_for_playlist(track_path: Path, playlist_dir: Path) -> str:
    # Use forward slashes for Rockbox friendliness
    rp = os.path.relpath(track_path.resolve(), playlist_dir.resolve())
    return rp.replace("\\", "/")

def read_tags(p: Path) -> Tuple[str, str, str, str, Optional[int]]:
    """
    Returns (artist, album, title, genre, seconds)
    Falls back to folder heuristics and filename if mutagen unavailable.
    """
    artist = album = title = genre = ""
    seconds: Optional[int] = None

    if _HAS_MUTAGEN:
        try:
            mf = MutagenFile(str(p), easy=True)
            if mf:
                def first(keys, default=""):
                    for k in keys:
                        if k in mf and mf[k]:
                            return str(mf[k][0]).strip()
                    return default

                artist = first(["albumartist", "artist", "ALBUMARTIST", "ARTIST"])
                album  = first(["album", "ALBUM"])
                title  = first(["title", "TITLE"]) or p.stem
                genre  = first(["genre", "GENRE"])
                # duration
                try:
                    mf2 = MutagenFile(str(p))  # non-easy for length
                    if hasattr(mf2, "info") and getattr(mf2.info, "length", None):
                        seconds = int(mf2.info.length)
                except Exception:
                    pass
        except Exception:
            pass

    # Heuristics if missing
    if not artist:
        artist = p.parent.parent.name if p.parent and p.parent.parent else ""
    if not album:
        album = p.parent.name if p.parent else ""
    if not title:
        title = p.stem
    if not genre:
        # crude guess: use top-level folder name if it looks like a genre
        top = p.parents[len(p.parents)-2].name if len(p.parents) >= 2 else ""
        genre = top if top.lower() in {"rock","pop","electronic","ambient","jazz","classical",
                                       "hip hop","hip-hop","rap","metal","blues","country",
                                       "folk","soul","r&b","rb","techno","house","trance",
                                       "soundtrack"} else ""

    return artist, album, title, genre, seconds

_BAD_GENRES = {"", "unknown", "(unknown)", "undef", "undefined", "n/a", "none", "genre:"}

def _split_genre_tokens(genre: str) -> List[str]:
    # Split on common separators seen in tags and UIs
    if not genre:
        return []
    raw = [genre]
    # Expand splits progressively
    seps = [';', '|', '/', ',']
    for sep in seps:
        tmp = []
        for item in raw:
            tmp.extend(item.split(sep))
        raw = tmp
    return [t.strip() for t in raw if t.strip()]

def is_valid_genre(genre: str) -> bool:
    # A genre string is valid if any token is valid
    tokens = _split_genre_tokens(genre)
    if not tokens:
        return False
    for t in tokens:
        if (t or '').strip().lower() not in _BAD_GENRES:
            return True
    return False

def scan_library(root: Path) -> List[Track]:
    tracks: List[Track] = []
    for p in root.rglob("*"):
        if not is_audio(p):
            continue
        artist, album, title, genre, seconds = read_tags(p)
        try:
            mtime = p.stat().st_mtime
        except Exception:
            mtime = time.time()
        g = (genre or "").strip()
        if not is_valid_genre(g):
            # Ignore empty/unknown genres
            continue
        tracks.append(Track(path=p, artist=artist or "Unknown Artist",
                            album=album or "Unknown Album",
                            title=title or p.stem,
                            genre=g,
                            seconds=seconds, mtime=mtime))
    return tracks

def choose_anchor_genres(all_tracks: List[Track], desired_count: int = 3) -> List[str]:
    # frequency count
    freq: Dict[str, int] = {}
    for t in all_tracks:
        g = t.genre.strip()
        if not is_valid_genre(g):
            continue
        for tok in _split_genre_tokens(g):
            if (tok or '').strip().lower() in _BAD_GENRES:
                continue
            freq[tok] = freq.get(tok, 0) + 1
    # pick top-N but add slight randomness
    ranked = sorted(freq.items(), key=lambda kv: kv[1], reverse=True)
    top = [g for g, _ in ranked[:max(2, desired_count + 2)]]
    random.shuffle(top)
    return sorted(list(dict.fromkeys(top[:desired_count])))

def weight_tracks(tracks: List[Track],
                  anchors: List[str],
                  fresh_days: Optional[int]) -> List[Tuple[Track, float]]:
    """
    Assign a sampling weight to each track:
      - Base weight 1.0
      - If genre in anchors: +1.0
      - If fresh_days set and file modified within window: +0.5
    """
    now = time.time()
    window = (fresh_days or 0) * 86400
    anchors_lc = {a.strip().lower() for a in anchors}
    weighted: List[Tuple[Track, float]] = []
    for t in tracks:
        w = 1.0
        toks = _split_genre_tokens(t.genre)
        if any(tok.strip().lower() in anchors_lc for tok in toks):
            w += 1.0
        if fresh_days and (now - t.mtime) <= window:
            w += 0.5
        weighted.append((t, w))
    return weighted

def pick_next(candidates: List[Tuple[Track, float]],
              used_paths: set,
              last_artist: Optional[str],
              per_artist_counts: Dict[str, int],
              per_artist_max: int) -> Optional[Track]:
    # Filter out used and over-cap artists; avoid same-artist adjacency
    filtered = [(t, w) for (t, w) in candidates
                if t.path not in used_paths
                and per_artist_counts.get(t.artist, 0) < per_artist_max
                and (last_artist is None or t.artist != last_artist)]
    if not filtered:
        # relax adjacency rule if needed
        filtered = [(t, w) for (t, w) in candidates
                    if t.path not in used_paths
                    and per_artist_counts.get(t.artist, 0) < per_artist_max]
    if not filtered:
        return None
    # Weighted random
    weights = [w for _, w in filtered]
    choice = random.choices(filtered, weights=weights, k=1)[0][0]
    return choice

def build_mix(tracks: List[Track],
              anchors: List[str],
              target_minutes: int,
              per_artist_max: int,
              fresh_days: Optional[int]) -> List[Track]:
    # Prepare weighted pool
    pool = weight_tracks(tracks, anchors=anchors, fresh_days=fresh_days)
    total_seconds_target = target_minutes * 60
    used_paths: set = set()
    per_artist_counts: Dict[str, int] = {}
    playlist: List[Track] = []
    last_artist: Optional[str] = None
    running_seconds = 0
    # Fallback if durations unknown: aim for ~18 tracks per 75 min => ~ target_minutes * 0.24
    approx_count = max(10, int(target_minutes * 0.24)) if not any(t.seconds for t, _ in pool) else None

    while True:
        nxt = pick_next(pool, used_paths, last_artist, per_artist_counts, per_artist_max)
        if not nxt:
            break
        dur = nxt.seconds or 240  # assume 4 min if unknown
        # stop if adding would significantly overshoot (unless playlist is too short)
        if any(t.seconds for t, _ in pool):
            if running_seconds > 0 and running_seconds + dur > total_seconds_target + 120:
                break
            running_seconds += dur
        else:
            # duration unknown: use approximate track count
            if len(playlist) >= approx_count:  # type: ignore[arg-type]
                break
        playlist.append(nxt)
        used_paths.add(nxt.path)
        per_artist_counts[nxt.artist] = per_artist_counts.get(nxt.artist, 0) + 1
        last_artist = nxt.artist

        # hard safety limit
        if len(playlist) >= 200:
            break

    return playlist

def write_m3u8(playlist_dir: Path, mix_name: str, tracks: List[Track]) -> Path:
    playlist_dir.mkdir(parents=True, exist_ok=True)
    safe_name = "".join(c for c in mix_name if c not in r'<>:"/\\|?*').strip() or "Daily Mix"
    ts = time.strftime("%Y-%m-%d")
    out = playlist_dir / f"{safe_name} - {ts}.m3u8"
    lines = ["#EXTM3U"]
    for t in tracks:
        if t.seconds is not None:
            lines.append(f"#EXTINF:{t.seconds},{t.artist} - {t.title}")
        rp = relpath_for_playlist(t.path, playlist_dir)
        lines.append(rp)
    out.write_text("\n".join(lines), encoding="utf-8")
    return out

# ---------- DB integration ----------

def load_tracks_from_db(db_path: Path) -> List[Track]:
    tracks: List[Track] = []
    if not db_path.exists():
        return tracks
    try:
        with sqlite3.connect(str(db_path)) as conn:
            cur = conn.execute(
                "SELECT path, artist, album, title, IFNULL(genre,''), IFNULL(duration_seconds,0), IFNULL(mtime,0) FROM tracks"
            )
            for (path, artist, album, title, genre, dur, mtime) in cur.fetchall():
                g = (genre or "").strip()
                if not is_valid_genre(g):
                    continue
                try:
                    p = Path(path)
                except Exception:
                    continue
                seconds = int(dur) if dur else None
                mt = float(mtime) if mtime else time.time()
                tracks.append(Track(path=p,
                                    artist=(artist or '').strip() or 'Unknown Artist',
                                    album=(album or '').strip() or 'Unknown Album',
                                    title=(title or '').strip() or p.stem,
                                    genre=g,
                                    seconds=seconds,
                                    mtime=mt))
    except Exception:
        return []
    return tracks

def resolve_db_path(db: Optional[Path], db_source: Optional[str], device_mount: Optional[Path]) -> Optional[Path]:
    if db:
        return db
    if (db_source or '').lower() == 'library':
        if _CONFIG_PATH is not None:
            return _CONFIG_PATH.with_name('music_index.sqlite3')
        # Fallback: repo/app/music_index.sqlite3
        return (Path(__file__).resolve().parents[1] / 'app' / 'music_index.sqlite3')
    if (db_source or '').lower() == 'device':
        if device_mount:
            return device_mount / '.rocksync' / 'music_index.sqlite3'
    return None

# ---------- CLI ----------

def parse_args():
    ap = argparse.ArgumentParser(description="Generate genre-weighted Daily Mix playlists (DB-aware).")
    src = ap.add_mutually_exclusive_group(required=False)
    src.add_argument("--library", type=Path, help="Scan this library folder directly (fallback if no DB).")
    ap.add_argument("--db", type=Path, help="Path to music_index.sqlite3 to read tracks from.")
    ap.add_argument("--db-source", choices=["library", "device"], help="Use the indexed DB for Library or Device.")
    ap.add_argument("--device-mount", type=Path, help="Device mountpoint when using --db-source device.")

    ap.add_argument("--out-dir", type=Path, required=True, help="Where to save .m3u8 playlists (PC or device).")
    ap.add_argument("--mix-name", type=str, default="Daily Mix", help="Base name for the playlist(s).")
    ap.add_argument("--target-min", type=int, default=75, help="Target playlist length in minutes.")
    ap.add_argument("--genres", nargs="*", default=None, help="Anchor genres to bias toward (if omitted, auto-picks).")
    ap.add_argument("--mix-count", type=int, default=1, help="How many mixes to create.")
    ap.add_argument("--per-artist-max", type=int, default=2, help="Max tracks from the same artist in a mix.")
    ap.add_argument("--fresh-days", type=int, default=None, help="Boost tracks modified within N days.")
    ap.add_argument("--seed", type=int, default=None, help="Random seed for reproducibility.")
    return ap.parse_args()

def main():
    args = parse_args()
    if args.seed is not None:
        random.seed(args.seed)

    # Prefer DB if provided/selected
    db_path = resolve_db_path(args.db, args.db_source, args.device_mount)
    tracks: List[Track]
    if db_path is not None and db_path.exists():
        tracks = load_tracks_from_db(db_path)
    else:
        # Fallback to scanning a folder if provided
        lib = args.library
        if not lib:
            print("No DB found/selected and no --library provided.")
            return
        tracks = scan_library(lib)
    if not tracks:
        print("No audio files found.")
        return

    # Clean provided anchors and ignore unknowns
    provided = None
    if args.genres:
        provided = [g for g in (args.genres or []) if is_valid_genre(str(g))]
    anchors = provided or choose_anchor_genres(tracks, desired_count=3)
    print(f"Anchor genres: {', '.join(anchors)}")

    for i in range(args.mix_count):
        mix = build_mix(tracks, anchors=anchors, target_minutes=args.target_min,
                        per_artist_max=args.per_artist_max, fresh_days=args.fresh_days)
        if not mix:
            print("Could not build a mix (insufficient tracks?).")
            break
        name = args.mix_name if args.mix_count == 1 else f"{args.mix_name} #{i+1}"
        out = write_m3u8(args.out_dir, name, mix)
        total_sec = sum(t.seconds or 240 for t in mix)
        mins = total_sec // 60
        print(f"✅ Wrote {out} ({len(mix)} tracks, ~{mins} min)")

if __name__ == "__main__":
    main()
