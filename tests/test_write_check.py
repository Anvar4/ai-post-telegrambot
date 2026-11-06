import json

import httpx
import respx

from app.pipeline.check import Checker, detect_uz_breach
from app.pipeline.state import PostKind
from app.pipeline.write import Writer, draft_with_checks
from tests.conftest import use_llm
from tests.fakes import ScriptedLLM

SRC_URL = "https://www.bleepingcomputer.com/news/security/chrome-zero-day/"
ALLOWED = {"bleepingcomputer.com"}
BODY = "Google Chrome brauzerida faol foydalanilayotgan zaiflik topildi va yangilanish chiqdi. " * 6


def draft(text: str = "", *, link: str | None = SRC_URL, title: str = "Chrome zaifligi") -> str:
    html = f"🔴 <b>OGOHLANTIRISH: {title}</b>\n\n{text or BODY}"
    if link:
        html += f'\n\n🔗 <a href="{link}">Manba: BleepingComputer</a>'
    html += "\n#kiberxavfsizlik #ogohlantirish"
    return html


def writer_json(html: str, title: str = "Chrome zaifligi") -> str:
    return json.dumps(
        {
            "title_short": title,
            "text_html": html,
            "hashtags": ["#kiberxavfsizlik"],
            "image_prompt_en": "browser shield",
        }
    )


def check_json(verdict: str, issues: list | None = None) -> str:
    return json.dumps({"verdict": verdict, "issues": issues or []})


async def test_writer_normalizes_uz_and_adds_footer(ctx) -> None:
    w = ScriptedLLM(
        provider="anthropic",
        model="claude-x",
        script=[writer_json(draft("o'zbek foydalanuvchilari uchun g'oyat muhim. " * 12))],
    )
    use_llm(ctx, writer=w)
    res = await Writer(ctx).write(
        PostKind.ALERT, source_text="src", story_title="Chrome", source_urls=[SRC_URL]
    )
    assert "oʻzbek" in res.output.text_html and "gʻoyat" in res.output.text_html
    assert res.output.text_html.rstrip().endswith("👉 @it_dunyosi")
    assert "<source>" in w.calls[0][-1].content
    assert "@it_dunyosi" in w.calls[0][0].content  # shablonda kanal nomi


async def test_writer_truncates_title_short(ctx) -> None:
    w = ScriptedLLM(script=[writer_json(draft(), title="A" * 80)])
    use_llm(ctx, writer=w)
    res = await Writer(ctx).write(PostKind.NEWS, source_text="s", story_title="t", source_urls=[SRC_URL])
    assert len(res.output.title_short) <= 60


async def test_invented_url_rejected_without_model_call(ctx) -> None:
    editor = ScriptedLLM(script=[])
    use_llm(ctx, editor=editor)
    report = await Checker(ctx).check(
        draft(link="https://totally-made-up.example/x"),
        source_text="s",
        kind=PostKind.ALERT,
        allowed=ALLOWED,
        has_image=True,
    )
    assert report.verdict == "reject"
    assert any(i["type"] == "fabricated" for i in report.code_issues)
    assert editor.calls == []


async def test_missing_source_link_is_issue_for_news(ctx) -> None:
    use_llm(ctx, editor=ScriptedLLM(script=[check_json("pass")]))
    report = await Checker(ctx).check(
        draft(link=None), source_text="s", kind=PostKind.NEWS, allowed=ALLOWED, has_image=False
    )
    assert report.verdict == "fix"
    assert any(i["type"] == "missing_source" for i in report.code_issues)


async def test_tip_without_link_passes(ctx) -> None:
    use_llm(ctx, editor=ScriptedLLM(script=[check_json("pass")]))
    report = await Checker(ctx).check(
        draft(link=None), source_text="", kind=PostKind.TIP, allowed=set(), has_image=False
    )
    assert report.verdict == "pass"
    assert report.needs_approval is False


async def test_too_short_post_is_length_issue(ctx) -> None:
    use_llm(ctx, editor=ScriptedLLM(script=[check_json("pass")]))
    report = await Checker(ctx).check(
        draft("Qisqa."), source_text="s", kind=PostKind.NEWS, allowed=ALLOWED, has_image=False
    )
    assert report.verdict == "fix"
    assert any(i["type"] == "length" for i in report.code_issues)


async def test_degraded_checker_forces_approval(ctx) -> None:
    writer = ScriptedLLM(provider="anthropic", model="claude-x", script=[check_json("pass")])
    use_llm(ctx, writer=writer, editor=None)
    report = await Checker(ctx).check(
        draft(), source_text="s", kind=PostKind.ALERT, allowed=ALLOWED, has_image=True
    )
    assert report.verdict == "pass"
    assert report.degraded is True
    assert report.needs_approval is True


async def test_uz_org_breach_forces_approval(ctx) -> None:
    use_llm(ctx, editor=ScriptedLLM(script=[check_json("pass")]))
    text = "Oʻzbekistondagi yirik bank xakerlar tomonidan buzildi, mijozlar maʼlumotlari sizib chiqdi. " * 6
    report = await Checker(ctx).check(
        draft(text), source_text="s", kind=PostKind.ALERT, allowed=ALLOWED, has_image=True
    )
    assert report.needs_approval is True
    assert "Oʻzbekiston" in (report.approval_reason or "")


def test_detect_uz_breach_cases() -> None:
    assert detect_uz_breach("Toshkentdagi vazirlik sayti xakerlar hujumiga uchradi va buzildi")
    assert detect_uz_breach("Uzbekistan telecom operator data leak")
    assert not detect_uz_breach("Google Chrome uchun yangilanish chiqdi")
    assert not detect_uz_breach("Oʻzbekistonda yangi IT park ochildi")


@respx.mock
async def test_dead_link_is_fix_issue(ctx) -> None:
    respx.head(SRC_URL).mock(return_value=httpx.Response(404))
    respx.get(SRC_URL).mock(return_value=httpx.Response(404))
    use_llm(ctx, editor=ScriptedLLM(script=[check_json("pass")]))
    async with httpx.AsyncClient(follow_redirects=True) as http:
        ctx.http = http
        report = await Checker(ctx).check(
            draft(), source_text="s", kind=PostKind.ALERT, allowed=ALLOWED, has_image=True
        )
    assert report.verdict == "fix"
    assert any(i["type"] == "missing_source" and "ishlamayapti" in i["fix"] for i in report.code_issues)


async def test_fix_loop_max_two_then_approval(ctx) -> None:
    writer = ScriptedLLM(provider="anthropic", model="claude-x", script=[writer_json(draft())] * 3)
    issue = [{"type": "wrong_number", "quote": "x", "fix": "raqamni tuzat"}]
    editor = ScriptedLLM(script=[check_json("fix", issue)] * 3)
    use_llm(ctx, writer=writer, editor=editor)
    res = await draft_with_checks(
        Writer(ctx),
        Checker(ctx),
        PostKind.ALERT,
        source_text="s",
        story_title="t",
        source_urls=[SRC_URL],
        has_image=True,
    )
    assert res.rounds == 2
    assert len(writer.calls) == 3
    assert res.report.needs_approval is True
    # ikkinchi yozishda muharrir izohlari yozuvchiga berilgan
    assert "raqamni tuzat" in writer.calls[1][-1].content
    assert "<draft>" in writer.calls[1][-1].content


async def test_fix_then_pass(ctx) -> None:
    writer = ScriptedLLM(script=[writer_json(draft()), writer_json(draft())])
    editor = ScriptedLLM(
        script=[check_json("fix", [{"type": "tone", "quote": "x", "fix": "y"}]), check_json("pass")]
    )
    use_llm(ctx, writer=writer, editor=editor)
    res = await draft_with_checks(
        Writer(ctx),
        Checker(ctx),
        PostKind.ALERT,
        source_text="s",
        story_title="t",
        source_urls=[SRC_URL],
        has_image=True,
    )
    assert res.rounds == 1
    assert res.report.verdict == "pass"
    assert res.report.needs_approval is False


async def test_reject_verdict_returned(ctx) -> None:
    writer = ScriptedLLM(script=[writer_json(draft())])
    editor = ScriptedLLM(script=[check_json("reject", [{"type": "fabricated", "quote": "x", "fix": ""}])])
    use_llm(ctx, writer=writer, editor=editor)
    res = await draft_with_checks(
        Writer(ctx),
        Checker(ctx),
        PostKind.ALERT,
        source_text="s",
        story_title="t",
        source_urls=[SRC_URL],
        has_image=True,
    )
    assert res.report.verdict == "reject"
    assert len(writer.calls) == 1
