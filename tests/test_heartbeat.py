import time
from pathlib import Path

from app.utils.heartbeat import heartbeat_age, touch_heartbeat


def test_heartbeat_age(tmp_path: Path) -> None:
    hb = tmp_path / "sub" / "heartbeat"
    assert heartbeat_age(hb) == float("inf")
    touch_heartbeat(hb)
    assert 0 <= heartbeat_age(hb) < 5
    assert heartbeat_age(hb, now=time.time() + 700) > 600
