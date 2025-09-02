import re
from pathlib import Path
from core import ROOT

THEMES_DIR = ROOT / "app" / "themes"


def list_theme_files():
    THEMES_DIR.mkdir(parents=True, exist_ok=True)
    return sorted([p.name for p in THEMES_DIR.glob("*.css")])


def parse_css_palette(path: Path) -> dict:
    """Parse a very small CSS subset: reads variables defined in :root { ... }.
    Supported lines inside the block: key: value; comments with // or /* */.
    Returns a palette dict.
    """
    txt = path.read_text(encoding="utf-8", errors="ignore")
    # Strip /* ... */ comments
    txt = re.sub(r"/\*.*?\*/", "", txt, flags=re.S)
    lines = [l.strip() for l in txt.splitlines()]
    in_root = False
    pal = {}
    for line in lines:
        if not line or line.startswith("//") or line.startswith("#"):
            continue
        if not in_root:
            if line.lower().startswith(":root") and line.endswith("{"):
                in_root = True
            continue
        else:
            if line.startswith("}"):
                break
            if ":" in line:
                key, val = line.split(":", 1)
                key = key.strip().replace("-","_")
                val = val.strip().rstrip(";")
                pal[key] = val
    return pal

