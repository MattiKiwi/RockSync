import argparse
import base64
import os
from io import BytesIO
from typing import Iterable

from mutagen import File
from mutagen.flac import FLAC, Picture
from PIL import Image

try:
    from mutagen.mp3 import MP3
    from mutagen.id3 import APIC, ID3NoHeaderError
except ImportError:  # pragma: no cover
    MP3 = None  # type: ignore
    APIC = None  # type: ignore
    ID3NoHeaderError = Exception  # type: ignore

try:
    from mutagen.mp4 import MP4, MP4Cover
except ImportError:  # pragma: no cover
    MP4 = None  # type: ignore
    MP4Cover = None  # type: ignore

try:
    from mutagen.oggvorbis import OggVorbis
except ImportError:  # pragma: no cover
    OggVorbis = None  # type: ignore

try:
    from mutagen.oggopus import OggOpus
except ImportError:  # pragma: no cover
    OggOpus = None  # type: ignore

DEFAULT_FOLDER_PATH = "/run/media/matti/Archive Drive/Music/Full-Quality/Playlists/Lofi"
DEFAULT_MAX_SIZE = 100
SUPPORTED_EXTENSIONS = (".flac", ".mp3", ".m4a", ".mp4", ".ogg", ".opus", ".oga")


def resize_with_aspect_ratio(image: Image.Image, max_size: int) -> Image.Image:
    image.thumbnail((max_size, max_size), Image.LANCZOS)
    return image


def ensure_jpeg(image: Image.Image) -> bytes:
    buffer = BytesIO()
    image.convert("RGB").save(buffer, format="JPEG")
    return buffer.getvalue()


def _decode_picture(encoded: str) -> Picture:
    picture = Picture()
    picture.load(base64.b64decode(encoded))
    return picture


def _encode_picture(picture: Picture) -> str:
    return base64.b64encode(picture.write()).decode("ascii")


def promote_flac(flac: FLAC, max_size: int) -> str:
    if any(p.type == 3 for p in flac.pictures):
        return "has_cover"

    if not flac.pictures:
        return "no_image"

    candidate_index = None
    for idx, picture in enumerate(flac.pictures):
        if candidate_index is None or flac.pictures[candidate_index].type != 0:
            candidate_index = idx
        if picture.type == 0:
            candidate_index = idx
            break

    if candidate_index is None:
        return "no_image"

    candidate = flac.pictures[candidate_index]
    try:
        image = Image.open(BytesIO(candidate.data))
    except Exception:
        return "no_image"

    image = resize_with_aspect_ratio(image.convert("RGB"), max_size)
    new_pic = Picture()
    new_pic.data = ensure_jpeg(image)
    new_pic.type = 3
    new_pic.mime = "image/jpeg"
    new_pic.width, new_pic.height = image.size
    new_pic.depth = 24
    new_pic.desc = "resized promoted cover"

    new_pictures = []
    for idx, picture in enumerate(flac.pictures):
        if idx == candidate_index:
            new_pictures.append(new_pic)
        else:
            new_pictures.append(picture)

    flac.clear_pictures()
    for pic in new_pictures:
        flac.add_picture(pic)
    flac.save()
    return "promoted"


def promote_mp3(path: str, max_size: int) -> str:
    if MP3 is None or APIC is None:
        return "unsupported"

    audio = MP3(path)
    if audio.tags is None:
        try:
            audio.add_tags()
        except (ID3NoHeaderError, Exception):  # pragma: no cover
            return "no_image"

    if any(getattr(frame, "type", 3) == 3 for frame in audio.tags.getall("APIC")):
        return "has_cover"

    frames = audio.tags.getall("APIC")
    if not frames:
        return "no_image"

    target = None
    for frame in frames:
        if target is None or getattr(target, "type", 255) != 0:
            target = frame
        if getattr(frame, "type", 255) == 0:
            target = frame
            break

    if target is None:
        return "no_image"

    try:
        image = Image.open(BytesIO(target.data))
    except Exception:
        return "no_image"

    image = resize_with_aspect_ratio(image.convert("RGB"), max_size)
    target.data = ensure_jpeg(image)
    target.mime = "image/jpeg"
    target.type = 3
    target.desc = "resized promoted cover"
    audio.save()
    return "promoted"


def promote_mp4(path: str, max_size: int) -> str:
    if MP4 is None or MP4Cover is None:
        return "unsupported"

    audio = MP4(path)
    if audio.tags is None:
        audio.add_tags()

    covers = audio.tags.get("covr")
    if covers:
        return "has_cover"

    return "no_image"


def promote_ogg(audio, max_size: int) -> str:
    pictures = audio.tags.get("metadata_block_picture") if audio.tags else None
    if not pictures:
        return "no_image"

    decoded = [_decode_picture(entry) for entry in pictures]
    if any(pic.type == 3 for pic in decoded):
        return "has_cover"

    target_index = 0
    for idx, picture in enumerate(decoded):
        if decoded[target_index].type != 0:
            target_index = idx
        if picture.type == 0:
            target_index = idx
            break

    target = decoded[target_index]
    try:
        image = Image.open(BytesIO(target.data))
    except Exception:
        return "no_image"

    image = resize_with_aspect_ratio(image.convert("RGB"), max_size)
    new_pic = Picture()
    new_pic.data = ensure_jpeg(image)
    new_pic.type = 3
    new_pic.mime = "image/jpeg"
    new_pic.width, new_pic.height = image.size
    new_pic.depth = 24
    new_pic.desc = "resized promoted cover"

    new_entries = []
    for idx, picture in enumerate(decoded):
        if idx == target_index:
            new_entries.append(_encode_picture(new_pic))
        else:
            new_entries.append(_encode_picture(picture))

    audio.tags["metadata_block_picture"] = new_entries
    audio.save()
    return "promoted"


def promote_cover(audio_path: str, max_size: int) -> None:
    try:
        audio = File(audio_path)
    except Exception as exc:
        print(f"❌ Failed to read {os.path.basename(audio_path)}: {exc}")
        return

    if audio is None:
        print(f"ℹ Unsupported file skipped: {os.path.basename(audio_path)}")
        return

    result = "unsupported"
    if isinstance(audio, FLAC):
        result = promote_flac(audio, max_size)
    elif MP3 is not None and isinstance(audio, MP3):
        result = promote_mp3(audio_path, max_size)
    elif MP4 is not None and isinstance(audio, MP4):
        result = promote_mp4(audio_path, max_size)
    elif (OggVorbis is not None and isinstance(audio, OggVorbis)) or (
        OggOpus is not None and isinstance(audio, OggOpus)
    ):
        result = promote_ogg(audio, max_size)

    name = os.path.basename(audio_path)
    if result == "promoted":
        print(f"✔ Promoted and resized image to cover for: {name}")
    elif result == "has_cover":
        print(f"⏭  Skipping (already has cover): {name}")
    elif result == "no_image":
        print(f"ℹ No suitable image to promote in: {name}")
    else:
        print(f"ℹ Unsupported file skipped: {name}")


def _is_supported(name: str) -> bool:
    lowered = name.lower().strip()
    return any(lowered.endswith(ext) for ext in SUPPORTED_EXTENSIONS)


def main():
    parser = argparse.ArgumentParser(
        description="Promote first non-cover image to front cover and resize"
    )
    parser.add_argument("--folder", default=DEFAULT_FOLDER_PATH, help="Folder to process recursively")
    parser.add_argument("--max-size", type=int, default=DEFAULT_MAX_SIZE, help="Max size (pixels) for width/height")
    parser.add_argument(
        "--files-from",
        help="Restrict processing to files listed in this file (one path per line)",
    )
    args = parser.parse_args()

    targets: Iterable[str]
    if args.files_from:
        try:
            with open(args.files_from, "r", encoding="utf-8") as fh:
                targets = [line.strip() for line in fh if _is_supported(line)]
        except Exception:
            targets = []
        for full_path in targets:
            promote_cover(full_path, args.max_size)
    else:
        for root, _, files in os.walk(args.folder):
            for file in files:
                if _is_supported(file):
                    full_path = os.path.join(root, file)
                    promote_cover(full_path, args.max_size)


if __name__ == "__main__":
    main()
