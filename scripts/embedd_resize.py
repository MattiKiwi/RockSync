import os
import argparse
from mutagen.flac import FLAC, Picture
from PIL import Image
from io import BytesIO

DEFAULT_FOLDER_PATH = "E:/Music/iPod_Downsampled/New/"
DEFAULT_TARGET_SIZE = (100, 100)

def resize_and_embed_flac_cover(flac_path, size):
    try:
        audio = FLAC(flac_path)
        new_pictures = []

        for picture in audio.pictures:
            if picture.type == 3:  # Front cover
                # Resize the image
                image = Image.open(BytesIO(picture.data)).convert("RGB")
                image = image.resize(size, Image.LANCZOS)

                # Save resized image to buffer
                buffer = BytesIO()
                image.save(buffer, format="JPEG")
                buffer.seek(0)

                # Create a new Picture object
                new_pic = Picture()
                new_pic.data = buffer.read()
                new_pic.type = 3
                new_pic.mime = "image/jpeg"
                new_pic.width, new_pic.height = size
                new_pic.depth = 24  # 8 bits per channel
                new_pic.desc = "resized cover"

                new_pictures.append(new_pic)
                print(f"✔ Resized and updated cover for: {os.path.basename(flac_path)}")
            else:
                new_pictures.append(picture)  # Preserve other pictures

        # Replace all pictures with the updated list
        audio.clear_pictures()
        for pic in new_pictures:
            audio.add_picture(pic)
        audio.save()

    except Exception as e:
        print(f"❌ Failed to process {flac_path}: {e}")

def main():
    parser = argparse.ArgumentParser(description="Resize and re-embed front cover images in FLAC files")
    parser.add_argument("--folder", default=DEFAULT_FOLDER_PATH, help="Folder to process recursively")
    parser.add_argument("--size", default=f"{DEFAULT_TARGET_SIZE[0]}x{DEFAULT_TARGET_SIZE[1]}", help="Target size WIDTHxHEIGHT")
    parser.add_argument("--files-from", help="Restrict processing to files listed in this file (one path per line)")
    args = parser.parse_args()

    try:
        width, height = map(int, args.size.lower().split("x"))
    except Exception:
        raise SystemExit("--size must be WIDTHxHEIGHT, e.g. 100x100")

    if args.files_from:
        try:
            with open(args.files_from, 'r', encoding='utf-8') as fh:
                files = [line.strip() for line in fh if line.strip().lower().endswith('.flac')]
        except Exception:
            files = []
        for full_path in files:
            resize_and_embed_flac_cover(full_path, (width, height))
    else:
        for root, _, files in os.walk(args.folder):
            for file in files:
                if file.lower().endswith(".flac"):
                    full_path = os.path.join(root, file)
                    resize_and_embed_flac_cover(full_path, (width, height))

if __name__ == "__main__":
    main()
