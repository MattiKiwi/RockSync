#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tag_genres.py — Fill in genre tags across a music library using AcoustID + MusicBrainz.

Features
- Fingerprint & match via AcoustID (Chromaprint/fpcalc required).
- Fetch canonical genres from MusicBrainz (recording/release/artist tags/genres).
- Write 'genre' tag with mutagen (MP3/FLAC/OGG/OPUS/AAC/M4A/WAV/WV/AIFF/APE/MPC).
- Dry-run, overwrite or only-missing modes, rate limiting, JSON cache.
- Optional folder-name fallback (e.g., /Jazz/… infers "Jazz").

Install
    pip install mutagen pyacoustid musicbrainzngs

System requirement
    fpcalc (Chromaprint). On Linux: apt install chromaprint
                             macOS: brew install chromaprint
                             Windows: download binaries from AcoustID/Chromaprint

Env
    export ACOUSTID_API_KEY=your_key_here

Usage
    # Dry run, only fill where genre is missing
    python tag_genres.py --library ~/Music --dry-run --only-missing

    # Actually write, overwrite existing genres
    python tag_genres.py --library ~/Music --overwrite

    # Limit to certain extensions, faster run, and verbose logs
    python tag_genres.py --library ~/Music --ext .mp3 .flac --verbose

    # Use folder fallback if lookups fail
    python tag_genres.py --library ~/Music --folder-fallback

Notes
- The script prefers MusicBrainz "genres" first, then top tags as a fallback.
- A small JSON cache ('.genre_cache.json') is kept in the library root.
"""

from __future__ import annotations
import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Dict, Optional, Tuple, List, Any

import mutagen
from mutagen.flac import FLAC
from mutagen.mp3 import EasyMP3
from mutagen.oggvorbis import OggVorbis
from mutagen.oggopus import OggOpus
from mutagen.easymp4 import EasyMP4

import acoustid
import musicbrainzngs
import sys

# ----------------------- Config -----------------------

DEFAULT_EXTS = [".mp3", ".flac", ".ogg", ".opus", ".aac", ".m4a", ".wav", ".wv", ".aiff", ".ape", ".mpc"]
CACHE_FILE = ".genre_cache.json"
MB_APP = ("RockboxGenreTagger", "1.0")  # app name, version for MusicBrainz

# Simple in-memory caches for a single run
MB_RELEASE_CACHE: Dict[str, dict] = {}
MB_RG_CACHE: Dict[str, dict] = {}
MB_ARTIST_CACHE: Dict[str, dict] = {}

# ----------------------- Utilities -----------------------

def is_audio(p: Path, allow_exts: List[str]) -> bool:
    return p.is_file() and p.suffix.lower() in allow_exts

def load_cache(root: Path) -> Dict[str, Any]:
    p = root / CACHE_FILE
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}

def save_cache(root: Path, cache: Dict[str, Any]) -> None:
    try:
        (root / CACHE_FILE).write_text(json.dumps(cache, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass

def cache_key_by_tags(audio: mutagen.FileType) -> Optional[str]:
    """Create a cache key from (artist, title, album, length)."""
    try:
        easy = mutagen.File(audio.filename, easy=True)
        artist = (easy.get("albumartist") or easy.get("artist") or [""])[0].strip()
        title  = (easy.get("title") or [""])[0].strip()
        album  = (easy.get("album") or [""])[0].strip()
        length = None
        full = mutagen.File(audio.filename)
        if hasattr(full, "info") and getattr(full.info, "length", None):
            length = int(full.info.length)
        if artist or title or album:
            return f"tags::{artist}|{title}|{album}|{length or ''}"
    except Exception:
        pass
    return None

def cache_key_by_fp(fp_signature: str) -> str:
    return f"fp::{fp_signature}"

def collect_genres(mb_recording: dict,
                   mb_release_group: Optional[dict],
                   mb_release: Optional[dict],
                   mb_artist: Optional[dict]) -> List[str]:
    """
    Prefer MusicBrainz 'genres' if present, else most popular tag among recording/release/artist.
    """
    def weighted_names(obj) -> List[Tuple[str, int]]:
        if not obj:
            return []
        out: List[Tuple[str, int]] = []
        g_list = obj.get("genre-list") or obj.get("genres") or []
        for g in g_list:
            name = (g.get("name") or "").strip()
            if not name:
                continue
            cnt = g.get("count") or g.get("vote-count") or 1
            try:
                cnt = int(cnt)
            except Exception:
                cnt = 1
            out.append((name, cnt))
        t_list = obj.get("tag-list") or obj.get("tags") or []
        for t in t_list:
            name = (t.get("name") or "").strip()
            if not name:
                continue
            cnt = t.get("count") or t.get("vote-count") or 1
            try:
                cnt = int(cnt)
            except Exception:
                cnt = 1
            out.append((name, cnt))
        # sort by weight desc
        out.sort(key=lambda x: x[1], reverse=True)
        return out

    seen = set()
    ordered: List[str] = []
    for obj in (mb_recording, mb_release_group, mb_release, mb_artist):
        for name, _w in weighted_names(obj):
            key = name.lower()
            if key not in seen:
                seen.add(key)
                ordered.append(name)
    return ordered

def rate_limit_sleep(last_call_ts: List[float], min_interval: float = 1.0):
    """MusicBrainz and AcoustID both appreciate ~1 req/sec."""
    now = time.time()
    if last_call_ts and (now - last_call_ts[0] < min_interval):
        time.sleep(min_interval - (now - last_call_ts[0]))
    last_call_ts[:] = [time.time()]

def _format_duration(seconds: float) -> str:
    try:
        s = int(round(max(0, seconds)))
    except Exception:
        s = 0
    h, rem = divmod(s, 3600)
    m, s = divmod(rem, 60)
    if h > 0:
        return f"{h}h {m}m {s}s"
    if m > 0:
        return f"{m}m {s}s"
    return f"{s}s"

# ----------------------- Lookup logic -----------------------

def lookup_genres_with_acoustid(file_path: Path, api_key: str,
                                mb_client: musicbrainzngs,
                                rl_ts: List[float],
                                max_genres: int) -> List[str]:
    """
    Fingerprint -> AcoustID -> MusicBrainz recording/release/artist -> genre
    """
    # acoustid.match returns list of (score, recording_id(s))
    rate_limit_sleep(rl_ts)
    try:
        results = acoustid.match(api_key, str(file_path))
    except acoustid.FingerprintGenerationError:
        return []
    except Exception:
        return []

    best_recid = None
    best_score = 0.0
    for score, rid, title, artist in results:
        if score > best_score and rid:
            best_recid = rid
            best_score = score

    if not best_recid:
        return []

    # MusicBrainz: fetch recording with tags + references
    rate_limit_sleep(rl_ts)
    try:
        rec = mb_client.get_recording_by_id(best_recid, includes=["tags", "releases", "artists"]).get("recording")
    except Exception:
        return []

    def weighted_names(obj) -> List[Tuple[str, int]]:
        if not obj:
            return []
        out: List[Tuple[str, int]] = []
        g_list = obj.get("genre-list") or obj.get("genres") or []
        for g in g_list:
            name = (g.get("name") or "").strip()
            if not name:
                continue
            cnt = g.get("count") or g.get("vote-count") or 1
            try:
                cnt = int(cnt)
            except Exception:
                cnt = 1
            out.append((name, cnt))
        t_list = obj.get("tag-list") or obj.get("tags") or []
        for t in t_list:
            name = (t.get("name") or "").strip()
            if not name:
                continue
            cnt = t.get("count") or t.get("vote-count") or 1
            try:
                cnt = int(cnt)
            except Exception:
                cnt = 1
            out.append((name, cnt))
        out.sort(key=lambda x: x[1], reverse=True)
        return out

    seen = set()
    ordered: List[str] = []
    def add_from(obj) -> bool:
        nonlocal ordered
        for name, _w in weighted_names(obj):
            key = name.lower()
            if key not in seen:
                seen.add(key)
                ordered.append(name)
                if len(ordered) >= max_genres:
                    return True
        return False

    # recording
    if add_from(rec):
        return ordered[:max_genres]

    # primary release
    if rec and rec.get("release-list"):
        rel_id = rec["release-list"][0]["id"]
        mb_release = MB_RELEASE_CACHE.get(rel_id)
        if not mb_release:
            rate_limit_sleep(rl_ts)
            try:
                mb_release = mb_client.get_release_by_id(rel_id, includes=["tags"]).get("release")
            except Exception:
                mb_release = None
            MB_RELEASE_CACHE[rel_id] = mb_release
        if add_from(mb_release):
            return ordered[:max_genres]
        if mb_release and mb_release.get("release-group"):
            rgid = mb_release["release-group"]["id"]
            mb_release_group = MB_RG_CACHE.get(rgid)
            if not mb_release_group:
                rate_limit_sleep(rl_ts)
                try:
                    mb_release_group = mb_client.get_release_group_by_id(rgid, includes=["tags"]).get("release-group")
                except Exception:
                    mb_release_group = None
                MB_RG_CACHE[rgid] = mb_release_group
            if add_from(mb_release_group):
                return ordered[:max_genres]

    # primary artist
    if rec and rec.get("artist-credit"):
        art_id = rec["artist-credit"][0]["artist"]["id"]
        mb_artist = MB_ARTIST_CACHE.get(art_id)
        if not mb_artist:
            rate_limit_sleep(rl_ts)
            try:
                mb_artist = mb_client.get_artist_by_id(art_id, includes=["tags"]).get("artist")
            except Exception:
                mb_artist = None
            MB_ARTIST_CACHE[art_id] = mb_artist
        add_from(mb_artist)

    return ordered[:max_genres]

def lookup_genres_with_tags(audio_path: Path,
                            mb_client: musicbrainzngs,
                            rl_ts: List[float],
                            max_genres: int) -> List[str]:
    """
    If we have artist/title (and maybe album, length), try MusicBrainz search without AcoustID.
    """
    easy = mutagen.File(str(audio_path), easy=True)
    if not easy:
        return []
    artist = (easy.get("albumartist") or easy.get("artist") or [""])[0].strip()
    title  = (easy.get("title") or [""])[0].strip()
    # length of track in seconds (mutagen returns float seconds)
    length_s: Optional[int] = None
    try:
        full = mutagen.File(str(audio_path))
        if hasattr(full, "info") and getattr(full.info, "length", None):
            length_s = int(round(full.info.length))
    except Exception:
        length_s = None
    if not (artist and title):
        return []

    rate_limit_sleep(rl_ts)
    try:
        # Search a wider set, then filter by artist/length
        res = musicbrainzngs.search_recordings(artist=artist, recording=title, limit=10)
    except Exception:
        return []

    rec_list = res.get("recording-list") or []
    if not rec_list:
        return []

    def norm(s: str) -> str:
        return "".join(ch.lower() for ch in s.strip())

    want_artist = norm(artist)

    def artist_matches(rec: dict) -> bool:
        ac = rec.get("artist-credit") or []
        names = []
        for part in ac:
            if isinstance(part, dict) and part.get("artist"):
                names.append(part["artist"].get("name", ""))
            elif isinstance(part, dict) and part.get("name"):
                names.append(part.get("name", ""))
        for n in names:
            if norm(n) == want_artist:
                return True
        return False

    def length_matches(rec: dict) -> bool:
        if length_s is None:
            return True
        try:
            mb_ms = int(rec.get("length", 0))
        except Exception:
            return True
        if mb_ms <= 0:
            return True
        # allow +/- 3 seconds tolerance
        return abs(mb_ms/1000 - length_s) <= 3

    # Score candidates: prefer artist match, length match, then ext:score
    def score_rec(r: dict) -> Tuple[int, int, int]:
        am = 1 if artist_matches(r) else 0
        lm = 1 if length_matches(r) else 0
        try:
            es = int(r.get("ext:score", "0"))
        except Exception:
            es = 0
        return (am, lm, es)

    rec_list.sort(key=score_rec, reverse=True)
    rec_id = rec_list[0]["id"]

    # Fetch details as in AcoustID path, but add incrementally until limit
    rate_limit_sleep(rl_ts)
    try:
        rec = mb_client.get_recording_by_id(rec_id, includes=["tags", "releases", "artists"]).get("recording")
    except Exception:
        return []

    def weighted_names(obj) -> List[Tuple[str, int]]:
        if not obj:
            return []
        out: List[Tuple[str, int]] = []
        g_list = obj.get("genre-list") or obj.get("genres") or []
        for g in g_list:
            name = (g.get("name") or "").strip()
            if not name:
                continue
            cnt = g.get("count") or g.get("vote-count") or 1
            try:
                cnt = int(cnt)
            except Exception:
                cnt = 1
            out.append((name, cnt))
        t_list = obj.get("tag-list") or obj.get("tags") or []
        for t in t_list:
            name = (t.get("name") or "").strip()
            if not name:
                continue
            cnt = t.get("count") or t.get("vote-count") or 1
            try:
                cnt = int(cnt)
            except Exception:
                cnt = 1
            out.append((name, cnt))
        out.sort(key=lambda x: x[1], reverse=True)
        return out

    seen = set()
    ordered: List[str] = []

    def add_from(obj) -> bool:
        nonlocal ordered
        for name, _w in weighted_names(obj):
            key = name.lower()
            if key not in seen:
                seen.add(key)
                ordered.append(name)
                if len(ordered) >= max_genres:
                    return True
        return False

    # recording
    if add_from(rec):
        return ordered[:max_genres]

    # primary release
    if rec and rec.get("release-list"):
        rel_id = rec["release-list"][0]["id"]
        mb_release = MB_RELEASE_CACHE.get(rel_id)
        if not mb_release:
            rate_limit_sleep(rl_ts)
            try:
                mb_release = mb_client.get_release_by_id(rel_id, includes=["tags"]).get("release")
            except Exception:
                mb_release = None
            MB_RELEASE_CACHE[rel_id] = mb_release
        if add_from(mb_release):
            return ordered[:max_genres]
        if mb_release and mb_release.get("release-group"):
            rgid = mb_release["release-group"]["id"]
            mb_release_group = MB_RG_CACHE.get(rgid)
            if not mb_release_group:
                rate_limit_sleep(rl_ts)
                try:
                    mb_release_group = mb_client.get_release_group_by_id(rgid, includes=["tags"]).get("release-group")
                except Exception:
                    mb_release_group = None
                MB_RG_CACHE[rgid] = mb_release_group
            if add_from(mb_release_group):
                return ordered[:max_genres]

    # primary artist
    if rec and rec.get("artist-credit"):
        art_id = rec["artist-credit"][0]["artist"]["id"]
        mb_artist = MB_ARTIST_CACHE.get(art_id)
        if not mb_artist:
            rate_limit_sleep(rl_ts)
            try:
                mb_artist = mb_client.get_artist_by_id(art_id, includes=["tags"]).get("artist")
            except Exception:
                mb_artist = None
            MB_ARTIST_CACHE[art_id] = mb_artist
        add_from(mb_artist)

    return ordered[:max_genres]

def folder_fallback_genre(p: Path) -> Optional[str]:
    """
    If library uses genre-top-level folders, guess from folder names (e.g., .../Jazz/Artist/Album/Track).
    """
    for part in p.parents:
        name = part.name.strip()
        if name.lower() in {
            "rock","pop","electronic","ambient","jazz","classical","hip hop","hip-hop","rap",
            "metal","blues","country","folk","soul","r&b","rb","techno","house","trance",
            "soundtrack","punk","indie","alternative","funk","disco","reggae","salsa","latin"
        }:
            return name.title()
    return None

# ----------------------- Tag writing -----------------------

def get_easy_file(path: Path):
    ext = path.suffix.lower()
    try:
        if ext == ".mp3":
            return EasyMP3(str(path))
        if ext in (".m4a", ".mp4", ".aac"):
            f = EasyMP4(str(path))
            # Ensure 'genre' is mapped
            if "genre" not in f.tags:
                pass  # EasyMP4 handles mapping automatically on set
            return f
        if ext == ".flac":
            return FLAC(str(path))
        if ext == ".ogg":
            return OggVorbis(str(path))
        if ext == ".opus":
            return OggOpus(str(path))
        # Fallback: let mutagen guess
        return mutagen.File(str(path), easy=True)
    except Exception:
        return None

def read_current_genre(path: Path) -> Optional[str]:
    f = get_easy_file(path)
    if not f:
        return None
    try:
        g = f.get("genre")
        if g and len(g) > 0 and str(g[0]).strip():
            return str(g[0]).strip()
    except Exception:
        pass
    return None

def write_genres(path: Path, genres: List[str]) -> bool:
    f = get_easy_file(path)
    if not f:
        return False
    try:
        # Ensure unique, preserve order
        out: List[str] = []
        seen = set()
        for g in genres:
            g = str(g).strip()
            if not g:
                continue
            key = g.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append(g)
        if not out:
            return False
        f["genre"] = out
        f.save()
        return True
    except Exception:
        return False

# ----------------------- Main flow -----------------------

def process_file(p: Path, args, cache: Dict[str, Any], mb_client, rl_ts: List[float]) -> Tuple[str, str]:
    """
    Returns (status, detail) where status in {"skip","ok","fail"}
    """
    if not is_audio(p, args.ext):
        return ("skip", "not-audio")

    # Respect only-missing vs overwrite
    existing = read_current_genre(p)
    if existing and args.only_missing:
        return ("skip", f"has genre '{existing}'")

    # Cache by tag key
    genres: Optional[List[str]] = None
    easy_key = None
    try:
        audio_easy = mutagen.File(str(p), easy=True)
    except Exception:
        audio_easy = None
    if audio_easy:
        easy_key = cache_key_by_tags(audio_easy)
        if easy_key and easy_key in cache:
            cached = cache[easy_key]
            if isinstance(cached, list):
                genres = [str(x) for x in cached if str(x).strip()]
            elif isinstance(cached, str):
                genres = [cached] if cached.strip() else None

    # Lookup via AcoustID if no cache hit
    if not genres and args.use_acoustid:
        api_key = os.environ.get("ACOUSTID_API_KEY", "").strip()
        if not api_key:
            if args.verbose:
                print(f"[acoustid] Skipping {p.name}: ACOUSTID_API_KEY not set")
        else:
            try:
                genres = lookup_genres_with_acoustid(p, api_key, musicbrainzngs, rl_ts, args.max_genres)
                if genres:
                    cache[cache_key_by_fp(str(p))] = genres
                elif args.verbose:
                    print(f"[acoustid] No genre match for {p.name}")
            except Exception as e:
                if args.verbose:
                    print(f"[acoustid] Error for {p.name}: {e}")

    # Lookup via tag search if still unknown
    if not genres and args.use_tag_search:
        genres = lookup_genres_with_tags(p, musicbrainzngs, rl_ts, args.max_genres)
        #try:
        #    genre = lookup_genre_with_tags(p, musicbrainzngs, rl_ts)
        #    if not genre and args.verbose:
        #        print(f"[mb-search] No genre via tag search for {p.name}")
        #except Exception as e:
        #    if args.verbose:
        #        print(p)
        #        print(rl_ts)
        #        print(f"[mb-search] Error for {p.name}: {e}")
        #    return ("fail", "search-error")

    # Folder fallback
    if (not genres or len(genres) == 0) and args.folder_fallback:
        ff = folder_fallback_genre(p)
        genres = [ff] if ff else None

    if not genres:
        return ("fail", "no-genre-found")

    # Write or simulate
    if args.dry_run:
        return ("ok", f"would set genres -> {', '.join(genres)}")

    ok = write_genres(p, genres)
    if ok:
        if easy_key:
            cache[easy_key] = genres
        return ("ok", f"set genres -> {', '.join(genres)}")
    else:
        return ("fail", "write-failed")

def parse_args():
    ap = argparse.ArgumentParser(description="Fill/overwrite genre tags using AcoustID + MusicBrainz.")
    ap.add_argument("--library", type=Path, required=True, help="Path to your music library root.")
    ap.add_argument("--dry-run", action="store_true", help="Show what would happen without writing tags.")
    group = ap.add_mutually_exclusive_group()
    group.add_argument("--only-missing", action="store_true", help="Only fill tracks with no genre (default).")
    group.add_argument("--overwrite", action="store_true", help="Replace existing genre values.")
    ap.add_argument("--ext", nargs="*", default=DEFAULT_EXTS, help="File extensions to include (default: common audio).")
    ap.add_argument("--verbose", action="store_true", help="Verbose logging.")
    ap.add_argument("--use-acoustid", action="store_true", help="Use AcoustID fingerprint lookup (requires ACOUSTID_API_KEY and fpcalc).")
    ap.add_argument("--use-tag-search", action="store_true", help="Use MusicBrainz title/artist search if AcoustID fails or is disabled.")
    ap.add_argument("--folder-fallback", action="store_true", help="Infer genre from folder names if lookups fail.")
    ap.add_argument("--max-genres", type=int, default=5, help="Maximum number of genres to write (default: 5).")
    ap.add_argument("--http-timeout", type=float, default=15.0, help="HTTP timeout in seconds for MusicBrainz requests (default: 15).")
    return ap.parse_args()

def main():
    args = parse_args()

    # Default mode = only-missing unless --overwrite is specified
    if not args.overwrite:
        args.only_missing = True

    # Init MusicBrainz client
    musicbrainzngs.set_useragent(MB_APP[0], MB_APP[1], "https://musicbrainz.org")
    # Be nice to MB servers and avoid indefinite hangs
    try:
        musicbrainzngs.set_rate_limit(True)
    except Exception:
        pass
    try:
        # Pass timeout to underlying requests if available
        musicbrainzngs.set_requests_kwargs({"timeout": args.http_timeout})
    except Exception:
        pass

    # Sensible defaults: if no lookup method selected, enable tag search by default
    if not (args.use_acoustid or args.use_tag_search or args.folder_fallback):
        args.use_tag_search = True
        if args.verbose:
            print("Defaulting to --use-tag-search (no lookup method specified)")

    root = args.library.expanduser().resolve()
    cache = load_cache(root)
    rl_ts = [0.0]

    audio_files = [p for p in root.rglob("*") if is_audio(p, args.ext)]
    total = len(audio_files)
    done_ok = 0
    done_fail = 0
    skipped = 0
    start_ts = time.time()

    print(f"Scanning: {root}")
    print(f"Found {total} audio files")

    for idx, p in enumerate(audio_files, 1):
        status, detail = process_file(p, args, cache, musicbrainzngs, rl_ts)
        if status == "ok":
            done_ok += 1
        elif status == "fail":
            done_fail += 1
        else:
            skipped += 1

        if args.verbose or status != "skip":
            print(f"[{idx}/{total}] {p.name}: {status} ({detail})")

        # Periodic progress with ETA
        if not args.verbose and (idx % 25 == 0 or idx == total):
            elapsed = max(0.0, time.time() - start_ts)
            rate = (elapsed / idx) if idx else 0.0
            remaining = rate * max(0, total - idx)
            finish_local = time.strftime("%H:%M", time.localtime(time.time() + remaining))
            print(f"… {idx}/{total} processed, ETA {_format_duration(remaining)} (finish ~{finish_local})")

        # Periodically flush cache
        if idx % 50 == 0:
            save_cache(root, cache)

    save_cache(root, cache)

    print("\nSummary")
    print(f"  ✓ Updated:   {done_ok}")
    print(f"  ✗ Failed:    {done_fail}")
    print(f"  ▫ Skipped:   {skipped}")
    print(f"  ⏱  Elapsed:   {_format_duration(time.time() - start_ts)}")

if __name__ == "__main__":
    main()
