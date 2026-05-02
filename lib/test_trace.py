"""Per-test trace logging utilities for developer diagnostics.

Writes one trace file per pytest testcase under:
  <results_dir>/test_logs/<sanitized-nodeid>.log
"""
import os
import re
import threading
from datetime import datetime

_LOCK = threading.Lock()
_CURRENT_LOG = None


def _sanitize_nodeid(nodeid):
    name = re.sub(r"[^A-Za-z0-9_.-]+", "_", nodeid)
    return name.strip("_")[:220] or "unknown_test"


def set_current_test(nodeid, results_dir):
    """Set active testcase trace file path."""
    global _CURRENT_LOG
    log_dir = os.path.join(results_dir, "test_logs")
    os.makedirs(log_dir, exist_ok=True)
    fname = _sanitize_nodeid(nodeid) + ".log"
    with _LOCK:
        _CURRENT_LOG = os.path.join(log_dir, fname)
        # Start each testcase log fresh so HTML/trace viewers show only the
        # latest run's events for this nodeid.
        with open(_CURRENT_LOG, "w", encoding="utf-8") as f:
            f.write(f"\n=== TEST START {nodeid} @ {datetime.now().isoformat()} ===\n")


def clear_current_test(nodeid=None):
    """Clear active testcase trace file path."""
    global _CURRENT_LOG
    with _LOCK:
        if _CURRENT_LOG:
            with open(_CURRENT_LOG, "a", encoding="utf-8") as f:
                suffix = f" {nodeid}" if nodeid else ""
                f.write(f"=== TEST END{suffix} @ {datetime.now().isoformat()} ===\n")
        _CURRENT_LOG = None


def log_event(source, message):
    """Append an event line to the active testcase trace file."""
    ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    line = f"[{ts}] [{source}] {message}\n"
    with _LOCK:
        if not _CURRENT_LOG:
            return
        with open(_CURRENT_LOG, "a", encoding="utf-8") as f:
            f.write(line)
