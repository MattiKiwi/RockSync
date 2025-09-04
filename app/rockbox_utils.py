import sys
import os
import re
from typing import List, Dict, Any


def list_rockbox_devices() -> List[Dict[str, Any]]:
    """Return a list of detected Rockbox devices using scripts/rockbox_detector.
    Each item contains: mountpoint, label, device, fstype, total_bytes, free_bytes.
    Returns an empty list if detector or psutil is unavailable.
    """
    try:
        # Ensure project root on sys.path so scripts.* is importable when running app/main.py
        from core import ROOT  # type: ignore
        root_str = str(ROOT)
        if root_str not in sys.path:
            sys.path.insert(0, root_str)
    except Exception:
        pass

    try:
        from scripts.rockbox_detector import RockboxDetector  # type: ignore
    except Exception:
        return _with_dummy([])

    try:
        det = RockboxDetector()
        devices_map = det.scan_once()
        out: List[Dict[str, Any]] = []
        for dev in devices_map.values():
            try:
                mp = getattr(dev, 'mountpoint', '')
                info = _detect_device_identity(mp)
                name = _detect_device_name(mp, getattr(dev, 'label', None))
                out.append({
                    'mountpoint': mp,
                    'label': getattr(dev, 'label', None),
                    'device': getattr(dev, 'device', ''),
                    'fstype': getattr(dev, 'fstype', ''),
                    'total_bytes': getattr(dev, 'total_bytes', 0),
                    'free_bytes': getattr(dev, 'free_bytes', 0),
                    'name': name,
                    'model': info.get('model'),
                    'target': info.get('target'),
                    'family': info.get('family'),
                    'display_model': _humanize_model(info.get('target'), info.get('model'), info.get('family')),
                })
            except Exception:
                continue
        return _with_dummy(out)
    except Exception:
        return _with_dummy([])


def _with_dummy(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Append a dummy device from settings if configured."""
    try:
        from app.settings_store import load_settings  # type: ignore
    except Exception:
        return items
    try:
        s = load_settings()
        if not bool(s.get('dummy_device_enabled', False)):
            return items
        dpath = (s.get('dummy_device_path') or '').strip()
        if not dpath:
            return items
        # Try to collect disk usage if path exists; otherwise leave zeroes
        total = free = 0
        try:
            import shutil as _sh
            if __import__('os').path.isdir(dpath):
                du = _sh.disk_usage(dpath)
                total, free = int(getattr(du, 'total', 0)), int(getattr(du, 'free', 0))
        except Exception:
            pass
        dummy_info = _detect_device_identity(dpath)
        dummy_name = _detect_device_name(dpath, 'Dummy Device')
        dummy = {
            'mountpoint': dpath,
            'label': 'Dummy Device',
            'device': dpath,
            'fstype': 'fs',
            'total_bytes': total,
            'free_bytes': free,
            'name': dummy_name,
            'model': dummy_info.get('model'),
            'target': dummy_info.get('target'),
            'family': dummy_info.get('family'),
            'display_model': _humanize_model(dummy_info.get('target'), dummy_info.get('model'), dummy_info.get('family')),
        }
        # Put dummy at the top for clarity
        return [dummy] + items
    except Exception:
        return items


def _detect_device_identity(mountpoint: str) -> Dict[str, str]:
    """Best-effort detection of Rockbox target/device model from filesystem heuristics.
    Tries these, in order:
    - Parse `/.rockbox/rockbox-info.txt` for Target/Model
    - Inspect presence of `/.rockbox/rockbox.*` file extension (e.g., ipod/e200/mi4)
    - iPod hints via `iPod_Control/Device/SysInfo` ModelNumStr
    Returns dict keys: model, target, family (strings, possibly None/empty).
    """
    result: Dict[str, str] = {}
    try:
        rb = os.path.join(mountpoint, ".rockbox")
        # 1) rockbox-info.txt
        info_txt = os.path.join(rb, "rockbox-info.txt")
        if os.path.isfile(info_txt):
            try:
                with open(info_txt, "r", encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        ls = line.strip()
                        if not ls:
                            continue
                        if ls.lower().startswith("target:") and 'target' not in result:
                            result['target'] = ls.split(":", 1)[1].strip()
                        elif ls.lower().startswith("model:") and 'model' not in result:
                            result['model'] = ls.split(":", 1)[1].strip()
                        elif ls.lower().startswith("platform:") and 'family' not in result:
                            result['family'] = ls.split(":", 1)[1].strip()
            except Exception:
                pass
        # 2) firmware file hint: .rockbox/rockbox.*
        if not result.get('target'):
            try:
                for name in os.listdir(rb):
                    if name.lower().startswith("rockbox.") and os.path.isfile(os.path.join(rb, name)):
                        ext = name.split(".", 1)[1].lower()
                        # Common mappings
                        ext_map = {
                            'ipod': ('Apple iPod', 'ipod'),
                            'e200': ('SanDisk Sansa e200', 'sansa-e200'),
                            'mi4': ('SanDisk Sansa (mi4)', 'sansa-mi4'),
                            'sansa': ('SanDisk Sansa', 'sansa'),
                            'iaudio': ('Cowon iAudio', 'iaudio'),
                            'x5': ('Cowon iAudio X5', 'iaudio-x5'),
                            'h10': ('iRiver H10', 'iriver-h10'),
                            'iriver': ('iRiver', 'iriver'),
                            'gigabeat': ('Toshiba Gigabeat', 'gigabeat'),
                            'zvm': ('Creative Zen Vision:M', 'zen-vision-m'),
                            'mrobe': ('Olympus m:robe', 'mrobe'),
                        }
                        fam, tgt = ext_map.get(ext, (None, None))
                        if tgt:
                            result.setdefault('family', fam or '')
                            result.setdefault('target', tgt)
                            if not result.get('model'):
                                result['model'] = fam or tgt
                        break
            except Exception:
                pass
        # 3) iPod SysInfo hints
        ipod_sys = os.path.join(mountpoint, 'iPod_Control', 'Device', 'SysInfo')
        if os.path.isfile(ipod_sys):
            try:
                model_num = None
                with open(ipod_sys, 'r', encoding='utf-8', errors='ignore') as f:
                    for line in f:
                        if 'ModelNumStr' in line:
                            model_num = line.split(':', 1)[1].strip()
                            break
                if model_num:
                    result.setdefault('family', 'Apple iPod')
                    result.setdefault('model', f"iPod ({model_num})")
                    result.setdefault('target', result.get('target') or 'ipod')
            except Exception:
                pass
    except Exception:
        pass
    return result


def _detect_device_name(mountpoint: str, label: str | None) -> str:
    """Try to find a user-visible device name.
    Priority:
      1) iPod SysInfoExtended or SysInfo 'User Visible Name' keys
      2) Volume label (provided by detector)
      3) Basename of mountpoint
    """
    # iPod name hints
    try:
        dev_dir = os.path.join(mountpoint, 'iPod_Control', 'Device')
        for fname in ('SysInfoExtended', 'SysInfo'):
            p = os.path.join(dev_dir, fname)
            if os.path.isfile(p):
                try:
                    with open(p, 'r', encoding='utf-8', errors='ignore') as f:
                        txt = f.read()
                    # Look for "User Visible Name" or similar
                    m = re.search(r"User(?: )?Visible(?: )?Name\s*:\s*(.+)", txt, re.I)
                    if not m:
                        m = re.search(r"VisibleName\s*=\s*([^\r\n]+)", txt, re.I)
                    if m:
                        name = m.group(1).strip()
                        if name:
                            return name
                except Exception:
                    pass
    except Exception:
        pass
    # Fallbacks
    if label and str(label).strip():
        return str(label).strip()
    try:
        base = os.path.basename(os.path.normpath(mountpoint))
        if base:
            return base
    except Exception:
        pass
    return mountpoint


def _humanize_model(target: str | None, model: str | None, family: str | None) -> str:
    """Create a pleasant, human-readable model string.
    Uses known mappings first; then generic prettifying.
    """
    # Known targets map
    known = {
        # iPod family
        'ipodvideo': 'iPod Video',
        'ipodcolor': 'iPod Color/Photo',
        'ipod4g': 'iPod (4G)',
        'ipod3g': 'iPod (3G)',
        'ipod1g2g': 'iPod (1G/2G)',
        'ipodmini1g': 'iPod mini (1G)',
        'ipodmini2g': 'iPod mini (2G)',
        'ipodnano1g': 'iPod nano (1G)',
        'ipodnano2g': 'iPod nano (2G)',
        # SanDisk Sansa
        'e200': 'SanDisk Sansa e200',
        'c200': 'SanDisk Sansa c200',
        'clip': 'SanDisk Sansa Clip',
        'clipplus': 'SanDisk Sansa Clip+',
        'clipzip': 'SanDisk Sansa Clip Zip',
        'fuze': 'SanDisk Sansa Fuze',
        'fuzev2': 'SanDisk Sansa Fuze v2',
        # Cowon
        'x5': 'Cowon iAudio X5',
        'm5': 'Cowon iAudio M5',
        # iRiver
        'h10': 'iriver H10',
        'h100': 'iriver H100',
        'h300': 'iriver H300',
        'h120': 'iriver H120',
        'h320': 'iriver H320',
        # Toshiba
        'gigabeatf': 'Toshiba Gigabeat F',
        'gigabeats': 'Toshiba Gigabeat S',
        # Creative
        'zvm': 'Creative Zen Vision:M',
        # Olympus
        'mrobe100': 'Olympus m:robe 100',
        'mrobe500': 'Olympus m:robe 500',
    }
    # Direct model override if provided and looks nice
    if model and any(ch.isalpha() for ch in model):
        # Title-case words but preserve iPod/m:robe styles
        nice = model.strip()
        # normalize ipod capitalization
        nice = re.sub(r"\bipod\b", "iPod", nice, flags=re.I)
        nice = nice.replace('Iaudio', 'iAudio').replace('Iriver', 'iriver')
        return nice
    tgt = (target or '').strip().lower()
    if tgt in known:
        return known[tgt]
    if not tgt:
        # Fall back to family if present
        if family:
            return family
        return ''
    # Generic prettifier: split letters/digits and case words
    # ipodnano2g -> iPod nano (2G)
    if tgt.startswith('ipod'):
        tail = tgt[4:]
        # extract series
        m = re.match(r"(video|color|nano|min i|classic|touch)?(\d+g)?", tail)
        # Basic mapping for common tails
        mapping = {
            'video': 'Video', 'color': 'Color/Photo', 'nano': 'nano', 'mini': 'mini',
        }
        pretty = 'iPod'
        if tail:
            for k, v in mapping.items():
                if tail.startswith(k):
                    pretty += f" {v}"
                    tail = tail[len(k):]
                    break
        gen = re.search(r"(\d+)g", tail)
        if gen:
            pretty += f" ({gen.group(1)}G)"
        return pretty
    # Default: split by non-alnum and title-case, keep digits
    parts = re.split(r"[^a-z0-9]+", tgt)
    parts = [p for p in parts if p]
    if parts:
        title = ' '.join(p.capitalize() if not p.isdigit() else p for p in parts)
        return title
    return tgt
