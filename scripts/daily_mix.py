#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
daily_mix.py — Auto-generate genre-weighted "Daily Mix" playlists for Rockbox.

Features
- Anchor genres to shape the mix (auto or user-specified).
- Weighted random selection with diversity constraints.
- Avoids back-to-back same artist; per-artist cap.
- Target duration (minutes) using audio lengths when available.
- Freshness boost for recently added tracks.
- Writes UTF-8 .m3u8 with relative paths (good for Rockbox).

Dependencies
- Optional: mutagen (pip install mutagen) for robust tags+durations.
  Without mutagen, script infers genre/artist/album from folders and
  estimates duration by track-count fallback.

Usage examples
--------------
Auto-pick genres, 75-minute mix, save to device Playlists:
    python daily_mix.py --library ~/Music --out-dir /media/ROCKBOX/Playlists \
        --target-min 75 --mix-name "Daily Mix"

Pick anchor genres explicitly:
    python daily_mix.py --library ~/Music --out-dir /media/ROCKBOX/Playlists \
        --target-min 60 --genres "Electronic" "Ambient"

Create 3 mixes, limit 2 tracks per artist, boost last 45 days:
    python daily_mix.py --library ~/Music --out-dir ./Playlists \
        --target-min 70 --mix-count 3 --per-artist-max 2 --fresh-days 45
"""

from __future__ import annotations
import argparse
import os
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
        tracks.append(Track(path=p, artist=artist or "Unknown Artist",
                            album=album or "Unknown Album",
                            title=title or p.stem,
                            genre=genre or "Unknown",
                            seconds=seconds, mtime=mtime))
    return tracks

def choose_anchor_genres(all_tracks: List[Track], desired_count: int = 3) -> List[str]:
    # frequency count
    freq: Dict[str, int] = {}
    for t in all_tracks:
        g = t.genre.strip() or "Unknown"
        freq[g] = freq.get(g, 0) + 1
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
    weighted: List[Tuple[Track, float]] = []
    for t in tracks:
        w = 1.0
        if t.genre in anchors:
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
            if len(playlist) >= approx_count:
                break
        playlist.append(nxt)
        used_paths.add(nxt.path)
        per_artist_counts[nxt.artist] = per_artist_counts.get(nxt.artist, 0) + 1
        last_artist = nxt.artist

        # small chance to inject a non-anchor after an anchor to keep variety
        # (handled implicitly by weights; no special logic needed here)

        # hard safety limit
        if len(playlist) >= 200:
            break

    return playlist

def write_m3u8(playlist_dir: Path, mix_name: str, tracks: List[Track]) -> Path:
    playlist_dir.mkdir(parents=True, exist_ok=True)
    safe_name = "".join(c for c in mix_name if c not in r'<>:"/\|?*').strip() or "Daily Mix"
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

# ---------- CLI ----------

def parse_args():
    ap = argparse.ArgumentParser(description="Generate genre-weighted Daily Mix playlists for Rockbox.")
    ap.add_argument("--library", type=Path, required=True, help="Path to your music library root.")
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

    tracks = scan_library(args.library)
    if not tracks:
        print("No audio files found.")
        return

    anchors = args.genres or choose_anchor_genres(tracks, desired_count=3)
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
