import os
import sys
from mutagen.flac import FLAC
from pathlib import Path
from lyricsgenius import Genius

# -- Settings --
MUSIC_DIR = "/run/media/matti/MARI_S CLAS/Music"  # ← Change this
LYRICS_SUBDIR = "Lyrics"
LYRICS_EXT = ".lrc"
#GENIUS_TOKEN = "Kl9cDpQNRJEn63Cfuidqu9xcxQIy50xb1rywhQwk8BKlEc5K3hOFUkTggoFUH6D2"
GENIUS_TOKEN = None #Deprecated
genius = Genius(GENIUS_TOKEN, skip_non_songs=True, remove_section_headers=True) \
    if GENIUS_TOKEN else None

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
    if not GENIUS_TOKEN:
        print("⚠ Warning: No Genius token; only embedded lyrics used.")
    for root, _, files in os.walk(MUSIC_DIR):
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
