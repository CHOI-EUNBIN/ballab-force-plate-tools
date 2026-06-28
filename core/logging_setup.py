"""Application logging — one rotating file + console, plus an uncaught-exception
hook, so calculation errors are CAPTURED even when the UI keeps running.

Why this exists: the analysis/calculation paths deliberately swallow exceptions
(``except Exception:`` → degrade gracefully so one bad step never crashes the app).
That hides the *reason* a result is missing. With logging installed, those sites
log a full traceback to a file the user can hand over for diagnosis, while the UI
still stays up. Pure / UI-free (no Qt import) so it lives in ``core``.

Log file location (so it's easy to find & share):
  Windows: %LOCALAPPDATA%\\Balancelab\\logs\\balancelab.log
  else:    ~/.balancelab/logs/balancelab.log
"""

import logging
import os
import sys
from logging.handlers import RotatingFileHandler

_configured = False


def log_dir():
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    d = os.path.join(base, "Balancelab", "logs")
    os.makedirs(d, exist_ok=True)
    return d


def log_path():
    return os.path.join(log_dir(), "balancelab.log")


def setup_logging(level=logging.INFO):
    """Configure root logging once: rotating file + console + uncaught hook.

    Returns the log file path (also printed by the caller so the user sees it)."""
    global _configured
    if _configured:
        return log_path()

    fmt = logging.Formatter(
        "%(asctime)s  %(levelname)-7s %(name)s: %(message)s", "%H:%M:%S")
    fh = RotatingFileHandler(log_path(), maxBytes=2_000_000, backupCount=3,
                             encoding="utf-8")
    fh.setFormatter(fmt)
    ch = logging.StreamHandler()
    ch.setFormatter(fmt)

    root = logging.getLogger()
    root.setLevel(level)
    root.addHandler(fh)
    root.addHandler(ch)

    def _excepthook(exc_type, exc, tb):
        logging.getLogger("uncaught").critical(
            "Uncaught exception", exc_info=(exc_type, exc, tb))
        sys.__excepthook__(exc_type, exc, tb)

    sys.excepthook = _excepthook
    logging.getLogger("balancelab").info(
        "===== session start =====  log: %s", log_path())
    _configured = True
    return log_path()
