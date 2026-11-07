"""Mini ilova serveri (aiohttp): statik sahifa + admin API (Telegram WebApp imzosi bilan)."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from aiogram import Bot
from aiogram.types import MenuButtonWebApp, WebAppInfo
from aiohttp import web
from loguru import logger

from app.config import Settings
from app.context import AppContext
from app.web import api
from app.web.auth import verify_init_data

STATIC = Path(__file__).parent / "static"
Handler = Callable[[web.Request], Awaitable[web.StreamResponse]]


def _auth_middleware(ctx: AppContext) -> Any:
    token = ctx.settings.telegram_bot_token.get_secret_value() if ctx.settings.telegram_bot_token else ""

    @web.middleware
    async def middleware(request: web.Request, handler: Handler) -> web.StreamResponse:
        if not request.path.startswith("/api/"):
            return await handler(request)
        header = request.headers.get("Authorization", "")
        user_id = verify_init_data(token, header[4:]) if header.startswith("tma ") else None
        if user_id is None:
            return web.json_response({"error": "Telegram orqali oching"}, status=401)
        if not ctx.settings.is_admin(user_id):
            logger.warning("Panelga begona foydalanuvchi kirmoqchi boʻldi: {}", user_id)
            return web.json_response({"error": "Faqat adminlar uchun"}, status=403)
        return await handler(request)

    return middleware


async def index(request: web.Request) -> web.FileResponse:
    return web.FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})


def build_web_app(ctx: AppContext) -> web.Application:
    app = web.Application(middlewares=[_auth_middleware(ctx)])
    app[api.CTX_KEY] = ctx
    app.router.add_get("/", index)
    app.router.add_static("/static", STATIC)
    app.router.add_get("/api/overview", api.overview)
    app.router.add_get("/api/posts", api.posts)
    app.router.add_post("/api/posts/{post_id}", api.post_action)
    app.router.add_get("/api/posts/{post_id}/image", api.post_image)
    app.router.add_get("/api/settings", api.get_settings)
    app.router.add_post("/api/settings", api.put_setting)
    return app


async def setup_panel_button(bot: Bot, settings: Settings) -> int:
    """Har bir admin chatida pastdagi menyu tugmasi — "📱 Panel" (faqat adminlarga koʻrinadi)."""
    url = settings.webapp_url
    if not url or not url.startswith("https://"):
        return 0
    done = 0
    for admin_id in settings.admin_ids:
        try:
            await bot.set_chat_menu_button(
                chat_id=admin_id, menu_button=MenuButtonWebApp(text="📱 Panel", web_app=WebAppInfo(url=url))
            )
            done += 1
        except Exception as exc:
            logger.warning("Panel tugmasi qoʻyilmadi ({}): {} — admin botga /start yozsin", admin_id, exc)
    return done


async def start_web(ctx: AppContext, host: str, port: int) -> web.AppRunner:
    runner = web.AppRunner(build_web_app(ctx), access_log=None)
    await runner.setup()
    await web.TCPSite(runner, host, port).start()
    logger.info("Mini ilova serveri: http://{}:{}", host, port)
    return runner
