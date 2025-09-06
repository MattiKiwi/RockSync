import os
import argparse
import subprocess
import json
from multiprocessing import Pool, cpu_count

DEFAULT_SOURCE_DIR = "E:/Music/iPod_Downsampled/New"
FFMPEG_PATH = "ffmpeg"   # Ensure ffmpeg is installed and in PATH
FFPROBE_PATH = "ffprobe" # Ensure ffprobe is installed and in PATH


def probe_audio_info(file_path):
    """Return (sample_rate:int|None, bits_per_sample:int|None, sample_fmt:str|None).
    Uses ffprobe; on failure returns (None, None, None).
    """
    try:
        cmd = [
            FFPROBE_PATH,
            "-v", "error",
            "-select_streams", "a:0",
            "-show_entries", "stream=sample_rate,bits_per_sample,sample_fmt",
            "-of", "json",
            file_path,
        ]
        out = subprocess.check_output(cmd, stderr=subprocess.STDOUT)
        data = json.loads(out.decode("utf-8", errors="ignore"))
        streams = data.get("streams") or []
        if not streams:
            return None, None, None
        st = streams[0]
        sr = st.get("sample_rate")
        try:
            sr = int(sr) if sr is not None else None
        except Exception:
            sr = None
        bps = st.get("bits_per_sample")
        try:
            bps = int(bps) if bps is not None else None
        except Exception:
            bps = None
        fmt = st.get("sample_fmt")
        return sr, bps, fmt
    except Exception:
        return None, None, None


def needs_downsample(file_path):
    """True if the file appears ABOVE 16-bit / 44.1kHz.
    If probing fails, return False to avoid degrading lower-quality sources.
    """
    sr, bps, fmt = probe_audio_info(file_path)
    # If we can't determine, do not touch the file
    if sr is None and bps is None and fmt is None:
        return False
    # Only downsample if sample rate is ABOVE target
    if sr is not None and sr > 44100:
        return True
    # Prefer bits_per_sample when available
    if bps is not None:
        if bps > 16:
            return True
    else:
        # Fall back to sample_fmt heuristic
        if fmt and not str(fmt).lower().startswith("s16"):
            return True
    # Already 16-bit/44.1kHz
    return False

def downsample_flac(file_path):
    # Skip if not required
    if not needs_downsample(file_path):
        print(f"⏭ Skipped (already 16-bit/44.1kHz): {file_path}")
        return
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
    parser.add_argument("--files-from", help="Process only files listed in this text file (one path per line)")
    args = parser.parse_args()

    if args.files_from:
        try:
            with open(args.files_from, 'r', encoding='utf-8') as fh:
                all_flacs = [line.strip() for line in fh if line.strip().lower().endswith('.flac')]
        except Exception:
            all_flacs = []
    else:
        all_flacs = find_flac_files(args.source)
    print(f"🔍 Found {len(all_flacs)} FLAC files. Starting conversion with {args.jobs} processes...")

    with Pool(args.jobs) as pool:
        pool.map(downsample_flac, all_flacs)

    print("✅ All conversions completed.")

if __name__ == "__main__":
    main()
