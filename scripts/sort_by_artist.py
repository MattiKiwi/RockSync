import os
import shutil
import argparse

DEFAULT_SOURCE_FOLDER = "E:/Music/Full-Quality/Albums"
DEFAULT_SEPARATOR = " - "
DEFAULT_DRY_RUN = False

SEPARATOR = DEFAULT_SEPARATOR
DRY_RUN = DEFAULT_DRY_RUN

def organize_albums_by_artist(folder_path):
    for item in os.listdir(folder_path):
        item_path = os.path.join(folder_path, item)

        if not os.path.isdir(item_path):
            continue

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

def main():
    parser = argparse.ArgumentParser(description="Group 'Artist - Album' folders under artist folders")
    parser.add_argument("--source", default=DEFAULT_SOURCE_FOLDER, help="Source folder containing 'Artist - Album' folders")
    parser.add_argument("--separator", default=DEFAULT_SEPARATOR, help="Separator between artist and album in names")
    parser.add_argument("--dry-run", action="store_true", default=DEFAULT_DRY_RUN, help="Preview without moving files")
    args = parser.parse_args()

    global SEPARATOR, DRY_RUN
    SEPARATOR = args.separator
    DRY_RUN = args.dry_run

    organize_albums_by_artist(args.source)

if __name__ == "__main__":
    main()

