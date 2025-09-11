# RockSync
An optional alternative to iTunes for Rockbox-based MP3 players. Browse your library, index it into a fast SQLite DB, scan a connected device, search, build mixes, one‑way sync to device, clean up covers/lyrics, and run helper scripts — all from a simple Qt (PySide6) app.

## Quick Start

- Requirements: Python 3.9+ and `PySide6`.
- Install (recommended):
  - `pip install PySide6 mutagen Pillow requests beautifulsoup4 psutil musicbrainzngs lyricsgenius tqdm`
  - Install `ffmpeg` (and `ffprobe`) via your OS package manager if you’ll convert/downsample.
  - Optional (TIDAL downloads): `pip install tidal-dl-ng`
- Run the app from the repo root:

```
python app/main.py
```

- Important: create the Library DB first
  - Open the app → go to “Database” → Source: “Library” → click “Scan”.
  - This builds `music_index.sqlite3` next to `app/settings.json`. Several features (Search and Daily Mix) rely on this index.

Settings live in `app/settings.json`. Logs are written to `app/latest.log` and `app/debug.log` (enable verbose logging in Settings).

## Capabilities

- Library Explorer: Browse your music root; preview basic tags and cover art. Right‑click folders to run tasks with that path prefilled.
- Device Explorer: Browse a connected Rockbox device’s `Music` folder. Works with detected devices or a configured dummy path.
- Search: Fast, DB‑backed search across artist/album/title/genre. Requires the Library DB to be built.
- Database: Index your library (or a device) into a SQLite DB with tags, duration, and file metadata.
- Daily Mix: Create themed, time‑balanced playlists based on genres/years from the DB. Requires Library or Device DB.
- Sync: One‑way mirror from library → device `Music`.
  - Full or Partial (selected folders) mode
  - Extensions filter; “only copy missing”; optionally delete extras on device
  - Post‑sync clean‑up: resize covers to 100x100, export embedded lyrics to sidecars, promote a non‑cover image if cover missing
  - Optional FLAC downsample on device to 16‑bit/44.1 kHz (requires `ffmpeg/ffprobe`)
- Rockbox Tools: Detect devices, manage `.cfg` under `/.rockbox`, browse/install themes from themes.rockbox.org per target.
- Tasks (Advanced): Run helper scripts below with arguments via a simple form; see output inline.
- Themes: Switch between bundled UI themes under `app/themes` or use system default.
- YouTube: Browse YouTube (search, playlists, Watch Later, Liked, Home) and download via yt‑dlp with cookies support. See “YouTube (Browse + Download)” below.

## First Run & Usage

- Configure Settings: Set `Music root`, `Device root`, lyrics subfolder/extension, cover size, job count, tokens (Genius/Last.fm), theme, and a dummy device path if desired.
- Build the Library DB: Go to “Database” → Source: “Library” → click “Scan”.
- Search: Use the Search tab after the DB exists. Change “Source” to search the Library DB or a device DB.
- Device detection: Detected automatically via `scripts/rockbox_detector.py` (uses `psutil`) by looking for `/.rockbox`. Or enable a dummy device path in Settings.
- Sync: Choose Full or Partial. In Partial mode, add folders from your library base and run.
- Themes (Rockbox): Select a target (e.g., `ipodvideo`, `ipod6g`), list themes, preview screenshots, open theme page, and install to `/.rockbox`.
- Daily Mix: Point to Library or Device DB and generate playlists into your chosen playlist folder.

## Python Dependencies

- Core GUI: `PySide6`
- YouTube: `yt-dlp`
- Metadata & tagging: `mutagen`
- Images (previews, resizing): `Pillow`
- Rockbox detection: `psutil`
- Themes browser/installer: `requests`, `beautifulsoup4`, `tqdm` (optional for CLI progress)
- Lyrics (optional online): `lyricsgenius`
- Genre tagging (optional): `musicbrainzngs`
- TIDAL integration (optional): `tidal-dl-ng`

System tools required by some features/scripts:
- `ffmpeg` and `ffprobe` on PATH (conversions, downsampling)

The app degrades gracefully: missing deps disable related features with a helpful note.

## YouTube (Browse + Download)

RockSync includes a YouTube browser and downloader powered by yt‑dlp. You can use it from the GUI (YouTube tab) or via the scripts directly.

- Browse (no downloads): `scripts/yt_browse.py`
  - Subcommands: `search`, `playlist`, `watchlater`, `liked`, `myplaylists`, `subs`, `home` (the latter set require cookies)
  - Fast paging with flat extraction; optional metadata enrichment for channel names and thumbnails
  - Table or JSON Lines output; selectable columns
  - Lightweight on-disk cache for public search/playlists to speed repeat queries
  - Cookies: pass `--cookies-from-browser <firefox|chrome|edge|brave>` or `--cookies-file /path/to/cookies.txt` for private feeds
  - Examples:
    - Search with selected columns: `python3 scripts/yt_browse.py search "pink floyd time" --columns title,channel,duration,url`
    - Playlist page 2 (items 26–50): `python3 scripts/yt_browse.py playlist https://www.youtube.com/playlist?list=XXXX --start 26 --limit 25`
    - Fast repeat using cache: `python3 scripts/yt_browse.py search "ambient mix" --cache-ttl 1800 --no-enrich`
  - Helpful flags:
    - `--columns` choose from: `title,channel,url,duration,date,id,thumbnail`
    - `--no-enrich` skip quick oEmbed lookups (fastest)
    - `--format table|jsonl` output format
    - `--cache-ttl <secs>` cache TTL for public search/playlist (default 900; 0 disables)
    - `--no-cache` disable cache for the run

- Download: `scripts/yt_download.py`
  - Destination folder (`--dest`) is required
  - Presets: `--preset audio-m4a | audio-flac | video-mp4`
  - Profiles: refer to profiles in `app/settings.json` (`youtube_profiles`) via `--profile-name <name>`
  - Raw yt‑dlp args: append with `--args "..."` (overrides conflicting preset/profile options)
  - Cookies: `--cookies-from-browser <browser>` or `--cookies-file <path>` supported
  - ffmpeg: ensure `ffmpeg`/`ffprobe` are installed and on PATH for audio extraction/format merging
  - Examples:
    - Best audio (M4A): `python3 scripts/yt_download.py --dest "~/Music/YouTube" --preset audio-m4a https://youtu.be/ID1 https://youtu.be/ID2`
    - Use a saved profile: `python3 scripts/yt_download.py --dest "~/Music/YouTube" --profile-name "My FLAC" https://www.youtube.com/playlist?list=XXXX`

- GUI: YouTube tab (`app/ui/youtube_pane.py`)
  - Search or open a playlist URL and scroll to load more; thumbnails, titles, channel and duration are shown
  - Enable “Use browser cookies” + choose a browser or point to a `cookies.txt` file to access private feeds (Home, Watch Later, Liked, My Playlists)
  - Choose a download destination and a preset/profile, then “Download Selected” for the checked items

Install the dependency:
- `pip install yt-dlp`

## TIDAL Integration (Optional)

RockSync can embed the upstream tidal-dl-ng graphical interface to search and download from TIDAL within the “Tidal-dl-ng” page.

- Install: `pip install tidal-dl-ng`
- Open the app → “Tidal-dl-ng”. On first use, you will be prompted to sign in to TIDAL via your web browser.
- Network access is required for login and downloading. If offline, the page will delay initialization and show a friendly message.

Notes and Disclaimers
- The TIDAL UI is not authored by this project. It is the official GUI from tidal-dl-ng embedded as-is.
- tidal-dl-ng is a third‑party, open‑source project by exislow. Its license, terms, and disclaimers apply to all TIDAL functionality used via this integration. See:
  - https://github.com/exislow/tidal-dl-ng
- This project is not affiliated with, endorsed, or supported by TIDAL or its partners. Use at your own risk.

## Scripts Overview (CLI and via GUI “Advanced”)

- `scripts/covers.py`: Resize `cover.jpg` recursively to a fixed size. Options: `--root`, `--size WxH`. Depends on `Pillow`.
- `scripts/embedd_resize.py`: Resize and re‑embed front cover images in FLAC files to a fixed size. Options: `--folder`, `--size WxH`. Depends on `mutagen`, `Pillow`.
- `scripts/embed_resize_no_cover.py`: If no front cover exists, promote the first non‑cover image to front cover and resize with aspect‑ratio. Options: `--folder`, `--max-size`. Depends on `mutagen`, `Pillow`.
- `scripts/downsampler.py`: In‑place downsample FLAC files to 16‑bit/44.1kHz. Options: `--source`, `--jobs`. Requires `ffmpeg`/`ffprobe`.
- `scripts/flac2alac.py`: Recursively convert FLAC → ALAC (`.m4a`) preserving cover art and metadata. Args: `source`, `output`, `--jobs`. Requires `ffmpeg`.
- `scripts/m4a2flac.py`: Recursively convert `.m4a` → `.flac` under a base folder. Arg: `base`. Requires `ffmpeg`.
- `scripts/inspect_flac.py`: Inspect a FLAC’s tags, lyrics tags, and embedded pictures. Arg: `file`. Depends on `mutagen`.
- `scripts/lyrics_local.py`: Export embedded lyrics from FLACs to sidecars; optional Genius fallback. Options: `--music-dir`, `--lyrics-subdir`, `--ext`, `--genius-token`. Depends on `mutagen`, optionally `lyricsgenius`.
- `scripts/order_playlist.py`: Prefix files in date order (e.g., `01. …`) for playlist folders. Options: `--folder`, `--include-subfolders`, `--ext`, `--dry-run`.
- `scripts/order_renamer.py`: Rename `001 Title.flac` → `01. Title.flac` in place. Option: `--base-dir`.
- `scripts/sort_by_artist.py`: Move `Artist - Album` folders under `Artist/` parent directories. Options: `--source`, `--separator`, `--dry-run`.
- `scripts/youtube_organizer.py`: Organize `.m4a` files named like `Playlist - 001 Artist - Title [...]` into per‑playlist folders, convert to FLAC, and tag via Last.fm. Options: `--source`, `--target-format`, `--lastfm-key`, `--jobs`. Requires `ffmpeg`, `requests`, `mutagen`.
- `scripts/daily_mix.py`: Build themed “Daily Mix” playlists using the Library/Device DB. See `--help` for advanced theme/seed options. Depends on `mutagen` (optional for durations).
- `scripts/themes.py`: Browse, preview, download, and install Rockbox themes by target. Subcommands: `list-devices`, `list-themes`, `show`, `download`, `install`. Depends on `requests`, `beautifulsoup4`, optionally `tqdm`.
- `scripts/rockbox_detector.py`: Cross‑platform Rockbox device detection using `psutil`.
- `scripts/tag_genres.py`: Fill in genre tags using MusicBrainz. Options include `--library`, `--overwrite`, `--only-missing`, `--ext`, `--folder-fallback`. Depends on `mutagen`, `musicbrainzngs`.
- `scripts/simple_mb_genres.py`: Simpler MusicBrainz‑based genre tagging helper. Depends on `mutagen`, `musicbrainzngs`.
- `scripts/read_rockbox_tcd_dynamic.py`: Utility to read Rockbox “tcd” dynamic playlists (developer/advanced).

## Rockbox Device Detection

- Implemented via `scripts/rockbox_detector.py`. Detects drives with a `/.rockbox` folder and surfaces label, capacity, and mountpoint. The GUI augments this to infer device names and iPod variants when possible.

## Tips & Troubleshooting

- Build the DB first: Open “Database” → Source: “Library” → “Scan”. Search and Daily Mix depend on this.
- `ffmpeg` errors: Ensure `ffmpeg`/`ffprobe` are installed and in PATH.
- No device found: Install `psutil`, plug/mount your device, or set a dummy device path in Settings.
- Missing images in previews: Install `Pillow`.
- GUI won’t start: Ensure `PySide6` and Python 3.9+.

—

If you want help wiring additional scripts into the GUI, see `app/tasks_registry.py` for examples.

## Building

- See `BUILD.md` for detailed, cross‑platform build instructions using PyInstaller, including the provided spec file and CI setup.
