from app.utils.runtime import Runtime


async def test_runtime_defaults_from_env(ctx) -> None:
    rt = Runtime(ctx.repo, ctx.settings)
    assert await rt.publish_mode() == "semi_auto"
    assert await rt.paused() is False
    assert await rt.get("slot_times") == ["08:30", "13:00", "19:30"]
    assert await rt.get("polls_per_week") == 2
    assert "kiber" in await rt.get("categories")


async def test_runtime_override_persists(ctx) -> None:
    rt = Runtime(ctx.repo, ctx.settings)
    await rt.set("publish_mode", "auto")
    await rt.set("slot_times", ["09:00"])
    rt2 = Runtime(ctx.repo, ctx.settings)
    assert await rt2.publish_mode() == "auto"
    assert await rt2.get("slot_times") == ["09:00"]


async def test_runtime_rejects_unknown_key(ctx) -> None:
    rt = Runtime(ctx.repo, ctx.settings)
    try:
        await rt.set("nope", 1)
    except KeyError:
        return
    raise AssertionError("KeyError kutilgan")
