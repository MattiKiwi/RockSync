# PyInstaller spec for RockSync (PySide6)
# Build with:  pyinstaller rocksync.spec

import os
from pathlib import Path

block_cipher = None


# Collect PySide6 datas/binaries/hiddenimports (Qt plugins, etc.)
hiddenimports, datas, binaries = [], [], []


project_root = Path(os.getcwd()).resolve()


def collect_dir_files(src_dir: Path, dest_prefix: str):
    pairs = []
    src_dir = Path(src_dir)
    if not src_dir.exists():
        return pairs
    for root, _dirs, files in os.walk(src_dir):
        for fname in files:
            full = Path(root) / fname
            rel = full.relative_to(src_dir)
            dest_dir = str(Path(dest_prefix) / rel.parent).replace('\\', '/')
            pairs.append((str(full), dest_dir))
    return pairs

# Recursively include themes and scripts as (file, destdir) pairs
datas += collect_dir_files(project_root / 'app' / 'themes', 'app/themes')
datas += collect_dir_files(project_root / 'scripts', 'scripts')


a = Analysis(
    ['app/main.py'],
    pathex=[str(project_root)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],                 # no binaries embedded here
    [],                 # no zipfiles embedded here
    [],                 # no datas embedded here
    exclude_binaries=True,
    name='RockSync',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,  # windowed app
    disable_windowed_traceback=True,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='RockSync'
)
