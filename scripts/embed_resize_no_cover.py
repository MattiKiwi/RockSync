import os
import argparse
from mutagen.flac import FLAC, Picture
from PIL import Image
from io import BytesIO

DEFAULT_FOLDER_PATH = "/run/media/matti/Archive Drive/Music/Full-Quality/Playlists/Lofi"
DEFAULT_MAX_SIZE = 100

def resize_with_aspect_ratio(image, max_size):
    """Resize image while preserving aspect ratio, fitting within max_size."""
    image.thumbnail((max_size, max_size), Image.LANCZOS)
    return image

def resize_and_promote_cover(flac_path, max_size):
    try:
        audio = FLAC(flac_path)
        new_pictures = []
        promoted = False

        for picture in audio.pictures:
            if picture.type == 0 and not promoted:  # Type 0 = Other
                # Resize and promote to front cover
                image = Image.open(BytesIO(picture.data)).convert("RGB")
                image = resize_with_aspect_ratio(image, max_size)

                buffer = BytesIO()
                image.save(buffer, format="JPEG")
                buffer.seek(0)

                new_pic = Picture()
                new_pic.data = buffer.read()
                new_pic.type = 3  # Promote to front cover
                new_pic.mime = "image/jpeg"
                new_pic.width, new_pic.height = image.size
                new_pic.depth = 24
                new_pic.desc = "resized promoted cover"

                new_pictures.append(new_pic)
                promoted = True
                print(f"✔ Promoted and resized image to cover for: {os.path.basename(flac_path)}")
            else:
                new_pictures.append(picture)  # Preserve all others

        if promoted:
            audio.clear_pictures()
            for pic in new_pictures:
                audio.add_picture(pic)
            audio.save()
        else:
            print(f"ℹ No suitable image to promote in: {os.path.basename(flac_path)}")

    except Exception as e:
        print(f"❌ Failed to process {flac_path}: {e}")

def main():
    parser = argparse.ArgumentParser(description="Promote first non-cover image to front cover and resize")
    parser.add_argument("--folder", default=DEFAULT_FOLDER_PATH, help="Folder to process recursively")
    parser.add_argument("--max-size", type=int, default=DEFAULT_MAX_SIZE, help="Max size (pixels) for width/height")
    args = parser.parse_args()

    for root, _, files in os.walk(args.folder):
        for file in files:
            if file.lower().endswith(".flac"):
                full_path = os.path.join(root, file)
                resize_and_promote_cover(full_path, args.max_size)

if __name__ == "__main__":
    main()
