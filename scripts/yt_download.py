#!/usr/bin/env python3
from __future__ import annotations
import argparse
import sys
import shlex
from typing import Any, Dict, List, Optional

# Local settings loader
from pathlib import Path
import os
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
try:
    from settings_store import load_settings  # type: ignore
except Exception:
    def load_settings():
        return {}
try:
    from core import cmd_exists  # type: ignore
except Exception:
    import shutil
    def cmd_exists(x: str) -> bool:
        return shutil.which(x) is not None

import subprocess
import re


def build_preset(name: str) -> Dict[str, Any]:
    # Map friendly preset names to yt-dlp options
    presets = {
        'audio-m4a': { 'postprocessors': [{
            'key': 'FFmpegExtractAudio', 'preferredcodec': 'm4a', 'preferredquality': '0'
        }]},
        'audio-flac': { 'postprocessors': [{
            'key': 'FFmpegExtractAudio', 'preferredcodec': 'flac', 'preferredquality': '0'
        }]},
        'video-mp4': { 'format': "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/best" },
    }
    return presets.get(name, {})


def parse_args(argv: List[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog='yt_download.py',
        description='Download YouTube videos or playlists using yt-dlp with presets/profiles.'
    )
    p.add_argument('--dest', required=True, help='Output directory')
    p.add_argument('--preset', choices=['audio-m4a', 'audio-flac', 'video-mp4'], help='Built-in preset')
    p.add_argument('--profile-name', help='Profile name from app settings (youtube_profiles)')
    p.add_argument('--args', help='Raw yt-dlp args string to append (overrides conflicting preset/profile opts)')
    p.add_argument('--cookies-from-browser', metavar='BROWSER', help='Read cookies from browser (firefox, chrome, brave, edge)')
    p.add_argument('--cookies-file', metavar='PATH', help='Path to cookies.txt (Netscape format)')
    p.add_argument('--ffmpeg-location', metavar='PATH', help='Path to ffmpeg/ffprobe directory or binary')
    p.add_argument('--debug-ffmpeg', action='store_true', help='Print ffmpeg path and encoder availability before download')
    p.add_argument('urls', nargs='+', help='Video or playlist URLs')
    return p.parse_args(argv)


def run(argv: List[str]) -> int:
    ns = parse_args(argv)
    dest = ns.dest
    urls = ns.urls
    settings = load_settings()

    # Validate destination directory
    try:
        dpath = Path(dest).expanduser()
        # Common mistake: using ffmpeg binary path as destination
        if dpath.name.lower().startswith('ffmpeg') and dpath.is_file():
            print("Error: Destination points to an ffmpeg binary. Set Destination to a writable folder, and pass ffmpeg via --ffmpeg-location.", file=sys.stderr)
            return 2
        if dpath.exists() and not dpath.is_dir():
            print(f"Error: Destination exists and is not a directory: {dpath}", file=sys.stderr)
            return 2
        if not dpath.exists():
            dpath.mkdir(parents=True, exist_ok=True)
        # Check writability by creating a temp file
        try:
            probe = dpath / '.rocksync_write_probe.tmp'
            with open(probe, 'w', encoding='utf-8') as f:
                f.write('')
            try:
                probe.unlink()
            except Exception:
                pass
        except Exception:
            print(f"Error: Destination is not writable: {dpath}", file=sys.stderr)
            return 13
        dest = str(dpath)
    except PermissionError:
        print(f"Error: Permission denied creating destination: {dest}", file=sys.stderr)
        return 13
    except Exception as e:
        print(f"Error: Could not prepare destination '{dest}': {e}", file=sys.stderr)
        return 1

    # Print a short heading
    print(f"Downloading to: {dest}")
    if ns.preset:
        print(f"Preset: {ns.preset}")
    if ns.profile_name:
        print(f"Profile: {ns.profile_name}")
    if ns.cookies_from_browser:
        print(f"Cookies: browser={ns.cookies_from_browser}")
    elif ns.cookies_file:
        print(f"Cookies: file={ns.cookies_file}")
    print(f"Items: {len(urls)}")

    # Build CLI command for yt-dlp for maximum compatibility with its args
    cmd: List[str] = ['yt-dlp']
    # Destination base path: use --paths so any -o from profiles remains relative to dest
    cmd += ['--paths', dest]
    # Default filename template (can be overridden by profile/raw args)
    cmd += ['-o', '%(title)s [%(id)s].%(ext)s']
    # Determine effective ffmpeg path:
    # Priority: explicit CLI flag > provided inside profile/raw args > app settings
    profile_args_str = ''
    if ns.profile_name:
        for p in settings.get('youtube_profiles', []) or []:
            if p.get('name') == ns.profile_name:
                profile_args_str = p.get('args') or ''
                break
    raw_args_str = ns.args or ''
    def tokens_contain_ffmpeg_location(s: str) -> bool:
        try:
            toks = shlex.split(s or '')
        except Exception:
            toks = (s or '').split()
        for i, t in enumerate(toks):
            if t == '--ffmpeg-location':
                return True
            if t.startswith('--ffmpeg-location='):
                return True
        return False
    has_ffmpeg_in_args = tokens_contain_ffmpeg_location(profile_args_str) or tokens_contain_ffmpeg_location(raw_args_str)
    effective_ffmpeg: Optional[str] = None
    if ns.ffmpeg_location:
        effective_ffmpeg = ns.ffmpeg_location
    elif not has_ffmpeg_in_args:
        spath = (settings.get('ffmpeg_path') or '').strip()
        if spath:
            effective_ffmpeg = spath
    if effective_ffmpeg:
        cmd += ['--ffmpeg-location', effective_ffmpeg]
    # Preset
    if ns.preset == 'audio-m4a':
        cmd += ['--extract-audio', '--audio-format', 'm4a']
    elif ns.preset == 'audio-flac':
        cmd += ['--extract-audio', '--audio-format', 'flac']
    elif ns.preset == 'video-mp4':
        cmd += ['-f', "bv*[ext=mp4]+ba[ext=m4a]/b[ext=mp4]/best"]
    # Profile from settings
    if ns.profile_name:
        prof = None
        for p in settings.get('youtube_profiles', []) or []:
            if p.get('name') == ns.profile_name:
                prof = p
                break
        if prof and prof.get('args'):
            cmd += shlex.split(prof['args'])
    # Raw args
    if ns.args:
        cmd += shlex.split(ns.args)
    # Cookies
    if ns.cookies_file:
        cmd += ['--cookies', ns.cookies_file]
    elif ns.cookies_from_browser:
        cmd += ['--cookies-from-browser', ns.cookies_from_browser]
    # URLs
    cmd += urls
    # Preflight: ffmpeg availability and encoder support when extracting audio
    def gather_formats(tokens: List[str]) -> Dict[str, str]:
        # Parse a subset of args for audio extraction and format
        extract = False
        a_fmt: Optional[str] = None
        it = iter(range(len(tokens)))
        for i in it:
            t = tokens[i]
            if t == '--extract-audio' or t == '-x':
                extract = True
            if t == '--audio-format' and i + 1 < len(tokens):
                a_fmt = tokens[i + 1]
            if t.startswith('--audio-format='):
                a_fmt = t.split('=', 1)[1]
        return {'extract': '1' if extract else '0', 'audio_format': a_fmt or ''}

    tokens = cmd[1:]  # skip program name
    fmt_info = gather_formats(tokens)
    needs_extract = fmt_info['extract'] == '1'
    audio_fmt = (fmt_info['audio_format'] or '').lower()

    def ffmpeg_has_encoder(enc: str) -> bool:
        """Return True if ffmpeg lists the given encoder name.

        Parses `ffmpeg -encoders` output robustly instead of guessing columns.
        """
        # Resolve executable path from --ffmpeg-location
        exe = 'ffmpeg'
        loc = effective_ffmpeg
        if loc:
            p = Path(loc).expanduser()
            if p.is_file():
                exe = str(p)
            elif p.is_dir():
                exe = str(p / ('ffmpeg.exe' if sys.platform.startswith('win') else 'ffmpeg'))
        try:
            out = subprocess.check_output([exe, '-hide_banner', '-encoders'], stderr=subprocess.STDOUT, text=True)
        except Exception:
            return False
        enc = enc.strip().lower()
        # Lines typically look like: " A..... aac             AAC (Advanced Audio Coding)"
        names = set()
        for line in out.splitlines():
            m = re.match(r"^\s*[AVS].*?\s+([A-Za-z0-9_]+)\s", line)
            if m:
                names.add(m.group(1).lower())
        return enc in names

    def ensure_ffmpeg() -> Optional[str]:
        # Check presence of ffmpeg
        if effective_ffmpeg:
            # If a directory is provided, assume binary name inside it
            p = Path(effective_ffmpeg)
            if p.is_dir():
                cand = p / ('ffmpeg.exe' if sys.platform.startswith('win') else 'ffmpeg')
                if cand.exists():
                    return None
            elif p.is_file():
                return None
            return 'ffmpeg not found at --ffmpeg-location'
        if not cmd_exists('ffmpeg'):
            return 'ffmpeg is not installed or not on PATH.'
        return None

    def resolved_ffmpeg_path() -> str:
        if effective_ffmpeg:
            p = Path(effective_ffmpeg).expanduser()
            if p.is_file():
                return str(p)
            if p.is_dir():
                return str(p / ('ffmpeg.exe' if sys.platform.startswith('win') else 'ffmpeg'))
        return 'ffmpeg'

    if needs_extract:
        err = ensure_ffmpeg()
        if err:
            print(f"Error: {err}\nInstall ffmpeg or set --ffmpeg-location to its path.", file=sys.stderr)
            return 127
        if ns.debug_ffmpeg:
            exe = resolved_ffmpeg_path()
            print(f"FFmpeg: {exe}")
            try:
                v = subprocess.check_output([exe, '-version'], stderr=subprocess.STDOUT, text=True).splitlines()[0]
                print(v)
            except Exception:
                pass
            aac_ok = (ffmpeg_has_encoder('aac') or ffmpeg_has_encoder('libfdk_aac') or (sys.platform == 'darwin' and ffmpeg_has_encoder('aac_at')))
            flac_ok = ffmpeg_has_encoder('flac')
            mp3_ok = ffmpeg_has_encoder('libmp3lame') or ffmpeg_has_encoder('libshine')
            print(f"Encoders: aac={'yes' if aac_ok else 'no'}, flac={'yes' if flac_ok else 'no'}, mp3={'yes' if mp3_ok else 'no'}")
        if audio_fmt in ('m4a', 'aac'):
            # m4a requires an AAC encoder
            if not (ffmpeg_has_encoder('aac') or ffmpeg_has_encoder('libfdk_aac') or (sys.platform == 'darwin' and ffmpeg_has_encoder('aac_at'))):
                print("Error: FFmpeg AAC encoder not available at the provided path.\n"
                      "- Fix: Install a full ffmpeg build with AAC (or libfdk_aac),\n"
                      "  or point --ffmpeg-location to that build.\n"
                      "- Workaround: Use --preset audio-flac or pass --args '-x --audio-format opus'",
                      file=sys.stderr)
                return 1
        elif audio_fmt == 'mp3':
            if not (ffmpeg_has_encoder('libmp3lame') or ffmpeg_has_encoder('libshine')):
                print("Error: FFmpeg MP3 encoder (libmp3lame/libshine) not available. Install a full ffmpeg build or choose a different audio format.", file=sys.stderr)
                return 1
        elif audio_fmt == 'flac':
            if not ffmpeg_has_encoder('flac'):
                print("Error: FFmpeg FLAC encoder not available. Install a full ffmpeg build or choose a different audio format.", file=sys.stderr)
                return 1

    # Run streaming
    try:
        proc = subprocess.Popen(cmd, stdout=sys.stdout, stderr=sys.stderr)
        return proc.wait()
    except FileNotFoundError:
        print("yt-dlp executable not found. Install it or add to PATH.", file=sys.stderr)
        return 127
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(run(sys.argv[1:]))
