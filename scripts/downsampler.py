import os
import argparse
import subprocess
import json
from multiprocessing import Pool, cpu_count

DEFAULT_SOURCE_DIR = "E:/Music/iPod_Downsampled/New"
FFMPEG_PATH = os.environ.get("ROCKSYNC_FFMPEG", "ffmpeg")   # Ensure ffmpeg is installed and in PATH
FFPROBE_PATH = os.environ.get("ROCKSYNC_FFPROBE", "ffprobe") # Ensure ffprobe is installed and in PATH


def probe_audio_info(file_path):
    """Return (sample_rate:int|None, bits_per_sample:int|None, sample_fmt:str|None, codec_name:str|None).
    Uses ffprobe; on failure returns (None, None, None, None).
    """
    try:
        cmd = [
            FFPROBE_PATH,
            "-v", "error",
            "-select_streams", "a:0",
            "-show_entries", "stream=sample_rate,bits_per_sample,sample_fmt,codec_name",
            "-of", "json",
            file_path,
        ]
        out = subprocess.check_output(cmd, stderr=subprocess.STDOUT)
        data = json.loads(out.decode("utf-8", errors="ignore"))
        streams = data.get("streams") or []
        if not streams:
            return None, None, None, None
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
        codec = st.get("codec_name")
        return sr, bps, fmt, codec
    except Exception:
        return None, None, None, None


def needs_downsample(file_path, target_bits: int, target_rate: int):
    """True if the file appears ABOVE 16-bit / 44.1kHz.
    If probing fails, return False to avoid degrading lower-quality sources.
    """
    sr, bps, fmt, codec = probe_audio_info(file_path)
    # If we can't determine, do not touch the file
    if sr is None and bps is None and fmt is None:
        return False
    # Only downsample if sample rate is ABOVE target
    if sr is not None and target_rate and sr > target_rate:
        return True
    # Prefer bits_per_sample when available
    if bps is not None:
        if target_bits and bps > target_bits:
            return True
    else:
        # Fall back to sample_fmt heuristic
        if fmt and target_bits == 16 and not str(fmt).lower().startswith("s16"):
            return True
    # Already 16-bit/44.1kHz
    return False

def _out_path(file_path: str) -> str:
    # Write to a side temp file in same folder with same extension
    ext = os.path.splitext(file_path)[1].lower()
    return file_path + f".tmp{ext}"

def downsample_lossless(file_path, target_bits: int, target_rate: int):
    # Only process supported lossless formats
    ext = os.path.splitext(file_path)[1].lower()
    if ext not in {'.flac', '.wav', '.aif', '.aiff', '.m4a'}:
        return
    # For m4a, ensure codec is ALAC
    if ext == '.m4a':
        _, _, _, codec = probe_audio_info(file_path)
        if (codec or '').lower() != 'alac':
            return  # skip AAC/AAC-LC/etc.
    # Skip if not required
    if not needs_downsample(file_path, target_bits, target_rate):
        if target_rate and target_bits:
            print(f"⏭ Skipped (already <= {target_bits}-bit/{target_rate/1000:.1f}kHz): {file_path}")
        else:
            print(f"⏭ Skipped (does not exceed target): {file_path}")
        return

    temp_output = _out_path(file_path)
    sample_fmt = f"s{target_bits}"
    cmd = [FFMPEG_PATH, "-y", "-i", file_path, "-sample_fmt", sample_fmt]
    if target_rate:
        cmd.extend(["-ar", str(target_rate)])
    # Preserve container/codec appropriately
    if ext == '.flac':
        pass  # default FLAC encoder
    elif ext in {'.wav', '.aif', '.aiff'}:
        # Let ffmpeg pick PCM s16 matching container
        pass
    elif ext == '.m4a':
        cmd.extend(["-c:a", "alac"])  # ensure ALAC output
    cmd.append(temp_output)
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        os.replace(temp_output, file_path)
        print(f"✔ Downsampled: {file_path}")
    except subprocess.CalledProcessError:
        print(f"❌ Failed: {file_path}")
        if os.path.exists(temp_output):
            os.remove(temp_output)

def find_candidate_files(root_dir):
    out = []
    for dirpath, _, filenames in os.walk(root_dir):
        for f in filenames:
            lf = f.lower()
            if lf.endswith((".flac", ".wav", ".aif", ".aiff", ".m4a")):
                out.append(os.path.join(dirpath, f))
    return out

def main():
    parser = argparse.ArgumentParser(description="Downsample lossless audio in place (FLAC/WAV/AIFF/ALAC)")
    parser.add_argument("--source", default=DEFAULT_SOURCE_DIR, help="Root folder to process")
    parser.add_argument("-j", "--jobs", type=int, default=cpu_count(), help="Number of parallel processes")
    parser.add_argument("--files-from", help="Process only files listed in this text file (one path per line)")
    parser.add_argument("--bits", type=int, default=16, help="Target bit-depth (e.g. 16 or 24)")
    parser.add_argument("--rate", type=int, default=44100, help="Target sample rate in Hz (e.g. 44100 or 48000)")
    args = parser.parse_args()

    if args.files_from:
        try:
            with open(args.files_from, 'r', encoding='utf-8') as fh:
                candidates = [line.strip() for line in fh if line.strip()]
        except Exception:
            candidates = []
    else:
        candidates = find_candidate_files(args.source)
    print(f"🔍 Found {len(candidates)} candidate files. Starting conversion with {args.jobs} processes to {args.bits}-bit/{args.rate/1000:.1f}kHz...")

    # Partial function-like wrapper to pass extra args
    def _runner(file_path: str):
        return downsample_lossless(file_path, args.bits, args.rate)

    with Pool(args.jobs) as pool:
        pool.map(_runner, candidates)

    print("✅ All conversions completed.")

if __name__ == "__main__":
    main()
