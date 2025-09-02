import os
import subprocess
from multiprocessing import Pool, cpu_count

# === Settings ===
SOURCE_DIR = "E:/Music/iPod_Downsampled/New"     # ← Change this
FFMPEG_PATH = "ffmpeg"                       # Make sure ffmpeg is installed and in PATH

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

if __name__ == "__main__":
    all_flacs = find_flac_files(SOURCE_DIR)
    print(f"🔍 Found {len(all_flacs)} FLAC files. Starting conversion with {cpu_count()} processes...")

    with Pool(cpu_count()) as pool:
        pool.map(downsample_flac, all_flacs)

    print("✅ All conversions completed.")
