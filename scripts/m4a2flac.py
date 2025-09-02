import os
import argparse
import subprocess
from pathlib import Path

def convert_m4a_to_flac(input_path, output_path):
    # Create the output directory if it doesn't exist
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # ffmpeg command: -map_metadata 0 to copy metadata
    command = [
        "ffmpeg",
        "-i", str(input_path),
        "-c:a", "flac",
        "-map_metadata", "0",
        "-compression_level", "5",
        str(output_path)
    ]

    print(f"Converting: {input_path} -> {output_path}")
    subprocess.run(command, check=True)

def scan_and_convert(base_dir):
    base_dir = Path(base_dir)
    for root, dirs, files in os.walk(base_dir):
        for file in files:
            if file.lower().endswith(".m4a"):
                input_file = Path(root) / file
                relative_path = input_file.relative_to(base_dir)
                output_file = base_dir / "converted_flac" / relative_path.with_suffix(".flac")

                if not output_file.exists():
                    convert_m4a_to_flac(input_file, output_file)
                else:
                    print(f"Skipped (already converted): {output_file}")

def main():
    parser = argparse.ArgumentParser(description="Recursively convert .m4a to .flac in a base folder")
    parser.add_argument("base", help="Base folder to scan recursively")
    args = parser.parse_args()
    scan_and_convert(args.base)

if __name__ == "__main__":
    main()
