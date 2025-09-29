#!/usr/bin/env python3
"""Lookup dominant genres for a song via MusicBrainz metadata search.

Pass a title, artist, and optional album name on the command line and the
script queries MusicBrainz for the best matching recording, then aggregates
genres and top tags from the recording, release, release group, and primary
artist.  Results are printed in order of relevance or emitted as JSON.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Dict, Iterable, List, Optional, Tuple

try:
    import musicbrainzngs
except ImportError as exc:  # pragma: no cover - library missing at runtime
    print("musicbrainzngs package is required (pip install musicbrainzngs)", file=sys.stderr)
    raise SystemExit(1) from exc


MB_APP = ("RockSyncGenreLookup", "1.0")

MB_RELEASE_CACHE: Dict[str, Optional[dict]] = {}
MB_RG_CACHE: Dict[str, Optional[dict]] = {}
MB_ARTIST_CACHE: Dict[str, Optional[dict]] = {}


def _norm(s: Optional[str]) -> str:
    return "".join(ch.lower() for ch in (s or ""))


def _weighted_names(obj: Optional[dict]) -> List[Tuple[str, int]]:
    if not obj:
        return []
    data: List[Tuple[str, int]] = []
    for key in ("genre-list", "genres"):
        for entry in obj.get(key) or []:
            name = (entry.get("name") or "").strip()
            if not name:
                continue
            cnt = entry.get("count") or entry.get("vote-count") or 1
            try:
                data.append((name, int(cnt)))
            except Exception:
                data.append((name, 1))
    for key in ("tag-list", "tags"):
        for entry in obj.get(key) or []:
            name = (entry.get("name") or "").strip()
            if not name:
                continue
            cnt = entry.get("count") or entry.get("vote-count") or 1
            try:
                data.append((name, int(cnt)))
            except Exception:
                data.append((name, 1))
    data.sort(key=lambda pair: pair[1], reverse=True)
    return data


def _extend_with(obj: Optional[dict], genres: List[str], seen: set, limit: int) -> None:
    for name, _weight in _weighted_names(obj):
        key = name.lower()
        if key in seen:
            continue
        genres.append(name)
        seen.add(key)
        if len(genres) >= limit:
            break


def _select_release(rec: dict, album: Optional[str]) -> Optional[dict]:
    releases = rec.get("release-list") or []
    if not releases:
        return None
    if album:
        want = _norm(album)
        for rel in releases:
            if _norm(rel.get("title")) == want:
                return rel
    return releases[0]


def _fetch_release(rel_id: str) -> Optional[dict]:
    if rel_id in MB_RELEASE_CACHE:
        return MB_RELEASE_CACHE[rel_id]
    try:
        release = musicbrainzngs.get_release_by_id(rel_id, includes=["tags"]).get("release")
    except Exception:
        release = None
    MB_RELEASE_CACHE[rel_id] = release
    return release


def _fetch_release_group(rgid: str) -> Optional[dict]:
    if rgid in MB_RG_CACHE:
        return MB_RG_CACHE[rgid]
    try:
        rg = musicbrainzngs.get_release_group_by_id(rgid, includes=["tags"]).get("release-group")
    except Exception:
        rg = None
    MB_RG_CACHE[rgid] = rg
    return rg


def _fetch_artist(artist_id: str) -> Optional[dict]:
    if artist_id in MB_ARTIST_CACHE:
        return MB_ARTIST_CACHE[artist_id]
    try:
        artist = musicbrainzngs.get_artist_by_id(artist_id, includes=["tags"]).get("artist")
    except Exception:
        artist = None
    MB_ARTIST_CACHE[artist_id] = artist
    return artist


def _artist_matches(rec: dict, artist: Optional[str]) -> bool:
    if not artist:
        return False
    target = _norm(artist)
    for credit in rec.get("artist-credit") or []:
        if isinstance(credit, dict):
            if _norm(credit.get("artist", {}).get("name")) == target:
                return True
            if _norm(credit.get("name")) == target:
                return True
        elif isinstance(credit, str) and _norm(credit) == target:
            return True
    return False


def _album_matches(rec: dict, album: Optional[str]) -> bool:
    if not album:
        return False
    want = _norm(album)
    for rel in rec.get("release-list") or []:
        if _norm(rel.get("title")) == want:
            return True
    return False


def _score_recording(rec: dict, title: Optional[str], artist: Optional[str], album: Optional[str]) -> Tuple[int, int, int, int]:
    artist_match = 1 if _artist_matches(rec, artist) else 0
    album_match = 1 if _album_matches(rec, album) else 0
    title_match = 1 if title and _norm(rec.get("title")) == _norm(title) else 0
    try:
        ext_score = int(rec.get("ext:score", "0"))
    except Exception:
        ext_score = 0
    return (artist_match, album_match, title_match, ext_score)


def collect_genres_for_recording(rec: dict, album: Optional[str], limit: int) -> List[str]:
    genres: List[str] = []
    seen: set = set()

    _extend_with(rec, genres, seen, limit)
    if len(genres) >= limit:
        return genres[:limit]

    rel_info = _select_release(rec, album)
    release = None
    if rel_info:
        release = _fetch_release(rel_info.get("id", ""))
        _extend_with(release, genres, seen, limit)

    if release and release.get("release-group"):
        rgid = release["release-group"].get("id")
        if rgid:
            rg = _fetch_release_group(rgid)
            _extend_with(rg, genres, seen, limit)

    artist_credit = rec.get("artist-credit") or []
    if artist_credit:
        primary = artist_credit[0]
        if isinstance(primary, dict) and primary.get("artist"):
            artist_id = primary["artist"].get("id")
            if artist_id:
                artist = _fetch_artist(artist_id)
                _extend_with(artist, genres, seen, limit)

    return genres[:limit]


def lookup_song_genres(title: str, artist: Optional[str], album: Optional[str], limit: int) -> Tuple[List[str], Optional[str]]:
    query: Dict[str, str] = {"recording": title}
    if artist:
        query["artist"] = artist
    if album:
        query["release"] = album

    try:
        res = musicbrainzngs.search_recordings(limit=10, **query)
    except Exception as exc:
        raise RuntimeError(f"MusicBrainz search failed: {exc}") from exc

    rec_list = res.get("recording-list") or []
    if not rec_list:
        return [], None

    rec_list.sort(key=lambda r: _score_recording(r, title, artist, album), reverse=True)
    rec_id = rec_list[0].get("id")
    if not rec_id:
        return [], None

    try:
        rec = musicbrainzngs.get_recording_by_id(rec_id, includes=["tags", "releases", "artists"]).get("recording")
    except Exception as exc:
        raise RuntimeError(f"Failed to fetch recording {rec_id}: {exc}") from exc

    if not rec:
        return [], rec_id

    genres = collect_genres_for_recording(rec, album, limit)
    return genres, rec_id


def parse_args(argv: Optional[Iterable[str]] = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Lookup dominant genres for a song using MusicBrainz")
    ap.add_argument("--title", required=True, help="Song title to search for")
    ap.add_argument("--artist", help="Artist name")
    ap.add_argument("--album", help="Album title (optional but helps disambiguate)")
    ap.add_argument("--max-genres", type=int, default=5, help="Maximum number of genres to return (default: 5)")
    ap.add_argument("--json", action="store_true", help="Print results as JSON")
    ap.add_argument("--http-timeout", type=float, default=15.0, help="MusicBrainz request timeout in seconds")
    return ap.parse_args(argv)


def main(argv: Optional[Iterable[str]] = None) -> int:
    args = parse_args(argv)

    if args.max_genres <= 0:
        print("--max-genres must be positive", file=sys.stderr)
        return 2

    musicbrainzngs.set_useragent(MB_APP[0], MB_APP[1], "https://musicbrainz.org")
    try:
        musicbrainzngs.set_rate_limit(True)
    except Exception:
        pass
    try:
        musicbrainzngs.set_requests_kwargs({"timeout": args.http_timeout})
    except Exception:
        pass

    try:
        genres, rec_id = lookup_song_genres(args.title, args.artist, args.album, args.max_genres)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    if args.json:
        payload = {
            "title": args.title,
            "artist": args.artist,
            "album": args.album,
            "genres": genres,
            "musicbrainz_recording_id": rec_id,
        }
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0 if genres else 3

    if not genres:
        print("No genres found for the supplied metadata.")
        return 3

    print(f"Top genres for '{args.title}'")
    if args.artist:
        print(f"Artist: {args.artist}")
    if args.album:
        print(f"Album:  {args.album}")
    if rec_id:
        print(f"Recording ID: {rec_id}")
    print("")
    for idx, genre in enumerate(genres, start=1):
        print(f"{idx}. {genre}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
