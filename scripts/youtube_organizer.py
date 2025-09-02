import os
import re
import argparse
import subprocess
import requests
from mutagen.flac import FLAC
from concurrent.futures import ThreadPoolExecutor, as_completed

# Defaults
DEFAULT_SOURCE_DIR = "/run/media/matti/Archive Drive/Music/Unsorted_Test/LoFi hip hop mix"
DEFAULT_TARGET_FORMAT = "flac"
DEFAULT_LASTFM_API_ROOT = "http://ws.audioscrobbler.com/2.0/"
DEFAULT_MAX_THREADS = 4

# === REGEX ===
pattern = re.compile(r"^(?P<playlist>.+?) - (?P<index>\d{3}) (?P<artist>.+?) - (?P<title>.+?) \[[^\]]+\]\.m4a$")

def reencode_to_flac(input_path, output_path):
    cmd = [
        "ffmpeg", "-y", "-i", input_path,
        "-c:a", "flac",
        "-sample_fmt", "s16",
        output_path
    ]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

def fetch_metadata_lastfm(artist, title):
    params = {
        "method": "track.getInfo",
        "api_key": LASTFM_API_KEY,
        "artist": artist,
        "track": title,
        "format": "json"
    }
    try:
        response = requests.get(LASTFM_API_ROOT, params=params, timeout=10)
        data = response.json()
        track_info = data.get("track", {})
        album = track_info.get("album", {}).get("title")
        return {
            "title": track_info.get("name") or title,
            "artist": track_info.get("artist", {}).get("name") or artist,
            "album": album or "",
        }
    except Exception as e:
        print(f"[Last.fm] {artist} - {title} lookup failed: {e}")
        return {
            "title": title,
            "artist": artist,
            "album": ""
        }

def embed_metadata(file_path, artist, title, track, album):
    audio = FLAC(file_path)
    audio.clear()
    audio["artist"] = artist
    audio["title"] = title
    audio["tracknumber"] = str(track)
    audio["album"] = album
    audio.save()

def process_file(filename, source_dir, target_format, lastfm_api_key):
    if not filename.endswith(".m4a"):
        return

    match = pattern.match(filename)
    if not match:
        print(f"[Skip] Unmatched: {filename}")
        return

    playlist = match["playlist"].strip()
    index = match["index"].strip()
    artist = match["artist"].strip()
    title = match["title"].strip()

    playlist_folder = os.path.join(source_dir, playlist)
    os.makedirs(playlist_folder, exist_ok=True)

    base_name = f"{index} {artist} - {title}"
    src_path = os.path.join(source_dir, filename)
    out_path = os.path.join(playlist_folder, f"{base_name}.{target_format}")

    print(f"[Processing] {base_name}")

    # Step 1: Convert
    reencode_to_flac(src_path, out_path)

    # Step 2: Fetch metadata
    # Require API key for metadata lookup
    metadata = fetch_metadata_lastfm(artist, title) if lastfm_api_key else {"title": title, "artist": artist, "album": ""}

    # Step 3: Tag file
    embed_metadata(out_path, metadata["artist"], metadata["title"], index, metadata["album"])

    # Step 4: Cleanup
    os.remove(src_path)

    print(f"[Done] {base_name}")

def main():
    parser = argparse.ArgumentParser(description="Organize YouTube playlist audio into per-playlist folders and tag")
    parser.add_argument("--source", default=DEFAULT_SOURCE_DIR, help="Source directory containing downloaded .m4a files")
    parser.add_argument("--target-format", default=DEFAULT_TARGET_FORMAT, choices=["flac"], help="Target audio format")
    parser.add_argument("--lastfm-key", default=os.getenv("LASTFM_API_KEY", None), help="Last.fm API key for metadata (optional)")
    parser.add_argument("-j", "--jobs", type=int, default=DEFAULT_MAX_THREADS, help="Parallel threads")
    args = parser.parse_args()

    files = [f for f in os.listdir(args.source) if f.endswith(".m4a")]

    with ThreadPoolExecutor(max_workers=args.jobs) as executor:
        futures = [executor.submit(process_file, f, args.source, args.target_format, args.lastfm_key) for f in files]
        for future in as_completed(futures):
            future.result()

if __name__ == "__main__":
    main()
