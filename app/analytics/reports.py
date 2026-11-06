"""Hisobotlar: statistika JSON, kunlik (21:30), haftalik (dushanba 09:00), eng yaxshi vaqtlar."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from sqlalchemy import func, select

from app.bot.approval_view import KIND_UZ
from app.content.formatting import escape
from app.db.models import LLMUsage, MemberEvent, Poll, Post, SubscriberSnapshot
from app.pipeline.state import PostStatus
from app.utils.timeutil import day_bounds, to_tz, utcnow

if TYPE_CHECKING:
    from app.context import AppContext

BEST_TIMES_MIN_DAYS = 14


class ReportService:
    def __init__(self, ctx: AppContext, *, clock: Callable[[], datetime] = utcnow) -> None:
        self.ctx = ctx
        self.clock = clock

    async def _posts(self, start: datetime, end: datetime) -> list[dict[str, Any]]:
        async with self.ctx.repo.session() as s:
            posts = (
                (
                    await s.execute(
                        select(Post)
                        .where(
                            Post.status == PostStatus.PUBLISHED,
                            Post.published_at >= start,
                            Post.published_at < end,
                        )
                        .order_by(Post.published_at)
                    )
                )
                .scalars()
                .all()
            )
            votes = dict((await s.execute(select(Poll.post_id, Poll.total_voters))).all())
        metrics = self.ctx.services.get("metrics")
        ids = [p.id for p in posts]
        reactions = await metrics.reactions_by_post(ids) if metrics else {}
        engagement = await metrics.engagement_by_post(ids) if metrics else {}
        out = []
        for p in posts:
            local = to_tz(p.published_at, self.ctx.settings.tz) if p.published_at else None
            out.append(
                {
                    "id": p.id,
                    "kind": p.kind,
                    "title": p.title_short or "",
                    "slot": (p.slot or "").split(":")[-1],
                    "published": local.strftime("%Y-%m-%d %H:%M") if local else None,
                    "hour": local.hour if local else None,
                    "weekday": local.weekday() if local else None,
                    "reactions": reactions.get(p.id, 0),
                    "comments": int((p.extra or {}).get("comments", 0)),
                    "poll_votes": int(votes.get(p.id) or 0),
                    "engagement": engagement.get(p.id, 0.0),
                }
            )
        return out

    async def stats(self, days: int = 7) -> dict[str, Any]:
        now = self.clock()
        start = now - timedelta(days=days)
        async with self.ctx.repo.session() as s:
            snaps = (
                (
                    await s.execute(
                        select(SubscriberSnapshot)
                        .where(SubscriberSnapshot.ts >= start)
                        .order_by(SubscriberSnapshot.ts)
                    )
                )
                .scalars()
                .all()
            )
            last = await s.scalar(
                select(SubscriberSnapshot.count).order_by(SubscriberSnapshot.id.desc()).limit(1)
            )
            events = dict(
                (
                    await s.execute(
                        select(MemberEvent.event, func.count())
                        .where(MemberEvent.ts >= start)
                        .group_by(MemberEvent.event)
                    )
                ).all()
            )
            cost = await s.scalar(
                select(func.coalesce(func.sum(LLMUsage.cost_usd), 0.0)).where(LLMUsage.ts >= start)
            )
            polls = (
                (await s.execute(select(Poll).where(Poll.created_at >= start, Poll.total_voters > 0)))
                .scalars()
                .all()
            )
        invites = self.ctx.services.get("invites")
        return {
            "period_days": days,
            "subscribers": {
                "start": snaps[0].count if snaps else (last or 0),
                "end": int(last or 0),
                "joins": int(events.get("join", 0)),
                "leaves": int(events.get("leave", 0)),
            },
            "posts": await self._posts(start, now),
            "invite_links": await invites.stats() if invites else [],
            "polls": [
                {"question": p.question, "results": p.results, "voters": p.total_voters, "purpose": p.purpose}
                for p in polls
            ],
            "ai_cost_usd": round(float(cost or 0.0), 4),
        }

    def stats_text(self, stats: dict[str, Any]) -> str:
        sub = stats["subscribers"]
        posts = stats["posts"]
        lines = [
            f"📈 <b>Statistika — oxirgi {stats['period_days']} kun</b>",
            f"Obunachilar: {sub['end']} (davr boshida {sub['start']}, {sub['end'] - sub['start']:+d}) · "
            f"qoʻshildi {sub['joins']}, chiqdi {sub['leaves']}",
            f"Postlar: {len(posts)}",
        ]
        if posts:
            avg = sum(p["engagement"] for p in posts) / len(posts)
            best = max(posts, key=lambda p: p["engagement"])
            worst = min(posts, key=lambda p: p["engagement"])
            lines.append(f"Oʻrtacha faollik balli: {avg:.1f}")
            lines.append(f"🏆 Eng yaxshi: {escape(best['title'][:60])} ({best['engagement']})")
            lines.append(f"🐢 Eng zaif: {escape(worst['title'][:60])} ({worst['engagement']})")
        for link in stats["invite_links"]:
            lines.append(
                f"🔗 {escape(link['name'])}: +{link['joins']} / −{link['leaves']}, "
                f"7 kundan keyin qolgan: {link['retained_7d']}/{link['mature_joins']}"
            )
        lines.append(f"AI xarajati: ${stats['ai_cost_usd']:.2f}")
        return "\n".join(lines)

    async def daily(self, now: datetime | None = None) -> str:
        now = now or self.clock()
        start, end = day_bounds(now, self.ctx.settings.tz)
        posts = await self._posts(start, end)
        async with self.ctx.repo.session() as s:
            events = dict(
                (
                    await s.execute(
                        select(MemberEvent.event, func.count())
                        .where(MemberEvent.ts >= start, MemberEvent.ts < end)
                        .group_by(MemberEvent.event)
                    )
                ).all()
            )
            subs = await s.scalar(
                select(SubscriberSnapshot.count).order_by(SubscriberSnapshot.id.desc()).limit(1)
            )
        spent = await self.ctx.repo.spent_today(now)
        errors = await self.ctx.repo.count_errors(start)
        local = to_tz(now, self.ctx.settings.tz)
        lines = [f"📊 <b>Kunlik hisobot — {local:%d.%m.%Y}</b>", f"Chiqqan postlar: {len(posts)}"]
        for p in posts:
            lines.append(
                f" • [{KIND_UZ.get(p['kind'], p['kind'])}] {escape(p['title'][:60])} — "
                f"👍 {p['reactions']} · 💬 {p['comments']}"
            )
        lines.append(f"Reaksiyalar jami: {sum(p['reactions'] for p in posts)}")
        lines.append(
            f"Obunachilar: {subs if subs is not None else '—'} "
            f"(bugun +{events.get('join', 0)} / −{events.get('leave', 0)})"
        )
        lines.append(f"AI xarajati: ${spent:.2f} / ${self.ctx.settings.daily_budget_usd:.2f}")
        lines.append(f"Xatolar: {errors}" + (" — /logs" if errors else ""))
        moderation = self.ctx.services.get("moderation")
        if moderation is not None:
            lines.append(await moderation.daily_summary(now))
        return "\n".join(lines)

    async def best_times(self, days: int = 28) -> str | None:
        stats = await self.stats(days)
        posts = [p for p in stats["posts"] if p["hour"] is not None]
        if not posts:
            return None
        first = min(datetime.fromisoformat(p["published"]) for p in posts)
        last = max(datetime.fromisoformat(p["published"]) for p in posts)
        if (last - first).days < BEST_TIMES_MIN_DAYS:
            return None
        by_hour: dict[int, list[float]] = defaultdict(list)
        for p in posts:
            by_hour[p["hour"]].append(p["engagement"])
        ranked = sorted(by_hour.items(), key=lambda kv: -sum(kv[1]) / len(kv[1]))[:3]
        parts = [f"{h:02d}:00 (oʻrtacha {sum(v) / len(v):.1f}, {len(v)} post)" for h, v in ranked]
        return (
            "🕒 Eng faol vaqtlar (≥2 hafta maʼlumot): "
            + ", ".join(parts)
            + "\nJadvalni oʻzgartirish faqat sizning tasdigʻingiz bilan: /set slots.evening HH:MM"
        )

    async def send_daily(self) -> None:
        await self.ctx.notifier.notify(await self.daily(), html=True)

    async def send_weekly(self) -> None:
        growth = self.ctx.services.get("growth")
        body = await growth.growth_report(7) if growth else self.stats_text(await self.stats(7))
        text = "📈 <b>Haftalik oʻsish hisoboti</b>\n\n" + body
        best = await self.best_times()
        if best:
            text += "\n\n" + best
        await self.ctx.notifier.notify(text, html=True)
