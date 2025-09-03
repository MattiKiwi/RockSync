# RockSync
An optional alternative of iTunes for MP3 players with Rockbox.

## GUI Wrapper

This repo now includes a lightweight Tkinter app that exposes your existing scripts via a simple GUI. You can select a task, adjust parameters (paths, sizes, options), and run scripts while viewing their output.

### Run

- Requirements: Python 3.9+ (Tkinter included), optional Python deps depending on task: `mutagen`, `Pillow`, `requests`, `psutil`. Some tasks also require `ffmpeg` in PATH.

- Start the app from the repo root:

```
python app/main.py
```

### Notes

- I refactored most scripts to accept CLI arguments and only run under `if __name__ == "__main__"` so they can be called safely from the GUI.
- Tasks show a warning if required dependencies are missing; you can still choose to run them.
- Defaults preserve your current hardcoded values, but you can override them per run.

## Parameterized scripts

Updated scripts that now support CLI args:

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
- `scripts/flac2alac.py` already supported args

## Next ideas

- Persist per-task presets (JSON) and last-used paths
- Progress bars per job, cancel with cleanup
- File pickers customized for music formats
- Optional integration with Rockbox/iPod mount points
