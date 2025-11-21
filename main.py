"""Entry point for Mafia Telegram bot."""
from __future__ import annotations

import asyncio

from telegram.ext import ApplicationBuilder

import config
import db
from engine import GameManager, register_handlers


def main() -> None:
    if config.BOT_TOKEN == "PASTE_TOKEN_HERE":
        raise SystemExit("Впиши BOT_TOKEN в config.py")
    asyncio.run(db.init_db())
    application = ApplicationBuilder().token(config.BOT_TOKEN).concurrent_updates(True).build()
    manager = GameManager(application)
    application.bot_data["manager"] = manager
    register_handlers(application, manager)
    try:
        application.run_polling(close_loop=True)
    finally:
        asyncio.run(db.close_pool())


if __name__ == "__main__":
    main()
