"""Bepul rasm: Pexels / Wikimedia qidiruvi, litsenziya va sifat tekshiruvi; topilmasa admin ruxsati."""

from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

import httpx
import respx
from PIL import Image

from app.bot.keyboards import ApprovalCB
from app.bot.setup import build_dispatcher
from app.db.models import Post
from app.images.search import Candidate, ImageSearch, license_ok
from app.pipeline.compose import compose
from app.pipeline.image import ImageStage
from app.pipeline.orchestrator import Pipeline
from app.pipeline.publish import Publisher
from app.pipeline.state import PostKind, PostStatus
from tests.conftest import use_llm
from tests.fakes import FakeImage
from tests.pipeline_helpers import make_llms, seed_story
from tests.tg import callback_update, make_bot

PEXELS = "https://api.pexels.com/v1/search"
COMMONS = "https://commons.wikimedia.org/w/api.php"
UPLOAD = "https://upload.wikimedia.org/wikipedia/commons/thumb/a/ab"
TZ = ZoneInfo("Asia/Tashkent")
NOW = datetime(2026, 11, 6, 8, 0, tzinfo=TZ)
SLOT_AT = datetime(2026, 11, 6, 8, 30, tzinfo=TZ)
ADMIN = 1


def jpeg(w: int = 1600, h: int = 900) -> bytes:
    buf = BytesIO()
    Image.new("RGB", (w, h), (30, 90, 160)).save(buf, format="JPEG")
    return buf.getvalue()


def pexels_payload(*photos: tuple[int, str]) -> dict:
    return {
        "photos": [
            {
                "id": pid,
                "width": 4000,
                "height": 2600,
                "url": f"https://www.pexels.com/photo/x-{pid}/",
                "photographer": name,
                "src": {"large2x": f"https://images.pexels.com/photos/{pid}/a.jpeg?w=1880"},
            }
            for pid, name in photos
        ]
    }


def commons_payload(*files: tuple[str, str, str, int, int]) -> dict:
    pages = {}
    for i, (title, lic, mime, w, h) in enumerate(files):
        pages[str(100 + i)] = {
            "pageid": 100 + i,
            "index": i + 1,
            "title": f"File:{title}",
            "imageinfo": [
                {
                    "url": f"https://upload.wikimedia.org/wikipedia/commons/a/ab/{title}",
                    "thumburl": f"{UPLOAD}/{title}/1600px-{title}",
                    "thumbwidth": w,
                    "thumbheight": h,
                    "width": w,
                    "height": h,
                    "mime": mime,
                    "descriptionurl": f"https://commons.wikimedia.org/wiki/File:{title}",
                    "extmetadata": {
                        "LicenseShortName": {"value": lic},
                        "LicenseUrl": {"value": "https://creativecommons.org/licenses/by-sa/4.0"},
                        "Artist": {
                            "value": '<a href="//commons.wikimedia.org/wiki/User:Ali">Ali Valiyev</a>'
                        },
                    },
                }
            ],
        }
    return {"query": {"pages": pages}}


async def add_post(ctx, **kw) -> int:
    values = {
        "kind": PostKind.NEWS,
        "status": PostStatus.CHECKED,
        "text_html": "📰 <b>Matn</b>\n\nTafsilot.\n👉 @it_dunyosi",
        "title_short": "Chrome zaifligi",
        "image_prompt": "browser with a shield",
        "extra": {"image_query": "browser security"},
    }
    values.update(kw)
    post = Post(**values)
    await ctx.repo.add(post)
    return post.id


def test_license_ok() -> None:
    for ok in ("CC0", "CC0 1.0", "CC BY 4.0", "CC BY-SA 3.0", "CC BY-SA 2.5 nl", "Public domain", "PD-USGov"):
        assert license_ok(ok), ok
    for bad in (
        "CC BY-NC-SA 2.0",
        "CC BY-ND 4.0",
        "CC BY-NC 3.0",
        "GFDL",
        "",
        "All rights reserved",
        "Fair use",
    ):
        assert not license_ok(bad), bad


# ---------------------------------------------------------------- qidiruv


@respx.mock
async def test_pexels_result_used_and_credited(ctx) -> None:
    await ctx.runtime.set("image_review", False)
    search = respx.get(PEXELS).mock(return_value=httpx.Response(200, json=pexels_payload((11, "Jane Doe"))))
    respx.get("https://images.pexels.com/photos/11/a.jpeg").mock(
        return_value=httpx.Response(200, content=jpeg())
    )
    img = FakeImage()
    use_llm(ctx, image=img)
    pid = await add_post(ctx)
    async with httpx.AsyncClient() as http:
        path = await ImageStage(ctx, search=ImageSearch(http, pexels_key="pk-test")).make_for_post(pid)
    assert path is not None and Path(path).is_file()  # noqa: ASYNC240
    req = search.calls.last.request
    assert req.headers["Authorization"] == "pk-test"
    assert parse_qs(urlparse(str(req.url)).query)["query"] == ["browser security"]
    assert img.prompts == []  # pullik AI rasm chaqirilmadi
    post = await ctx.repo.get_post(pid)
    assert post.image_path == path
    assert post.extra["image_status"] == "found"
    credit = post.extra["image_credit"]
    assert "Jane Doe" in credit and "Pexels" in credit and "https://www.pexels.com/photo/x-11/" in credit
    [msg] = compose(post, Path(path).read_bytes())  # noqa: ASYNC240
    assert msg.kind == "photo"
    assert "Jane Doe" in msg.text
    assert msg.text.rstrip().endswith("👉 @it_dunyosi")  # kredit imzodan oldin


@respx.mock
async def test_wikimedia_nc_license_rejected(ctx) -> None:
    await ctx.runtime.set("image_review", False)
    respx.get(COMMONS).mock(
        return_value=httpx.Response(
            200,
            json=commons_payload(
                ("NC.jpg", "CC BY-NC-SA 2.0", "image/jpeg", 1600, 1000),
                ("Logo.svg", "CC0", "image/svg+xml", 1600, 1600),
                ("Small.jpg", "CC0", "image/jpeg", 300, 200),
                ("Good.jpg", "CC BY-SA 4.0", "image/jpeg", 1600, 1067),
            ),
        )
    )
    nc = respx.get(f"{UPLOAD}/NC.jpg/1600px-NC.jpg").mock(return_value=httpx.Response(200, content=jpeg()))
    good = respx.get(f"{UPLOAD}/Good.jpg/1600px-Good.jpg").mock(
        return_value=httpx.Response(200, content=jpeg(1600, 1067))
    )
    pid = await add_post(ctx)
    async with httpx.AsyncClient() as http:
        search = ImageSearch(http, pexels_key=None)  # Pexels kaliti yoʻq — faqat Wikimedia
        assert await ImageStage(ctx, search=search).make_for_post(pid) is not None
    assert not nc.called and good.called
    credit = (await ctx.repo.get_post(pid)).extra["image_credit"]
    assert "Ali Valiyev" in credit and "CC BY-SA 4.0" in credit and "Wikimedia Commons" in credit


@respx.mock
async def test_download_checks_host_and_quality() -> None:
    respx.get("https://upload.wikimedia.org/x/small.jpg").mock(
        return_value=httpx.Response(200, content=jpeg(400, 300))
    )
    respx.get("https://upload.wikimedia.org/x/page.jpg").mock(
        return_value=httpx.Response(200, content=b"<html>")
    )
    respx.get("https://upload.wikimedia.org/x/big.jpg").mock(return_value=httpx.Response(200, content=jpeg()))

    def cand(url: str) -> Candidate:
        return Candidate(
            "wikimedia", url, url, "Ali", "https://commons.wikimedia.org/wiki/File:x", "CC0", None
        )

    async with httpx.AsyncClient() as http:
        s = ImageSearch(http, pexels_key=None)
        assert await s.download(cand("https://evil.example/x.jpg")) is None  # begona sayt
        assert await s.download(cand("https://upload.wikimedia.org/x/small.jpg")) is None  # kichik
        assert await s.download(cand("https://upload.wikimedia.org/x/page.jpg")) is None  # rasm emas
        assert await s.download(cand("https://upload.wikimedia.org/x/big.jpg")) is not None


@respx.mock
async def test_search_errors_mean_no_image(ctx) -> None:
    respx.get(PEXELS).mock(return_value=httpx.Response(500))
    respx.get(COMMONS).mock(side_effect=httpx.ConnectTimeout("timeout"))
    pid = await add_post(ctx)
    async with httpx.AsyncClient() as http:
        assert await ImageStage(ctx, search=ImageSearch(http, pexels_key="k")).make_for_post(pid) is None
    assert (await ctx.repo.get_post(pid)).extra["image_status"] == "missing"


@respx.mock
async def test_other_image_button_picks_next_result(ctx) -> None:
    await ctx.runtime.set("image_review", False)
    respx.get(PEXELS).mock(return_value=httpx.Response(200, json=pexels_payload((11, "Jane"), (12, "John"))))
    respx.get("https://images.pexels.com/photos/11/a.jpeg").mock(
        return_value=httpx.Response(200, content=jpeg())
    )
    respx.get("https://images.pexels.com/photos/12/a.jpeg").mock(
        return_value=httpx.Response(200, content=jpeg())
    )
    pid = await add_post(ctx)
    async with httpx.AsyncClient() as http:
        stage = ImageStage(ctx, search=ImageSearch(http, pexels_key="k"))
        await stage.make_for_post(pid)
        await stage.make_for_post(pid)  # qayta yozishda rasm saqlanadi
        assert "Jane" in (await ctx.repo.get_post(pid)).extra["image_credit"]
        await stage.make_for_post(pid, fresh=True)  # "🖼 Boshqa rasm"
        assert "John" in (await ctx.repo.get_post(pid)).extra["image_credit"]
        await stage.make_for_post(pid, fresh=True)  # boshqa natija yoʻq — oldingi rasm qoladi
    post = await ctx.repo.get_post(pid)
    assert post.image_path and "John" in post.extra["image_credit"]
    assert post.extra["image_status"] == "found"


async def test_image_mode_none_skips_images(ctx) -> None:
    await ctx.runtime.set("image_mode", "none")
    img = FakeImage()
    use_llm(ctx, image=img)
    pid = await add_post(ctx)
    assert await ImageStage(ctx).make_for_post(pid) is None
    assert img.prompts == []
    assert "image_status" not in (await ctx.repo.get_post(pid)).extra


# ---------------------------------------------------------------- topilmasa — admin ruxsati


async def missing_image_post(ctx, http: httpx.AsyncClient, mode: str = "auto") -> tuple[int, FakeImage]:
    llms = make_llms(ctx)
    img = FakeImage()
    use_llm(ctx, writer=llms["writer"], editor=llms["editor"], fast=llms["fast"], image=img)
    await ctx.runtime.set("publish_mode", mode)
    await ctx.runtime.set("image_review", False)
    ctx.services["images"] = ImageStage(ctx, search=ImageSearch(http, pexels_key="pk"))
    pipeline = Pipeline(ctx, clock=lambda: NOW.astimezone(UTC))
    ctx.services["pipeline"] = pipeline
    ctx.services["publisher"] = Publisher(
        ctx.repo, ctx.sender, ctx.settings, ctx.notifier, runtime=ctx.runtime
    )
    await seed_story(ctx, now=NOW)
    pid = await pipeline.prepare_slot("08:30", SLOT_AT)
    assert pid is not None
    return pid, img


def empty_search() -> respx.Route:
    respx.get(COMMONS).mock(return_value=httpx.Response(200, json={"batchcomplete": ""}))
    return respx.get(PEXELS).mock(return_value=httpx.Response(200, json={"photos": []}))


@respx.mock
async def test_no_image_found_asks_admin_even_in_auto(ctx) -> None:
    pexels = empty_search()
    async with httpx.AsyncClient() as http:
        pid, img = await missing_image_post(ctx, http)
    assert parse_qs(urlparse(str(pexels.calls.last.request.url)).query)["query"] == ["browser security"]
    post = await ctx.repo.get_post(pid)
    assert post.status == PostStatus.PENDING_APPROVAL  # auto rejimda ham oʻzi chiqmaydi
    assert post.needs_approval and "rasm" in post.approval_reason.lower()
    assert post.image_path is None
    assert img.prompts == []  # ruxsatsiz pullik rasm yoʻq
    kb = ctx.sender.sent[-1].kwargs["reply_markup"]
    texts = [b.text for row in kb.inline_keyboard for b in row]
    assert any("AI rasm" in t for t in texts) and any("Rasmsiz" in t for t in texts)
    assert any("Rad etish" in t for t in texts)


@respx.mock
async def test_ai_image_button_generates_and_schedules(ctx) -> None:
    empty_search()
    async with httpx.AsyncClient() as http:
        pid, img = await missing_image_post(ctx, http)
        dp, bot = build_dispatcher(ctx), make_bot()
        await dp.feed_update(bot, callback_update(ApprovalCB(action="aiimg", post_id=pid).pack(), ADMIN))
    post = await ctx.repo.get_post(pid)
    assert len(img.prompts) == 1
    assert post.image_path and Path(post.image_path).is_file()  # noqa: ASYNC240
    assert post.extra["image_status"] == "ai"
    assert post.status == PostStatus.SCHEDULED  # rasmdan boshqa sabab yoʻq — auto davom etadi


@respx.mock
async def test_ai_image_in_semi_auto_returns_for_approval(ctx) -> None:
    empty_search()
    async with httpx.AsyncClient() as http:
        pid, img = await missing_image_post(ctx, http, mode="semi_auto")
        sent_before = len(ctx.sender.sent)
        dp, bot = build_dispatcher(ctx), make_bot()
        await dp.feed_update(bot, callback_update(ApprovalCB(action="aiimg", post_id=pid).pack(), ADMIN))
    post = await ctx.repo.get_post(pid)
    assert post.status == PostStatus.PENDING_APPROVAL
    assert post.image_path and len(img.prompts) == 1
    new = ctx.sender.sent[sent_before:]
    assert any(s.method == "photo" for s in new)  # yangi rasm bilan qayta koʻrsatildi
    texts = [b.text for row in new[-1].kwargs["reply_markup"].inline_keyboard for b in row]
    assert any("Chiqarish" in t for t in texts)


@respx.mock
async def test_no_image_button_schedules_text_only(ctx) -> None:
    empty_search()
    async with httpx.AsyncClient() as http:
        pid, img = await missing_image_post(ctx, http)
        dp, bot = build_dispatcher(ctx), make_bot()
        await dp.feed_update(bot, callback_update(ApprovalCB(action="noimg", post_id=pid).pack(), ADMIN))
    post = await ctx.repo.get_post(pid)
    assert post.status == PostStatus.SCHEDULED
    assert post.image_path is None and post.extra["image_status"] == "none"
    assert img.prompts == []
    before = len(ctx.sender.sent)
    post.scheduled_at = NOW.astimezone(UTC)
    await ctx.repo.posts.save(post)
    assert await ctx.services["publisher"].publish(pid)
    assert [s.method for s in ctx.sender.sent[before:]] == ["message"]


@respx.mock
async def test_ai_image_double_click_generates_once(ctx) -> None:
    empty_search()
    async with httpx.AsyncClient() as http:
        pid, img = await missing_image_post(ctx, http, mode="semi_auto")
        pipeline = ctx.services["pipeline"]
        await pipeline.use_ai_image(pid)
        again = await pipeline.use_ai_image(pid)  # ikkinchi bosish — pul ikki marta sarflanmaydi
    assert len(img.prompts) == 1
    assert "allaqachon" in again


@respx.mock
async def test_ai_image_failure_restores_choice(ctx) -> None:
    empty_search()
    async with httpx.AsyncClient() as http:
        pid, _img = await missing_image_post(ctx, http)

        async def boom(*args, **kwargs):
            raise OSError("disk full")

        ctx.services["images"].make_for_post = boom
        result = await ctx.services["pipeline"].use_ai_image(pid)
    assert "❌" in result
    post = await ctx.repo.get_post(pid)
    assert post.status == PostStatus.PENDING_APPROVAL
    assert post.extra["image_status"] == "missing"  # admin qayta urina oladi


@respx.mock
async def test_cover_render_failure_counts_as_missing(ctx, monkeypatch) -> None:
    await ctx.runtime.set("image_review", False)
    respx.get(PEXELS).mock(return_value=httpx.Response(200, json=pexels_payload((11, "Jane"))))
    respx.get("https://images.pexels.com/photos/11/a.jpeg").mock(
        return_value=httpx.Response(200, content=jpeg())
    )

    def broken(*args, **kwargs):
        raise ValueError("font yoʻq")

    monkeypatch.setattr("app.pipeline.image.render_cover", broken)
    pid = await add_post(ctx)
    async with httpx.AsyncClient() as http:
        assert await ImageStage(ctx, search=ImageSearch(http, pexels_key="k")).make_for_post(pid) is None
    assert (await ctx.repo.get_post(pid)).extra["image_status"] == "missing"  # admin soʻraladi


@respx.mock
async def test_found_photo_uses_lenient_photo_review(ctx) -> None:
    from tests.fakes import ScriptedLLM

    respx.get(PEXELS).mock(return_value=httpx.Response(200, json=pexels_payload((11, "Jane"))))
    respx.get("https://images.pexels.com/photos/11/a.jpeg").mock(
        return_value=httpx.Response(200, content=jpeg())
    )
    editor = ScriptedLLM(script=['{"ok": true, "reason": "mos"}'])
    use_llm(ctx, editor=editor)
    pid = await add_post(ctx)
    async with httpx.AsyncClient() as http:
        assert await ImageStage(ctx, search=ImageSearch(http, pexels_key="k")).make_for_post(pid) is not None
    system = editor.calls[0][0].content
    assert "fotosurat" in system  # fotolar uchun alohida prompt
    assert "logotip" not in system  # real fotodagi yozuv/logotip sabab rad etilmaydi


@respx.mock
async def test_download_retries_once_on_rate_limit() -> None:
    route = respx.get("https://upload.wikimedia.org/x/big.jpg").mock(
        side_effect=[httpx.Response(429), httpx.Response(200, content=jpeg())]
    )
    cand = Candidate(
        "wikimedia", "w:1", "https://upload.wikimedia.org/x/big.jpg", "Ali", "https://c", "CC0", None
    )

    async def no_sleep(_: float) -> None:
        return None

    async with httpx.AsyncClient() as http:
        assert await ImageSearch(http, pexels_key=None, sleep=no_sleep).download(cand) is not None
    assert route.call_count == 2
