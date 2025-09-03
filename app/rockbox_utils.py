import sys
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
                out.append({
                    'mountpoint': getattr(dev, 'mountpoint', ''),
                    'label': getattr(dev, 'label', None),
                    'device': getattr(dev, 'device', ''),
                    'fstype': getattr(dev, 'fstype', ''),
                    'total_bytes': getattr(dev, 'total_bytes', 0),
                    'free_bytes': getattr(dev, 'free_bytes', 0),
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
        dummy = {
            'mountpoint': dpath,
            'label': 'Dummy Device',
            'device': dpath,
            'fstype': 'fs',
            'total_bytes': total,
            'free_bytes': free,
        }
        # Put dummy at the top for clarity
        return [dummy] + items
    except Exception:
        return items
