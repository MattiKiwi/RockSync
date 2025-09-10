#!/usr/bin/env python3
from __future__ import annotations
import argparse, sys, textwrap
from typing import Any, Dict, List, Optional, Tuple, Union
from yt_dlp import YoutubeDL

# ---------- Helpers ----------
def make_ydl(cookies_from_browser: Optional[str] = None,
             cookies_file: Optional[str] = None,
             flat: bool = True,
             verbose: bool = False) -> YoutubeDL:
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
        # A realistic UA can reduce bot friction on some hosts
        "http_headers": {"User-Agent": "Mozilla/5.0"},
    }
    if cookies_from_browser:
        # yt-dlp Python API expects a tuple/list (browser[, profile[, keyring[, container]]]).
        # Passing a bare string can be unpacked char-by-char in some versions.
        # Wrap in a 1-tuple so 'firefox' becomes ('firefox',)
        ydl_opts["cookiesfrombrowser"] = (cookies_from_browser,)
    if cookies_file:
        ydl_opts["cookiefile"] = cookies_file
    return YoutubeDL(ydl_opts)

def print_rows(rows: List[Dict[str, Any]], cols: List[Tuple[str, str]]):
    # cols = [(field, header), ...]
    if not rows:
        print("(no results)")
        return
    # simple human-readable table
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

def normalize(e: Dict[str, Any]) -> Dict[str, Any]:
    # yt-dlp keys vary by page type; this normalizes the core fields we care about
    url = e.get("webpage_url") or e.get("url") or e.get("original_url")
    return {
        "id": e.get("id"),
        "title": e.get("title"),
        "channel": e.get("uploader") or e.get("channel") or e.get("channel_id") or "",
        "duration": e.get("duration") or "",
        "upload_date": e.get("upload_date") or e.get("release_date") or "",
        "url": url if (url and url.startswith("http")) else (f"https://www.youtube.com/watch?v={e.get('id')}" if e.get("id") else url),
    }

# ---------- Commands ----------
def cmd_search(args):
    with make_ydl(flat=True, verbose=args.verbose) as ydl:
        url = f"ytsearch{args.limit}:{args.query}"
        ents = extract_entries(url, ydl, args.limit)
        rows = [normalize(e) for e in ents]
        print_rows(rows, [("title", "Title"), ("channel", "Channel"), ("url", "URL")])

def cmd_playlist(args):
    with make_ydl(flat=True, verbose=args.verbose) as ydl:
        url = args.url
        ents = extract_entries(url, ydl, args.limit)
        rows = [normalize(e) for e in ents]
        print_rows(rows, [("title", "Title"), ("channel", "Channel"), ("url", "URL")])

def _authed_ydl(args) -> YoutubeDL:
    if not (args.cookies_from_browser or args.cookies_file):
        raise SystemExit("This command requires auth. Pass --cookies-from-browser <browser> or --cookies-file <path>.")
    return make_ydl(cookies_from_browser=args.cookies_from_browser, cookies_file=args.cookies_file,
                    flat=True, verbose=args.verbose)

def cmd_watch_later(args):
    with _authed_ydl(args) as ydl:
        ents = extract_entries("https://www.youtube.com/playlist?list=WL", ydl, args.limit)
        rows = [normalize(e) for e in ents]
        print_rows(rows, [("title", "Title"), ("channel", "Channel"), ("url", "URL")])

def cmd_liked(args):
    with _authed_ydl(args) as ydl:
        ents = extract_entries("https://www.youtube.com/playlist?list=LL", ydl, args.limit)
        rows = [normalize(e) for e in ents]
        print_rows(rows, [("title", "Title"), ("channel", "Channel"), ("url", "URL")])

def cmd_my_playlists(args):
    with _authed_ydl(args) as ydl:
        ents = extract_entries("https://www.youtube.com/feed/playlists", ydl, args.limit)
        # For playlists, expose the playlist URL if present
        rows = []
        for e in ents:
            ne = normalize(e)
            ne["url"] = e.get("webpage_url") or e.get("url") or ne["url"]
            rows.append(ne)
        print_rows(rows, [("title", "Playlist"), ("channel", "Owner/Channel"), ("url", "URL")])

def cmd_subscriptions(args):
    with _authed_ydl(args) as ydl:
        ents = extract_entries("https://www.youtube.com/feed/channels", ydl, args.limit)
        rows = [normalize(e) for e in ents]
        print_rows(rows, [("title", "Title"), ("channel", "Channel"), ("url", "URL")])

def cmd_home(args):
    with _authed_ydl(args) as ydl:
        # Try a few known URLs for the Home feed; yt-dlp support varies by version.
        # Include desktop and mobile variants and older aliases.
        candidates = [
            "https://www.youtube.com/feed/home",
            "https://www.youtube.com/feed/what_to_watch",
            "https://www.youtube.com/feed/recommended",
            "https://www.youtube.com/?app=desktop",
            "https://www.youtube.com/?app=m&persist_app=1",
            "https://m.youtube.com/?persist_app=1",
            "https://m.youtube.com/feed/home",
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
                ents = trial
                break
        if not ents:
            raise SystemExit(
                "Could not extract Home feed with this yt-dlp version. "
                "Try 'subs', 'watchlater', or 'liked' instead, or update yt-dlp."
            )
        rows = [normalize(e) for e in ents]
        print_rows(rows, [("title", "Title"), ("channel", "Channel"), ("url", "URL")])

# ---------- Main ----------
def main():
    p = argparse.ArgumentParser(
        prog="yt_browse.py",
        formatter_class=argparse.RawTextHelpFormatter,
        description="Browse YouTube with yt-dlp (search, playlists, Watch Later, subscriptions, home feed)."
    )
    p.add_argument("--verbose", action="store_true", help="Verbose yt-dlp output")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("search", help="Search public videos")
    sp.add_argument("query")
    sp.add_argument("--limit", type=int, default=25)
    sp.set_defaults(func=cmd_search)

    pl = sub.add_parser("playlist", help="Browse a playlist by URL")
    pl.add_argument("url", help="Playlist URL (public or unlisted; private requires cookies)")
    pl.add_argument("--limit", type=int, default=200)
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
