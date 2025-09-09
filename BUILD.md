Build RockSync executables

Prereqs
- Python 3.9+ (same as the app)
- Virtual environment recommended
- PyInstaller 5.10+ (or any recent 6.x)
- System tools for optional features (ffmpeg/ffprobe) are not required to build, only to run certain tasks.

1) Create a venv and install deps
```
python -m venv .venv
. .venv/bin/activate          # on Windows: .venv\Scripts\activate
pip install --upgrade pip
pip install PyInstaller PySide6 mutagen Pillow requests beautifulsoup4 psutil musicbrainzngs lyricsgenius tqdm tidal-dl-ng
```

2) Build with the provided spec (recommended)
```
pyinstaller rocksync.spec
```

Artifacts are written to `dist/RockSync/` (one-folder). Run the app executable inside that folder.

3) One-file build (optional)
One-file works too, but startup unpacks to a temp folder and may be slower. Example command:
```
pyinstaller \
  --noconfirm --name RockSync --windowed --onefile \
  --collect-qt-plugins=all \
  --add-data "app/settings.json:app" \
  --add-data "app/themes:app/themes" \
  --add-data "scripts:scripts" \
  app/main.py
```
On Windows, use `;` in `--add-data` instead of `:`:
```
--add-data "app\\settings.json;app" \
--add-data "app\\themes;app/themes" \
--add-data "scripts;scripts"
```

Notes
- Qt plugins: PyInstaller’s hooks for PySide6 are included via the spec and should bundle required Qt libraries/plugins. If you see a platform plugin error (e.g., “could not load the Qt platform plugin xcb”), add `--collect-qt-plugins=platforms,styles` to your command or ensure you build with the spec file.
- Resources: The app reads `app/settings.json`, `app/themes/*.css`, and files in `scripts/`. The spec bundles these; if you use a raw command, keep the `--add-data` flags.
- Cross-platform: Build on each target OS for a native binary (Windows on Windows, macOS on macOS, Linux on Linux).
- Console vs windowed: The spec disables the console (`console=False`). For debugging, you can toggle this or pass `--console` in a CLI build.
- Running scripts on Windows: The Advanced/Tasks tab uses `/bin/sh -c` to run shell commands, which is POSIX-only. Most core GUI features work cross‑platform, but some tasks may require adapting to `cmd.exe`/PowerShell or using WSL.

Troubleshooting
- NameError `__file__` in spec: Use the included `rocksync.spec` (it uses `cwd` instead). If you edited it, set `project_root = Path(os.getcwd()).resolve()`.
- PySide6 deploy_lib warning: `Failed to collect submodules for 'PySide6.scripts.deploy_lib' ... ModuleNotFoundError: project_lib` is a harmless warning during collection. It does not affect the build.
- One-file persistence: In `--onefile` builds, `app/settings.json` is inside the temporary unpack dir and may not persist changes across runs. Prefer the default one-folder build if you want settings to persist next to the app.

CI Builds (GitHub Actions)
- Multi‑platform builds are automated via `.github/workflows/release.yml`.
- Triggers:
  - Tag push like `v1.2.3` → builds on Windows, macOS, Linux and publishes a GitHub Release with assets.
  - Manual run via “Run workflow” (workflow_dispatch) → uploads build artifacts to the run.
- What it does:
  - Sets up Python 3.12, installs deps (PyInstaller + runtime libs), runs `pyinstaller rocksync.spec`.
  - Packages outputs as `RockSync-<tag>-<OS>.{zip|tar.gz}` and uploads to the Release.
- Notes:
  - Cross‑compile is not supported by PyInstaller; the workflow builds natively on each OS runner.
  - macOS builds are unsigned; users may need to right‑click → Open to pass Gatekeeper.
