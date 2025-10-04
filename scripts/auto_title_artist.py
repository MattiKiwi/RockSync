#!/usr/bin/env python3
"""Extract title/artist from filenames and write them into audio metadata tags."""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

try:
    from mutagen import File as MutagenFile  # type: ignore
    from mutagen.easyid3 import EasyID3  # type: ignore
    from mutagen.easymp4 import EasyMP4  # type: ignore
    from mutagen.flac import FLAC  # type: ignore
    from mutagen.id3 import ID3, ID3NoHeaderError  # type: ignore
    from mutagen.oggopus import OggOpus  # type: ignore
    from mutagen.oggvorbis import OggVorbis  # type: ignore
except ImportError as exc:  # pragma: no cover - runtime dependency
    sys.stderr.write("mutagen is required. Install with 'pip install mutagen'.\n")
    raise SystemExit(1) from exc

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.settings_store import load_settings

DEFAULT_EXTENSIONS = (
    ".flac",
    ".mp3",
    ".m4a",
    ".aac",
    ".ogg",
    ".opus",
    ".wav",
    ".wv",
    ".aiff",
    ".ape",
    ".mpc",
)
DEFAULT_PATTERN = r"^\d+\.\s*(?P<title>.*?)\s+by\s+(?P<artist>.*?)\.(?P<ext>m4a|mp3|flac|wav|aac|ogg|wma|alac)$"


@dataclass
class MatchResult:
    path: Path
    title: str
    artist: str
    changed: bool
    existing_title: str
    existing_artist: str


def _default_library_root() -> str:
    """Return the configured music_root, falling back to the repository root."""

    try:
        settings = load_settings()
        base = (settings or {}).get("music_root")
        if isinstance(base, str) and base.strip():
            return str(Path(base).expanduser())
    except Exception:
        pass
    return str(ROOT)


def _normalise_extensions(values: Sequence[str]) -> List[str]:
    result: List[str] = []
    for item in values:
        if not item:
            continue
        ext = str(item).lower().strip()
        if not ext:
            continue
        if not ext.startswith('.'):
            ext = f'.{ext}'
        result.append(ext)
    return result


def _parse_extensions(raw_values: Sequence[str]) -> List[str]:
    if not raw_values:
        return list(DEFAULT_EXTENSIONS)

    tokens: List[str] = []
    for value in raw_values:
        text = str(value or '').strip()
        if not text:
            continue
        parts = re.split(r"[\s,;|/]+", text)
        tokens.extend(part for part in parts if part)

    return _normalise_extensions(tokens)


def _iter_audio_files(folder: Path, extensions: Sequence[str], recursive: bool) -> Iterable[Path]:
    exts = {ext.lower() for ext in extensions if ext}
    iterator = folder.rglob('*') if recursive else folder.iterdir()
    for candidate in iterator:
        try:
            if candidate.is_file() and candidate.suffix.lower() in exts:
                yield candidate
        except PermissionError:
            continue


def _ensure_audio(path: Path):
    audio = None
    try:
        audio = MutagenFile(str(path), easy=True)
    except Exception:
        audio = None

    if audio is not None and getattr(audio, 'tags', None) is not None:
        return audio

    suffix = path.suffix.lower()

    try:
        if suffix in {'.mp3', '.mp2', '.mpga'}:
            try:
                EasyID3(str(path))
            except ID3NoHeaderError:
                ID3().save(str(path))
                EasyID3(str(path))
        elif suffix == '.flac':
            flac = FLAC(str(path))
            if flac.tags is None:
                flac.tags = []
            flac.save()
        elif suffix in {'.m4a', '.m4b', '.mp4', '.aac'}:
            mp4 = EasyMP4(str(path))
            if mp4.tags is None:
                mp4.add_tags()
            mp4.save()
        elif suffix == '.ogg':
            ogg = OggVorbis(str(path))
            if ogg.tags is None:
                ogg.tags = {}
            ogg.save()
        elif suffix == '.opus':
            opus = OggOpus(str(path))
            if opus.tags is None:
                opus.tags = {}
            opus.save()
    except Exception:
        pass

    audio = MutagenFile(str(path), easy=True)
    if audio is None or getattr(audio, 'tags', None) is None:
        raise RuntimeError(f"Unsupported or unreadable audio file: {path}")
    return audio


def _first_value(values: Optional[Sequence[str]]) -> str:
    if not values:
        return ''
    try:
        first = values[0]
    except Exception:
        first = values
    return str(first or '').strip()


def _extract_fields(match: re.Match[str]) -> Optional[Dict[str, str]]:
    groups = match.groupdict()
    title = groups.get('title')
    artist = groups.get('artist')

    if not title and match.lastindex and match.lastindex >= 1:
        title = match.group(1)
    if not artist and match.lastindex and match.lastindex >= 2:
        artist = match.group(2)

    if not title or not artist:
        return None

    return {
        'title': title.strip(),
        'artist': artist.strip(),
    }


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Extract title and artist from audio filenames using a regex pattern "
            "and apply them to metadata tags."
        )
    )
    parser.add_argument(
        '--folder',
        default=_default_library_root(),
        help='Folder containing audio files. Defaults to the configured music_root.',
    )
    parser.add_argument(
        '--regex',
        default=DEFAULT_PATTERN,
        help=(
            "Python regex used to parse filenames (without extension). The pattern "
            "must capture title/artist via named groups or positional groups."
        ),
    )
    parser.add_argument(
        '--ignore-case',
        action='store_true',
        help='Match filenames case-insensitively.',
    )
    parser.add_argument(
        '--recursive',
        action='store_true',
        help='Recurse into subdirectories.',
    )
    parser.add_argument(
        '--ext',
        nargs='*',
        default=list(DEFAULT_EXTENSIONS),
        help='File extensions to include (e.g. .flac .m4a). Defaults cover common formats.',
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Preview changes without writing tags to disk.',
    )
    parser.add_argument(
        '--verbose',
        action='store_true',
        help='Print per-file status for every match.',
    )
    parser.add_argument(
        '--debug-regex',
        action='store_true',
        help='Print filenames that fail to match the regex.',
    )
    return parser.parse_args(argv)


def process_file(path: Path, pattern: re.Pattern[str], dry_run: bool) -> Optional[MatchResult]:
    stem = path.name.strip()
    match = pattern.search(stem)
    if not match:
        return None

    fields = _extract_fields(match)
    if not fields:
        return None

    title = fields['title']
    artist = fields['artist']

    if dry_run:
        return MatchResult(
            path=path,
            title=title,
            artist=artist,
            changed=False,
            existing_title='',
            existing_artist='',
        )

    audio = _ensure_audio(path)
    existing_title = _first_value(audio.tags.get('title') if audio.tags else [])
    existing_artist = _first_value(audio.tags.get('artist') if audio.tags else [])

    changed = False
    if title and title != existing_title:
        audio['title'] = [title]
        changed = True
    if artist and artist != existing_artist:
        audio['artist'] = [artist]
        changed = True

    if changed:
        audio.save()
    return MatchResult(
        path=path,
        title=title,
        artist=artist,
        changed=changed,
        existing_title=existing_title,
        existing_artist=existing_artist,
    )


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)

    folder = Path(args.folder).expanduser()
    if not folder.exists() or not folder.is_dir():
        sys.stderr.write(f"Folder does not exist or is not a directory: {folder}\n")
        return 2

    extensions = _parse_extensions(args.ext)
    if not extensions:
        sys.stderr.write("No valid extensions provided.\n")
        return 2

    flags = re.IGNORECASE if args.ignore_case else 0
    try:
        pattern = re.compile(args.regex, flags)
    except re.error as exc:
        sys.stderr.write(f"Invalid regex: {exc}\n")
        return 2

    dry_run = args.dry_run
    processed = 0
    matched = 0
    updated = 0
    unchanged = 0
    skipped = 0
    failed: List[Path] = []
    errors: List[str] = []

    for path in _iter_audio_files(folder, extensions, args.recursive):
        processed += 1
        try:
            result = process_file(path, pattern, dry_run)
        except Exception as exc:
            errors.append(f"{path}: {exc}")
            continue

        if result is None:
            skipped += 1
            if args.debug_regex:
                failed.append(path)
            continue

        matched += 1
        if dry_run:
            print(f"[DRY] {path.name} -> title='{result.title}' | artist='{result.artist}'")
        else:
            if result.changed:
                updated += 1
                print(
                    f"[OK] {path.name} | title: '{result.existing_title}' -> '{result.title}' | "
                    f"artist: '{result.existing_artist}' -> '{result.artist}'"
                )
            else:
                unchanged += 1
                if args.verbose:
                    print(f"[SKIP] {path.name} already up to date.")

    print("--- Summary ---")
    print(f"Processed: {processed}")
    print(f"Matched (regex): {matched}")
    if dry_run:
        print(f"Previewed updates: {matched}")
    else:
        print(f"Updated: {updated}")
        print(f"Unchanged (already tagged): {unchanged}")
    print(f"Skipped (no match): {skipped}")
    if errors:
        print(f"Errors: {len(errors)}")
        for line in errors:
            print(f"  {line}")

    if args.debug_regex and failed:
        print("--- Unmatched filenames ---")
        for path in failed:
            print(f"  {path.relative_to(folder)}")

    return 0


if __name__ == '__main__':
    raise SystemExit(main())
