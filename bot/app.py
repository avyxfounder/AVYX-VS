import logging
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from .config import Settings
from .handlers import router
from . import handlers

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

    logging.info("AVYX VS is starting...")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)
