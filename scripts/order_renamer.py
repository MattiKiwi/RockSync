import os
import re
import argparse

DEFAULT_BASE_DIR = "/run/media/matti/Archive Drive/Music/Unsorted_Test/LoFi hip hop mix/Lofi hip hop mix - Beats to Relax⧸Study to [2018]"

def rename_in_dir(base_dir):
    pattern = re.compile(r"^(?P<number>\d{3}) (?P<rest>.+?)\.flac$")
    for root, _, files in os.walk(base_dir):
        for filename in files:
            if not filename.endswith(".flac"):
                continue

            match = pattern.match(filename)
            if not match:
                continue

            number = int(match["number"])
            rest = match["rest"]

            new_name = f"{number:02d}. {rest}.flac"
            old_path = os.path.join(root, filename)
            new_path = os.path.join(root, new_name)

            print(f"Renaming: {filename} → {new_name}")
            os.rename(old_path, new_path)

def main():
    parser = argparse.ArgumentParser(description="Rename files like '001 Title.flac' to '01. Title.flac'")
    parser.add_argument("--base-dir", default=DEFAULT_BASE_DIR, help="Base folder to process recursively")
    args = parser.parse_args()
    rename_in_dir(args.base_dir)

if __name__ == "__main__":
    main()
