from pathlib import Path

from PIL import Image

from app.db.models import Post
from app.pipeline.image import ImageStage
from app.pipeline.state import PostKind, PostStatus
from tests.conftest import use_llm
from tests.fakes import FakeImage, ScriptedLLM


async def add_post(ctx, kind=PostKind.NEWS) -> int:
    post = Post(
        kind=kind,
        status=PostStatus.CHECKED,
        text_html="x",
        title_short="Chrome zaifligi",
        image_prompt="browser with a shield",
    )
    await ctx.repo.add(post)
    return post.id


async def test_image_saved_and_linked_to_post(ctx) -> None:
    img = FakeImage()
    use_llm(ctx, image=img)
    await ctx.runtime.set("image_review", False)
    pid = await add_post(ctx)
    path = await ImageStage(ctx).make_for_post(pid, force_ai=True)
    assert path is not None and Path(path).is_file()  # noqa: ASYNC240
    assert Path(path).parent == Path(ctx.settings.data_path) / "images"
    assert (await ctx.repo.get_post(pid)).image_path == path
    assert "browser with a shield" in img.prompts[0]
    assert "NO text" in img.prompts[0]  # brend prompti qolipi


async def test_image_provider_failure_falls_back_to_brand(ctx) -> None:
    use_llm(ctx, image=FakeImage(fail=True))
    pid = await add_post(ctx)
    path = await ImageStage(ctx).make_for_post(pid, force_ai=True)
    assert path is not None
    assert Image.open(path).size == (1080, 1080)


async def test_no_image_provider_uses_brand_background(ctx) -> None:
    use_llm(ctx, image=None)
    pid = await add_post(ctx)
    assert await ImageStage(ctx).make_for_post(pid, force_ai=True) is not None


async def test_garbage_image_bytes_fall_back_to_brand(ctx) -> None:
    use_llm(ctx, image=FakeImage(data=b"garbage"))
    await ctx.runtime.set("image_review", False)
    pid = await add_post(ctx)
    path = await ImageStage(ctx).make_for_post(pid, force_ai=True)
    assert path is not None and Image.open(path).size == (1080, 1080)


async def test_ai_image_is_generated_once_without_extra_paid_calls(ctx) -> None:
    img = FakeImage()
    editor = ScriptedLLM(script=[])
    use_llm(ctx, image=img, editor=editor)
    pid = await add_post(ctx)
    assert await ImageStage(ctx).make_for_post(pid, force_ai=True) is not None
    assert len(img.prompts) == 1  # bitta ruxsat — bitta pullik rasm
    assert editor.calls == []  # qoʻshimcha vision tekshiruvi (pullik) yoʻq


async def test_ai_is_never_used_without_permission(ctx) -> None:
    img = FakeImage()
    use_llm(ctx, image=img)
    await ctx.runtime.set("image_mode", "ai")
    pid = await add_post(ctx)
    await ImageStage(ctx).make_for_post(pid)
    assert img.prompts == []


async def test_poll_posts_get_no_image(ctx) -> None:
    img = FakeImage()
    use_llm(ctx, image=img)
    pid = await add_post(ctx, kind=PostKind.QUIZ)
    assert await ImageStage(ctx).make_for_post(pid, force_ai=True) is None
    assert img.prompts == []
