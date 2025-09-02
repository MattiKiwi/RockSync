import os
import shutil

# === Settings ===
SOURCE_FOLDER = "E:\Music\Full-Quality\Albums"  # ← Change this
SEPARATOR = " - "  # Separator between artist and album in folder names
DRY_RUN = False     # Set to True to preview actions without moving

def organize_albums_by_artist(folder_path):
    for item in os.listdir(folder_path):
        item_path = os.path.join(folder_path, item)

        # Skip non-directories
        if not os.path.isdir(item_path):
            continue

        # Check for proper naming convention
        if SEPARATOR not in item:
            print(f"⚠ Skipping (no separator): {item}")
            continue

        artist, album = item.split(SEPARATOR, 1)
        artist = artist.strip()
        album = album.strip()

        artist_folder = os.path.join(folder_path, artist)
        new_path = os.path.join(artist_folder, item)

        if DRY_RUN:
            print(f"[DRY RUN] Would move:\n  {item} → {artist}/{item}")
        else:
            os.makedirs(artist_folder, exist_ok=True)
            shutil.move(item_path, new_path)
            print(f"✔ Moved: {item} → {artist}/{item}")

# === Run it ===
organize_albums_by_artist(SOURCE_FOLDER)
