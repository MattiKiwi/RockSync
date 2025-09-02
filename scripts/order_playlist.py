import os
import argparse
import time
from pathlib import Path

DEFAULT_FOLDER_PATH = "E:/Music/Full-Quality/Playlists/Vibe/Roadtrip 2000-2025"
DEFAULT_INCLUDE_SUBFOLDERS = False
DEFAULT_FILE_EXTENSIONS = (".flac", ".mp3", ".wav", ".m4a")
DEFAULT_DRY_RUN = False

FILE_EXTENSIONS = DEFAULT_FILE_EXTENSIONS
DRY_RUN = DEFAULT_DRY_RUN

def get_files_sorted_by_date(folder_path, include_subfolders):
    files = []
    for root, _, filenames in os.walk(folder_path):
        for filename in filenames:
            if filename.lower().endswith(FILE_EXTENSIONS):
                full_path = os.path.join(root, filename)
                stat = os.stat(full_path)
                files.append((full_path, stat.st_mtime))
        if not include_subfolders:
            break
    return sorted(files, key=lambda x: x[1])

def rename_with_prefix(files):
    digits = len(str(len(files)))
    for index, (filepath, _) in enumerate(files, start=1):
        dir_path = os.path.dirname(filepath)
        original_name = os.path.basename(filepath)
        name_part = original_name

        if original_name[:4].isdigit() and original_name[3] in (" ", "-", "_"):
            name_part = original_name[5:]

        new_name = f"{str(index).zfill(digits)}. {name_part}"
        new_path = os.path.join(dir_path, new_name)

        if filepath == new_path:
            continue

        if DRY_RUN:
            print(f"[DRY RUN] Would rename:\n  {original_name}\n→ {new_name}\n")
        else:
            os.rename(filepath, new_path)
            print(f"✔ Renamed:\n  {original_name}\n→ {new_name}\n")

def main():
    parser = argparse.ArgumentParser(description="Prefix files with index in date order")
    parser.add_argument("--folder", default=DEFAULT_FOLDER_PATH, help="Folder to process")
    parser.add_argument("--include-subfolders", action="store_true", default=DEFAULT_INCLUDE_SUBFOLDERS, help="Include subfolders")
    parser.add_argument("--ext", nargs="*", default=list(DEFAULT_FILE_EXTENSIONS), help="Extensions to include e.g. .flac .m4a")
    parser.add_argument("--dry-run", action="store_true", default=DEFAULT_DRY_RUN, help="Preview without renaming")
    args = parser.parse_args()

    global FILE_EXTENSIONS, DRY_RUN
    FILE_EXTENSIONS = tuple(args.ext)
    DRY_RUN = args.dry_run

    files_sorted = get_files_sorted_by_date(args.folder, args.include_subfolders)
    rename_with_prefix(files_sorted)

if __name__ == "__main__":
    main()

