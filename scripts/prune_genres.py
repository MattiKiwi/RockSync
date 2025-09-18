#!/usr/bin/env python3
import argparse
import sys
from pathlib import Path
from typing import Iterable, Optional, Tuple

try:
    import mutagen
except ImportError:  # pragma: no cover
    sys.stderr.write("mutagen is required. Install with 'pip install mutagen'.\n")
    sys.exit(1)


DEFAULT_EXTS = (".mp3", ".flac", ".m4a", ".aac", ".ogg", ".opus", ".wav", ".wv", ".aiff", ".ape", ".mpc")
IGNORED_GENRES = {"unknown", "unknown genre", "n/a", "none"}


def iter_audio_files(folder: Path, extensions: Iterable[str]) -> Iterable[Path]:
    ext_lc = {ext.lower() for ext in extensions}
    for path in folder.rglob("*"):
        if path.is_file() and path.suffix.lower() in ext_lc:
            yield path


def split_candidates(raw: str) -> Iterable[str]:
    text = str(raw or "")
    for delim in (";", ",", "/", "|"):
        if delim in text:
            parts = text.split(delim)
            if parts:
                yield parts[0]
                return
    yield text


def clean_genre(value: str) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    lower = text.lower()
    if lower.startswith("genre:"):
        text = text.split(":", 1)[1].strip()
    return text.strip()


def pick_primary(genres: Iterable[str]) -> Tuple[str, bool, bool]:
    for_raw = False
    for candidate in genres:
        for_raw = True
        for piece in split_candidates(candidate):
            cleaned = clean_genre(piece)
            if not cleaned:
                continue
            lowered = cleaned.lower()
            if lowered in IGNORED_GENRES:
                return "", True, True
            return cleaned, False, True
    return "", False, for_raw


def process_file(path: Path, dry_run: bool) -> Tuple[str, Optional[bool]]:
    try:
        audio = mutagen.File(path, easy=True)
    except Exception as exc:
        return f"error: {path} ({exc})", None
    if audio is None or getattr(audio, "tags", None) is None:
        return f"skip: {path} (no readable tags)", None
    tags = audio.tags
    genres = tags.get("genre")
    if not genres:
        return f"skip: {path} (no genres)", False

    raw_values = [str(g or "").strip() for g in genres]
    cleaned_pairs = [(value, clean_genre(value)) for value in raw_values]
    cleaned_current = [pair[1] for pair in cleaned_pairs]
    usable_current = [value for value in cleaned_current if value]

    needs_cleanup = any(
        original and sanitized != original
        for original, sanitized in cleaned_pairs
        if sanitized
    ) or any(original and not sanitized for original, sanitized in cleaned_pairs)

    if not usable_current and genres:
        if dry_run:
            return f"dry-run: {path} -> cleared invalid genres", False
        try:
            tags.pop("genre", None)
            audio.save()
            return f"updated: {path} -> cleared invalid genres", False
        except Exception as exc:  # pragma: no cover
            return f"error: {path} ({exc})", None

    primary, is_unknown, had_any = pick_primary(genres)
    if not primary:
        if is_unknown:
            return f"skip: {path} (unknown genre)", False
        if had_any:
            return f"skip: {path} (no usable genre)", False
        return f"skip: {path} (no genres)", False

    current = usable_current
    if len(current) == 1 and current[0] == primary and not needs_cleanup:
        return f"ok: {path} ({primary})", True

    if dry_run:
        return f"dry-run: {path} -> {primary}", True

    try:
        tags["genre"] = [primary]
        audio.save()
        return f"updated: {path} -> {primary}", True
    except Exception as exc:  # pragma: no cover
        return f"error: {path} ({exc})", None


def main():
    parser = argparse.ArgumentParser(description="Keep only the first genre tag per track.")
    parser.add_argument("--folder", default=str(Path.cwd()), help="Folder to scan (recursively)")
    parser.add_argument("--ext", nargs="*", default=list(DEFAULT_EXTS), help="Extensions to include (e.g. .flac .mp3)")
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without writing tags")
    args = parser.parse_args()

    folder = Path(args.folder).expanduser()
    if not folder.exists():
        sys.stderr.write(f"Folder does not exist: {folder}\n")
        sys.exit(2)

    if not args.ext:
        extensions = list(DEFAULT_EXTS)
    elif len(args.ext) == 1 and " " in args.ext[0]:
        extensions = [ext.strip() for ext in args.ext[0].split() if ext.strip()]
    else:
        extensions = [ext.strip() for ext in args.ext if ext.strip()]
    if not extensions:
        sys.stderr.write("No valid extensions provided.\n")
        sys.exit(2)

    summary = {
        "updated": 0,
        "dry-run": 0,
        "skip": 0,
        "ok": 0,
        "error": 0,
        "with_genre": 0,
        "without_genre": 0,
    }

    for audio_path in iter_audio_files(folder, extensions):
        message, has_genre = process_file(audio_path, args.dry_run)
        if message.startswith("updated"):
            summary["updated"] += 1
        elif message.startswith("dry-run"):
            summary["dry-run"] += 1
        elif message.startswith("ok"):
            summary["ok"] += 1
        elif message.startswith("error"):
            summary["error"] += 1
        else:
            summary["skip"] += 1

        if has_genre is True:
            summary["with_genre"] += 1
        elif has_genre is False:
            summary["without_genre"] += 1

        print(message)

    print("\nSummary:")
    for key in ("updated", "dry-run", "skip", "ok", "error"):
        print(f"  {key}: {summary[key]}")

    accounted = summary["with_genre"] + summary["without_genre"]
    if accounted:
        print("  --")
        print(f"  with_genre: {summary['with_genre']}")
        print(f"  without_genre: {summary['without_genre']}")


if __name__ == "__main__":
    main()
