# RockSync
An optional alternative to iTunes for Rockbox-based MP3 players. Browse your library, scan a connected device, sync music one-way, clean up covers/lyrics, and run helper scripts — all from a simple Qt (PySide6) app.

## Quick Start

- Requirements: Python 3.9+ and `PySide6`. Optional per‑feature deps: `mutagen`, `Pillow`, `requests`, `beautifulsoup4`, `psutil`. Some conversions need `ffmpeg` on PATH.
- Install (recommended):
  - `pip install PySide6 mutagen Pillow requests beautifulsoup4 psutil`
  - Install `ffmpeg` via your OS package manager if you’ll convert/downsample.
- Run the app (repo root):

```
python app/main.py
```

Settings are saved to `app/settings.json`. Logs are written to `app/latest.log` and `app/debug.log` (enable verbose logging in Settings).

## What’s Inside

- Library Explorer: Browse your music root; preview tags, embedded lyrics, and cover art. Right‑click folders to run tasks with that folder prefilled.
- Device Explorer: Browse a connected Rockbox device’s `Music` folder. Works with detected devices or a configured path.
- Tracks Scanner: Scan a device to list tracks with basic metadata and whether lyrics/cover are present.
- Sync: One‑way mirror from library → device `Music`.
  - Full or Partial (selected folders) mode
  - Include extensions filter, “only copy missing” toggle, optional delete of extras on device (dangerous)
  - Optional post‑sync clean‑up: resize front covers to 100x100, export embedded lyrics to sidecars, and promote a non‑cover image as front cover if missing
  - Optional FLAC downsample on device to 16‑bit/44.1 kHz
- Rockbox Tools: Detect devices, manage `.cfg` profiles under `/.rockbox`, and browse/install themes from themes.rockbox.org (per target).
- Tasks (Advanced): Run the helper scripts below with arguments via a simple form; see output inline.
- Themes: Switch between bundled UI themes under `app/themes` or use system default.

## Dependencies by Feature

- Core GUI: `PySide6`
- Audio metadata and lyrics/cover extraction: `mutagen` (optional), `Pillow` (optional for image preview)
- Device detection: `psutil` (used by `scripts/rockbox_detector.py`)
- Themes browser/installer: `requests`, `beautifulsoup4` (for site parsing), optional `tqdm` for CLI progress
- Transcoding/downsampling: `ffmpeg` in PATH

The app degrades gracefully: missing deps disable related features and show a helpful note.

## GUI Usage

- Settings: Configure Music root, Device root, lyrics subfolder and extension, default cover sizes, job count, API tokens (Genius, Last.fm), theme, and a dummy device for testing.
- Device detection: The app polls connected drives and identifies Rockbox devices (looks for `/.rockbox`). You can also specify a dummy path in Settings to try the UI without hardware.
- Themes (Rockbox): Choose a target (e.g., `ipodvideo`, `ipod6g`), load themes, preview screenshots, open the theme page, and install directly into `/.rockbox` on the device.
- Sync: Choose full or partial mode. In partial mode, add folders from your library base; the sync will mirror just those selections.

## Parameterized Scripts (CLI and via GUI)

These scripts accept arguments and are wired into the GUI’s “Tasks (Advanced)” tab.

- `scripts/covers.py` — `--root`, `--size WIDTHxHEIGHT`
- `scripts/embedd_resize.py` — `--folder`, `--size WIDTHxHEIGHT`
- `scripts/embed_resize_no_cover.py` — `--folder`, `--max-size`
- `scripts/downsampler.py` — `--source`, `--jobs`
- `scripts/order_playlist.py` — `--folder`, `--include-subfolders`, `--ext`, `--dry-run`
- `scripts/order_renamer.py` — `--base-dir`
- `scripts/m4a2flac.py` — positional `base`
- `scripts/inspect_flac.py` — positional `file`
- `scripts/sort_by_artist.py` — `--source`, `--separator`, `--dry-run`
- `scripts/lyrics_local.py` — `--music-dir`, `--lyrics-subdir`, `--ext`, `--genius-token`
- `scripts/youtube_organizer.py` — `--source`, `--target-format`, `--lastfm-key`, `--jobs`
- `scripts/flac2alac.py` — `source`, `output`, `--jobs`

Additional utilities in `scripts/` (e.g., `tag_genres.py`, `daily_mix.py`, `themes.py`) can be used directly from CLI; some may not appear in the GUI yet.

## Rockbox Device Detection

- Backed by `scripts/rockbox_detector.py` (cross‑platform, uses `psutil`). Detects drives that have a `/.rockbox` folder and surfaces label, capacity, and mountpoint.
- The GUI enhances detection with heuristics to infer device/target names and iPod variants when possible.

## Notes & Tips

- ffmpeg: required for conversions (`flac2alac`, `m4a2flac`) and the optional downsampling step in Sync.
- Large folders: Sync runs in a background thread and streams logs into the UI. You can stop mid‑sync; partial results remain on disk.
- Themes preview: Requires `requests`. If previews fail, open the theme page and install from there, or install via CLI (`scripts/themes.py`).

## Troubleshooting

- GUI doesn’t start: Ensure `PySide6` is installed and you’re running Python 3.9+.
- No device found: Install `psutil`, plug/mount your device, or configure a dummy device path in Settings.
- Images not visible in previews: Install `Pillow`.
- Conversions fail: Verify `ffmpeg` is installed and available in PATH.

---

Happy syncing! If you want help wiring additional scripts into the GUI, see `app/tasks_registry.py` for examples.
