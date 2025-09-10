#!/usr/bin/env python3
from __future__ import annotations
import argparse, sys, textwrap, json
from typing import Any, Dict, List, Optional, Tuple, Union
from yt_dlp import YoutubeDL
import concurrent.futures
import urllib.parse
try:
    import requests  # Fast oEmbed lookups
except Exception:
    requests = None  # type: ignore

# ---------- Helpers ----------
def make_ydl(cookies_from_browser: Optional[str] = None,
             cookies_file: Optional[str] = None,
             flat: bool = True,
             verbose: bool = False,
             playlist_limit: Optional[int] = None) -> YoutubeDL:
    """
    Build a YoutubeDL instance configured for *browsing* (fast, no download).
    You can pass either cookies_from_browser (e.g. 'chrome', 'firefox', 'edge', 'brave')
    or cookies_file (path to Netscape cookies.txt).
    """
    ydl_opts: Dict[str, Any] = {
        "quiet": not verbose,
        "skip_download": True,
        "extract_flat": True if flat else "in_playlist",
        "noplaylist": False,
        "concurrent_fragment_downloads": 1,   # we aren't downloading anyway
        "ratelimit": 0,
        # Bound retries and socket timeouts for snappier failures
        "retries": 3,
        "extractor_retries": 2,
        "socket_timeout": 10,
        # Enable cache (player JSON, etc.) for speed across runs
        "cachedir": True,
        # A realistic UA can reduce bot friction on some hosts
        "http_headers": {"User-Agent": "Mozilla/5.0"},
    }
    if playlist_limit is not None and isinstance(playlist_limit, int) and playlist_limit > 0:
        # Stop extraction early for long playlists/feeds
        ydl_opts["playlistend"] = int(playlist_limit)
    if cookies_from_browser:
        # yt-dlp Python API expects a tuple/list (browser[, profile[, keyring[, container]]]).
        # Passing a bare string can be unpacked char-by-char in some versions.
        # Wrap in a 1-tuple so 'firefox' becomes ('firefox',)
        ydl_opts["cookiesfrombrowser"] = (cookies_from_browser,)
    if cookies_file:
        ydl_opts["cookiefile"] = cookies_file
    return YoutubeDL(ydl_opts)

def emit_rows(rows: List[Dict[str, Any]], cols: List[Tuple[str, str]], fmt: str = 'table'):
    # fmt: 'table' or 'jsonl'
    if fmt == 'jsonl':
        for r in rows:
            try:
                print(json.dumps(r, ensure_ascii=False))
            except Exception:
                # Fallback to str keys only
                clean = {k: (str(v) if not isinstance(v, (str, int, float, bool)) else v) for k, v in r.items()}
                print(json.dumps(clean, ensure_ascii=False))
        return
    # Table mode
    if not rows:
        print("(no results)")
        return
    widths = []
    for field, header in cols:
        maxw = max(len(header), *(len(str(r.get(field, ""))) for r in rows))
        widths.append(maxw)
    header_line = " | ".join(h.ljust(w) for (f, h), w in zip(cols, widths))
    sep = "-+-".join("-" * w for w in widths)
    print(header_line)
    print(sep)
    for r in rows:
        print(" | ".join(str(r.get(f, "")).ljust(w) for (f, h), w in zip(cols, widths)))

def extract_entries(url: str, ydl: YoutubeDL, limit: int) -> List[Dict[str, Any]]:
    """
    Use yt-dlp to extract entries (no download). Works for ytsearch, playlists, feeds, homepage, etc.
    """
    info = ydl.extract_info(url, download=False)
    entries = []
    # yt-dlp returns either a single dict or a playlist-like dict with "entries"
    if isinstance(info, dict) and "entries" in info and info.get("_type") in ("playlist", "multi_video", "url"):
        seq = info["entries"] or []
        for e in seq:
            if isinstance(e, dict):
                entries.append(e)
                if len(entries) >= limit:
                    break
    else:
        # Single video result
        if isinstance(info, dict):
            entries = [info]
    return entries[:limit]

def _best_thumbnail(e: Dict[str, Any]) -> Optional[str]:
    # Prefer explicit 'thumbnail', else pick the largest from 'thumbnails'
    th = e.get("thumbnail")
    if isinstance(th, str) and th.startswith("http"):
        return th
    ths = e.get("thumbnails") or []
    if isinstance(ths, list) and ths:
        # Sort by area or width if available
        def score(t: Dict[str, Any]) -> int:
            w = int(t.get("width") or 0)
            h = int(t.get("height") or 0)
            return w * h if (w and h) else w or h
        try:
            best = max((t for t in ths if isinstance(t, dict) and isinstance(t.get("url"), str)), key=score)
            url = best.get("url")
            if isinstance(url, str) and url.startswith("http"):
                return url
        except Exception:
            # Fallback to last item
            last = ths[-1]
            if isinstance(last, dict) and isinstance(last.get("url"), str):
                return last.get("url")
    return None

def _fmt_duration(d: Union[int, float, str, None]) -> str:
    try:
        # yt-dlp may provide float; coerce to non-negative int seconds
        secs = int(round(float(d)))
        if secs < 0:
            secs = 0
        h, rem = divmod(secs, 3600)
        m, s = divmod(rem, 60)
        return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"
    except Exception:
        return ""

def _enrich_missing_metadata(rows: List[Dict[str, Any]],
                             cookies_from_browser: Optional[str] = None,
                             cookies_file: Optional[str] = None,
                             verbose: bool = False,
                             max_lookups: int = 24,
                             max_workers: int = 8) -> None:
    """Fast best-effort enrichment for missing 'channel' (and some other fields).

    Strategy:
    - Try YouTube oEmbed in parallel (very fast, public), to get author_name and thumbnail.
    - For any remaining items, do a limited number of yt-dlp (non-flat) lookups as fallback.
    - Update rows in-place; keeps total work bounded via limits.
    """
    if not rows:
        return
    # Limit the number of additional lookups to avoid heavy requests on large lists
    def _looks_like_video(u: str) -> bool:
        return (('/watch?v=' in u) or ('/shorts/' in u) or u.startswith('https://youtu.be/'))

    todo = [r for r in rows
            if not (r.get('channel') or '').strip()
            and isinstance(r.get('url'), str)
            and r['url'].startswith('http')
            and _looks_like_video(r['url'])]
    if not todo:
        return
    if max_lookups > 0:
        todo = todo[:max_lookups]

    # First try oEmbed concurrently for speed
    failures: List[Dict[str, Any]] = []
    if requests is not None:
        def oembed_lookup(u: str) -> Optional[Dict[str, Any]]:
            try:
                url = 'https://www.youtube.com/oembed?format=json&url=' + urllib.parse.quote(u, safe='')
                resp = requests.get(url, timeout=6)
                if resp.status_code != 200:
                    return None
                data = resp.json()
                return {
                    'channel': data.get('author_name') or '',
                    'thumbnail': data.get('thumbnail_url') or '',
                }
            except Exception:
                return None

        with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, min(max_workers, len(todo)))) as ex:
            futs = {ex.submit(oembed_lookup, r['url']): r for r in todo}
            for fut in concurrent.futures.as_completed(futs):
                r = futs[fut]
                info = fut.result()
                if info and (info.get('channel') or info.get('thumbnail')):
                    if info.get('channel') and not r.get('channel'):
                        r['channel'] = info['channel']
                    if info.get('thumbnail') and not r.get('thumbnail'):
                        r['thumbnail'] = info['thumbnail']
                else:
                    failures.append(r)
    else:
        failures = todo[:]

    # Limited fallback using yt-dlp for the first few unresolved
    # Default to no heavy fallback for snappier UX; oEmbed covers public videos
    fallback_cap = 0
    if fallback_cap:
        try:
            with make_ydl(cookies_from_browser=cookies_from_browser,
                          cookies_file=cookies_file,
                          flat=False,
                          verbose=verbose) as y2:
                for r in failures[:fallback_cap]:
                    url = r.get('url')
                    if not url:
                        continue
                    try:
                        info = y2.extract_info(url, download=False)
                    except Exception:
                        continue
                    if not isinstance(info, dict):
                        continue
                    ch = info.get('uploader') or info.get('channel') or info.get('uploader_id') or info.get('channel_id') or ''
                    if ch and not r.get('channel'):
                        r['channel'] = ch
                    if not r.get('duration') and info.get('duration') is not None:
                        r['duration'] = _fmt_duration(info.get('duration'))
                    if not r.get('upload_date'):
                        r['upload_date'] = info.get('upload_date') or info.get('release_date') or ''
                    if not r.get('thumbnail') and isinstance(info.get('thumbnail'), str):
                        r['thumbnail'] = info.get('thumbnail')
        except Exception:
            pass

def normalize(e: Dict[str, Any]) -> Dict[str, Any]:
    # yt-dlp keys vary by page type; this normalizes the core fields we care about
    url = e.get("webpage_url") or e.get("url") or e.get("original_url")
    return {
        "id": e.get("id"),
        "title": e.get("title"),
        "channel": e.get("uploader") or e.get("channel") or e.get("channel_id") or "",
        "duration": _fmt_duration(e.get("duration")),
        "upload_date": e.get("upload_date") or e.get("release_date") or "",
        "url": url if (url and url.startswith("http")) else (f"https://www.youtube.com/watch?v={e.get('id')}" if e.get("id") else url),
        "thumbnail": _best_thumbnail(e) or "",
    }

# ---------- Commands ----------
def cmd_search(args):
    with make_ydl(flat=True, verbose=args.verbose, playlist_limit=None) as ydl:
        url = f"ytsearch{args.limit}:{args.query}"
        ents = extract_entries(url, ydl, args.limit)
        rows = [normalize(e) for e in ents]
        _enrich_missing_metadata(rows, verbose=args.verbose)
        emit_rows(rows, [("title", "Title"), ("channel", "Channel"), ("url", "URL")], getattr(args, 'format', 'table'))

def cmd_playlist(args):
    with make_ydl(cookies_from_browser=getattr(args, 'cookies_from_browser', None),
                  cookies_file=getattr(args, 'cookies_file', None),
                  flat=True, verbose=args.verbose, playlist_limit=args.limit) as ydl:
        url = args.url
        ents = extract_entries(url, ydl, args.limit)
        rows = [normalize(e) for e in ents]
        _enrich_missing_metadata(rows,
                                 cookies_from_browser=getattr(args, 'cookies_from_browser', None),
                                 cookies_file=getattr(args, 'cookies_file', None),
                                 verbose=args.verbose)
        emit_rows(rows, [("title", "Title"), ("channel", "Channel"), ("url", "URL")], getattr(args, 'format', 'table'))

def _authed_ydl(args) -> YoutubeDL:
    if not (args.cookies_from_browser or args.cookies_file):
        raise SystemExit("This command requires auth. Pass --cookies-from-browser <browser> or --cookies-file <path>.")
    return make_ydl(cookies_from_browser=args.cookies_from_browser, cookies_file=args.cookies_file,
                    flat=True, verbose=args.verbose, playlist_limit=getattr(args, 'limit', None))

def cmd_watch_later(args):
    with _authed_ydl(args) as ydl:
        ents = extract_entries("https://www.youtube.com/playlist?list=WL", ydl, args.limit)
        rows = [normalize(e) for e in ents]
        _enrich_missing_metadata(rows,
                                 cookies_from_browser=getattr(args, 'cookies_from_browser', None),
                                 cookies_file=getattr(args, 'cookies_file', None),
                                 verbose=args.verbose)
        emit_rows(rows, [("title", "Title"), ("channel", "Channel"), ("url", "URL")], getattr(args, 'format', 'table'))

def cmd_liked(args):
    with _authed_ydl(args) as ydl:
        ents = extract_entries("https://www.youtube.com/playlist?list=LL", ydl, args.limit)
        rows = [normalize(e) for e in ents]
        _enrich_missing_metadata(rows,
                                 cookies_from_browser=getattr(args, 'cookies_from_browser', None),
                                 cookies_file=getattr(args, 'cookies_file', None),
                                 verbose=args.verbose)
        emit_rows(rows, [("title", "Title"), ("channel", "Channel"), ("url", "URL")], getattr(args, 'format', 'table'))

def cmd_my_playlists(args):
    with _authed_ydl(args) as ydl:
        ents = extract_entries("https://www.youtube.com/feed/playlists", ydl, args.limit)
        # For playlists, expose the playlist URL if present
        rows = []
        for e in ents:
            ne = normalize(e)
            ne["url"] = e.get("webpage_url") or e.get("url") or ne["url"]
            rows.append(ne)
        _enrich_missing_metadata(rows,
                                 cookies_from_browser=getattr(args, 'cookies_from_browser', None),
                                 cookies_file=getattr(args, 'cookies_file', None),
                                 verbose=args.verbose)
        emit_rows(rows, [("title", "Playlist"), ("channel", "Owner/Channel"), ("url", "URL")], getattr(args, 'format', 'table'))

def cmd_subscriptions(args):
    with _authed_ydl(args) as ydl:
        ents = extract_entries("https://www.youtube.com/feed/channels", ydl, args.limit)
        rows = [normalize(e) for e in ents]
        _enrich_missing_metadata(rows,
                                 cookies_from_browser=getattr(args, 'cookies_from_browser', None),
                                 cookies_file=getattr(args, 'cookies_file', None),
                                 verbose=args.verbose)
        emit_rows(rows, [("title", "Title"), ("channel", "Channel"), ("url", "URL")], getattr(args, 'format', 'table'))

def cmd_home(args):
    with _authed_ydl(args) as ydl:
        # Try a few known URLs for the Home feed; yt-dlp support varies by version.
        # Include desktop and mobile variants and older aliases.
        candidates = [
            "https://www.youtube.com/feed/recommended",
            "https://www.youtube.com/?app=desktop",
            "https://www.youtube.com/?app=m&persist_app=1",
            "https://www.youtube.com/",
        ]
        ents: List[Dict[str, Any]] = []
        for url in candidates:
            try:
                trial = extract_entries(url, ydl, args.limit)
            except Exception:
                continue
            # Heuristics to detect bogus results commonly returned by yt-dlp for Home:
            # - A single entry pointing at a YouTube root/landing URL
            # - Entries that lack both id and title
            def is_bogus(e: Dict[str, Any]) -> bool:
                u = (e.get("webpage_url") or e.get("url") or "").rstrip("/")
                no_meta = not (e.get("id") or e.get("title"))
                rootish = u in {"https://www.youtube.com", "https://www.youtube.com?app=desktop", "https://www.youtube.com?app=m&persist_app=1"} or (
                    u.startswith("https://www.youtube.com") and ("watch?v=" not in u and "/playlist" not in u and "/channel/" not in u and "/@" not in u)
                )
                return no_meta or rootish

            if not trial:
                continue
            # Filter out bogus entries; accept if anything real remains
            filtered = [e for e in trial if isinstance(e, dict) and not is_bogus(e)]
            if filtered:
                ents = filtered
                break
        if not ents:
            raise SystemExit(
                "Could not extract Home feed with this yt-dlp version. "
                "Try 'subs', 'watchlater', or 'liked' instead, or update yt-dlp."
            )
        rows = [normalize(e) for e in ents]
        _enrich_missing_metadata(rows,
                                 cookies_from_browser=getattr(args, 'cookies_from_browser', None),
                                 cookies_file=getattr(args, 'cookies_file', None),
                                 verbose=args.verbose)
        emit_rows(rows, [("title", "Title"), ("channel", "Channel"), ("url", "URL")], getattr(args, 'format', 'table'))

# ---------- Main ----------
def main():
    p = argparse.ArgumentParser(
        prog="yt_browse.py",
        formatter_class=argparse.RawTextHelpFormatter,
        description="Browse YouTube with yt-dlp (search, playlists, Watch Later, subscriptions, home feed)."
    )
    p.add_argument("--verbose", action="store_true", help="Verbose yt-dlp output")
    p.add_argument("--format", choices=["table","jsonl"], default="table", help="Output format")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("search", help="Search public videos")
    sp.add_argument("query")
    sp.add_argument("--limit", type=int, default=25)
    sp.set_defaults(func=cmd_search)

    pl = sub.add_parser("playlist", help="Browse a playlist by URL")
    pl.add_argument("url", help="Playlist URL (public or unlisted; private requires cookies)")
    pl.add_argument("--limit", type=int, default=200)
    # Optional cookies for private playlists
    pl.add_argument("--cookies-from-browser", metavar="BROWSER",
                   help="Read cookies directly from your browser (e.g. chrome, firefox, edge, brave)")
    pl.add_argument("--cookies-file", metavar="PATH",
                   help="Path to cookies.txt (Netscape format)")
    pl.set_defaults(func=cmd_playlist)

    # Auth-needed commands share cookie args
    def add_auth(a):
        a.add_argument("--cookies-from-browser", metavar="BROWSER",
                       help="Read cookies directly from your browser (e.g. chrome, firefox, edge, brave)")
        a.add_argument("--cookies-file", metavar="PATH",
                       help="Path to cookies.txt (Netscape format)")
        a.add_argument("--limit", type=int, default=200)

    wl = sub.add_parser("watchlater", help="Your Watch Later (requires cookies)")
    add_auth(wl); wl.set_defaults(func=cmd_watch_later)

    ll = sub.add_parser("liked", help="Your Liked Videos (requires cookies)")
    add_auth(ll); ll.set_defaults(func=cmd_liked)

    mpl = sub.add_parser("myplaylists", help="Your Playlists page (requires cookies)")
    add_auth(mpl); mpl.set_defaults(func=cmd_my_playlists)

    subs = sub.add_parser("subs", help="Your Subscriptions feed (requires cookies)")
    add_auth(subs); subs.set_defaults(func=cmd_subscriptions)

    home = sub.add_parser("home", help="Your Home recommendations (requires cookies)")
    add_auth(home); home.set_defaults(func=cmd_home)

    args = p.parse_args()
    try:
        args.func(args)
    except Exception as e:
        if args.verbose:
            raise
        sys.exit(f"Error: {e}")

if __name__ == "__main__":
    main()
