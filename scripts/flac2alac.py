import os
import subprocess
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

def convert_file(flac_file, source_root, output_root):
    relative_path = flac_file.relative_to(source_root).with_suffix(".m4a")
    alac_file = output_root / relative_path
    alac_file.parent.mkdir(parents=True, exist_ok=True)

    command = [
        "ffmpeg",
        "-i", str(flac_file),
        "-map", "0:a",
        "-map", "0:v?",
        "-c:a", "alac",
        "-c:v", "copy",
        "-disposition:v", "attached_pic",
        "-map_metadata", "0",
        str(alac_file)
    ]

    print(f"[START] {flac_file} -> {alac_file}")
    result = subprocess.run(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    if result.returncode != 0:
        print(f"[ERROR] {flac_file.name} failed:\n{result.stderr}")
    else:
        print(f"[DONE] {flac_file.name}")
    return result.returncode

def convert_all_flac_to_alac(source_root, output_root, max_workers=4):
    source_root = Path(source_root).resolve()
    output_root = Path(output_root).resolve()

    flac_files = list(source_root.rglob("*.flac"))
    if not flac_files:
        print("No FLAC files found.")
        return

    print(f"Converting {len(flac_files)} FLAC files using {max_workers} threads...")

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [
            executor.submit(convert_file, flac_file, source_root, output_root)
            for flac_file in flac_files
        ]
        for future in as_completed(futures):
            _ = future.result()  # Catch exceptions from threads if needed

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Recursively convert FLAC to ALAC with cover art and multithreading.")
    parser.add_argument("source", help="Root folder containing FLAC files and subfolders")
    parser.add_argument("output", help="Output folder to store converted ALAC files")
    parser.add_argument("-j", "--jobs", type=int, default=4, help="Number of threads to use (default: 4)")

    args = parser.parse_args()
    convert_all_flac_to_alac(args.source, args.output, args.jobs)
