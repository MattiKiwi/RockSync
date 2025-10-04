#!/usr/bin/env python3
"""Synchronise device track genres with the local library."""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

try:
    import mutagen
    from mutagen.id3 import ID3, ID3NoHeaderError  # type: ignore
    from mutagen.easyid3 import EasyID3  # type: ignore
    from mutagen.flac import FLAC  # type: ignore
    from mutagen.easymp4 import EasyMP4  # type: ignore
    from mutagen.oggvorbis import OggVorbis  # type: ignore
    from mutagen.oggopus import OggOpus  # type: ignore
except ImportError as exc:  # pragma: no cover - runtime dependency
    sys.stderr.write("mutagen is required. Install with 'pip install mutagen'.\n")
    raise SystemExit(1) from exc

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.settings_store import load_settings
from app.rockbox_utils import list_rockbox_devices

DEFAULT_EXTS = (".mp3", ".flac", ".m4a", ".aac", ".ogg", ".opus", ".wav", ".wv", ".aiff", ".ape", ".mpc")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Update genre tags on a device so they mirror the genres from a local "
            "library with the same file layout."
        )
    )
    parser.add_argument(
        "--source-root",
        dest="source_root",
        help="Override the local library root (defaults to music_root setting)",
    )
    parser.add_argument(
        "--device",
        dest="device_hint",
        help="Device name or mount path (auto-detects if only one device is connected)",
    )
    parser.add_argument(
        "--device-root",
        dest="device_hint",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--ext",
        nargs="*",
        default=list(DEFAULT_EXTS),
        help="Extensions to include (e.g. .flac .mp3)",
    )
    parser.add_argument(
        "--device-subdir",
        dest="device_subdir",
        default="Music",
        help="Subdirectory on the device that mirrors the library structure (default: Music)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without writing to files or the device database",
    )
    parser.add_argument(
        "--skip-missing-source",
        action="store_true",
        help="Do not clear the device genre when the source track has no genre",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Always print per-track status (default prints only when changes occur)",
    )
    return parser.parse_args()


def iter_audio_files(folder: Path, extensions: Iterable[str]) -> Iterable[Path]:
    ext_lc = {ext.lower() for ext in extensions}
    for path in folder.rglob("*"):
        if path.is_file() and path.suffix.lower() in ext_lc:
            yield path


def clean_genre(value: Optional[str]) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    lower = text.lower()
    if lower.startswith("genre:"):
        text = text.split(":", 1)[1].strip()
    return text


def extract_genre_list(tags) -> List[str]:
    if tags is None:
        return []
    values = tags.get("genre") or []
    cleaned: List[str] = []
    for raw in values:
        cleaned_value = clean_genre(raw)
        if cleaned_value:
            cleaned.append(cleaned_value)
    return cleaned[:1]

def format_genres(values: List[str]) -> str:
    return ", ".join(values) if values else "<cleared>"


def _prepare_device_audio(audio_path: Path, dry_run: bool):
    try:
        audio = mutagen.File(str(audio_path), easy=True)
    except Exception:
        audio = None

    if audio and getattr(audio, "tags", None) is not None:
        return audio

    if dry_run:
        return audio

    suffix = audio_path.suffix.lower()

    try:
        if suffix in {".mp3", ".mp2", ".mpga"}:
            try:
                EasyID3(str(audio_path))
            except ID3NoHeaderError:
                ID3().save(str(audio_path))
                EasyID3(str(audio_path))
            audio = mutagen.File(str(audio_path), easy=True)
        elif suffix == ".flac":
            flac = FLAC(str(audio_path))
            if flac.tags is None:
                flac.tags = []
            flac.save()
            audio = mutagen.File(str(audio_path), easy=True)
        elif suffix in {".m4a", ".m4b", ".mp4", ".aac"}:
            mp4 = EasyMP4(str(audio_path))
            if mp4.tags is None:
                mp4.add_tags()
            mp4.save()
            audio = mutagen.File(str(audio_path), easy=True)
        elif suffix in {".ogg"}:
            ogg = OggVorbis(str(audio_path))
            if ogg.tags is None:
                ogg.tags = {}
            ogg.save()
            audio = mutagen.File(str(audio_path), easy=True)
        elif suffix in {".opus"}:
            opus = OggOpus(str(audio_path))
            if opus.tags is None:
                opus.tags = {}
            opus.save()
            audio = mutagen.File(str(audio_path), easy=True)
        elif audio is not None:
            raw = mutagen.File(str(audio_path))
            add_tags = getattr(raw, "add_tags", None)
            if callable(add_tags):
                add_tags()
            if hasattr(raw, "save"):
                raw.save()
            audio = mutagen.File(str(audio_path), easy=True)
    except Exception:
        pass

    return audio


def _get_tag_mapping(audio) -> Optional[Any]:
    if audio is None:
        return None
    tags = getattr(audio, "tags", None)
    if tags is not None:
        return tags
    if hasattr(audio, "get"):
        return audio
    return None


def _ensure_device_schema(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS tracks (
            path TEXT PRIMARY KEY,
            title TEXT,
            artist TEXT,
            album TEXT,
            albumartist TEXT,
            genre TEXT,
            track TEXT,
            disc TEXT,
            year TEXT,
            date TEXT,
            composer TEXT,
            comment TEXT,
            duration_seconds INTEGER,
            format TEXT,
            mtime INTEGER,
            size INTEGER,
            md5 TEXT
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tracks_artist ON tracks(artist)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tracks_album ON tracks(album)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tracks_title ON tracks(title)")


def _update_device_db(conn: sqlite3.Connection, path: str, genres: List[str]) -> bool:
    desired = genres[0] if genres else ""
    cur = conn.execute("SELECT genre FROM tracks WHERE path = ?", (path,))
    row = cur.fetchone()
    if row is None:
        conn.execute(
            "INSERT INTO tracks (path, genre) VALUES (?, ?)",
            (path, desired or None),
        )
        return True
    existing = (row[0] or "").strip()
    if existing == desired:
        return False
    conn.execute("UPDATE tracks SET genre = ? WHERE path = ?", (desired or None, path))
    return True


def _resolve_library_root(override: Optional[str]) -> Path:
    if override:
        path = Path(override).expanduser()
        return path.resolve()
    settings = load_settings()
    base = settings.get("music_root")
    if not base:
        sys.stderr.write("music_root is not configured in settings.\n")
        raise SystemExit(2)
    return Path(base).expanduser().resolve()


def _resolve_device_root(hint: Optional[str]) -> Path:
    try:
        devices = list_rockbox_devices() or []
    except Exception:
        devices = []

    def _display(dev: Dict[str, Any]) -> str:
        name = str(dev.get("name") or "").strip()
        model = str(dev.get("display_model") or dev.get("model") or "").strip()
        mount = str(dev.get("mountpoint") or "").strip()
        if name and model and name.lower() != model.lower():
            return f"{name} ({model}) — {mount}"
        label = name or model or mount or "Device"
        return f"{label} — {mount}" if mount and mount not in label else label

    if hint:
        candidate = Path(hint).expanduser()
        if candidate.exists():
            return candidate
        hint_lower = str(hint).strip().lower()
        for dev in devices:
            mount = str(dev.get("mountpoint") or "").strip()
            label_matches = {
                mount.lower(),
                str(dev.get("name") or "").strip().lower(),
                str(dev.get("label") or "").strip().lower(),
                str(dev.get("display_model") or "").strip().lower(),
            }
            if hint_lower in label_matches:
                resolved = Path(mount).expanduser()
                if resolved.exists():
                    return resolved
        if devices:
            sys.stderr.write(f"Device '{hint}' not found among detected devices. Available devices:\n")
            for dev in devices:
                sys.stderr.write(f"  - {_display(dev)}\n")
        else:
            sys.stderr.write("No Rockbox devices detected.\n")
        raise SystemExit(2)

    if len(devices) == 1:
        mount = devices[0].get("mountpoint")
        if mount:
            resolved = Path(str(mount)).expanduser()
            if resolved.exists():
                return resolved

    if not devices:
        sys.stderr.write("No Rockbox devices detected. Connect a device or supply --device pointing to the mount path.\n")
    else:
        sys.stderr.write("Multiple devices detected. Please choose one with --device:\n")
        for dev in devices:
            sys.stderr.write(f"  - {_display(dev)}\n")
    raise SystemExit(2)


def main() -> None:
    args = parse_args()

    source_root = _resolve_library_root(args.source_root)
    device_root = _resolve_device_root(args.device_hint)

    if not source_root.exists() or not source_root.is_dir():
        sys.stderr.write(f"Source root does not exist or is not a directory: {source_root}\n")
        raise SystemExit(2)
    if not device_root.exists() or not device_root.is_dir():
        sys.stderr.write(f"Device root does not exist or is not a directory: {device_root}\n")
        raise SystemExit(2)

    if not args.ext:
        extensions = list(DEFAULT_EXTS)
    elif len(args.ext) == 1 and " " in args.ext[0]:
        extensions = [ext.strip() for ext in args.ext[0].split() if ext.strip()]
    else:
        extensions = [ext.strip() for ext in args.ext if ext.strip()]
    if not extensions:
        sys.stderr.write("No valid extensions provided.\n")
        raise SystemExit(2)

    device_base = device_root
    if args.device_subdir:
        device_base = (device_root / args.device_subdir).expanduser()
    try:
        device_base = device_base.resolve()
    except Exception:
        device_base = device_base
    if args.device_subdir and not device_base.exists():
        print(f"warning: device subdir does not exist: {device_base}")

    summary: Dict[str, int] = {
        "scanned": 0,
        "updated": 0,
        "pending": 0,
        "skip_same": 0,
        "skip_source_missing": 0,
        "skip_source_genre": 0,
        "missing_device": 0,
        "errors": 0,
        "db_updated": 0,
        "db_pending": 0,
        "db_skipped": 0,
        "db_errors": 0,
    }

    db_conn: Optional[sqlite3.Connection] = None
    if not args.dry_run:
        try:
            db_path = device_root / '.rocksync' / 'music_index.sqlite3'
            db_path.parent.mkdir(parents=True, exist_ok=True)
            db_conn = sqlite3.connect(str(db_path))
            _ensure_device_schema(db_conn)
        except Exception as exc:
            print(f"warning: could not open device database ({exc})")
            db_conn = None

    for source_path in iter_audio_files(source_root, extensions):
        summary["scanned"] += 1
        relative = source_path.relative_to(source_root)
        device_path = device_base / relative

        source_audio = mutagen.File(str(source_path), easy=True)
        if not source_audio or getattr(source_audio, "tags", None) is None:
            summary["skip_source_missing"] += 1
            if args.verbose:
                print(f"skip: {source_path} | no readable tags")
            continue

        source_genres = extract_genre_list(source_audio.tags)
        if not source_genres and args.skip_missing_source:
            summary["skip_source_genre"] += 1
            if args.verbose:
                print(f"skip: {source_path} | no genre in source")
            continue

        if not device_path.exists():
            summary["missing_device"] += 1
            print(f"missing: {device_path}")
            continue

        device_audio = _prepare_device_audio(device_path, args.dry_run)
        if not device_audio:
            summary["errors"] += 1
            print(f"error: {device_path} | could not open (mutagen unsupported)")
            continue

        tag_map = _get_tag_mapping(device_audio)
        if tag_map is None and not args.dry_run:
            summary["errors"] += 1
            print(f"error: {device_path} | no writable tags")
            continue

        desired_genres = source_genres if source_genres else []
        existing_genres: List[str] = extract_genre_list(tag_map) if tag_map else []

        if existing_genres == desired_genres:
            summary["skip_same"] += 1
            if args.verbose:
                print(f"ok: {device_path} | {format_genres(existing_genres)}")
            continue

        if args.dry_run:
            summary["pending"] += 1
            print(
                f"dry-run: {device_path} | {format_genres(existing_genres)} -> {format_genres(desired_genres)}"
            )
            summary["db_pending"] += 1
            continue

        try:
            tag_map = _get_tag_mapping(device_audio)
            if tag_map is None:
                raise ValueError("no tag map available")
            if desired_genres:
                tag_map["genre"] = desired_genres
            else:
                try:
                    tag_map.pop("genre", None)
                except AttributeError:
                    if "genre" in tag_map:
                        del tag_map["genre"]
            device_audio.save()
        except Exception as exc:  # pragma: no cover - filesystem dependent
            summary["errors"] += 1
            print(f"error: {device_path} | failed to save ({exc})")
            continue

        if db_conn:
            try:
                changed = _update_device_db(db_conn, str(device_path), desired_genres)
                if changed:
                    summary["db_updated"] += 1
                else:
                    summary["db_skipped"] += 1
            except Exception as exc:
                summary["errors"] += 1
                summary["db_errors"] += 1
                print(f"error: device db update failed for {device_path} ({exc})")
        else:
            summary["db_skipped"] += 1

        summary["updated"] += 1
        print(f"updated: {device_path} | -> {format_genres(desired_genres)}")

    if db_conn:
        try:
            db_conn.commit()
        except Exception:
            pass
        db_conn.close()

    print("\nSummary:")
    for key in (
        "scanned",
        "updated",
        "pending",
        "skip_same",
        "skip_source_missing",
        "skip_source_genre",
        "missing_device",
        "errors",
        "db_updated",
        "db_pending",
        "db_skipped",
        "db_errors",
    ):
        print(f"  {key}: {summary[key]}")


if __name__ == "__main__":
    main()
