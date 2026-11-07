"""Mini ilova JSON API: analitika, postlar va navbat, sozlamalar."""

from __future__ import annotations

from collections import Counter
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from aiohttp import web

from app.analytics.reports import ReportService
from app.bot.approval_view import KIND_UZ
from app.bot.handlers.admin_content import apply_setting
from app.content.formatting import html_to_text
from app.content.schedule import CATEGORY_LABELS, MAX_SLOTS_PER_DAY, TIME_CHOICES
from app.content.templates import telegram_post_link
from app.context import AppContext
from app.db.models import Post
from app.pipeline.actions import admin_action
from app.pipeline.image import IMAGE_MODES
from app.pipeline.state import PostStatus
from app.utils.runtime import PUBLISH_MODES
from app.utils.timeutil import to_tz, utcnow

CTX_KEY = web.AppKey("ctx", AppContext)
S = PostStatus
STATUS_UZ = {
    "PENDING_APPROVAL": "Tasdiq kutmoqda",
    "SCHEDULED": "Rejada",
    "PUBLISHED": "Chiqdi",
    "FAILED": "Xato",
    "REJECTED": "Rad etilgan",
    "EXPIRED": "Eskirgan",
}
IMAGE_MODE_UZ = {
    "search_then_ask": "Internetdan qidirish (bepul). Topilmasa — AI uchun sizdan ruxsat soʻraladi",
    "none": "Rasmsiz",
}
PUBLISH_MODE_UZ = {
    "auto": "Avtomatik — postlar oʻzi chiqadi",
    "semi_auto": "Tasdiq bilan — har post sizga keladi",
    "manual": "Faqat qoʻlda — AI post tayyorlamaydi",
}


def _ctx(request: web.Request) -> AppContext:
    return request.app[CTX_KEY]


def _days(today: date, n: int) -> list[date]:
    return [today - timedelta(days=i) for i in range(n - 1, -1, -1)]


def _post_item(ctx: AppContext, post: Post, reactions: dict[int, int]) -> dict[str, Any]:
    tz = ctx.settings.tz
    when = post.published_at if post.status == S.PUBLISHED else post.scheduled_at
    extra = post.extra or {}
    link = None
    if post.message_id and post.chat_id:
        link = telegram_post_link(
            post.chat_id,
            post.message_id,
            channel_id=ctx.settings.channel_id,
            username=ctx.settings.channel_username,
        )
    return {
        "id": post.id,
        "kind": post.kind,
        "kind_uz": KIND_UZ.get(post.kind, post.kind),
        "title": post.title_short or "",
        "status": post.status,
        "status_uz": STATUS_UZ.get(post.status, post.status),
        "when": to_tz(when, tz).strftime("%d.%m %H:%M") if when else None,
        "text": html_to_text(post.text_html or "")[:1500],
        "image": bool(post.image_path and Path(post.image_path).is_file()),
        "media": (extra.get("media") or {}).get("type"),
        "reason": post.approval_reason,
        "views": extra.get("views"),
        "reactions": reactions.get(post.id, 0),  # type: ignore[arg-type]
        "comments": int(extra.get("comments", 0)),
        "link": link,
    }


async def _reactions(ctx: AppContext, posts: list[Post]) -> dict[int, int]:
    metrics = ctx.services.get("metrics")
    ids = [p.id for p in posts if p.id is not None]
    return dict(await metrics.reactions_by_post(ids)) if metrics is not None and ids else {}


# ---------------------------------------------------------------- analitika


async def overview(request: web.Request) -> web.Response:
    ctx = _ctx(request)
    days = 30 if request.query.get("days") == "30" else 7
    now = utcnow()
    tz = ctx.settings.tz
    stats = await (ctx.services.get("reports") or ReportService(ctx)).stats(days)
    sub = stats["subscribers"]
    start = now - timedelta(days=days)
    labels = _days(to_tz(now, tz).date(), days)

    events = await ctx.repo.member_events.find({"ts": {"$gte": start}})
    joins = Counter(to_tz(e.ts, tz).date() for e in events if e.event == "join")
    leaves = Counter(to_tz(e.ts, tz).date() for e in events if e.event == "leave")
    snaps = await ctx.repo.snapshots.find({"ts": {"$gte": start}}, sort=[("ts", 1)])
    per_day = {to_tz(s.ts, tz).date(): s.count for s in snaps}
    subs_series: list[int | None] = []
    last: int | None = None
    for d in labels:
        last = per_day.get(d, last)
        subs_series.append(last)

    ids = [p["id"] for p in stats["posts"]]
    posts = {p.id: p for p in await ctx.repo.posts.find({"_id": {"$in": ids}})}
    views = {pid: int((p.extra or {}).get("views") or 0) for pid, p in posts.items()}
    rows = []
    for item in stats["posts"]:
        post = posts.get(item["id"])
        rows.append(
            {
                **_post_item(ctx, post, {item["id"]: item["reactions"]}),
                "engagement": item["engagement"],
            }
            if post is not None
            else item
        )
    rows.sort(key=lambda r: (r.get("views") or 0, r.get("engagement", 0)), reverse=True)

    queue = await ctx.repo.posts.find({"status": {"$in": [S.PENDING_APPROVAL, S.SCHEDULED]}})
    return web.json_response(
        {
            "channel": ctx.settings.channel_username,
            "mode": await ctx.runtime.publish_mode(),
            "paused": await ctx.runtime.paused(),
            "live": not ctx.settings.dry_run,
            "subscribers": {
                "now": sub["end"],
                "start": sub["start"],
                "change": sub["end"] - sub["start"],
                "joins": sub["joins"],
                "leaves": sub["leaves"],
            },
            "series": {
                "days": [d.strftime("%d.%m") for d in labels],
                "joins": [joins.get(d, 0) for d in labels],
                "leaves": [leaves.get(d, 0) for d in labels],
                "subscribers": subs_series,
            },
            "totals": {
                "posts": len(stats["posts"]),
                "views": sum(views.values()),
                "reactions": sum(p["reactions"] for p in stats["posts"]),
                "comments": sum(p["comments"] for p in stats["posts"]),
            },
            "views_available": any(views.values()),
            "top_posts": rows[:5],
            "queue": {
                "pending": sum(p.status == S.PENDING_APPROVAL for p in queue),
                "scheduled": sum(p.status == S.SCHEDULED for p in queue),
            },
            "invite_links": stats["invite_links"],
            "channel_stats": await ctx.repo.get_setting("channel_stats"),
            "ai_cost_usd": stats["ai_cost_usd"],
            "spent_today": round(await ctx.repo.spent_today(), 4),
            "budget_usd": ctx.settings.daily_budget_usd,
        }
    )


# ---------------------------------------------------------------- postlar


async def posts(request: web.Request) -> web.Response:
    ctx = _ctx(request)
    tab = request.query.get("tab", "queue")
    if tab == "published":
        rows = await ctx.repo.posts.find({"status": S.PUBLISHED}, sort=[("published_at", -1)], limit=40)
    elif tab == "failed":
        rows = await ctx.repo.posts.find({"status": S.FAILED}, sort=[("_id", -1)], limit=20)
    else:
        rows = await ctx.repo.posts.find(
            {"status": {"$in": [S.PENDING_APPROVAL, S.SCHEDULED]}}, sort=[("scheduled_at", 1), ("_id", 1)]
        )
        rows.sort(key=lambda p: (p.status != S.PENDING_APPROVAL, p.scheduled_at is None))
    reactions = await _reactions(ctx, rows)
    return web.json_response({"items": [_post_item(ctx, p, reactions) for p in rows]})


async def post_action(request: web.Request) -> web.Response:
    ctx = _ctx(request)
    try:
        post_id = int(request.match_info["post_id"])
        body = await request.json()
    except (ValueError, TypeError):
        return web.json_response({"ok": False, "message": "Notoʻgʻri soʻrov"}, status=400)
    ok, message = await admin_action(ctx, post_id, str(body.get("action", "")), actor="panel")
    return web.json_response({"ok": ok, "message": message})


async def post_image(request: web.Request) -> web.StreamResponse:
    ctx = _ctx(request)
    try:
        post = await ctx.repo.posts.get(int(request.match_info["post_id"]))
    except ValueError:
        post = None
    if post is None or not post.image_path or not Path(post.image_path).is_file():  # noqa: ASYNC240
        raise web.HTTPNotFound()
    return web.FileResponse(post.image_path)


# ---------------------------------------------------------------- sozlamalar


async def _settings_payload(ctx: AppContext) -> dict[str, Any]:
    return {
        "values": await ctx.runtime.all() | {"publish_mode": await ctx.runtime.publish_mode()},
        "choices": {
            "times": list(TIME_CHOICES),
            "max_slots": MAX_SLOTS_PER_DAY,
            "categories": CATEGORY_LABELS,
            "image_modes": {k: IMAGE_MODE_UZ[k] for k in IMAGE_MODES},
            "publish_modes": {k: PUBLISH_MODE_UZ[k] for k in PUBLISH_MODES},
        },
    }


async def get_settings(request: web.Request) -> web.Response:
    return web.json_response(await _settings_payload(_ctx(request)))


async def put_setting(request: web.Request) -> web.Response:
    ctx = _ctx(request)
    try:
        body = await request.json()
        key, value = str(body["key"]), body["value"]
    except (ValueError, KeyError, TypeError):
        return web.json_response({"ok": False, "error": "Notoʻgʻri soʻrov"}, status=400)
    try:
        if key == "publish_mode":
            if value not in PUBLISH_MODES:
                raise ValueError("Rejim: " + ", ".join(PUBLISH_MODES))
            await ctx.runtime.set("publish_mode", value)
        elif key == "paused":
            await ctx.runtime.set("paused", bool(value))
        else:
            if isinstance(value, list):
                raw = ",".join(str(v) for v in value)
            elif isinstance(value, bool):
                raw = "true" if value else "false"
            else:
                raw = str(value)
            await apply_setting(ctx, key, raw)
    except ValueError as exc:
        return web.json_response({"ok": False, "error": str(exc)})
    return web.json_response({"ok": True, **await _settings_payload(ctx)})
