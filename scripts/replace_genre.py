#!/usr/bin/env python3
"""Replace track genres in the music index (and optionally audio tags)."""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Update genres in the RockSync music index database. Optionally "
            "write the new genre into audio files using mutagen."
        )
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=Path("app/music_index.sqlite3"),
        help="Path to the music index SQLite database (default: app/music_index.sqlite3)",
    )
    parser.add_argument(
        "--from-genre",
        dest="source_genre",
        required=True,
        help="Genre value to search for",
    )
    parser.add_argument(
        "--to-genre",
        dest="target_genre",
        required=True,
        help="Replacement genre value (use an empty string to clear the genre)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without touching the database or files",
    )
    parser.add_argument(
        "--update-tags",
        action="store_true",
        help="Also update genre tags in the underlying audio files using mutagen",
    )
    parser.add_argument(
        "--case-sensitive",
        action="store_true",
        help="Match the source genre with case sensitivity (default: case-insensitive)",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print every processed track even if no change was needed",
    )
    return parser.parse_args()


def fetch_tracks(
    conn: sqlite3.Connection, source_genre: str, case_sensitive: bool
) -> List[Tuple[str, Optional[str]]]:
    if case_sensitive:
        query = "SELECT path, genre FROM tracks WHERE genre = ?"
        params = (source_genre.strip(),)
    else:
        query = "SELECT path, genre FROM tracks WHERE genre IS NOT NULL AND LOWER(genre) = ?"
        params = (source_genre.strip().lower(),)
    cursor = conn.execute(query, params)
    return [(row[0], row[1]) for row in cursor]


def update_database_genre(
    conn: sqlite3.Connection,
    track_path: str,
    new_genre: Optional[str],
    dry_run: bool,
) -> bool:
    if dry_run:
        return True
    conn.execute("UPDATE tracks SET genre = ? WHERE path = ?", (new_genre, track_path))
    return True


def load_mutagen():  # type: ignore[return-type]
    try:
        import mutagen  # type: ignore
    except ImportError as exc:  # pragma: no cover - runtime dependency
        sys.stderr.write(
            "mutagen is required for --update-tags. Install with 'pip install mutagen'.\n"
        )
        raise SystemExit(1) from exc
    return mutagen


def update_file_genre(
    mutagen_module,
    audio_path: Path,
    new_genre: Optional[str],
    dry_run: bool,
) -> Tuple[bool, str]:
    try:
        audio = mutagen_module.File(str(audio_path), easy=True)
    except Exception as exc:  # pragma: no cover - filesystem dependent
        return False, f"error reading tags ({exc})"
    if audio is None or getattr(audio, "tags", None) is None:
        return False, "no tags"

    tags = audio.tags
    existing_raw = tags.get("genre") or []
    existing_clean = [str(item).strip() for item in existing_raw if str(item).strip()]
    desired_list = [new_genre] if new_genre else []

    if existing_clean == desired_list:
        return False, "ok"

    if dry_run:
        return True, "would update"

    try:
        if new_genre:
            tags["genre"] = [new_genre]
        else:
            tags.pop("genre", None)
        audio.save()
        return True, "updated"
    except Exception as exc:  # pragma: no cover - filesystem dependent
        return False, f"error saving tags ({exc})"


def main() -> None:
    args = parse_args()

    db_path = args.db.expanduser()
    if not db_path.exists():
        sys.stderr.write(f"Database not found: {db_path}\n")
        raise SystemExit(2)

    source_genre = args.source_genre.strip()
    target_genre = args.target_genre.strip()
    target_value: Optional[str] = target_genre if target_genre else None

    with sqlite3.connect(str(db_path)) as conn:
        tracks = fetch_tracks(conn, source_genre, args.case_sensitive)
        total = len(tracks)
        if total == 0:
            print("No tracks matched the requested genre.")
            return

        mutagen_module = None
        if args.update_tags:
            mutagen_module = load_mutagen()

        summary: Dict[str, int] = {
            "matched": total,
            "db_updated": 0,
            "db_skipped": 0,
            "tag_updated": 0,
            "tag_skipped": 0,
            "tag_errors": 0,
        }

        for path_str, current_genre in tracks:
            db_needs_update = (current_genre or "").strip() != (target_value or "")
            file_changed = False
            file_status = ""

            if db_needs_update:
                if update_database_genre(conn, path_str, target_value, args.dry_run):
                    summary["db_updated"] += 1
            else:
                summary["db_skipped"] += 1

            if args.update_tags:
                audio_path = Path(path_str)
                if not audio_path.exists():
                    summary["tag_errors"] += 1
                    file_status = "missing file"
                else:
                    changed, status = update_file_genre(
                        mutagen_module, audio_path, target_value, args.dry_run
                    )
                    file_changed = changed
                    file_status = status
                    if changed:
                        summary["tag_updated"] += 1
                    elif status.startswith("error"):
                        summary["tag_errors"] += 1
                    else:
                        summary["tag_skipped"] += 1

            if args.verbose or db_needs_update or file_changed:
                target_display = target_value if target_value is not None else "<cleared>"
                parts = [f"{path_str}", f"{current_genre or '<none>'} -> {target_display}"]
                if args.update_tags:
                    parts.append(f"tags: {file_status or 'ok'}")
                prefix = "dry-run" if args.dry_run else "update"
                print(f"{prefix}: " + " | ".join(parts))

        if args.dry_run:
            print("Dry-run complete; no changes were committed.")
        else:
            conn.commit()
            print("Database updates committed.")

        print("\nSummary:")
        for key in (
            "matched",
            "db_updated",
            "db_skipped",
            "tag_updated",
            "tag_skipped",
            "tag_errors",
        ):
            print(f"  {key}: {summary[key]}")


if __name__ == "__main__":
    main()
