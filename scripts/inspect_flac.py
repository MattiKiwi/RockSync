from mutagen.flac import FLAC
from pathlib import Path
import sys

def debug_flac_tags(flac_path):
    path = Path(flac_path)
    if not path.exists() or path.suffix.lower() != ".flac":
        print("❌ Please provide a valid .flac file path.")
        return

    print(f"🔍 Inspecting: {flac_path}")
    try:
        audio = FLAC(flac_path)

        print("\n🎵 === FLAC Tags ===")
        for key, values in audio.tags.items():
            for value in values:
                preview = value.replace("\n", "⏎")[:200]  # Shorten long values
                print(f"{key}: {preview}")

        print("\n📝 === Detected Lyrics Tags ===")
        found = False
        for key, values in audio.tags.items():
            if "lyric" in key.lower():
                print(f"{key}: {values[0][:200]}")  # Show up to 200 chars
                found = True
        if not found:
            print("No tags containing 'lyric' found.")

        print("\n🖼️ === Embedded Pictures ===")
        if audio.pictures:
            for i, pic in enumerate(audio.pictures):
                print(f"Picture {i+1}: {pic.mime}, {pic.width}x{pic.height}, desc: {pic.desc}")
        else:
            print("No embedded images.")

        print("\n === All Keys ===")
        print(audio.tags)

    except Exception as e:
        print(f"❌ Error reading FLAC: {e}")

# === Usage ===
if __name__ == "__main__":
    debug_flac_tags("/run/media/matti/Archive Drive/Music/Albums/Eminem - Encore (Deluxe Version) (Explicit)/101. Eminem - Curtains Up (Explicit).flac")
