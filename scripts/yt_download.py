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
import uuid

# Initialize CLI logging early so all prints are captured to logs
try:
    from _cli_logging import setup_cli_logging
    _LOGGER = setup_cli_logging(debug=False, session_id=str(uuid.uuid4())[:8])
except Exception:
    _LOGGER = None


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
    # Safety: when using --split-chapters with embedding flags, disable embedding and
    # write sidecar files instead for safe post-processing.
    def _has_flag(tokens: List[str], flag: str) -> bool:
        for t in tokens:
            if t == flag or t.startswith(flag + '='):
                return True
        return False
    def _has_any(tokens: List[str], flags: List[str]) -> bool:
        return any(_has_flag(tokens, f) for f in flags)
    has_split = _has_flag(cmd, '--split-chapters')
    has_embed_meta = _has_any(cmd, ['--embed-metadata', '--add-metadata'])
    has_embed_thumb = _has_flag(cmd, '--embed-thumbnail')
    if has_split and (has_embed_meta or has_embed_thumb):
        sanitized: List[str] = []
        i = 0
        while i < len(cmd):
            t = cmd[i]
            if t == '--embed-metadata' or t.startswith('--embed-metadata=') or t == '--add-metadata' or t.startswith('--add-metadata='):
                i += 1
                continue
            if t == '--embed-thumbnail' or t.startswith('--embed-thumbnail='):
                i += 1
                continue
            sanitized.append(t)
            i += 1
        cmd = sanitized
        print('[yt_download] Notice: Disabled metadata/thumbnail embedding with --split-chapters; writing sidecar files instead.', flush=True)
        if not _has_flag(cmd, '--write-thumbnail'):
            cmd += ['--write-thumbnail']
        if not _has_flag(cmd, '--convert-thumbnails'):
            cmd += ['--convert-thumbnails', 'jpg']
        if not _has_flag(cmd, '--write-info-json'):
            cmd += ['--write-info-json']
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

    # If this is a split-chapters run, stage downloads into a temp folder under dest
    stage_dir: Optional[Path] = None
    if has_split:
        try:
            # Find and replace our --paths dest with a temp subfolder
            sid = str(uuid.uuid4())[:8]
            stage_dir = (Path(dest).expanduser() / f".rocksync_ytdl_tmp_{sid}")
            stage_dir.mkdir(parents=True, exist_ok=True)
            print(f"[yt_download] Staging split-chapter download in: {stage_dir}")
            try:
                # Replace the value after the first '--paths'
                if '--paths' in cmd:
                    i = cmd.index('--paths')
                    if i + 1 < len(cmd):
                        cmd[i + 1] = str(stage_dir)
                else:
                    # Should not happen (we set it), but keep robust
                    cmd = cmd[:1] + ['--paths', str(stage_dir)] + cmd[1:]
            except Exception:
                pass
        except Exception:
            stage_dir = None

    # Run streaming
    try:
        # Capture output and forward to stdout so it gets logged via our logger redirection
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        print(cmd)
        assert proc.stdout is not None
        for line in proc.stdout:
            try:
                # Keep streaming output visible and logged
                print(line.rstrip())
            except Exception:
                pass
        rc = proc.wait()
        if rc == 0 and has_split and stage_dir and stage_dir.exists():
            try:
                print('[yt_download] Post-processing split chapters: embedding sidecars and moving into destination…', flush=True)
                _postprocess_split_chapters(stage_dir, Path(dest))
            except Exception as e:
                print(f"[yt_download] Post-process warning: {e}")
        return rc
    except FileNotFoundError:
        print("yt-dlp executable not found. Install it or add to PATH.", file=sys.stderr)
        return 127
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


# ----------------- Post-processing helpers -----------------

def _postprocess_split_chapters(stage_root: Path, final_dest: Path) -> None:
    """Embed sidecar metadata/thumbnail into split chapter files and move chapter
    folders from a staging directory into the final destination.

    Heuristics:
    - Detect per-video chapter folders whose name starts with 'chapter:'.
    - For each chapter folder, find a matching info JSON and thumbnail under the
      staging root; use JSON['title'] to match the folder title when possible.
    - Embed: album = video title, artist/albumartist = channel/uploader/artist fallback,
      tracknumber = parsed from leading digits in filename, title = filename sans prefix,
      date = upload_date (YYYY or YYYY-MM-DD), cover = thumbnail image.
    - Move finished chapter folders to final_dest and delete the staging root.
    """
    import json
    from typing import Tuple
    from mutagen import File as MFile
    from mutagen.flac import FLAC, Picture  # type: ignore
    from mutagen.mp4 import MP4, MP4Cover  # type: ignore
    from mutagen.id3 import ID3, APIC, TIT2, TALB, TPE1, TPE2, TRCK, TDRC, ID3NoHeaderError  # type: ignore

    def _collect_info_jsons(root: Path) -> list[Path]:
        out: list[Path] = []
        for p in root.glob('**/*.info.json'):
            try:
                # Only consider files directly under root (top-level sidecars are most reliable)
                if p.parent == root:
                    out.append(p)
            except Exception:
                continue
        # Fallback: allow nested if none found at top-level
        if not out:
            out = list(root.glob('**/*.info.json'))
        return out

    def _load_json(path: Path) -> dict:
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {}

    def _normalize_date(s: str) -> str:
        s = (s or '').strip()
        if not s:
            return ''
        # yt-dlp uses YYYYMMDD usually
        if len(s) == 8 and s.isdigit():
            return f"{s[0:4]}-{s[4:6]}-{s[6:8]}"
        return s

    def _guess_track_info(filename: str) -> Tuple[int, str]:
        base = Path(filename).stem
        m = re.match(r'^(\d{1,3})[\). _-]+(.*)$', base)
        if m:
            try:
                n = int(m.group(1))
            except Exception:
                n = 0
            title = (m.group(2) or '').strip() or base
            return n, title
        return 0, base

    def _bytes_for_image(img_path: Optional[Path]) -> tuple[bytes, str]:
        if not img_path or not img_path.exists():
            return b'', ''
        try:
            data = img_path.read_bytes()
            ext = img_path.suffix.lower()
            if ext == '.png':
                return data, 'image/png'
            return data, 'image/jpeg'
        except Exception:
            return b'', ''

    def _embed_tags(audio_path: Path, meta: dict, thumb_path: Optional[Path]) -> None:
        artist = (meta.get('artist') or meta.get('channel') or meta.get('uploader') or '').strip()
        album = (meta.get('title') or '').strip()
        date = _normalize_date(str(meta.get('upload_date') or ''))
        track_no, title = _guess_track_info(audio_path.name)
        ext = audio_path.suffix.lower()
        img_data, img_mime = _bytes_for_image(thumb_path)

        try:
            if ext in ('.flac',):
                f = FLAC(str(audio_path))
                if title:
                    f['title'] = [title]
                if album:
                    f['album'] = [album]
                if artist:
                    f['artist'] = [artist]
                    f['albumartist'] = [artist]
                if date:
                    f['date'] = [date]
                if track_no > 0:
                    f['tracknumber'] = [str(track_no)]
                if img_data:
                    pic = Picture()
                    pic.type = 3
                    pic.mime = img_mime or 'image/jpeg'
                    pic.desc = 'Cover'
                    pic.data = img_data
                    # remove existing front cover(s)
                    f.clear_pictures()
                    f.add_picture(pic)
                f.save()
                return
            if ext in ('.m4a', '.mp4', '.alac', '.aac'):
                m = MP4(str(audio_path))
                if title:
                    m['\xa9nam'] = [title]
                if album:
                    m['\xa9alb'] = [album]
                if artist:
                    m['\xa9ART'] = [artist]
                    m['aART'] = [artist]
                if date:
                    m['\xa9day'] = [date]
                if track_no > 0:
                    m['trkn'] = [(track_no, 0)]
                if img_data:
                    fmt = MP4Cover.FORMAT_PNG if (img_mime == 'image/png') else MP4Cover.FORMAT_JPEG
                    m['covr'] = [MP4Cover(img_data, imageformat=fmt)]
                m.save()
                return
            if ext in ('.mp3', '.ogg', '.opus'):
                # Use ID3 for mp3; for ogg/opus, mutagen maps Easy keys reasonably but APIC not supported.
                try:
                    id3 = ID3(str(audio_path))
                except ID3NoHeaderError:
                    id3 = ID3()
                if title:
                    id3.add(TIT2(encoding=3, text=title))
                if album:
                    id3.add(TALB(encoding=3, text=album))
                if artist:
                    id3.add(TPE1(encoding=3, text=artist))
                    id3.add(TPE2(encoding=3, text=artist))
                if date:
                    id3.add(TDRC(encoding=3, text=date))
                if track_no > 0:
                    id3.add(TRCK(encoding=3, text=str(track_no)))
                if img_data and audio_path.suffix.lower() == '.mp3':
                    id3.add(APIC(encoding=3, mime=img_mime or 'image/jpeg', type=3, desc='Cover', data=img_data))
                id3.save(str(audio_path))
                return
            # Fallback: try easy tags
            mf = MFile(str(audio_path), easy=True)
            if mf is not None:
                if title:
                    mf['title'] = [title]
                if album:
                    mf['album'] = [album]
                if artist:
                    mf['artist'] = [artist]
                if track_no > 0:
                    mf['tracknumber'] = [str(track_no)]
                mf.save()
        except Exception:
            # Non-fatal; keep the file even if tagging failed
            pass

    print(f"[yt_download] Inspecting staged files in: {stage_root}")
    # Discover per-video chapter folders under the staging root.
    chapter_dirs: list[Path] = []
    AUDIO_EXTS = {'.flac','.mp3','.m4a','.alac','.aac','.ogg','.opus','.wav'}
    def _has_audio_recursive(d: Path) -> bool:
        try:
            for sub in d.rglob('*'):
                try:
                    if sub.is_file() and sub.suffix.lower() in AUDIO_EXTS:
                        return True
                except Exception:
                    continue
        except Exception:
            return False
        return False
    for p in stage_root.iterdir():
        try:
            if not p.is_dir():
                continue
            if _has_audio_recursive(p):
                chapter_dirs.append(p)
        except Exception:
            continue
    print(f"[yt_download] Found {len(chapter_dirs)} chapter folder(s): {[p.name for p in chapter_dirs]}")

    # Load available infos once to match metadata; try to locate thumbnails near info files
    info_files = _collect_info_jsons(stage_root)
    info_by_title: dict[str, dict] = {}
    def _norm_title(x: str) -> str:
        s = (x or '').lower()
        try:
            s = s.replace('chapter:', '')
            s = re.sub(r'[^a-z0-9]+', ' ', s)
            s = ' '.join(s.split())
        except Exception:
            pass
        return s
    info_by_norm: dict[str, dict] = {}
    for inf in info_files:
        data = _load_json(inf)
        t = (data.get('title') or '').strip()
        if t:
            info_by_title.setdefault(t, data)
            info_by_norm.setdefault(_norm_title(t), data)
    # Try to locate thumbnails by info title or id (fallback map)
    thumb_by_info_title: dict[str, Path] = {}
    thumb_by_info_id: dict[str, Path] = {}
    for inf in info_files:
        try:
            data = _load_json(inf)
            t = (data.get('title') or '').strip()
            vid = (data.get('id') or '').strip()
            # Prefer <staging>/<title>*.jpg (handle extra suffix like video id)
            if t:
                for ext in ('.jpg', '.jpeg', '.png'):
                    matches = sorted(stage_root.glob(f"{t}*{ext}"))
                    if matches:
                        thumb_by_info_title[_norm_title(t)] = matches[0]
                        break
            if vid:
                for ext in ('.jpg', '.jpeg', '.png'):
                    matches = sorted(stage_root.glob(f"*{vid}*{ext}"))
                    if matches:
                        thumb_by_info_id[vid] = matches[0]
                        break
        except Exception:
            continue

    def _pick_meta_for_folder(title: str) -> dict:
        return info_by_title.get(title) or info_by_norm.get(_norm_title(title)) or {}

    def _find_thumbnail_for_folder(folder: Path, title: str) -> Optional[Path]:
        # Prefer files named after the folder (or stripped title), allowing extra suffix like video id.
        # Search inside the folder first, then at the staging root; also try matching by video id from sidecar.
        base_names = [folder.name]
        if folder.name.startswith('chapter:'):
            base_names.append(folder.name[len('chapter:'):].strip())
        if title and title not in base_names:
            base_names.append(title)
        # Try inside the folder (exact then wildcard)
        for bn in base_names:
            for ext in ('.jpg', '.jpeg', '.png'):
                p = folder / f"{bn}{ext}"
                if p.exists():
                    return p
            for ext in ('.jpg', '.jpeg', '.png'):
                matches = sorted(folder.glob(f"{bn}*{ext}"))
                if matches:
                    return matches[0]
        # Try staging root (exact then wildcard)
        for bn in base_names:
            for ext in ('.jpg', '.jpeg', '.png'):
                p = stage_root / f"{bn}{ext}"
                if p.exists():
                    return p
            for ext in ('.jpg', '.jpeg', '.png'):
                matches = sorted(stage_root.glob(f"{bn}*{ext}"))
                if matches:
                    return matches[0]
        # If a matching info has a video id, try id-based matching
        meta_for_title = _pick_meta_for_folder(title)
        vid = (meta_for_title.get('id') or '').strip() if isinstance(meta_for_title, dict) else ''
        if vid:
            for ext in ('.jpg', '.jpeg', '.png'):
                matches = sorted(folder.glob(f"*{vid}*{ext}"))
                if matches:
                    return matches[0]
            for ext in ('.jpg', '.jpeg', '.png'):
                matches = sorted(stage_root.glob(f"*{vid}*{ext}"))
                if matches:
                    return matches[0]
        # Fallback via normalized title mapped to an info-based thumb
        tnorm = _norm_title(title)
        if tnorm in thumb_by_info_title:
            return thumb_by_info_title[tnorm]
        # Any image inside folder as last resort
        for img in folder.glob('*'):
            try:
                if img.is_file() and img.suffix.lower() in ('.jpg','.jpeg','.png'):
                    return img
            except Exception:
                continue
        return None

    # Process each chapter folder
    for cdir in chapter_dirs:
        try:
            # Determine base title for this folder
            base = cdir.name
            if base.startswith('chapter:'):
                base = base[len('chapter:'):].strip() or 'Untitled'
            # Per-folder: pick thumbnail based on folder/title
            thumb = _find_thumbnail_for_folder(cdir, base)
            # Load metadata (JSON) for tags
            meta = _pick_meta_for_folder(base)
            thumb_desc = thumb.name if isinstance(thumb, Path) else 'none'
            print(f"[yt_download] Tagging: {cdir.name}  (album='{base}', cover={thumb_desc})")
            tagged = 0; total = 0
            # Tag all audio files inside
            for ap in cdir.glob('*'):
                if not ap.is_file():
                    continue
                if ap.suffix.lower() not in {'.flac','.mp3','.m4a','.alac','.aac','.ogg','.opus','.wav'}:
                    continue
                total += 1
                try:
                    _embed_tags(ap, meta, thumb)
                    tagged += 1
                except Exception as e:
                    print(f"[yt_download]   tag warn: {ap.name}: {e}")
            print(f"[yt_download]   tagged {tagged}/{total} files")
        except Exception as e:
            print(f"[yt_download]   tagging error in {cdir.name}: {e}")
            continue

    # Move chapter folders into final destination
    final_dest.mkdir(parents=True, exist_ok=True)
    for cdir in chapter_dirs:
        try:
            target = final_dest / cdir.name
            i = 1
            while target.exists():
                target = final_dest / f"{cdir.name}_{i}"
                i += 1
            cdir.rename(target)
            print(f"[yt_download] Moved: {cdir.name} -> {target}")
        except Exception:
            # As a fallback, try copytree then remove
            try:
                import shutil
                t = final_dest / cdir.name
                i = 1
                while t.exists():
                    t = final_dest / f"{cdir.name}_{i}"
                    i += 1
                shutil.copytree(cdir, t)
                shutil.rmtree(cdir)
                print(f"[yt_download] Copied: {cdir.name} -> {t}")
            except Exception:
                pass

    # If no chapter dirs were found, do not move sidecars blindly. Leave staging for inspection.
    if not chapter_dirs:
        print("[yt_download] Warning: No chapter folders were detected; leaving staging intact for manual review.")

    # Cleanup staging dir only if we successfully identified and moved chapter folders
    if chapter_dirs:
        try:
            import shutil
            shutil.rmtree(stage_root)
            print(f"[yt_download] Cleaned up staging: {stage_root}")
        except Exception:
            pass

if __name__ == '__main__':
    raise SystemExit(run(sys.argv[1:]))
