#!/usr/bin/env python3
"""
Browse and download Rockbox themes by device (target).
Works with themes.rockbox.org structure:
  - List page:  index.php?target=<target>
  - Theme page: index.php?themeid=<id>&target=<target>

Features
- list-devices: show common targets (you can add more)
- list-themes <target> [--search "query"] : list themes for a device
- show <target> <themeid> : show details & preview URLs
- download <target> <themeid> [--out DIR] : fetch the theme ZIP
- install <target> <themeid> --mount /path/to/ipod : download+merge into .rockbox/

Dependencies: requests, beautifulsoup4, tqdm (optional, for progress)
    pip install requests beautifulsoup4 tqdm
"""

import argparse
import os
import re
import sys
import time
import zipfile
from dataclasses import dataclass
from typing import List, Optional, Dict
from urllib.parse import urljoin, urlencode

import requests
from bs4 import BeautifulSoup

BASE = "https://themes.rockbox.org/"  # Do not hit too rapidly; be polite.
HEADERS = {"User-Agent": "RockboxThemeCLI/1.0 (+personal use)"}

# Starter list; add your device(s) here if missing.
COMMON_TARGETS = {
    # iPod family
    "ipodvideo": "iPod Video (5G/5.5G)",
    "ipod6g": "iPod Classic (6G/7G)",
    "ipod4g": "iPod 4G",
    "ipodcolor": "iPod Color/Photo",
    "ipodmini": "iPod Mini 1G",
    "ipodmini2g": "iPod Mini 2G",
    "ipodnano1g": "iPod Nano 1G",
    "ipodnano2g": "iPod Nano 2G",
    # Sandisk examples
    "sansaclip": "Sansa Clip (original)",
    "sansaclipv2": "Sansa Clip v2",
    "sansaclipplus": "Sansa Clip+",
    "sansaclipzip": "Sansa Clip Zip",
    # Add more Rockbox targets as needed...
}

@dataclass
class Theme:
    id: str
    name: str
    author: Optional[str]
    downloads: Optional[int]
    rating: Optional[str]
    page_url: str
    preview_urls: List[str]

def _get(url: str, params=None) -> requests.Response:
    resp = requests.get(url, params=params, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    return resp

def _parse_list_page(html: str, target: str) -> List[Theme]:
    soup = BeautifulSoup(html, "html.parser")
    themes: List[Theme] = []

    # The list page has a grid/table of themes. We’ll look for links that include themeid=
    for a in soup.select('a[href*="themeid="]'):
        href = a.get("href", "")
        m = re.search(r"themeid=(\d+)", href)
        if not m:
            continue
        themeid = m.group(1)
        # Try to extract name & surrounding metadata
        name = a.get_text(strip=True) or f"Theme {themeid}"
        card = a.find_parent(["div", "tr"])  # heuristics for card/row
        author = None
        downloads = None
        rating = None
        previews = []

        if card:
            # Author / stats heuristics
            txt = card.get_text(" ", strip=True)
            ma = re.search(r"Author:\s*(.+?)(?:\s{2,}|$)", txt, re.I)
            if ma: author = ma.group(1).strip()
            md = re.search(r"Downloads?:\s*([0-9,]+)", txt, re.I)
            if md:
                try: downloads = int(md.group(1).replace(",", ""))
                except: pass
            mr = re.search(r"Rating:\s*([0-9.]+\/[0-9]+|[★☆]+)", txt, re.I)
            if mr: rating = mr.group(1).strip()

            # preview images (thumbnails)
            for img in card.select("img"):
                src = img.get("src")
                if src and ("preview" in src or "thumb" in src or src.endswith((".jpg", ".png", ".gif"))):
                    previews.append(urljoin(BASE, src))

        page_url = urljoin(BASE, f"index.php?{urlencode({'themeid': themeid, 'target': target})}")
        themes.append(Theme(themeid, name, author, downloads, rating, page_url, list(dict.fromkeys(previews))))

    # De-duplicate by id (some pages repeat anchors)
    uniq: Dict[str, Theme] = {}
    for t in themes:
        uniq[t.id] = t
    return list(uniq.values())

def list_themes(target: str, search: Optional[str] = None) -> List[Theme]:
    url = urljoin(BASE, "index.php")
    html = _get(url, params={"target": target}).text
    themes = _parse_list_page(html, target)
    if search:
        q = search.lower()
        themes = [t for t in themes if q in t.name.lower() or (t.author and q in t.author.lower())]
    return themes

def _parse_theme_page(html: str, target: str, themeid: str) -> Dict[str, str]:
    """
    Extract details & the download link from a theme page.
    We search for an anchor whose href includes 'download' and ends with .zip (robust to minor site changes).
    """
    soup = BeautifulSoup(html, "html.parser")
    details = {}

    # Name
    h = soup.find(["h1", "h2"])
    if h:
        details["name"] = h.get_text(strip=True)

    # Find a download link
    dl = None
    for a in soup.select('a[href]'):
        href = a["href"]
        if "download" in href.lower() and href.lower().endswith(".zip"):
            dl = urljoin(BASE, href)
            break
    # Fallback: any .zip link on the page
    if not dl:
        z = soup.select_one('a[href$=".zip"]')
        if z:
            dl = urljoin(BASE, z["href"])

    # Absolute fallback (try a common pattern used historically):
    # index.php?download=true&themeid=<id>&target=<target>
    if not dl:
        maybe = urljoin(BASE, f"index.php?{urlencode({'download':'true','themeid':themeid,'target':target})}")
        # We won't HEAD it (to avoid extra call). Return and let download() handle errors.
        dl = maybe

    details["download_url"] = dl or ""
    # Collect full-size previews if present
    previews = []
    for img in soup.select("img"):
        src = img.get("src")
        if src and ("preview" in src or "screenshot" in src or src.endswith((".jpg",".png",".gif"))):
            previews.append(urljoin(BASE, src))
    if previews:
        details["previews"] = "\n".join(list(dict.fromkeys(previews)))
    return details

def show_theme(target: str, themeid: str) -> Dict[str, str]:
    html = _get(urljoin(BASE, "index.php"), params={"themeid": themeid, "target": target}).text
    return _parse_theme_page(html, target, themeid)

def _stream_download(url: str, out_path: str) -> str:
    import math
    from tqdm import tqdm  # optional progress bar
    with requests.get(url, headers=HEADERS, stream=True, timeout=60) as r:
        r.raise_for_status()
        total = int(r.headers.get("Content-Length", "0"))
        os.makedirs(out_path, exist_ok=True)
        filename = re.findall(r"[^/\\]+\.zip", url) or [f"theme_{int(time.time())}.zip"]
        dest = os.path.join(out_path, filename[0])
        chunk = 1024 * 64
        if total:
            with open(dest, "wb") as f, tqdm(total=total, unit="B", unit_scale=True) as p:
                for buf in r.iter_content(chunk_size=chunk):
                    if buf: f.write(buf); p.update(len(buf))
        else:
            with open(dest, "wb") as f:
                for buf in r.iter_content(chunk_size=chunk):
                    if buf: f.write(buf)
        return dest

def download_theme(target: str, themeid: str, out_dir: str) -> str:
    info = show_theme(target, themeid)
    dl = info.get("download_url", "")
    if not dl:
        raise RuntimeError("Could not find a download link on the theme page.")
    return _stream_download(dl, out_dir)

def install_theme_zip(zip_path: str, mountpoint: str) -> None:
    """
    Merge the ZIP into the device's .rockbox/ directory.
    Most theme ZIPs contain a top-level .rockbox/; we preserve structure.
    """
    if not os.path.isdir(mountpoint):
        raise RuntimeError(f"Mountpoint not found: {mountpoint}")
    with zipfile.ZipFile(zip_path) as zf:
        for member in zf.infolist():
            # Avoid path traversal
            member_path = os.path.normpath(member.filename)
            if member_path.startswith(("..", "/","\\")):
                continue
            dest = os.path.join(mountpoint, member_path)
            if member.is_dir():
                os.makedirs(dest, exist_ok=True)
            else:
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                with zf.open(member) as src, open(dest, "wb") as out:
                    out.write(src.read())

def main():
    ap = argparse.ArgumentParser(description="Browse & download Rockbox themes")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list-devices", help="Show common Rockbox targets")

    lp = sub.add_parser("list-themes", help="List themes for a device")
    lp.add_argument("target", help="Rockbox target (e.g., ipodvideo, ipod6g, sansaclipzip)")
    lp.add_argument("--search", help="Filter by name/author")

    sp = sub.add_parser("show", help="Show details for a theme")
    sp.add_argument("target")
    sp.add_argument("themeid")

    dp = sub.add_parser("download", help="Download a theme ZIP")
    dp.add_argument("target")
    dp.add_argument("themeid")
    dp.add_argument("--out", default="downloads", help="Output directory")

    ip = sub.add_parser("install", help="Download and install to a mounted device")
    ip.add_argument("target")
    ip.add_argument("themeid")
    ip.add_argument("--mount", required=True, help="Mountpoint of your Rockbox device")
    ip.add_argument("--keep-zip", action="store_true")

    args = ap.parse_args()

    if args.cmd == "list-devices":
        print("Known targets:")
        for k, v in COMMON_TARGETS.items():
            print(f"  {k:15}  {v}")
        print("\nTip: If your target is missing, you can still try it — the site usually accepts many target names.")
        return

    if args.cmd == "list-themes":
        themes = list_themes(args.target, search=args.search)
        if not themes:
            print("No themes found (or parsing failed). Try a different target or without --search.")
            return
        for t in themes:
            line = f"#{t.id}  {t.name}"
            if t.author: line += f"  — {t.author}"
            if t.downloads: line += f"  [{t.downloads} dl]"
            if t.rating: line += f"  ★ {t.rating}"
            print(line)
        return

    if args.cmd == "show":
        info = show_theme(args.target, args.themeid)
        if not info:
            print("Could not parse theme page.")
            return
        print(f"Name: {info.get('name','(unknown)')}")
        print(f"Theme URL: {urljoin(BASE, f'index.php?themeid={args.themeid}&target={args.target}')}")
        print(f"Download: {info.get('download_url','(not found)')}")
        previews = info.get("previews")
        if previews:
            print("Previews:")
            for u in previews.splitlines():
                print("  ", u)
        return

    if args.cmd == "download":
        dest = download_theme(args.target, args.themeid, args.out)
        print(f"Saved: {dest}")
        return

    if args.cmd == "install":
        z = download_theme(args.target, args.themeid, args.mount if args.keep_zip else "/tmp")
        try:
            install_theme_zip(z, args.mount)
            print(f"Installed to {args.mount}")
        finally:
            if (not args.keep_zip) and os.path.exists(z):
                try: os.remove(z)
                except: pass

if __name__ == "__main__":
    main()
