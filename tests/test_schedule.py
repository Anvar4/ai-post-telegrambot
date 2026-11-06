from collections import Counter
from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo

from app.content.schedule import ALL_CATEGORIES, DEFAULT_SLOT_TIMES, plan_day, slot_datetime
from app.pipeline.state import PostKind
from app.utils.timeutil import in_quiet_hours, shift_out_of_quiet

TZ = ZoneInfo("Asia/Tashkent")


def local(y, m, d, hh, mm) -> datetime:
    return datetime(y, m, d, hh, mm, tzinfo=TZ)


N, TOOL, SITE, TIP = PostKind.NEWS, PostKind.TOOL, PostKind.SITE, PostKind.TIP
POLL, QUIZ = PostKind.POLL, PostKind.QUIZ
# Oldingi qatʼiy jadval: 08:30 yangilik · 13:00 ilova/sayt/maslahat · 19:30 yangilik/soʻrovnoma/test
OLD_MIDDAY = [TOOL, SITE, TIP, TOOL, SITE, TOOL, TIP]
OLD_EVENING = [N, POLL, QUIZ, N, POLL, QUIZ, N]
FIVE = ["08:00", "11:00", "14:00", "17:00", "20:00"]


def week(times, cats, polls, quizzes) -> Counter:
    return Counter(k for wd in range(7) for k in plan_day(wd, times, cats, polls, quizzes))


def test_plan_day_default_matches_old_rotation() -> None:
    for wd in range(7):
        assert plan_day(wd, DEFAULT_SLOT_TIMES, ALL_CATEGORIES, 2, 2) == [N, OLD_MIDDAY[wd], OLD_EVENING[wd]]
    assert week(DEFAULT_SLOT_TIMES, ALL_CATEGORIES, 2, 2) == {
        N: 10,
        TOOL: 3,
        SITE: 2,
        TIP: 2,
        POLL: 2,
        QUIZ: 2,
    }


def test_plan_day_respects_categories_and_quotas() -> None:
    c = week(FIVE, ALL_CATEGORIES, 3, 1)
    assert (c[POLL], c[QUIZ], sum(c.values())) == (3, 1, 35)
    assert set(week(FIVE, ["ai"], 0, 0)) == {N}  # faqat yangilik turkumi
    assert set(week(DEFAULT_SLOT_TIMES, ["ilova", "maslahat"], 0, 0)) == {TOOL, TIP}  # yangiliksiz
    assert set(week(FIVE, ["kiber", "sayt"], 0, 0)) == {N, SITE}
    for wd in range(7):
        day = plan_day(wd, FIVE, ALL_CATEGORIES, 7, 7)
        assert day[0] == N  # birinchi post doim yangilik
        assert len(day) == 5
    # kuniga bitta post: soʻrovnoma kuni — soʻrovnoma, boshqa kuni — yangilik
    assert plan_day(1, ["10:00"], ALL_CATEGORIES, 2, 0) == [POLL]
    assert plan_day(0, ["10:00"], ALL_CATEGORIES, 2, 0) == [N]
    assert plan_day(3, [], ALL_CATEGORIES, 2, 2) == []


def test_plan_day_spreads_interactive_over_week() -> None:
    days = [wd for wd in range(7) if POLL in plan_day(wd, DEFAULT_SLOT_TIMES, ALL_CATEGORIES, 3, 0)]
    assert len(days) == 3
    assert week(DEFAULT_SLOT_TIMES, ALL_CATEGORIES, 7, 0)[POLL] == 7
    assert week(DEFAULT_SLOT_TIMES, ALL_CATEGORIES, 0, 0)[POLL] == 0


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
