from pathlib import Path
import shutil

# Core paths
ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"
USER_SCRIPTS_DIR = ROOT / "user_scripts"
CONFIG_PATH = ROOT / "app" / "settings.json"


def cmd_exists(cmd: str) -> bool:
    return shutil.which(cmd) is not None
