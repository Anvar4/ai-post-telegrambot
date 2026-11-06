"""Docker HEALTHCHECK: heartbeat 10 daqiqadan eski bo'lsa bot jarayonini to'xtatadi (keyin restart)."""

from __future__ import annotations

import os
import signal
import sys
from pathlib import Path

from app.utils.heartbeat import heartbeat_age

MAX_AGE_SECONDS = 600


def check(data_dir: Path) -> int:
    if heartbeat_age(data_dir / "heartbeat") <= MAX_AGE_SECONDS:
        return 0
    try:
        pid = int((data_dir / "bot.pid").read_text().strip())
        os.kill(pid, getattr(signal, "SIGKILL", signal.SIGTERM))
    except (OSError, ValueError):
        pass
    return 1


if __name__ == "__main__":
    sys.exit(check(Path(os.environ.get("DATA_DIR", "data"))))
