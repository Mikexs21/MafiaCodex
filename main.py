"""Entry point for Mafia Telegram bot."""
from __future__ import annotations

import asyncio

from telegram.ext import ApplicationBuilder

import config
import db
from engine import GameManager, register_handlers


async def _run_application() -> None:
    if config.BOT_TOKEN == "PASTE_TOKEN_HERE":
        raise SystemExit("Впиши BOT_TOKEN в config.py")

    await db.init_db()
def main() -> None:
    if config.BOT_TOKEN == "PASTE_TOKEN_HERE":
        raise SystemExit("Впиши BOT_TOKEN в config.py")
    asyncio.run(db.init_db())
    application = ApplicationBuilder().token(config.BOT_TOKEN).concurrent_updates(True).build()
    manager = GameManager(application)
    application.bot_data["manager"] = manager
    register_handlers(application, manager)

    await application.initialize()
    try:
        await application.start()
        await application.updater.start_polling()
        await application.updater.wait()
    finally:
        await application.stop()
        await application.shutdown()
        await db.close_pool()


def main() -> None:
    asyncio.run(_run_application())
    try:
        application.run_polling(close_loop=True)
    finally:
        asyncio.run(db.close_pool())


if __name__ == "__main__":
    main()
