import os
from PIL import Image

# Settings
ROOT_DIR = "/run/media/matti/Archive Drive/Music/iPod_Downsampled"  # <- Replace this
TARGET_SIZE = (100, 100)  # Rockbox-friendly size

def resize_cover_images(root_dir, size):
    for subdir, _, files in os.walk(root_dir):
        for file in files:
            if file.lower() == "cover.jpg":
                full_path = os.path.join(subdir, file)
                try:
                    with Image.open(full_path) as img:
                        img = img.convert("RGB")  # Ensure compatibility
                        img = img.resize(size, Image.LANCZOS)
                        img.save(full_path, "JPEG")
                        print(f"Resized: {full_path}")
                except Exception as e:
                    print(f"Failed to resize {full_path}: {e}")

# Run the function
resize_cover_images(ROOT_DIR, TARGET_SIZE)
