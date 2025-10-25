#!/usr/bin/env python3
"""
Simple helper to rewrite the stored library paths inside `music_index.sqlite3`.

Usage:
    python scripts/relocate_music_paths.py \
        --db app/music_index.sqlite3 \
        --old "/run/media/matti/Archive Drive/Music/Full-Quality/" \
        --new "/run/media/mschirmer/Archive Drive/Music/Full-Quality/"
"""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default="app/music_index.sqlite3", type=Path, help="Path to music_index.sqlite3")
    parser.add_argument("--old", required=True, help="Old prefix to replace")
    parser.add_argument("--new", required=True, help="Replacement prefix")
    parser.add_argument("--dry-run", action="store_true", help="Report how many rows would change without writing")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    db_path: Path = args.db
    if not db_path.exists():
        raise SystemExit(f"Database not found: {db_path}")

    old_prefix = args.old.rstrip("/ ")
    new_prefix = args.new.rstrip("/ ")

    if old_prefix == new_prefix:
        raise SystemExit("Old and new prefixes are identical; nothing to do.")

    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        like_pattern = old_prefix + "%"
        cur.execute("SELECT COUNT(1) FROM tracks WHERE path LIKE ?", (like_pattern,))
        affected = cur.fetchone()[0]
        if affected == 0:
            print("No rows matched the old prefix.")
            return
        print(f"Found {affected} row(s) to update in {db_path}.")

        if not args.dry_run:
            # substr() is 1-indexed in SQLite, so skip the old prefix length + 1.
            start_idx = len(old_prefix) + 1
            cur.execute(
                "UPDATE tracks SET path = ? || substr(path, ?) WHERE path LIKE ?",
                (new_prefix, start_idx, like_pattern),
            )
            conn.commit()
            print(f"Updated {cur.rowcount} row(s).")
        else:
            print("Dry-run mode enabled; no changes written.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
