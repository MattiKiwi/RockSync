import os
import sys
import argparse
from mutagen.flac import FLAC
from pathlib import Path
try:
    from lyricsgenius import Genius
except Exception:
    Genius = None

# -- Defaults --
DEFAULT_MUSIC_DIR = "/run/media/matti/MARI_S CLAS/Music"
DEFAULT_LYRICS_SUBDIR = "Lyrics"
DEFAULT_LYRICS_EXT = ".lrc"
DEFAULT_GENIUS_TOKEN = None

genius = None

LOG = []

def extract_embedded(audio):
    for key, vals in audio.tags.items():
        if "lyric" in key.lower():
            text = vals[0]
            if isinstance(text, str) and text.strip():
                return text
    return None

def fetch_online(title, artist=None):
    if not genius:
        return None
    try:
        song = genius.search_song(title, artist) if artist else genius.search_song(title)
        if song and song.lyrics:
            return song.lyrics
    except Exception as e:
        LOG.append(f"Error fetching online for '{title}': {e}")
    return None

def process_file(flac_path):
    audio = FLAC(flac_path)
    lyrics = extract_embedded(audio)
    used_source = "embedded"
    title = audio.get("title", [Path(flac_path).stem])[0]
    artist = audio.get("artist", [None])[0]
    
    if lyrics:
        print(f"Local Lyrics found for {title} by {artist}")

    if not lyrics:
        lyrics = fetch_online(title, artist)
        used_source = "online" if lyrics else None

    if not lyrics:
        LOG.append(f"No lyrics for {flac_path}")
        return

    outdir = Path(flac_path).parent / LYRICS_SUBDIR
    outdir.mkdir(exist_ok=True)
    outpath = outdir / (Path(flac_path).stem + LYRICS_EXT)

    with open(outpath, "w", encoding="utf-8") as f:
        f.write(lyrics)
    LOG.append(f"Wrote {used_source} lyrics to {outpath}")

def main():
    parser = argparse.ArgumentParser(description="Export embedded or fetched lyrics to sidecar files for FLACs")
    parser.add_argument("--music-dir", default=DEFAULT_MUSIC_DIR, help="Root music directory to scan")
    parser.add_argument("--lyrics-subdir", default=DEFAULT_LYRICS_SUBDIR, help="Subdirectory name to store lyrics files")
    parser.add_argument("--ext", default=DEFAULT_LYRICS_EXT, help="Lyrics file extension, e.g. .lrc or .txt")
    parser.add_argument("--genius-token", default=DEFAULT_GENIUS_TOKEN, help="Genius API token (optional)")
    args = parser.parse_args()

    global genius, LYRICS_SUBDIR, LYRICS_EXT
    LYRICS_SUBDIR = args.lyrics_subdir
    LYRICS_EXT = args.ext

    if args.genius_token and Genius:
        try:
            print("Using Genius for online fallback...")
            genius = Genius(args.genius_token, skip_non_songs=True, remove_section_headers=True)
        except Exception as e:
            print(f"⚠ Could not initialize Genius client: {e}")
            genius = None
    else:
        if not Genius and args.genius_token:
            print("⚠ lyricsgenius not installed; skipping online fetch.")
        print("⚠ No Genius token; only embedded lyrics used.")

    for root, _, files in os.walk(args.music_dir):
        for f in files:
            if f.lower().endswith(".flac"):
                try:
                    process_file(os.path.join(root, f))
                except Exception as e:
                    LOG.append(f"Error processing {f}: {e}")

    print("\n=== Process Complete ===")
    for line in LOG:
        print(line)

if __name__ == "__main__":
    main()
