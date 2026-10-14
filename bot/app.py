import asyncio
import logging
import os
from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from .config import Settings
from .handlers import router
from . import handlers
from .access import AccessManager
from .content import BotContent
from .usage import UsageManager
from .billing import BillingManager
from .publications import PublicationManager
from .support import SupportManager
from .utils import cleanup_stale_jobs

async def health(request: web.Request):
    return web.json_response({"status": "ok", "service": "avyx-vs"})

async def run_health_server():
    app = web.Application()
    app.router.add_get("/", health)
    app.router.add_get("/health", health)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", int(os.getenv("PORT", "10000")))
    await site.start()
    return runner

async def main():
    logging.basicConfig(level=logging.INFO)
    settings = Settings.from_env()
    handlers.settings = settings
    handlers.access = AccessManager(settings.access_db, settings.owner_id)
    handlers.content = BotContent(settings.content_db)
    handlers.usage = UsageManager(settings.usage_db)
    handlers.billing = BillingManager(settings.billing_db)
    handlers.publications = PublicationManager(settings.publication_db)
if not publications.data.get("internal_pin"):
    publications.set_internal_pin("bot_info", 0)
    handlers.support = SupportManager(settings.support_db)
    cleanup_stale_jobs(settings.temp_dir)

    bot = Bot(token=settings.bot_token, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    dp.include_router(router)
    runner = await run_health_server()
    cleanup_task = asyncio.create_task(handlers.publications.cleanup_loop(bot))
    logging.info("AVYX VS is starting...")
    try:
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot)
    finally:
        cleanup_task.cancel()
        await runner.cleanup()
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())
