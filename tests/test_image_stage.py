import json
from io import BytesIO
from pathlib import Path

from PIL import Image

from app.db.models import Post
from app.pipeline.image import ImageStage
from app.pipeline.state import PostKind, PostStatus
from tests.conftest import use_llm
from tests.fakes import FakeImage, ScriptedLLM


async def add_post(ctx, kind=PostKind.NEWS) -> int:
    async with ctx.repo.session() as s:
        post = Post(
            kind=kind,
            status=PostStatus.CHECKED,
            text_html="x",
            title_short="Chrome zaifligi",
            image_prompt="browser with a shield",
        )
        s.add(post)
        await s.commit()
        return post.id


async def test_image_saved_and_linked_to_post(ctx) -> None:
    img = FakeImage()
    use_llm(ctx, image=img)
    await ctx.runtime.set("image_review", False)
    pid = await add_post(ctx)
    path = await ImageStage(ctx).make_for_post(pid)
    assert path is not None and Path(path).is_file()  # noqa: ASYNC240
    assert Path(path).parent == Path(ctx.settings.data_path) / "images"
    assert (await ctx.repo.get_post(pid)).image_path == path
    assert "browser with a shield" in img.prompts[0]
    assert "NO text" in img.prompts[0]  # brend prompti qolipi


async def test_image_provider_failure_falls_back_to_brand(ctx) -> None:
    use_llm(ctx, image=FakeImage(fail=True))
    pid = await add_post(ctx)
    path = await ImageStage(ctx).make_for_post(pid)
    assert path is not None
    assert Image.open(path).size == (1080, 1080)


async def test_no_image_provider_uses_brand_background(ctx) -> None:
    use_llm(ctx, image=None)
    pid = await add_post(ctx)
    assert await ImageStage(ctx).make_for_post(pid) is not None


async def test_garbage_image_bytes_fall_back_to_brand(ctx) -> None:
    use_llm(ctx, image=FakeImage(data=b"garbage"))
    await ctx.runtime.set("image_review", False)
    pid = await add_post(ctx)
    path = await ImageStage(ctx).make_for_post(pid)
    assert path is not None and Image.open(path).size == (1080, 1080)


async def test_vision_reject_triggers_one_regeneration(ctx) -> None:
    img = FakeImage()
    editor = ScriptedLLM(script=[json.dumps({"ok": False, "reason": "matn bor"})])
    use_llm(ctx, image=img, editor=editor)
    pid = await add_post(ctx)
    assert await ImageStage(ctx).make_for_post(pid) is not None
    assert len(img.prompts) == 2
    assert len(editor.calls) == 1
    assert editor.calls[0][-1].images  # rasm modelga berilgan


async def test_vision_ok_single_generation(ctx) -> None:
    img = FakeImage()
    editor = ScriptedLLM(script=[json.dumps({"ok": True, "reason": ""})])
    use_llm(ctx, image=img, editor=editor)
    pid = await add_post(ctx)
    await ImageStage(ctx).make_for_post(pid)
    assert len(img.prompts) == 1


async def test_review_disabled_no_editor_call(ctx) -> None:
    img = FakeImage()
    editor = ScriptedLLM(script=[])
    use_llm(ctx, image=img, editor=editor)
    await ctx.runtime.set("image_review", False)
    await ImageStage(ctx).make_for_post(await add_post(ctx))
    assert editor.calls == []


async def test_poll_posts_get_no_image(ctx) -> None:
    img = FakeImage()
    use_llm(ctx, image=img)
    pid = await add_post(ctx, kind=PostKind.QUIZ)
    assert await ImageStage(ctx).make_for_post(pid) is None
    assert img.prompts == []


async def test_review_image_is_downscaled(ctx) -> None:
    big = BytesIO()
    Image.new("RGB", (2048, 2048), (10, 20, 30)).save(big, format="PNG")
    img = FakeImage(data=big.getvalue())
    editor = ScriptedLLM(script=[json.dumps({"ok": True})])
    use_llm(ctx, image=img, editor=editor)
    await ImageStage(ctx).make_for_post(await add_post(ctx))
    sent = Image.open(BytesIO(editor.calls[0][-1].images[0]))
    assert max(sent.size) <= 768
