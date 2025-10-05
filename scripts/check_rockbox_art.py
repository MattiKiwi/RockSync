#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Check embedded album art for Rockbox/iPod Video color issues.

Flags images that are likely to show up grayscale on device:
- Progressive JPEGs
- CMYK color space
- Non-RGB JPEGs (e.g., YCbCr okay, but CMYK is a problem)
- PNGs/BMPs that might be too large (Rockbox can resize but small is safer)
- Embedded ICC profiles (can confuse decoders)
Outputs a CSV report with details per audio file.

Usage:
  python check_rockbox_art.py /path/to/music

Requires:
  pip install pillow mutagen
"""
import argparse
import base64
import csv
import io
import sys
from pathlib import Path
from typing import List, Tuple, Optional

try:
    from PIL import Image
except Exception as e:
    print("ERROR: Pillow (PIL) is required. Install with: pip install pillow", file=sys.stderr)
    raise

try:
    from mutagen import File as MutagenFile
    from mutagen.id3 import ID3, APIC, error as ID3Error
    from mutagen.flac import FLAC, Picture
    from mutagen.mp4 import MP4, MP4Cover
    import mutagen
except Exception as e:
    print("ERROR: mutagen is required. Install with: pip install mutagen", file=sys.stderr)
    raise


AUDIO_EXTS = {".mp3", ".flac", ".m4a", ".mp4", ".aac", ".ogg", ".opus", ".wv", ".ape", ".wav"}


def extract_pictures(p: Path) -> List[Tuple[bytes, str]]:
    """
    Return list of (image_bytes, source_desc) from the file.
    source_desc indicates tag/container origin for debugging.
    """
    pics: List[Tuple[bytes, str]] = []
    ext = p.suffix.lower()
    try:
        if ext == ".mp3":
            try:
                tags = ID3(str(p))
            except ID3Error:
                tags = None
            if tags:
                for f in tags.getall("APIC"):
                    if isinstance(f, APIC) and f.data:
                        mime = f.mime or "image/unknown"
                        desc = f"ID3.APIC({mime})"
                        pics.append((bytes(f.data), desc))
        elif ext == ".flac":
            try:
                fl = FLAC(str(p))
                for i, pic in enumerate(fl.pictures or []):
                    if isinstance(pic, Picture):
                        desc = f"FLAC.Picture({pic.mime or 'image/unknown'})"
                        pics.append((bytes(pic.data), desc))
                # Some FLACs store vorbis comment METADATA_BLOCK_PICTURE base64 strings (rare outside FLAC, common in Ogg Vorbis/Opus)
                for key, vals in (fl.tags or {}).items():
                    if key.upper() == "METADATA_BLOCK_PICTURE":
                        for b64 in vals:
                            try:
                                pic = Picture(base64.b64decode(b64))
                                desc = f"FLAC.VorbisPic({pic.mime or 'image/unknown'})"
                                pics.append((bytes(pic.data), desc))
                            except Exception:
                                pass
            except Exception:
                pass
        elif ext in {".m4a", ".mp4", ".aac"}:
            try:
                mp4 = MP4(str(p))
                covr = mp4.tags.get('covr') if mp4.tags else None
                if covr:
                    for c in covr:
                        if isinstance(c, MP4Cover):
                            fmt = "jpeg" if c.imageformat == MP4Cover.FORMAT_JPEG else "png"
                            desc = f"MP4.covr({fmt})"
                            pics.append((bytes(c), desc))
            except Exception:
                pass
        else:
            # Generic read: try MutagenFile and guess
            mf = MutagenFile(str(p))
            if mf is None:
                return pics
            # Ogg Vorbis/Opus store pictures in 'metadata_block_picture' (base64)
            for key in ["metadata_block_picture", "METADATA_BLOCK_PICTURE"]:
                if key in (getattr(mf, "tags", {}) or {}):
                    for b64 in mf.tags.get(key, []):
                        try:
                            pic = Picture(base64.b64decode(b64))
                            desc = f"Ogg.Picture({pic.mime or 'image/unknown'})"
                            pics.append((bytes(pic.data), desc))
                        except Exception:
                            pass
    except Exception as e:
        # Swallow per-file extraction errors
        pass
    return pics


def analyze_image(data: bytes) -> dict:
    """
    Analyze image bytes, returning a dict of properties and flags.
    """
    props = {
        "format": None,
        "mode": None,
        "size": None,
        "icc_profile": False,
        "progressive": False,
        "issues": [],
    }
    try:
        with Image.open(io.BytesIO(data)) as im:
            props["format"] = (im.format or "").upper()
            props["mode"] = im.mode
            props["size"] = f"{im.width}x{im.height}"
            info = im.info or {}
            props["icc_profile"] = bool(info.get("icc_profile"))
            # Pillow sets 'progressive' for JPEGs; sometimes 'progression'
            prog = info.get("progressive") or info.get("progression")
            props["progressive"] = bool(prog)
            fmt = props["format"]

            # Heuristics for Rockbox/iPod Video
            if fmt == "JPEG":
                if props["progressive"]:
                    props["issues"].append("progressive_jpeg")
                # Mode hints: 'CMYK' commonly problematic; 'RGB' and 'L' are fine; 'YCbCr' is ok for baseline JPEG usually.
                if im.mode == "CMYK":
                    props["issues"].append("cmyk_color_space")
            else:
                # Non-JPEG formats often ok but slower; recommend RGB JPEG for safety
                if fmt in {"PNG", "BMP"}:
                    # Large art can be slow; recommend <= 200x200 (100x100 ideal)
                    if im.width > 200 or im.height > 200:
                        props["issues"].append("large_dimensions_nonjpeg")
                else:
                    props["issues"].append("nonstandard_format")

            if props["icc_profile"]:
                props["issues"].append("embedded_icc_profile")

            # General size recommendation (<= 200x200)
            if im.width > 200 or im.height > 200:
                props["issues"].append("large_dimensions")

            return props
    except Exception as e:
        return {**props, "issues": ["unreadable_image"]}


def scan_folder(root: Path) -> List[dict]:
    rows: List[dict] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() not in AUDIO_EXTS:
            continue
        pictures = extract_pictures(path)
        if not pictures:
            rows.append({
                "file": str(path),
                "art_index": "",
                "source": "",
                "format": "",
                "mode": "",
                "size": "",
                "progressive": "",
                "icc_profile": "",
                "issues": "no_embedded_art"
            })
            continue
        for idx, (img_bytes, source) in enumerate(pictures):
            props = analyze_image(img_bytes)
            rows.append({
                "file": str(path),
                "art_index": idx,
                "source": source,
                "format": props.get("format", ""),
                "mode": props.get("mode", ""),
                "size": props.get("size", ""),
                "progressive": props.get("progressive", False),
                "icc_profile": props.get("icc_profile", False),
                "issues": ";".join(props.get("issues", [])) or "ok"
            })
    return rows


def main():
    ap = argparse.ArgumentParser(description="Scan audio files for potentially incompatible album art (Rockbox/iPod Video).")
    ap.add_argument("folder", type=str, help="Root folder to scan (recursively).")
    ap.add_argument("--csv", type=str, default="rockbox_art_report.csv", help="Where to write the CSV report.")
    args = ap.parse_args()

    root = Path(args.folder).expanduser().resolve()
    if not root.exists():
        print(f"Path not found: {root}", file=sys.stderr)
        sys.exit(1)

    rows = scan_folder(root)
    # Print brief summary to stdout
    total = len(rows)
    issues = sum(1 for r in rows if r["issues"] != "ok")
    print(f"Scanned entries: {total}  |  With issues: {issues}")

    # Write CSV
    out = Path(args.csv).resolve()
    with out.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["file","art_index","source","format","mode","size","progressive","icc_profile","issues"])
        writer.writeheader()
        writer.writerows(rows)

    print(f"Wrote report: {out}")


if __name__ == "__main__":
    main()
