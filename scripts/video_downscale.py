#!/usr/bin/env python3
"""
Utility to downscale videos for small LCD playback.

The script enforces a 320x240 frame with the active picture letterboxed
(or pillarboxed) to 16:9 (320x180). Content is scaled down while preserving
its original aspect ratio and centered within the frame.

Example usage:
    python -m scripts.video_downscale input.mp4

Environment variables:
    ROCKSYNC_FFMPEG (optional): path to the ffmpeg binary to use.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

FFMPEG_BIN = os.environ.get("ROCKSYNC_FFMPEG", "ffmpeg")
DEFAULT_SUFFIX = "_320x240.mp4"


def build_filter_chain() -> str:
    """Return the ffmpeg filter chain for 320x240 frame with 16:9 content."""
    parts = [
        "scale=320:180:force_original_aspect_ratio=decrease",
        "pad=320:180:(ow-iw)/2:(oh-ih)/2:black",
        "pad=320:240:(ow-iw)/2:(oh-ih)/2:black",
        "setsar=1",
    ]
    return ",".join(parts)


def ensure_ffmpeg_available() -> None:
    """Exit early if the ffmpeg binary cannot be located."""
    if shutil.which(FFMPEG_BIN) is None:
        print(
            f"ffmpeg binary '{FFMPEG_BIN}' not found. Set ROCKSYNC_FFMPEG or adjust PATH.",
            file=sys.stderr,
        )
        sys.exit(1)


def derive_output_path(input_path: Path, output_arg: str | None) -> Path:
    """Derive output path from CLI args, ensuring it does not clobber input."""
    if output_arg:
        return Path(output_arg)
    stem = input_path.stem
    return input_path.with_name(f"{stem}{DEFAULT_SUFFIX}")


def run_ffmpeg(
    input_path: Path,
    output_path: Path,
    overwrite: bool,
    crf: int,
    preset: str,
    audio_bitrate: str,
    dry_run: bool,
) -> int:
    """Execute ffmpeg with the desired parameters, returning the exit code."""
    if input_path == output_path:
        print("Output path must differ from input path to avoid clobbering.", file=sys.stderr)
        return 1

    filter_chain = build_filter_chain()
    cmd = [
        FFMPEG_BIN,
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(input_path),
        "-vf",
        filter_chain,
        "-c:v",
        "libx264",
        "-preset",
        preset,
        "-crf",
        str(crf),
        "-c:a",
        "aac",
        "-b:a",
        audio_bitrate,
        "-movflags",
        "+faststart",
    ]
    cmd.append(str(output_path))

    if overwrite:
        cmd.insert(1, "-y")
    else:
        cmd.insert(1, "-n")

    if dry_run:
        print("DRY RUN:", " ".join(cmd))
        return 0

    try:
        subprocess.run(cmd, check=True)
    except subprocess.CalledProcessError as exc:
        print(f"ffmpeg failed for {input_path}: {exc}", file=sys.stderr)
        return exc.returncode or 1
    except FileNotFoundError:
        print(f"ffmpeg binary '{FFMPEG_BIN}' not found.", file=sys.stderr)
        return 1

    return 0


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inputs", nargs="+", help="Video file(s) to convert.")
    parser.add_argument(
        "-o",
        "--output",
        help="Output file path (only valid with a single input).",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing output files without prompting.",
    )
    parser.add_argument(
        "--crf",
        type=int,
        default=20,
        help="libx264 CRF quality setting (lower is better quality). Default: 20.",
    )
    parser.add_argument(
        "--preset",
        default="medium",
        help="libx264 preset (e.g., ultrafast, medium, slow). Default: medium.",
    )
    parser.add_argument(
        "--audio-bitrate",
        default="128k",
        help="Audio bitrate for AAC encoding. Default: 128k.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print ffmpeg command without executing it.",
    )
    return parser.parse_args()


def validate_args(args: argparse.Namespace) -> None:
    if args.output and len(args.inputs) != 1:
        print("--output can only be used with a single input file.", file=sys.stderr)
        sys.exit(2)


def main() -> int:
    args = parse_arguments()
    validate_args(args)

    if not args.dry_run:
        ensure_ffmpeg_available()

    overall_status = 0
    for input_item in args.inputs:
        input_path = Path(input_item)
        if not input_path.is_file():
            print(f"Input file not found: {input_path}", file=sys.stderr)
            overall_status = 1
            continue

        output_path = derive_output_path(input_path, args.output)
        print(f"→ Converting {input_path} -> {output_path}")
        status = run_ffmpeg(
            input_path=input_path,
            output_path=output_path,
            overwrite=args.overwrite,
            crf=args.crf,
            preset=args.preset,
            audio_bitrate=args.audio_bitrate,
            dry_run=args.dry_run,
        )
        if status != 0:
            overall_status = status

    return overall_status


if __name__ == "__main__":
    sys.exit(main())
