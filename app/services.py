"""Servislarni kontekstga ulash (har bosqich o'z servislarini shu yerga qo'shadi)."""

from __future__ import annotations

from app.context import AppContext


def register_services(ctx: AppContext) -> None:
    """Barcha servislarni `ctx.services` ga joylaydi."""
    return None
