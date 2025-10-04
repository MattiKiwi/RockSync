#!/usr/bin/env python3
"""Delete tracks that match a specific genre from the library index.

The script can remove entries from the SQLite music index and optionally delete
matching audio files from disk. Run with --dry-run first to preview the
impacted tracks.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Remove tracks from the RockSync music index when their genre matches "
            "the provided value. Optionally delete the corresponding audio files."
        )
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=Path("app/music_index.sqlite3"),
        help="Path to the music index SQLite database (default: app/music_index.sqlite3)",
    )
    parser.add_argument(
        "--genre",
        dest="genre",
        required=True,
        help="Genre value to match against",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview deletions without modifying the database or files",
    )
    parser.add_argument(
        "--delete-files",
        action="store_true",
        help="Also delete the matching audio files from disk",
    )
    parser.add_argument(
        "--case-sensitive",
        action="store_true",
        help="Match the genre with case sensitivity (default: case-insensitive)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print every matched track even if no changes occur",
    )
    return parser.parse_args()


def fetch_tracks(
    conn: sqlite3.Connection,
    genre: str,
    case_sensitive: bool,
) -> List[Tuple[str, Optional[str]]]:
    if case_sensitive:
        query = "SELECT path, genre FROM tracks WHERE genre = ?"
        params = (genre.strip(),)
    else:
        query = "SELECT path, genre FROM tracks WHERE genre IS NOT NULL AND LOWER(genre) = ?"
        params = (genre.strip().lower(),)
    cursor = conn.execute(query, params)
    return [(row[0], row[1]) for row in cursor]


def delete_from_database(
    conn: sqlite3.Connection,
    track_path: str,
    dry_run: bool,
) -> Tuple[bool, Optional[str]]:
    if dry_run:
        return False, "would delete"
    try:
        conn.execute("DELETE FROM tracks WHERE path = ?", (track_path,))
        return True, "deleted"
    except Exception as exc:  # pragma: no cover - sqlite error path
        return False, f"error deleting ({exc})"


def delete_file(audio_path: Path, dry_run: bool) -> Tuple[bool, str]:
    if not audio_path.exists():
        return False, "missing file"
    if dry_run:
        return False, "would delete file"
    try:
        audio_path.unlink()
        return True, "deleted file"
    except Exception as exc:  # pragma: no cover - filesystem error path
        return False, f"error deleting file ({exc})"


def main() -> None:
    args = parse_args()

    db_path = args.db.expanduser()
    if not db_path.exists():
        sys.stderr.write(f"Database not found: {db_path}\n")
        raise SystemExit(2)

    genre = args.genre.strip()
    if not genre:
        sys.stderr.write("Genre argument cannot be empty.\n")
        raise SystemExit(2)

    with sqlite3.connect(str(db_path)) as conn:
        tracks = fetch_tracks(conn, genre, args.case_sensitive)
        total = len(tracks)
        if total == 0:
            print("No tracks matched the requested genre.")
            return

        summary: Dict[str, int] = {
            "matched": total,
            "db_deleted": 0,
            "db_pending": 0,
            "db_errors": 0,
            "file_deleted": 0,
            "file_pending": 0,
            "file_missing": 0,
            "file_errors": 0,
        }

        for path_str, current_genre in tracks:
            db_changed, db_msg = delete_from_database(conn, path_str, args.dry_run)
            if args.dry_run:
                summary["db_pending"] += 1
            elif db_changed:
                summary["db_deleted"] += 1
            else:
                summary["db_errors"] += 1

            file_msg = "not requested"
            if args.delete_files:
                file_path = Path(path_str)
                file_changed, file_msg = delete_file(file_path, args.dry_run)
                if file_msg == "missing file":
                    summary["file_missing"] += 1
                elif args.dry_run and file_msg == "would delete file":
                    summary["file_pending"] += 1
                elif file_changed:
                    summary["file_deleted"] += 1
                elif file_msg.startswith("error"):
                    summary["file_errors"] += 1

            if args.verbose or args.dry_run or db_msg != "deleted":
                pieces = [path_str, f"genre: {current_genre or '<none>'}"]
                pieces.append(f"db: {db_msg}")
                if args.delete_files:
                    pieces.append(f"file: {file_msg}")
                prefix = "dry-run" if args.dry_run else "delete"
                print(f"{prefix}: " + " | ".join(pieces))

        if args.dry_run:
            print("Dry-run complete; no changes were committed.")
        else:
            conn.commit()
            print("Database deletions committed.")

        print("\nSummary:")
        for key in (
            "matched",
            "db_deleted",
            "db_pending",
            "db_errors",
            "file_deleted",
            "file_pending",
            "file_missing",
            "file_errors",
        ):
            print(f"  {key}: {summary[key]}")


if __name__ == "__main__":
    main()
