from collections import Counter
from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo

from app.content.schedule import slot_datetime, slot_kind
from app.pipeline.state import PostKind
from app.utils.timeutil import in_quiet_hours, shift_out_of_quiet

TZ = ZoneInfo("Asia/Tashkent")


def local(y, m, d, hh, mm) -> datetime:
    return datetime(y, m, d, hh, mm, tzinfo=TZ)


def test_slot_rotation_weekly_quotas() -> None:
    midday = Counter(slot_kind("midday", wd) for wd in range(7))
    assert midday == {PostKind.TOOL: 3, PostKind.SITE: 2, PostKind.TIP: 2}
    evening = Counter(slot_kind("evening", wd) for wd in range(7))
    assert evening[PostKind.POLL] == 2
    assert evening[PostKind.QUIZ] == 2
    assert evening[PostKind.NEWS] == 3
    assert {slot_kind("morning", wd) for wd in range(7)} == {PostKind.NEWS}


def test_quiet_hours_boundaries() -> None:
    assert not in_quiet_hours(local(2026, 11, 6, 22, 59))
    assert in_quiet_hours(local(2026, 11, 6, 23, 0))
    assert in_quiet_hours(local(2026, 11, 7, 6, 59))
    assert not in_quiet_hours(local(2026, 11, 7, 7, 0))


def test_quiet_hours_shift_to_0730() -> None:
    assert shift_out_of_quiet(local(2026, 11, 6, 23, 30)) == local(2026, 11, 7, 7, 30)
    assert shift_out_of_quiet(local(2026, 11, 7, 3, 0)) == local(2026, 11, 7, 7, 30)
    noon = local(2026, 11, 7, 12, 0)
    assert shift_out_of_quiet(noon) == noon


def test_quiet_hours_with_utc_input() -> None:
    # 18:30 UTC = 23:30 Toshkent
    assert in_quiet_hours(datetime(2026, 11, 6, 18, 30, tzinfo=UTC))
    assert shift_out_of_quiet(datetime(2026, 11, 6, 18, 30, tzinfo=UTC)) == local(2026, 11, 7, 7, 30)


def test_custom_quiet_window() -> None:
    assert in_quiet_hours(local(2026, 11, 6, 22, 30), start=time(22, 0), end=time(8, 0))
    assert shift_out_of_quiet(
        local(2026, 11, 6, 22, 30), start=time(22, 0), end=time(8, 0), resume=time(8, 15)
    ) == local(2026, 11, 7, 8, 15)


def test_slot_datetime_is_tashkent() -> None:
    dt = slot_datetime(date(2026, 11, 6), "08:30")
    assert dt == local(2026, 11, 6, 8, 30)
    assert dt.astimezone(UTC).hour == 3
