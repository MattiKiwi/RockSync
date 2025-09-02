import os
import argparse
from PIL import Image

DEFAULT_ROOT_DIR = "/run/media/matti/Archive Drive/Music/iPod_Downsampled"
DEFAULT_TARGET_SIZE = (100, 100)  # Rockbox-friendly size

def resize_cover_images(root_dir, size):
    for subdir, _, files in os.walk(root_dir):
        for file in files:
            if file.lower() == "cover.jpg":
                full_path = os.path.join(subdir, file)
                try:
                    with Image.open(full_path) as img:
                        img = img.convert("RGB")
                        img = img.resize(size, Image.LANCZOS)
                        img.save(full_path, "JPEG")
                        print(f"Resized: {full_path}")
                except Exception as e:
                    print(f"Failed to resize {full_path}: {e}")

def main():
    parser = argparse.ArgumentParser(description="Resize cover.jpg images recursively to a fixed size")
    parser.add_argument("--root", default=DEFAULT_ROOT_DIR, help="Root directory to scan")
    parser.add_argument("--size", default=f"{DEFAULT_TARGET_SIZE[0]}x{DEFAULT_TARGET_SIZE[1]}", help="Target size WIDTHxHEIGHT")
    args = parser.parse_args()

    try:
        width, height = map(int, args.size.lower().split("x"))
    except Exception:
        raise SystemExit("--size must be WIDTHxHEIGHT, e.g. 100x100")

    resize_cover_images(args.root, (width, height))

if __name__ == "__main__":
    main()
