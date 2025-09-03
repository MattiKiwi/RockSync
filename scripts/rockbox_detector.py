#!/usr/bin/env python3
"""
Universal Rockbox device detector (Windows/macOS/Linux)
- Detects USB mass storage devices that contain a `/.rockbox/` folder.
- Polls mounted drives at a configurable interval (default: 2 seconds).
- Fires callbacks on connect/disconnect with handy info about the device.

Usage (CLI):
    python rockbox_detector.py

Embedding:
    from rockbox_detector import RockboxDetector
    det = RockboxDetector(on_connect=my_handler, on_disconnect=my_handler)
    det.start()
    ...
    det.stop()
"""

from __future__ import annotations
import os
import sys
import time
import threading
import psutil
import platform
from dataclasses import dataclass
from typing import Callable, Dict, Optional, Set


@dataclass(frozen=True)
class RockboxDevice:
    mountpoint: str            # e.g., "E:\\" on Windows, "/Volumes/iPod" on macOS, "/media/user/IPOD" on Linux
    device: str                # underlying device path (best-effort; e.g., "\\\\.\\E:" on Windows, "/dev/sdb1" on Linux)
    fstype: str                # filesystem type (e.g., "vfat", "exfat", "ntfs", "hfs", etc.)
    total_bytes: int           # disk size (bytes)
    free_bytes: int            # free space (bytes)
    label: Optional[str] = None  # best-effort volume label (may be None on some platforms)


def _get_volume_label_windows(mountpoint: str) -> Optional[str]:
    # Best-effort volume label via WinAPI. Safe no-op on non-Windows.
    if platform.system() != "Windows":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        GetVolumeInformationW = ctypes.windll.kernel32.GetVolumeInformationW
        root_path = ctypes.c_wchar_p(mountpoint)
        vol_name_buf = ctypes.create_unicode_buffer(261)
        fs_name_buf = ctypes.create_unicode_buffer(261)
        serial = wintypes.DWORD()
        max_comp_len = wintypes.DWORD()
        fs_flags = wintypes.DWORD()

        ok = GetVolumeInformationW(
            root_path,
            vol_name_buf,
            len(vol_name_buf),
            ctypes.byref(serial),
            ctypes.byref(max_comp_len),
            ctypes.byref(fs_flags),
            fs_name_buf,
            len(fs_name_buf),
        )
        if ok:
            return vol_name_buf.value or None
    except Exception:
        pass
    return None


def _infer_label_cross_platform(mountpoint: str) -> Optional[str]:
    """
    Best-effort label inference without platform-specific APIs:
    - macOS: /Volumes/Label -> 'Label'
    - Linux: /media/$USER/Label -> 'Label'
    - Windows: use WinAPI, else None
    """
    if platform.system() == "Windows":
        return _get_volume_label_windows(mountpoint)
    # On POSIX, last path component is often the label
    base = os.path.basename(os.path.normpath(mountpoint))
    return base or None


def _is_probably_external(part: psutil._common.sdiskpart) -> bool:
    """
    Heuristic to prefer removable/external mounts.
    Allow common external roots while skipping obvious system mounts.
    """
    mp = part.mountpoint.replace("\\", "/")
    sysname = platform.system()
    if sysname == "Windows":
        # Keep all drives on Windows; filtering is unreliable.
        return True
    # Fast-path for typical external media mount roots
    if sysname == "Linux":
        if mp.startswith("/run/media/") or mp.startswith("/media/") or mp.startswith("/mnt/"):
            return True
    if sysname == "Darwin":  # macOS
        if mp.startswith("/Volumes/"):
            return True
    # Generic system paths to skip
    sys_paths = (
        "/", "/boot", "/System", "/private", "/proc", "/sys", "/dev", "/run",
        "/var", "/usr", "/etc", "/snap", "/Applications"
    )
    return not any(mp == p or mp.startswith(p + "/") for p in sys_paths)


def _looks_like_rockbox_root(mountpoint: str) -> bool:
    # Rockbox devices look like a regular drive with a top-level `.rockbox` directory.
    # Some installs may also have `/.rockbox/rockbox.ipod` (iPod targets).
    rb_dir = os.path.join(mountpoint, ".rockbox")
    return os.path.isdir(rb_dir)


def _build_device(part: psutil._common.sdiskpart) -> Optional[RockboxDevice]:
    try:
        usage = psutil.disk_usage(part.mountpoint)
        label = _infer_label_cross_platform(part.mountpoint)
        return RockboxDevice(
            mountpoint=part.mountpoint,
            device=part.device,
            fstype=part.fstype,
            total_bytes=usage.total,
            free_bytes=usage.free,
            label=label,
        )
    except Exception:
        return None


class RockboxDetector:
    """
    Poll-based, cross-platform detector.
    - Calls `on_connect(device: RockboxDevice)` when a new Rockbox drive appears.
    - Calls `on_disconnect(device: RockboxDevice)` when a previously seen Rockbox drive disappears.
    """

    def __init__(
        self,
        on_connect: Optional[Callable[[RockboxDevice], None]] = None,
        on_disconnect: Optional[Callable[[RockboxDevice], None]] = None,
        interval_seconds: float = 2.0,
    ) -> None:
        self.on_connect = on_connect
        self.on_disconnect = on_disconnect
        self.interval = interval_seconds
        self._stop_evt = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._known: Dict[str, RockboxDevice] = {}  # key: mountpoint

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        # Initial scan so already-connected devices fire on_connect immediately
        try:
            current = self._scan_now()
            for mp, dev in current.items():
                if mp not in self._known:
                    self._known[mp] = dev
                    if self.on_connect:
                        try:
                            self.on_connect(dev)
                        except Exception:
                            pass
        except Exception:
            pass

        self._stop_evt.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_evt.set()
        if self._thread:
            self._thread.join(timeout=self.interval * 2)
            self._thread = None

    def _scan_now(self) -> Dict[str, RockboxDevice]:
        found: Dict[str, RockboxDevice] = {}
        try:
            parts = psutil.disk_partitions(all=True)
        except Exception:
            parts = []

        for part in parts:
            # Skip obviously non-usable mounts on POSIX to reduce noise
            if not _is_probably_external(part):
                continue

            mp = part.mountpoint
            # Quick existence check; some transient mounts may appear briefly
            if not os.path.isdir(mp):
                continue

            # Look for Rockbox signature
            try:
                if _looks_like_rockbox_root(mp):
                    dev = _build_device(part)
                    if dev:
                        found[mp] = dev
            except PermissionError:
                # Some mounts might be permission-protected; ignore gracefully
                continue
            except Exception:
                continue

        return found

    # Public helper for one-off scans
    def scan_once(self) -> Dict[str, RockboxDevice]:
        return self._scan_now()

    def _run(self) -> None:
        while not self._stop_evt.is_set():
            current = self._scan_now()
            prev_mounts: Set[str] = set(self._known.keys())
            curr_mounts: Set[str] = set(current.keys())

            # New devices
            for mp in curr_mounts - prev_mounts:
                dev = current[mp]
                self._known[mp] = dev
                if self.on_connect:
                    try:
                        self.on_connect(dev)
                    except Exception:
                        pass

            # Disconnected devices
            for mp in prev_mounts - curr_mounts:
                dev = self._known.pop(mp, None)
                if dev and self.on_disconnect:
                    try:
                        self.on_disconnect(dev)
                    except Exception:
                        pass

            # Update any changed metadata (rare but possible)
            for mp in curr_mounts & prev_mounts:
                self._known[mp] = current[mp]

            self._stop_evt.wait(self.interval)


# ----------------------------
# CLI demo for quick testing
# ----------------------------
def _fmt_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024.0:
            return f"{n:.1f} {unit}"
        n /= 1024.0
    return f"{n:.1f} PB"


def _print_connect(dev: RockboxDevice) -> None:
    print("🎧 Rockbox device connected!")
    print(f"  Mountpoint : {dev.mountpoint}")
    print(f"  Device     : {dev.device}")
    print(f"  FS type    : {dev.fstype}")
    print(f"  Label      : {dev.label or '(unknown)'}")
    print(f"  Capacity   : {_fmt_size(dev.total_bytes)} total, {_fmt_size(dev.free_bytes)} free")
    print("-" * 40)


def _print_disconnect(dev: RockboxDevice) -> None:
    print("🔌 Rockbox device disconnected!")
    print(f"  Mountpoint : {dev.mountpoint}")
    print(f"  Device     : {dev.device}")
    print("-" * 40)


def main() -> int:
    print("Starting universal Rockbox detector (Ctrl+C to stop)...")
    det = RockboxDetector(on_connect=_print_connect, on_disconnect=_print_disconnect, interval_seconds=2.0)
    det.start()
    try:
        while True:
            time.sleep(1.0)
    except KeyboardInterrupt:
        pass
    finally:
        det.stop()
        print("Stopped.")
    return 0


