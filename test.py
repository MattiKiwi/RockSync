#!/usr/bin/env python3

"""
List your TIDAL favorite albums.

Notes:
- This uses the `tidalapi` Python library for a clean programmatic interface.
- It works fine alongside tidal-dl-ng and uses the same TIDAL account.

Setup:
  pip install tidalapi

Run:
  python test.py
"""

import sys
from typing import List

try:
    import tidalapi
except ImportError:
    print(
        "Missing dependency: tidalapi.\n"
        "Install with: pip install tidalapi",
        file=sys.stderr,
    )
    sys.exit(1)


def login_session() -> "tidalapi.Session":
    """Log in to TIDAL via OAuth device flow (opens a browser/code prompt)."""
    session = tidalapi.Session()
    # This prompts you to open a URL and enter a short code.
    # Once approved, the session is authenticated and cached locally.
    ok = session.login_oauth_simple()
    if not ok:
        raise RuntimeError("Failed to authenticate with TIDAL.")
    return session


def fetch_all_favorite_albums(favorites: "tidalapi.Favorites", batch: int = 50) -> List["tidalapi.Album"]:
    """Fetch all favorite albums with simple pagination."""
    albums: List["tidalapi.Album"] = []
    offset = 0
    while True:
        chunk = favorites.albums(limit=batch, offset=offset)
        if not chunk:
            break
        albums.extend(chunk)
        if len(chunk) < batch:
            break
        offset += batch
    return albums


def main() -> int:
    session = login_session()
    favorites = tidalapi.Favorites(session, session.user.id)

    albums = fetch_all_favorite_albums(favorites)
    # Sort for nicer output
    albums.sort(key=lambda a: ((a.artist.name or "").lower(), (a.name or "").lower()))

    print(f"Found {len(albums)} favorite albums:\n")
    for a in albums:
        artist = getattr(a.artist, "name", None) or "Unknown Artist"
        name = a.name or "Unknown Album"
        year = getattr(a, "release_date", None) or getattr(a, "releaseDate", None) or ""
        year = str(year)[:4] if year else ""
        extra = f" ({year})" if year else ""
        print(f"- {artist} — {name}{extra} [id: {a.id}]")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
