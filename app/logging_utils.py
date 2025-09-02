import sys
import json
import io
import logging
import logging.handlers
import warnings
from pathlib import Path
from core import ROOT


def setup_logging(settings: dict, session_id: str) -> logging.Logger:
    log_level = logging.DEBUG if settings.get("debug") else logging.INFO

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)
    for h in list(root_logger.handlers):
        try:
            root_logger.removeHandler(h)
            h.close()
        except Exception:
            pass

    class SessionFilter(logging.Filter):
        def __init__(self, session):
            super().__init__()
            self.session = session
        def filter(self, record):
            record.session = self.session
            return True

    sess_filter = SessionFilter(session_id)

    console_fmt = logging.Formatter("[%(levelname)s] %(message)s")
    file_fmt = logging.Formatter("%(asctime)s [%(levelname)s] [%(name)s] %(module)s:%(lineno)d | %(message)s | session=%(session)s")

    # Console
    sh = logging.StreamHandler(sys.stdout)
    sh.setLevel(log_level)
    sh.setFormatter(console_fmt)
    sh.addFilter(sess_filter)
    root_logger.addHandler(sh)

    # latest.log
    latest_path = ROOT / "app" / "latest.log"
    latest_path.parent.mkdir(parents=True, exist_ok=True)
    lh = logging.FileHandler(latest_path, mode='w', encoding='utf-8')
    lh.setLevel(logging.DEBUG)
    lh.setFormatter(file_fmt)
    lh.addFilter(sess_filter)
    root_logger.addHandler(lh)

    # debug.log (rotating)
    debug_path = ROOT / "app" / "debug.log"
    rh = logging.handlers.RotatingFileHandler(debug_path, maxBytes=1_000_000, backupCount=5, encoding='utf-8')
    rh.setLevel(logging.DEBUG)
    rh.setFormatter(file_fmt)
    rh.addFilter(sess_filter)
    root_logger.addHandler(rh)

    # ui_state.log
    ui_path = ROOT / "app" / "ui_state.log"
    uh = logging.FileHandler(ui_path, mode='w', encoding='utf-8')
    uh.setLevel(logging.DEBUG)
    uh.setFormatter(file_fmt)
    uh.addFilter(sess_filter)
    logging.getLogger("RockSyncGUI.UI").addHandler(uh)
    logging.getLogger("RockSyncGUI.UI").setLevel(logging.DEBUG)

    # Warnings
    try:
        warnings.captureWarnings(True)
    except Exception:
        pass

    # Redirect stdout/err
    class StreamToLogger(io.TextIOBase):
        def __init__(self, logger, level):
            self.logger = logger
            self.level = level
            self._buf = ""
        def write(self, b):
            try:
                s = str(b)
            except Exception:
                s = b.decode('utf-8', errors='ignore')
            self._buf += s
            while "\n" in self._buf:
                line, self._buf = self._buf.split("\n", 1)
                if line.strip():
                    self.logger.log(self.level, line)
            return len(b) if hasattr(b, '__len__') else 0
        def flush(self):
            if self._buf.strip():
                self.logger.log(self.level, self._buf.strip())
            self._buf = ""

    try:
        sys.stdout = StreamToLogger(logging.getLogger("stdout"), logging.INFO)
        sys.stderr = StreamToLogger(logging.getLogger("stderr"), logging.ERROR)
    except Exception:
        pass

    app_logger = logging.getLogger("RockSyncGUI")
    app_logger.setLevel(log_level)
    app_logger.log(log_level, "Logger initialized | debug=%s | session=%s", settings.get("debug"), session_id)
    return app_logger


def ui_log(event: str, **data):
    try:
        payload = json.dumps(data, ensure_ascii=False, default=str)
    except Exception:
        payload = str(data)
    logging.getLogger("RockSyncGUI.UI").info(payload)

