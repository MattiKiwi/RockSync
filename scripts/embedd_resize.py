import argparse
import base64
import os
from io import BytesIO
from typing import Iterable, Optional, Tuple

from mutagen import File
from mutagen.flac import FLAC, Picture
from PIL import Image

try:  # Optional extras.
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

DEFAULT_FOLDER_PATH = "E:/Music/iPod_Downsampled/New/"
DEFAULT_TARGET_SIZE = (100, 100)
SUPPORTED_EXTENSIONS = (".flac", ".mp3", ".m4a", ".mp4", ".ogg", ".opus", ".oga")


def resize_image_exact(data: bytes, size: Tuple[int, int]) -> Tuple[Optional[bytes], Tuple[int, int]]:
    with Image.open(BytesIO(data)) as original:
        width, height = original.size
        if width == 0 or height == 0:
            raise ValueError("Cannot resize empty image")

        target_width, target_height = size
        is_target_size = width == target_width and height == target_height
        is_rgb_jpeg = (original.mode == "RGB") and (original.format or "").upper() == "JPEG"
        if is_target_size and is_rgb_jpeg:
            return None, (width, height)

        image = original.convert("RGB")

    width, height = image.size
    # Crop to a centered square before scaling so Rockbox gets a consistent cover.
    crop_edge = min(width, height)
    left = (width - crop_edge) // 2
    top = (height - crop_edge) // 2
    image = image.crop((left, top, left + crop_edge, top + crop_edge))

    if image.size != size:
        image = image.resize(size, Image.LANCZOS)

    buffer = BytesIO()
    image.save(buffer, format="JPEG")
    return buffer.getvalue(), image.size


def handle_flac(flac: FLAC, size: Tuple[int, int]) -> bool:
    updated = False
    new_pictures = []
    for picture in flac.pictures:
        if picture.type == 3:
            try:
                resized, dimensions = resize_image_exact(picture.data, size)
            except Exception:
                new_pictures.append(picture)
                continue

            if resized is None:
                new_pictures.append(picture)
                continue

            new_pic = Picture()
            new_pic.data = resized
            new_pic.type = 3
            new_pic.mime = "image/jpeg"
            new_pic.width, new_pic.height = dimensions
            new_pic.depth = 24
            new_pic.desc = "resized cover"
            new_pictures.append(new_pic)
            updated = True
        else:
            new_pictures.append(picture)

    if updated:
        flac.clear_pictures()
        for pic in new_pictures:
            flac.add_picture(pic)
        flac.save()
    return updated


def handle_mp3(path: str, size: Tuple[int, int]) -> bool:
    if MP3 is None or APIC is None:
        return False

    audio = MP3(path)
    if audio.tags is None:
        try:
            audio.add_tags()
        except (ID3NoHeaderError, Exception):  # pragma: no cover
            return False

    updated = False
    for frame in list(audio.tags.getall("APIC")):
        if getattr(frame, "type", 3) == 3:
            try:
                resized, _ = resize_image_exact(frame.data, size)
            except Exception:
                continue
            if resized is None:
                continue
            frame.data = resized
            frame.mime = "image/jpeg"
            frame.desc = "resized cover"
            frame.type = 3
            updated = True

    if updated:
        audio.save()
    return updated


def handle_mp4(path: str, size: Tuple[int, int]) -> bool:
    if MP4 is None or MP4Cover is None:
        return False

    audio = MP4(path)
    covers = audio.tags.get("covr") if audio.tags else None
    if not covers:
        return False

    new_covers = []
    updated = False
    for cover in covers:
        try:
            resized, _ = resize_image_exact(bytes(cover), size)
        except Exception:
            new_covers.append(cover)
            continue
        if resized is None:
            new_covers.append(cover)
            continue
        new_covers.append(MP4Cover(resized, imageformat=MP4Cover.FORMAT_JPEG))
        updated = True

    if updated:
        audio.tags["covr"] = new_covers
        audio.save()
    return updated


def _decode_picture(encoded: str) -> Picture:
    picture = Picture()
    picture.load(base64.b64decode(encoded))
    return picture


def _encode_picture(picture: Picture) -> str:
    return base64.b64encode(picture.write()).decode("ascii")


def handle_ogg(audio, size: Tuple[int, int]) -> bool:
    pictures = audio.tags.get("metadata_block_picture") if audio.tags else None
    if not pictures:
        return False

    new_entries = []
    updated = False
    for entry in pictures:
        picture = _decode_picture(entry)
        if picture.type == 3:
            try:
                resized, dimensions = resize_image_exact(picture.data, size)
            except Exception:
                new_entries.append(entry)
                continue
            if resized is None:
                new_entries.append(entry)
                continue
            new_pic = Picture()
            new_pic.data = resized
            new_pic.type = 3
            new_pic.mime = "image/jpeg"
            new_pic.width, new_pic.height = dimensions
            new_pic.depth = 24
            new_pic.desc = "resized cover"
            new_entries.append(_encode_picture(new_pic))
            updated = True
        else:
            new_entries.append(entry)

    if updated:
        audio.tags["metadata_block_picture"] = new_entries
        audio.save()
    return updated


def resize_and_embed_cover(audio_path: str, size: Tuple[int, int]) -> None:
    try:
        audio = File(audio_path)
    except Exception as exc:
        print(f"❌ Failed to read {os.path.basename(audio_path)}: {exc}")
        return

    if audio is None:
        print(f"ℹ Unsupported file skipped: {os.path.basename(audio_path)}")
        return

    updated = False
    if isinstance(audio, FLAC):
        updated = handle_flac(audio, size)
    elif MP3 is not None and isinstance(audio, MP3):
        updated = handle_mp3(audio_path, size)
    elif MP4 is not None and isinstance(audio, MP4):
        updated = handle_mp4(audio_path, size)
    elif (OggVorbis is not None and isinstance(audio, OggVorbis)) or (
        OggOpus is not None and isinstance(audio, OggOpus)
    ):
        updated = handle_ogg(audio, size)

    if updated:
        print(f"✔ Resized and updated cover for: {os.path.basename(audio_path)}")
    else:
        print(f"ℹ No front cover to resize in: {os.path.basename(audio_path)}")


def _is_supported(name: str) -> bool:
    lowered = name.lower().strip()
    return any(lowered.endswith(ext) for ext in SUPPORTED_EXTENSIONS)


def main():
    parser = argparse.ArgumentParser(description="Resize and re-embed front cover images in audio files")
    parser.add_argument("--folder", default=DEFAULT_FOLDER_PATH, help="Folder to process recursively")
    parser.add_argument(
        "--size",
        default=f"{DEFAULT_TARGET_SIZE[0]}x{DEFAULT_TARGET_SIZE[1]}",
        help="Target size WIDTHxHEIGHT",
    )
    parser.add_argument(
        "--files-from",
        help="Restrict processing to files listed in this file (one path per line)",
    )
    args = parser.parse_args()

    try:
        width, height = map(int, args.size.lower().split("x"))
    except Exception:
        raise SystemExit("--size must be WIDTHxHEIGHT, e.g. 100x100")

    targets: Iterable[str]
    if args.files_from:
        try:
            with open(args.files_from, "r", encoding="utf-8") as fh:
                targets = [line.strip() for line in fh if _is_supported(line)]
        except Exception:
            targets = []
        for full_path in targets:
            resize_and_embed_cover(full_path, (width, height))
    else:
        for root, _, files in os.walk(args.folder):
            for file in files:
                if _is_supported(file):
                    full_path = os.path.join(root, file)
                    resize_and_embed_cover(full_path, (width, height))


if __name__ == "__main__":
    main()
