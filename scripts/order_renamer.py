import os
import re

BASE_DIR = "/run/media/matti/Archive Drive/Music/Unsorted_Test/LoFi hip hop mix/Lofi hip hop mix - Beats to Relax⧸Study to [2018]"

# Pattern: 3-digit track number at the beginning
pattern = re.compile(r"^(?P<number>\d{3}) (?P<rest>.+?)\.flac$")

for root, _, files in os.walk(BASE_DIR):
    for filename in files:
        if not filename.endswith(".flac"):
            continue

        match = pattern.match(filename)
        if not match:
            continue  # Skip files already renamed or with different format

        number = int(match["number"])
        rest = match["rest"]

        new_name = f"{number:02d}. {rest}.flac"
        old_path = os.path.join(root, filename)
        new_path = os.path.join(root, new_name)

        print(f"Renaming: {filename} → {new_name}")
        os.rename(old_path, new_path)
