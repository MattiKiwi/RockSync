import os
import re
import subprocess
import requests
from mutagen.flac import FLAC
from concurrent.futures import ThreadPoolExecutor, as_completed

# === CONFIGURATION ===
SOURCE_DIR = "/run/media/matti/Archive Drive/Music/Unsorted_Test/LoFi hip hop mix"
TARGET_FORMAT = "flac"
LASTFM_API_KEY = "9e779da31c1e603cae855a52e60031dd"
LASTFM_API_ROOT = "http://ws.audioscrobbler.com/2.0/"
MAX_THREADS = 4  # Adjust based on CPU/network capability

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

def process_file(filename):
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

    playlist_folder = os.path.join(SOURCE_DIR, playlist)
    os.makedirs(playlist_folder, exist_ok=True)

    base_name = f"{index} {artist} - {title}"
    src_path = os.path.join(SOURCE_DIR, filename)
    out_path = os.path.join(playlist_folder, f"{base_name}.{TARGET_FORMAT}")

    print(f"[Processing] {base_name}")

    # Step 1: Convert
    reencode_to_flac(src_path, out_path)

    # Step 2: Fetch metadata
    metadata = fetch_metadata_lastfm(artist, title)

    # Step 3: Tag file
    embed_metadata(out_path, metadata["artist"], metadata["title"], index, metadata["album"])

    # Step 4: Cleanup
    os.remove(src_path)

    print(f"[Done] {base_name}")

def main():
    files = [f for f in os.listdir(SOURCE_DIR) if f.endswith(".m4a")]

    with ThreadPoolExecutor(max_workers=MAX_THREADS) as executor:
        futures = [executor.submit(process_file, f) for f in files]
        for future in as_completed(futures):
            future.result()  # raises exception if any

if __name__ == "__main__":
    main()
