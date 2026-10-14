import logging
import os
from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from .config import Settings
from .handlers import router
from . import handlers

async def health(request: web.Request):
    return web.json_response({"status": "ok", "service": "avyx-vs"})

async def run_health_server():
    app = web.Application()
    app.router.add_get("/", health)
    app.router.add_get("/health", health)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.getenv("PORT", "10000"))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    logging.info("Health server listening on port %s", port)
    return runner

async def main():
    logging.basicConfig(level=logging.INFO)
    settings = Settings.from_env()
    handlers.settings = settings

    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()
    dp.include_router(router)

    runner = await run_health_server()
    logging.info("AVYX VS is starting...")
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    finally:
        await runner.cleanup()
        await bot.session.close()
