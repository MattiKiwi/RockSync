#!/usr/bin/env python3
"""Restore track genres from a backup database and remove stray 'Genre:' tags."""

import argparse
import sqlite3
import sys
from pathlib import Path
from typing import Dict, Iterable, Optional, Tuple

try:
    import mutagen
except ImportError:  # pragma: no cover
    sys.stderr.write("mutagen is required. Install with 'pip install mutagen'.\n")
    sys.exit(1)


def sanitize_genre(value: Optional[str]) -> str:
    """Normalize a genre string by trimming and stripping the 'Genre:' prefix."""
    if value is None:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    lower = text.lower()
    if lower.startswith("genre:"):
        text = text.split(":", 1)[1].strip()
    return text


def load_backup_genres(db_path: Path) -> Dict[str, str]:
    with sqlite3.connect(str(db_path)) as conn:
        cursor = conn.execute("SELECT path, genre FROM tracks")
        return {row[0]: sanitize_genre(row[1]) for row in cursor}


def load_current_tracks(db_path: Path) -> Dict[str, Optional[str]]:
    with sqlite3.connect(str(db_path)) as conn:
        cursor = conn.execute("SELECT path, genre FROM tracks")
        return {row[0]: row[1] for row in cursor}


def needs_tag_update(existing: Optional[Iterable[str]], desired: Iterable[str]) -> bool:
    existing_list = list(existing or [])
    desired_list = list(desired)
    cleaned_existing = [sanitize_genre(item) for item in existing_list if sanitize_genre(item)]
    if cleaned_existing != desired_list:
        return True
    # Even if the cleaned values match, ensure we strip any lingering 'Genre:' prefix.
    if any(str(item or "").strip().lower().startswith("genre:") for item in existing_list):
        return True
    if not desired_list and existing_list:
        return True
    return False


def update_file_genre(path: Path, target_genre: str, dry_run: bool) -> Tuple[bool, str]:
    try:
        audio = mutagen.File(path, easy=True)
    except Exception as exc:  # pragma: no cover
        return False, f"error reading file ({exc})"

    if audio is None or getattr(audio, "tags", None) is None:
        return False, "no tags"

    tags = audio.tags
    desired_list = [target_genre] if target_genre else []
    existing = tags.get("genre")
    if not needs_tag_update(existing, desired_list):
        return False, "ok"

    if dry_run:
        return True, "would update"

    try:
        if target_genre:
            tags["genre"] = [target_genre]
        else:
            tags.pop("genre", None)
        audio.save()
        return True, "updated"
    except Exception as exc:  # pragma: no cover
        return False, f"error saving tags ({exc})"


def update_database_genre(conn: sqlite3.Connection, path: str, target_genre: str, dry_run: bool) -> bool:
    cursor = conn.execute("SELECT genre FROM tracks WHERE path = ?", (path,))
    row = cursor.fetchone()
    if row is None:
        return False
    current_value = row[0] or ""
    if current_value == target_genre:
        # If the stored value is the same, no update needed.
        return False
    if dry_run:
        return True
    conn.execute("UPDATE tracks SET genre = ? WHERE path = ?", (target_genre, path))
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Restore genres using backup database entries.")
    parser.add_argument("--current-db", default="app/music_index.sqlite3", type=Path, help="Path to the working music index database")
    parser.add_argument("--backup-db", default="backup_music_index.sqlite3", type=Path, help="Path to the backup music index database")
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without touching files or the database")
    args = parser.parse_args()

    if not args.backup_db.exists():
        sys.stderr.write(f"Backup DB not found: {args.backup_db}\n")
        sys.exit(2)
    if not args.current_db.exists():
        sys.stderr.write(f"Current DB not found: {args.current_db}\n")
        sys.exit(2)

    backup_genres = load_backup_genres(args.backup_db)
    current_entries = load_current_tracks(args.current_db)

    if not backup_genres:
        sys.stderr.write("Backup database contains no tracks.\n")
        sys.exit(3)

    summary = {
        "file_updated": 0,
        "file_skipped": 0,
        "file_errors": 0,
        "db_updated": 0,
        "db_skipped": 0,
        "missing_files": 0,
        "restored": 0,
        "cleaned": 0,
    }

    with sqlite3.connect(str(args.current_db)) as conn:
        for path_str, raw_genre in current_entries.items():
            target = None
            reason = None

            if path_str in backup_genres:
                target = backup_genres[path_str]
                reason = "backup"
            else:
                cleaned = sanitize_genre(raw_genre)
                if cleaned != (raw_genre or "").strip():
                    target = cleaned
                    reason = "cleanup"
                elif (raw_genre or "").strip().lower() == "genre:":
                    target = ""
                    reason = "cleanup"

            if target is None:
                summary["db_skipped"] += 1
                summary["file_skipped"] += 1
                continue

            path = Path(path_str)
            is_restore = reason == "backup"
            if is_restore:
                summary["restored"] += 1
            else:
                summary["cleaned"] += 1

            # Update audio file tags
            if path.exists():
                changed, msg = update_file_genre(path, target, args.dry_run)
                if changed:
                    summary["file_updated"] += 1
                    action = "restore" if is_restore else "cleanup"
                    prefix = "dry-run" if args.dry_run else action
                    print(f"{prefix}: {path} -> '{target}' ({reason})")
                else:
                    if msg.startswith("error"):
                        summary["file_errors"] += 1
                        print(f"error: {path} ({msg})")
                    else:
                        summary["file_skipped"] += 1
                        if msg not in {"ok"}:
                            print(f"skip: {path} ({msg})")
            else:
                summary["missing_files"] += 1
                summary["file_skipped"] += 1
                print(f"missing: {path}")

            # Update database entry
            db_changed = update_database_genre(conn, path_str, target, args.dry_run)
            if db_changed:
                summary["db_updated"] += 1
            else:
                summary["db_skipped"] += 1

        if not args.dry_run:
            conn.commit()

    print("\nSummary:")
    for key in (
        "file_updated",
        "file_errors",
        "file_skipped",
        "db_updated",
        "db_skipped",
        "missing_files",
        "restored",
        "cleaned",
    ):
        print(f"  {key}: {summary[key]}")


if __name__ == "__main__":
    main()
