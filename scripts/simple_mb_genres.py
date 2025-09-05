#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
simple_mb_genres.py — Simple MusicBrainz-only genre tagger (two-phase: gather -> write)

What it does
------------
1) Scans your library for audio files.
2) For each file, reads Artist/Title (and Album if available) and searches MusicBrainz.
3) Gathers genres from Recording, Release, Release Group, and Artist.
4) Aggregates + ranks genres; keeps TOP 5 per track (by count).
5) After ALL lookups are complete, writes those genres into files (unless --dry-run).

Why this design?
----------------
- You asked for: MusicBrainz-only, no AcoustID; collect everything first, then write once.
- “Top 5” genres per track for richer tagging.

Install
-------
    pip install mutagen musicbrainzngs

Usage
-----
Dry run (no writing), save a JSON of planned updates:
    python simple_mb_genres.py --library ~/Music --dry-run --save-json genres_plan.json

Actually write:
    python simple_mb_genres.py --library ~/Music --save-json genres_written.json

Limit to MP3/FLAC only:
    python simple_mb_genres.py --library ~/Music --ext .mp3 .flac

Notes
-----
- We do ~1 request/second (friendly to MusicBrainz).
- We use simple search (artist+title, optional album).
- Writes multiple genres where possible; otherwise joins with '; '.
"""

from __future__ import annotations
import argparse
import json
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import re
import random

import musicbrainzngs
import mutagen
from mutagen.flac import FLAC
from mutagen.mp3 import EasyMP3
from mutagen.oggvorbis import OggVorbis
from mutagen.oggopus import OggOpus
from mutagen.easymp4 import EasyMP4

# ---------- Config ----------
DEFAULT_EXTS = [".mp3", ".flac", ".ogg", ".opus", ".aac", ".m4a", ".wav", ".wv", ".aiff", ".ape", ".mpc"]
MB_APP = ("RBXSimpleGenreTagger", "1.0")  # user agent for MusicBrainz

# ---------- Helpers ----------

def is_audio(p: Path, allow_exts: List[str]) -> bool:
    return p.is_file() and p.suffix.lower() in allow_exts

def get_easy_file(path: Path):
    ext = path.suffix.lower()
    try:
        if ext == ".mp3":
            return EasyMP3(str(path))
        if ext in (".m4a", ".mp4", ".aac"):
            return EasyMP4(str(path))
        if ext == ".flac":
            return FLAC(str(path))
        if ext == ".ogg":
            return OggVorbis(str(path))
        if ext == ".opus":
            return OggOpus(str(path))
        # fallback: let mutagen guess
        return mutagen.File(str(path), easy=True)
    except Exception:
        return None

def read_basic_tags(path: Path) -> Tuple[str, str, Optional[str]]:
    """
    Returns (artist, title, album?) using 'easy' tags; falls back to filename heuristics.
    """
    artist = title = ""
    album: Optional[str] = None
    try:
        f = mutagen.File(str(path), easy=True)
    except Exception:
        f = None
    if f:
        artist = (f.get("albumartist") or f.get("artist") or [""])[0].strip()
        title  = (f.get("title") or [""])[0].strip()
        albumv = (f.get("album") or [""])
        if albumv and albumv[0]:
            album = str(albumv[0]).strip()

    # crude fallbacks if empty
    if not title:
        title = path.stem
    if not artist:
        # try folder structure .../Artist/Album/Track
        try:
            artist = path.parent.parent.name
        except Exception:
            artist = "Unknown Artist"

    return artist, title, album

def normalize(s: str) -> str:
    s = s.lower()
    s = re.sub(r'\(feat[^\)]*\)|\[feat[^\]]*\]|feat\.? .+$', '', s)
    s = re.sub(r'[^a-z0-9\s]+', ' ', s)
    s = re.sub(r'\s+', ' ', s).strip()
    return s

def rate_limit_sleep(last_ts: List[float], min_interval: float = 1.0):
    now = time.time()
    if last_ts and now - last_ts[0] < min_interval:
        time.sleep(min_interval - (now - last_ts[0]))
    last_ts[:] = [time.time()]

def backoff_sleep(attempt: int):
    base = min(6, 0.8 * (2 ** attempt))
    time.sleep(base * (0.7 + 0.6 * random.random()))

def best_5(genres_blocks: List[List[Dict]]) -> List[str]:
    """
    Given lists like [{'name': 'Rock','count':12}, ...] across entities,
    combine counts and return top 5 names.
    """
    agg: Dict[str, int] = {}
    for block in genres_blocks:
        for g in block or []:
            name = g.get("name")
            if not name:
                continue
            agg[name] = agg.get(name, 0) + int(g.get("count", 0) or 0) + 1  # +1 biases presence
    # sort by count desc, then name
    ranked = sorted(agg.items(), key=lambda kv: (-kv[1], kv[0]))
    return [name for name, _ in ranked[:5]]

def extract_genre_blocks(entity: Optional[dict]) -> List[Dict]:
    """
    Normalize MB genres/tags into [{'name':..., 'count':...}] list.
    Prefer 'genres', else fallback to 'tags'.
    """
    out: List[Dict] = []
    if not entity:
        return out
    if entity.get("genres"):
        for g in entity["genres"]:
            n = g.get("name")
            c = int(g.get("count", 0) or 0)
            if n:
                out.append({"name": n, "count": c})
    elif entity.get("tags"):
        for t in entity["tags"]:
            n = t.get("name")
            c = int(t.get("count", 0) or 0)
            if n:
                out.append({"name": n, "count": c})
    return out

# ---------- MusicBrainz simple search ----------

def mb_simple_search(artist: str, title: str, album: Optional[str], rl_ts: List[float]) -> Tuple[Optional[dict], Optional[dict], Optional[dict], Optional[dict]]:
    """
    Simple search flow:
      1) search_recordings(artist=, recording=, release=album?) -> pick best by score
      2) fetch recording (genres/tags, releases, artists)
      3) fetch first release (genres/tags + release-group)
      4) fetch release-group (genres/tags)
      5) fetch primary artist (genres/tags)
    Returns tuple: (recording, release, release_group, artist)
    """
    # step 1: search
    rec = rel = rg = art = None
    for attempt in range(3):
        try:
            rate_limit_sleep(rl_ts)
            res = musicbrainzngs.search_recordings(
                artist=artist, recording=title, release=album or None, limit=5
            )
            rec_list = res.get("recording-list") or []
            if not rec_list:
                return None, None, None, None
            # pick highest score, prefer normalized artist/title match
            norm_artist = normalize(artist)
            norm_title  = normalize(title)
            rec_list.sort(key=lambda r: int(r.get("ext:score", "0")), reverse=True)
            # small bonus for close normalized matches
            def score_item(r):
                s = int(r.get("ext:score", "0"))
                rtitle = normalize(r.get("title", ""))
                ra = r.get("artist-credit") or []
                rartist = normalize(ra[0]["artist"]["name"]) if ra else ""
                if rtitle == norm_title:
                    s += 10
                if rartist == norm_artist:
                    s += 10
                return s
            best = max(rec_list, key=score_item)
            rec_id = best["id"]
            break
        except Exception:
            if attempt == 2:
                return None, None, None, None
            backoff_sleep(attempt)

    # step 2: fetch recording details
    for attempt in range(3):
        try:
            rate_limit_sleep(rl_ts)
            rec = musicbrainzngs.get_recording_by_id(
                rec_id, includes=["genres", "tags", "releases", "artists"]
            ).get("recording")
            break
        except Exception:
            if attempt == 2:
                return rec, None, None, None
            backoff_sleep(attempt)

    # step 3: release (first)
    if rec and rec.get("release-list"):
        rel_id = rec["release-list"][0]["id"]
        for attempt in range(3):
            try:
                rate_limit_sleep(rl_ts)
                rel = musicbrainzngs.get_release_by_id(
                    rel_id, includes=["genres", "tags", "release-groups"]
                ).get("release")
                break
            except Exception:
                if attempt == 2:
                    break
                backoff_sleep(attempt)

        # step 4: release group
        try:
            if rel and "release-group" in rel:
                rg_id = rel["release-group"]["id"]
                for attempt in range(3):
                    try:
                        rate_limit_sleep(rl_ts)
                        rg = musicbrainzngs.get_release_group_by_id(
                            rg_id, includes=["genres", "tags"]
                        ).get("release-group")
                        break
                    except Exception:
                        if attempt == 2:
                            break
                        backoff_sleep(attempt)
        except Exception:
            pass

    # step 5: artist
    if rec and rec.get("artist-credit"):
        art_id = rec["artist-credit"][0]["artist"]["id"]
        for attempt in range(3):
            try:
                rate_limit_sleep(rl_ts)
                art = musicbrainzngs.get_artist_by_id(
                    art_id, includes=["genres", "tags"]
                ).get("artist")
                break
            except Exception:
                if attempt == 2:
                    break
                backoff_sleep(attempt)

    return rec, rel, rg, art

def top5_from_entities(rec: Optional[dict], rel: Optional[dict], rg: Optional[dict], art: Optional[dict]) -> List[str]:
    blocks = [
        extract_genre_blocks(rec),
        extract_genre_blocks(rel),
        extract_genre_blocks(rg),
        extract_genre_blocks(art),
    ]
    return best_5(blocks)

# ---------- Writer ----------

def write_genres_to_file(path: Path, genres: List[str]) -> bool:
    """
    Try writing multiple values where the format supports it; otherwise join with '; '.
    """
    f = get_easy_file(path)
    if not f:
        return False
    try:
        # Attempt list write first
        if genres:
            f["genre"] = genres  # EasyMP3/FLAC/Vorbis accept lists
        else:
            f["genre"] = []
        f.save()
        return True
    except Exception:
        try:
            # fallback: single string joined
            f["genre"] = ["; ".join(genres)]
            f.save()
            return True
        except Exception:
            return False

# ---------- Main ----------

def parse_args():
    ap = argparse.ArgumentParser(description="MusicBrainz-only genre tagger (gather first, write after).")
    ap.add_argument("--library", type=Path, required=True, help="Path to your music library root.")
    ap.add_argument("--ext", nargs="*", default=DEFAULT_EXTS, help="File extensions to include.")
    ap.add_argument("--dry-run", action="store_true", help="Do not write tags; just show/save plan.")
    ap.add_argument("--save-json", type=Path, default=None, help="Save gathered genres (plan/result) to this JSON.")
    ap.add_argument("--verbose", action="store_true", help="Verbose progress.")
    ap.add_argument("--only-missing", action="store_true", help="Only add genres if file currently has none.")
    return ap.parse_args()

def main():
    args = parse_args()
    musicbrainzngs.set_useragent(MB_APP[0], MB_APP[1], "https://musicbrainz.org")

    root = args.library.expanduser().resolve()
    files = [p for p in root.rglob("*") if is_audio(p, args.ext)]
    total = len(files)
    if total == 0:
        print("No audio files found.")
        return

    print(f"Scanning {total} files...\n")

    # Phase 1: Gather
    rl_ts = [0.0]
    plan: Dict[str, List[str]] = {}   # absolute path -> top5 genres
    misses: int = 0
    skipped_existing: int = 0

    for idx, p in enumerate(files, 1):
        artist, title, album = read_basic_tags(p)
        if args.verbose:
            print(f"[{idx}/{total}] {p.name} | Artist='{artist}' Title='{title}' Album='{album or ''}'")

        rec, rel, rg, art = mb_simple_search(artist, title, album, rl_ts)
        genres = top5_from_entities(rec, rel, rg, art) if rec else []

        if genres:
            # Respect --only-missing by skipping files that already have a genre
            if args.only_missing:
                try:
                    f = get_easy_file(p)
                    existing = None
                    if f:
                        g = f.get("genre")
                        if g and len(g) > 0 and str(g[0]).strip():
                            existing = str(g[0]).strip()
                    if existing:
                        skipped_existing += 1
                        if args.verbose:
                            print(f"  -> skip (already has genre: '{existing}')")
                        continue
                except Exception:
                    # If we can't read existing genre, proceed to plan update
                    pass

            plan[str(p)] = genres
            if args.verbose:
                print(f"  -> genres: {', '.join(genres)}")
        else:
            misses += 1
            if args.verbose:
                print(f"  -> no genres found")

        # light heartbeat if not verbose
        if not args.verbose and idx % 25 == 0:
            print(f"... looked up {idx}/{total}")

    if args.save_json:
        try:
            args.save_json.write_text(json.dumps(plan, indent=2, ensure_ascii=False), encoding="utf-8")
            print(f"\nSaved lookup plan to: {args.save_json}")
        except Exception as e:
            print(f"\nWarning: could not save JSON plan: {e}")

    # Phase 2: Write
    print(f"\nLookup complete. Will write genres for {len(plan)} files (misses: {misses}, skipped-existing: {skipped_existing}).")
    if args.dry_run:
        print("Dry-run: not writing tags.")
        return

    ok = fail = 0
    for path_str, genres in plan.items():
        p = Path(path_str)
        # Respect --only-missing again at write time (defensive)
        if args.only_missing:
            try:
                f = get_easy_file(p)
                if f:
                    g = f.get("genre")
                    if g and len(g) > 0 and str(g[0]).strip():
                        if args.verbose:
                            print(f"- Skipped {p.name}: already has genre '{str(g[0]).strip()}'")
                        continue
            except Exception:
                # if read fails, fall through to write attempt
                pass

        success = write_genres_to_file(p, genres)
        if success:
            ok += 1
        else:
            fail += 1
        if args.verbose:
            print(f"{'✓' if success else '✗'} {p.name}: {', '.join(genres) if genres else '-'}")

    # Done
    print("\nSummary")
    print(f"  ✓ Tagged: {ok}")
    print(f"  ✗ Failed: {fail}")
    print(f"  ∅ No-genre matches: {misses}")

if __name__ == "__main__":
    main()
