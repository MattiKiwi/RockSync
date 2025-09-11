import sys
import uuid
import logging
from pathlib import Path


def setup_cli_logging(debug: bool = False, session_id: str | None = None) -> logging.Logger:
    """Initialize logging for standalone CLI scripts.

    - Attempts to reuse the app's logging_utils.setup_logging to keep logs unified.
    - Falls back to a basic rotating file + console logger if app modules are unavailable.
    - Redirects stdout/stderr so print() also goes to logs.
    """
    session = (session_id or str(uuid.uuid4())[:8])
    root = Path(__file__).resolve().parents[1]
    app_dir = root / 'app'
    sys.path.insert(0, str(app_dir))

    try:
        # Use the app's logging configuration for consistency
        from logging_utils import setup_logging as _setup
        settings = {'debug': bool(debug)}
        return _setup(settings, session)
    except Exception:
        pass

    # Fallback: minimal consistent logging
    logger = logging.getLogger('RockSyncCLI')
    logger.setLevel(logging.DEBUG if debug else logging.INFO)
    for h in list(logging.getLogger().handlers):
        try:
            logging.getLogger().removeHandler(h)
            h.close()
        except Exception:
            pass
    fmt_console = logging.Formatter('[%(levelname)s] %(message)s')
    fmt_file = logging.Formatter('%(asctime)s [%(levelname)s] [%(name)s] %(module)s:%(lineno)d | %(message)s | session=%(session)s')

    class SessionFilter(logging.Filter):
        def __init__(self, sess):
            super().__init__()
            self._s = sess
        def filter(self, record):
            record.session = self._s
            return True

    filt = SessionFilter(session)

    # Console
    ch = logging.StreamHandler(getattr(sys, '__stdout__', sys.stdout))
    ch.setLevel(logging.DEBUG if debug else logging.INFO)
    ch.setFormatter(fmt_console)
    ch.addFilter(filt)
    logging.getLogger().addHandler(ch)

    # File logs under dedicated logs directory
    log_dir = root / 'logs'
    log_dir.mkdir(parents=True, exist_ok=True)
    fh = logging.FileHandler(log_dir / 'latest.log', mode='w', encoding='utf-8')
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt_file)
    fh.addFilter(filt)
    logging.getLogger().addHandler(fh)
    try:
        import logging.handlers
        rh = logging.handlers.RotatingFileHandler(log_dir / 'debug.log', maxBytes=1_000_000, backupCount=5, encoding='utf-8')
        rh.setLevel(logging.DEBUG)
        rh.setFormatter(fmt_file)
        rh.addFilter(filt)
        logging.getLogger().addHandler(rh)
    except Exception:
        pass

    # Redirect stdout/err to logger
    class _StreamToLogger:
        def __init__(self, logger, level):
            self._logger = logger
            self._level = level
            self._buf = ''
        def write(self, b):
            s = str(b)
            self._buf += s
            while '\n' in self._buf:
                line, self._buf = self._buf.split('\n', 1)
                if line.strip():
                    self._logger.log(self._level, line)
            return len(b) if hasattr(b, '__len__') else 0
        def flush(self):
            if self._buf.strip():
                self._logger.log(self._level, self._buf.strip())
            self._buf = ''

    try:
        sys.stdout = _StreamToLogger(logging.getLogger('stdout'), logging.INFO)
        sys.stderr = _StreamToLogger(logging.getLogger('stderr'), logging.ERROR)
    except Exception:
        pass

    logger.log(logging.DEBUG if debug else logging.INFO, 'CLI logger initialized | debug=%s | session=%s', bool(debug), session)
    return logger
