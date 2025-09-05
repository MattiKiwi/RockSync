#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
daily_mix.py — Thematic "Daily Mix" playlists with deterministic daily seed.

What’s new vs. your version
- Deterministic daily theme chosen by date + optional --seed
- Theme = (primary genre token [+ decade]) picked from your catalog
- Anchor tracks inside the theme (one representative, one fresh)
- Similarity-driven candidate ranking:
    sim = 0.55*genre_jaccard + 0.25*artist/album boost + 0.20*year proximity
- Explore/exploit balance (mix in ~25% lower-familiarity but on-theme)
- Flow-aware ordering (greedy nearest-neighbor + small local improvements)

Keeps:
- Your DB/scan inputs, m3u8 output, per-artist cap, freshness boost flag

New optional flags
--daily-seed / --no-daily-seed   Use today’s date to make a stable mix for the day (default: on)
--theme-era                       Try to pin the theme to a decade when years exist (default: on)
--explore-rate FLOAT              Fraction of exploratory picks (default: 0.25)
--max-per-album INT               Max tracks per album (default: 1)
--theme-size-min INT              Minimum tracks needed to call it a theme (default: 60)
--theme-genre GENRE               Force the theme’s primary genre token (overrides auto)
--theme-era-spec YYYYs            Force theme decade (e.g., 1990s); requires some year data

Usage (same as before, plus new flags if you like)
    python daily_mix.py --db-source library --out-dir /media/ROCKBOX/Playlists \
        --target-min 75 --mix-name "Daily Mix"

"""

from __future__ import annotations
import argparse
import os
import re
import sqlite3
import sys
from pathlib import Path
import random
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple, Iterable, Set

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
    seconds: Optional[int]         # None if unknown
    mtime: float                   # for freshness (file modified time)
    year: Optional[int] = None     # optional (parsed from tags/path)
    genre_tokens: Optional[Set[str]] = None  # filled later

# ---------- Helpers ----------

_BAD_GENRES = {"", "unknown", "(unknown)", "undef", "undefined", "n/a", "none", "genre:"}

def is_audio(p: Path) -> bool:
    return p.is_file() and p.suffix.lower() in AUDIO_EXTS

def relpath_for_playlist(track_path: Path, playlist_dir: Path) -> str:
    rp = os.path.relpath(track_path.resolve(), playlist_dir.resolve())
    return rp.replace("\\", "/")

def _split_genre_tokens(genre: str) -> List[str]:
    if not genre:
        return []
    raw = [genre]
    for sep in [';', '|', '/', ',']:
        tmp: List[str] = []
        for item in raw:
            tmp.extend(item.split(sep))
        raw = tmp
    return [t.strip() for t in raw if t.strip()]

def is_valid_genre(genre: str) -> bool:
    tokens = _split_genre_tokens(genre)
    if not tokens:
        return False
    for t in tokens:
        if (t or '').strip().lower() not in _BAD_GENRES:
            return True
    return False

_YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")

def _parse_year_from_str(s: str) -> Optional[int]:
    if not s:
        return None
    m = _YEAR_RE.search(s)
    if not m:
        return None
    try:
        y = int(m.group(0))
        if 1900 <= y <= 2100:
            return y
    except Exception:
        pass
    return None

def read_tags(p: Path) -> Tuple[str, str, str, str, Optional[int], Optional[int]]:
    """
    Returns (artist, album, title, genre, seconds, year)
    Falls back to folder heuristics and filename if mutagen unavailable.
    """
    artist = album = title = genre = ""
    seconds: Optional[int] = None
    year: Optional[int] = None

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
                year_s = first(["date", "year", "originaldate", "ORIGINALDATE"])
                # normalize year if it's like "1999-05-04"
                if year_s:
                    y = _parse_year_from_str(year_s)
                    if y:
                        year = y
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
        top = p.parents[len(p.parents)-2].name if len(p.parents) >= 2 else ""
        genre = top if top.lower() in {
            "rock","pop","electronic","ambient","jazz","classical","hip hop","hip-hop","rap",
            "metal","blues","country","folk","soul","r&b","rb","techno","house","trance","soundtrack"
        } else ""

    if year is None:
        # Try album or path
        year = _parse_year_from_str(album) or _parse_year_from_str(str(p))

    return artist, album, title, genre, seconds, year

def scan_library(root: Path) -> List[Track]:
    tracks: List[Track] = []
    for p in root.rglob("*"):
        if not is_audio(p):
            continue
        artist, album, title, genre, seconds, year = read_tags(p)
        try:
            mtime = p.stat().st_mtime
        except Exception:
            mtime = time.time()
        g = (genre or "").strip()
        if not is_valid_genre(g):
            continue
        toks = {t.lower() for t in _split_genre_tokens(g)}
        tracks.append(Track(path=p, artist=artist or "Unknown Artist",
                            album=album or "Unknown Album",
                            title=title or p.stem,
                            genre=g,
                            seconds=seconds, mtime=mtime,
                            year=year, genre_tokens=toks))
    return tracks

# ---------- DB integration (unchanged, but now fills year/tokens when possible) ----------

def load_tracks_from_db(db_path: Path) -> List[Track]:
    tracks: List[Track] = []
    if not db_path.exists():
        return tracks
    try:
        with sqlite3.connect(str(db_path)) as conn:
            # Adjust if your schema differs; year column optional
            cols = "path, artist, album, title, IFNULL(genre,''), IFNULL(duration_seconds,0), IFNULL(mtime,0)"
            # Try to see if there's a 'year' column
            has_year = False
            try:
                cur = conn.execute("PRAGMA table_info(tracks)")
                names = [r[1].lower() for r in cur.fetchall()]
                has_year = "year" in names
            except Exception:
                pass
            if has_year:
                cols += ", IFNULL(year,0)"
            cur = conn.execute(f"SELECT {cols} FROM tracks")
            for row in cur.fetchall():
                if has_year:
                    (path, artist, album, title, genre, dur, mtime, year_val) = row
                else:
                    (path, artist, album, title, genre, dur, mtime) = row
                    year_val = 0
                g = (genre or "").strip()
                if not is_valid_genre(g):
                    continue
                try:
                    p = Path(path)
                except Exception:
                    continue
                seconds = int(dur) if dur else None
                mt = float(mtime) if mtime else time.time()
                y: Optional[int] = int(year_val) if year_val else None
                if y is None:
                    # fallback parse from album/path if DB lacks year
                    y = _parse_year_from_str(album) or _parse_year_from_str(str(p))
                toks = {t.lower() for t in _split_genre_tokens(g)}
                tracks.append(Track(path=p,
                                    artist=(artist or '').strip() or 'Unknown Artist',
                                    album=(album or '').strip() or 'Unknown Album',
                                    title=(title or '').strip() or p.stem,
                                    genre=g,
                                    seconds=seconds,
                                    mtime=mt,
                                    year=y,
                                    genre_tokens=toks))
    except Exception:
        return []
    return tracks

def resolve_db_path(db: Optional[Path], db_source: Optional[str], device_mount: Optional[Path]) -> Optional[Path]:
    if db:
        return db
    if (db_source or '').lower() == 'library':
        if _CONFIG_PATH is not None:
            return _CONFIG_PATH.with_name('music_index.sqlite3')
        return (Path(__file__).resolve().parents[1] / 'app' / 'music_index.sqlite3')
    if (db_source or '').lower() == 'device':
        if device_mount:
            return device_mount / '.rocksync' / 'music_index.sqlite3'
    return None

# ---------- Theme & similarity ----------

def decade_of(year: int) -> int:
    return (year // 10) * 10

def jaccard(a: Set[str], b: Set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    if inter == 0:
        return 0.0
    union = len(a | b)
    return inter / union if union else 0.0

def year_affinity(a: Optional[int], b: Optional[int], tau: float = 6.0) -> float:
    if a is None or b is None:
        return 0.0
    d = abs(a - b)
    # exponential falloff; ~0.85 at 1 yr, 0.72 at 2 yrs, ~0.19 at 10 yrs (tau=6)
    return pow(2.718281828, -d / tau)

def artist_album_boost(a: Track, b: Track) -> float:
    if a.artist == b.artist:
        return 1.0
    if a.album and a.album == b.album:
        return 0.6
    return 0.0

def similarity(a: Track, b: Track) -> float:
    """0..1"""
    g = jaccard(a.genre_tokens or set(), b.genre_tokens or set())
    aa = artist_album_boost(a, b)
    ya = year_affinity(a.year, b.year)
    return 0.55 * g + 0.25 * aa + 0.20 * ya

def pick_daily_seed(daily_seed: bool, user_seed: Optional[int]) -> int:
    seed_val = user_seed if user_seed is not None else 0
    if daily_seed:
        today = time.strftime("%Y-%m-%d", time.localtime())
        seed_val ^= hash(("daily", today)) & 0xFFFFFFFF
    return seed_val

def choose_theme(tracks: List[Track],
                 rng: random.Random,
                 force_genre: Optional[str],
                 force_era: Optional[str],
                 use_era: bool,
                 theme_size_min: int) -> Tuple[str, Optional[int], List[Track]]:
    """
    Returns (primary_genre_token, decade_or_None, themed_tracks)
    """
    # Build token -> track subset
    token_map: Dict[str, List[Track]] = {}
    for t in tracks:
        for tok in (t.genre_tokens or {t.genre.lower()}):
            token_map.setdefault(tok, []).append(t)

    if force_genre:
        gtok = force_genre.strip().lower()
        pool = token_map.get(gtok, [])
        if not pool:
            # fallback: ignore force
            force_genre = None

    # rank tokens by support
    ranked = sorted(token_map.items(), key=lambda kv: len(kv[1]), reverse=True)
    top_tokens = [tok for tok, lst in ranked if len(lst) >= max(30, theme_size_min // 2)]
    if not top_tokens:
        # fallback: take any token with at least 15 tracks
        top_tokens = [tok for tok, lst in ranked if len(lst) >= 15] or [ranked[0][0]]

    # choose token deterministically
    if force_genre:
        primary = force_genre.strip().lower()
    else:
        primary = top_tokens[rng.randrange(len(top_tokens))]

    themed = token_map.get(primary, [])

    # Optionally pick an era (decade) inside this token
    chosen_decade: Optional[int] = None
    if use_era and any(t.year for t in themed):
        # histogram by decade
        counts: Dict[int, int] = {}
        for t in themed:
            if t.year:
                counts[decade_of(t.year)] = counts.get(decade_of(t.year), 0) + 1
        if counts:
            # force era if asked and present
            if force_era and force_era.endswith("s") and force_era[:-1].isdigit():
                dec = int(force_era[:-1])
                if dec in counts and counts[dec] >= max(20, theme_size_min // 3):
                    chosen_decade = dec
            if chosen_decade is None:
                # pick the most populated decade but with a weighted randomness
                decs = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)
                total = sum(c for _, c in decs)
                weights = [c/total for _, c in decs]
                idx = rng.choices(range(len(decs)), weights=weights, k=1)[0]
                chosen_decade = decs[idx][0]

    # apply era filter if chosen
    if chosen_decade is not None:
        themed = [t for t in themed if t.year and decade_of(t.year) == chosen_decade]

    # ensure minimum size
    if len(themed) < theme_size_min:
        # widen to ±5 years around the decade center if we selected an era
        if chosen_decade is not None:
            center = chosen_decade + 5
            themed = [t for t in token_map[primary] if (t.year and abs(t.year - center) <= 5)]
        # still small? fallback to token only
        if len(themed) < theme_size_min:
            themed = token_map[primary]

    return primary, chosen_decade, themed

def pick_anchors(theme_tracks: List[Track], rng: random.Random) -> Tuple[Track, Track]:
    """
    Pick (representative, fresh) anchors inside the theme.
    Representative ~= closest to median year and most common artist within the theme.
    Fresh ~= most recently modified among underexposed artists/albums.
    """
    assert theme_tracks, "empty theme"
    # Representative
    years = sorted([t.year for t in theme_tracks if t.year is not None])
    median_year = years[len(years)//2] if years else None

    # score representativeness by closeness to median year + artist popularity inside theme
    artist_counts: Dict[str, int] = {}
    for t in theme_tracks:
        artist_counts[t.artist] = artist_counts.get(t.artist, 0) + 1

    def rep_score(t: Track) -> float:
        y = 1.0 - (abs((t.year or median_year or 0) - (median_year or (t.year or 0))) / 8.0 if (t.year or median_year) else 1.0)
        y = max(0.0, min(1.0, y))
        a = artist_counts.get(t.artist, 1) ** 0.5
        return 0.6*y + 0.4*(a / (max(artist_counts.values()) or 1))

    representative = max(theme_tracks, key=rep_score)

    # Fresh anchor: recent mtime but avoid the rep artist when possible
    candidates = [t for t in theme_tracks if t.artist != representative.artist] or theme_tracks
    fresh = min(candidates, key=lambda t: t.mtime)  # smaller mtime == older; we want recent -> use max
    # Correct: pick max mtime (most recently modified)
    fresh = max(candidates, key=lambda t: t.mtime)

    # random tie-break
    if rng.random() < 0.33:
        representative, fresh = fresh, representative
    return representative, fresh

# ---------- Scoring, selection, ordering ----------

def novelty_boost(t: Track, now: float, fresh_days: Optional[int]) -> float:
    # If the user passed --fresh-days, treat "recently added/modified" as a positive.
    if not fresh_days:
        return 0.0
    window = fresh_days * 86400
    return 1.0 if (now - t.mtime) <= window else 0.0

def score_track(t: Track,
                anchors: Tuple[Track, Track],
                theme_token: str,
                now: float,
                fresh_days: Optional[int]) -> float:
    a1, a2 = anchors
    sim_anchor = max(similarity(t, a1), similarity(t, a2))              # 0..1
    theme_term = 1.0 if (theme_token in (t.genre_tokens or set())) else 0.7
    novelty = 0.35 * novelty_boost(t, now, fresh_days)                  # 0 or 0.35
    # final score
    return 0.55*sim_anchor + 0.25*theme_term + novelty

def build_candidates(tracks: List[Track],
                     theme_tracks: List[Track],
                     anchors: Tuple[Track, Track]) -> List[Track]:
    # Start with theme tracks plus the anchors’ nearest neighbors inside the full library
    lib = tracks
    a1, a2 = anchors
    # compute similarity once
    sims1 = sorted(((similarity(a1, t), t) for t in lib if t is not a1), reverse=True)
    sims2 = sorted(((similarity(a2, t), t) for t in lib if t is not a2), reverse=True)
    # take top-N neighbors and intersect with theme
    N = 300
    neigh = {t for _, t in sims1[:N]} | {t for _, t in sims2[:N]}
    pool = [t for t in theme_tracks if t in neigh or t is a1 or t is a2]
    # ensure anchors present
    if a1 not in pool: pool.append(a1)
    if a2 not in pool: pool.append(a2)
    return pool

def select_mix(candidates: List[Track],
               anchors: Tuple[Track, Track],
               theme_token: str,
               target_minutes: int,
               per_artist_max: int,
               per_album_max: int,
               fresh_days: Optional[int],
               explore_rate: float,
               rng: random.Random) -> List[Track]:
    now = time.time()
    # Score & sort
    scored = [(score_track(t, anchors, theme_token, now, fresh_days), t) for t in candidates]
    scored.sort(key=lambda x: x[0], reverse=True)

    # split into exploit (top 70-75%) and explore (rest)
    split = int(len(scored) * (1.0 - max(0.0, min(0.9, explore_rate))))
    exploit = [t for _, t in scored[:split]]
    explore = [t for _, t in scored[split:]]

    # interleave selection
    dur_target = target_minutes * 60
    playlist: List[Track] = []
    used: Set[Path] = set()
    artist_ct: Dict[str, int] = {}
    album_ct: Dict[str, int] = {}
    running = 0

    def ok(t: Track, last_artist: Optional[str]) -> bool:
        if t.path in used:
            return False
        if artist_ct.get(t.artist, 0) >= per_artist_max:
            return False
        if album_ct.get(t.album, 0) >= per_album_max:
            return False
        if last_artist is not None and t.artist == last_artist:
            return False
        return True

    i_exploit = 0
    i_explore = 0
    last_artist: Optional[str] = None
    # prefer real durations; assume 240s if unknown
    any_dur = any(t.seconds for t in candidates)

    while True:
        pick_from_explore = (rng.random() < explore_rate)
        chosen: Optional[Track] = None
        pool = explore if pick_from_explore else exploit
        idx = i_explore if pick_from_explore else i_exploit

        # find next acceptable track
        for j in range(idx, len(pool)):
            t = pool[j]
            if ok(t, last_artist):
                chosen = t
                if pick_from_explore: i_explore = j + 1
                else: i_exploit = j + 1
                break

        # fallback: try the other pool
        if not chosen:
            pool = exploit if pick_from_explore else explore
            idx = i_exploit if pick_from_explore else i_explore
            for j in range(idx, len(pool)):
                t = pool[j]
                if ok(t, last_artist):
                    chosen = t
                    if pick_from_explore: i_exploit = j + 1
                    else: i_explore = j + 1
                    break

        if not chosen:
            break

        dur = chosen.seconds or 240
        if any_dur:
            if running > 0 and running + dur > dur_target + 120:
                break
            running += dur
        else:
            # unknown durations: cap by track count approximation
            approx_count = max(12, int(target_minutes * 0.24))
            if len(playlist) >= approx_count:
                break

        playlist.append(chosen)
        used.add(chosen.path)
        artist_ct[chosen.artist] = artist_ct.get(chosen.artist, 0) + 1
        album_ct[chosen.album] = album_ct.get(chosen.album, 0) + 1
        last_artist = chosen.artist

        if len(playlist) >= 200:
            break

    # Guarantee anchors are present (append if constraints blocked them)
    for a in anchors:
        if a not in playlist:
            playlist.insert(min(1, len(playlist)), a)

    return playlist

def order_for_flow(tracks: List[Track]) -> List[Track]:
    """
    Greedy nearest-neighbor ordering by similarity, then local 2-swap improvement.
    """
    if not tracks:
        return tracks
    # start from a middle track (median year) to avoid immediate cliffs
    ys = [t.year for t in tracks if t.year is not None]
    start = tracks[0]
    if ys:
        med = sorted(ys)[len(ys)//2]
        start = min(tracks, key=lambda t: abs((t.year or med) - med))

    remaining = set(tracks)
    order: List[Track] = []
    cur = start
    order.append(cur)
    remaining.remove(cur)

    while remaining:
        nxt = max(remaining, key=lambda t: similarity(cur, t))
        order.append(nxt)
        remaining.remove(nxt)
        cur = nxt

    # local improvement: swap adjacent pairs if it improves neighbor sims
    improved = True
    def pair_sim(i: int) -> float:
        if i < 0 or i+1 >= len(order): return 0.0
        return similarity(order[i], order[i+1])

    while improved:
        improved = False
        for i in range(len(order)-2):
            a, b, c = order[i], order[i+1], order[i+2]
            cur_sum = similarity(a, b) + similarity(b, c)
            swap_sum = similarity(a, c) + similarity(c, b)
            if swap_sum > cur_sum + 0.05:
                order[i+1], order[i+2] = c, b
                improved = True

    return order

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

# ---------- CLI ----------

def parse_args():
    ap = argparse.ArgumentParser(description="Generate thematic Daily Mix playlists (DB-aware).")
    src = ap.add_mutually_exclusive_group(required=False)
    src.add_argument("--library", type=Path, help="Scan this library folder directly (fallback if no DB).")
    ap.add_argument("--db", type=Path, help="Path to music_index.sqlite3 to read tracks from.")
    ap.add_argument("--db-source", choices=["library", "device"], help="Use the indexed DB for Library or Device.")
    ap.add_argument("--device-mount", type=Path, help="Device mountpoint when using --db-source device.")

    ap.add_argument("--out-dir", type=Path, required=True, help="Where to save .m3u8 playlists (PC or device).")
    ap.add_argument("--mix-name", type=str, default="Daily Mix", help="Base name for the playlist(s).")
    ap.add_argument("--target-min", type=int, default=75, help="Target playlist length in minutes.")
    ap.add_argument("--genres", nargs="*", default=None, help="(Deprecated here) Anchor genres; use --theme-genre instead.")
    ap.add_argument("--mix-count", type=int, default=1, help="How many mixes to create.")
    ap.add_argument("--per-artist-max", type=int, default=2, help="Max tracks from the same artist in a mix.")
    ap.add_argument("--fresh-days", type=int, default=None, help="Boost tracks modified within N days.")
    ap.add_argument("--seed", type=int, default=None, help="Base random seed for reproducibility.")

    # New:
    ap.add_argument("--daily-seed", dest="daily_seed", action="store_true", default=True,
                    help="Derive randomness from today's date (default: on)")
    ap.add_argument("--no-daily-seed", dest="daily_seed", action="store_false",
                    help="Disable daily seeding")
    ap.add_argument("--theme-era", dest="theme_era", action="store_true", default=True,
                    help="Try to pick a decade within the theme (default: on)")
    ap.add_argument("--no-theme-era", dest="theme_era", action="store_false",
                    help="Do not pick a decade; theme by genre only")
    ap.add_argument("--explore-rate", type=float, default=0.25, help="Share of exploratory tracks (0..0.9).")
    ap.add_argument("--max-per-album", type=int, default=1, help="Max tracks per album.")
    ap.add_argument("--theme-size-min", type=int, default=60, help="Minimum tracks to call it a theme.")
    ap.add_argument("--theme-genre", type=str, default=None, help="Force theme primary genre token (case-insensitive).")
    ap.add_argument("--theme-era-spec", type=str, default=None, help="Force theme decade (e.g., 1990s).")

    return ap.parse_args()

# ---------- Main ----------

def main():
    args = parse_args()
    # Seed
    seed_val = pick_daily_seed(args.daily_seed, args.seed)
    rng = random.Random(seed_val)

    # Load tracks
    db_path = resolve_db_path(args.db, args.db_source, args.device_mount)
    if db_path is not None and db_path.exists():
        tracks = load_tracks_from_db(db_path)
    else:
        lib = args.library
        if not lib:
            print("No DB found/selected and no --library provided.")
            return
        tracks = scan_library(lib)

    if not tracks:
        print("No audio files found.")
        return

    # Ensure genre tokens filled (DB path may have skipped scan)
    for t in tracks:
        if t.genre_tokens is None:
            t.genre_tokens = {x.lower() for x in _split_genre_tokens(t.genre)}

    # Optional legacy anchors support (if user passed --genres)
    provided = [g for g in (args.genres or []) if is_valid_genre(str(g))]
    if provided:
        print(f"(note) --genres is deprecated for theming; prefer --theme-genre")
        # We'll bias the theme selection using the first provided token if present:
        theme_force = provided[0].strip().lower()
    else:
        theme_force = args.theme_genre.strip().lower() if args.theme_genre else None

    # Choose theme
    primary_tok, decade, theme_tracks = choose_theme(
        tracks, rng,
        force_genre=theme_force,
        force_era=args.theme_era_spec,
        use_era=args.theme_era,
        theme_size_min=args.theme_size_min,
    )

    # Anchors inside the theme
    a_rep, a_fresh = pick_anchors(theme_tracks, rng)
    anchors = (a_rep, a_fresh)

    # Candidate pool and selection
    candidates = build_candidates(tracks, theme_tracks, anchors)
    mix_all: List[Track] = []

    for i in range(args.mix_count):
        mix = select_mix(
            candidates=candidates,
            anchors=anchors,
            theme_token=primary_tok,
            target_minutes=args.target_min,
            per_artist_max=args.per_artist_max,
            per_album_max=args.max_per_album,
            fresh_days=args.fresh_days,
            explore_rate=args.explore_rate,
            rng=rng
        )
        ordered = order_for_flow(mix)
        name = args.mix_name if args.mix_count == 1 else f"{args.mix_name} #{i+1}"
        out = write_m3u8(args.out_dir, name, ordered)
        total_sec = sum(t.seconds or 240 for t in ordered)
        mins = total_sec // 60
        theme_label = primary_tok.title() + (f" • {decade}s" if decade is not None else "")
        print(f"🎛️  Theme: {theme_label}   Anchors: {a_rep.artist} — {a_rep.title} | {a_fresh.artist} — {a_fresh.title}")
        print(f"✅ Wrote {out} ({len(ordered)} tracks, ~{mins} min)")

        mix_all.extend(ordered)

if __name__ == "__main__":
    main()
