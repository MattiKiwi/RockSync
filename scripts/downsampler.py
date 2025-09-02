import os
import argparse
import subprocess
from multiprocessing import Pool, cpu_count

DEFAULT_SOURCE_DIR = "E:/Music/iPod_Downsampled/New"
FFMPEG_PATH = "ffmpeg"  # Ensure ffmpeg is installed and in PATH

def downsample_flac(file_path):
    temp_output = file_path + ".tmp.flac"
    command = [
        FFMPEG_PATH,
        "-y",                         # Overwrite
        "-i", file_path,
        "-sample_fmt", "s16",         # 16-bit
        "-ar", "44100",               # 44.1 kHz
        temp_output
    ]
    try:
        subprocess.run(command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        os.replace(temp_output, file_path)
        print(f"✔ Downsampled: {file_path}")
    except subprocess.CalledProcessError:
        print(f"❌ Failed: {file_path}")
        if os.path.exists(temp_output):
            os.remove(temp_output)

def find_flac_files(root_dir):
    flac_files = []
    for dirpath, _, filenames in os.walk(root_dir):
        for f in filenames:
            if f.lower().endswith(".flac"):
                flac_files.append(os.path.join(dirpath, f))
    return flac_files

def main():
    parser = argparse.ArgumentParser(description="Downsample FLAC files to 16-bit 44.1kHz in place")
    parser.add_argument("--source", default=DEFAULT_SOURCE_DIR, help="Root folder to process")
    parser.add_argument("-j", "--jobs", type=int, default=cpu_count(), help="Number of parallel processes")
    args = parser.parse_args()

    all_flacs = find_flac_files(args.source)
    print(f"🔍 Found {len(all_flacs)} FLAC files. Starting conversion with {args.jobs} processes...")

    with Pool(args.jobs) as pool:
        pool.map(downsample_flac, all_flacs)

    print("✅ All conversions completed.")

if __name__ == "__main__":
    main()
