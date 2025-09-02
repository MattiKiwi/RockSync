import os
import time
from pathlib import Path

# === Settings ===
FOLDER_PATH = "E:\Music\Full-Quality\Playlists\Vibe\Roadtrip 2000-2025"  # ← Change this
INCLUDE_SUBFOLDERS = False              # Set to True if needed
FILE_EXTENSIONS = (".flac", ".mp3", ".wav", ".m4a")  # Supported audio types
DRY_RUN = False                         # Set to True to preview without renaming

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
    return sorted(files, key=lambda x: x[1])  # Sort by date

def rename_with_prefix(files):
    digits = len(str(len(files)))
    for index, (filepath, _) in enumerate(files, start=1):
        dir_path = os.path.dirname(filepath)
        original_name = os.path.basename(filepath)
        name_part = original_name

        # Remove existing numeric prefix if present
        if original_name[:4].isdigit() and original_name[3] in (" ", "-", "_"):
            name_part = original_name[5:]

        new_name = f"{str(index).zfill(digits)}. {name_part}"
        new_path = os.path.join(dir_path, new_name)

        if filepath == new_path:
            continue  # Already named correctly

        if DRY_RUN:
            print(f"[DRY RUN] Would rename:\n  {original_name}\n→ {new_name}\n")
        else:
            os.rename(filepath, new_path)
            print(f"✔ Renamed:\n  {original_name}\n→ {new_name}\n")

# === Run it ===
files_sorted = get_files_sorted_by_date(FOLDER_PATH, INCLUDE_SUBFOLDERS)
rename_with_prefix(files_sorted)
