"""Entry point for Mafia Telegram bot."""
from __future__ import annotations

import asyncio

from telegram.ext import ApplicationBuilder

import config
import db
from engine import GameManager, register_handlers


def main() -> None:
    """Start bot with safe loop ownership.

    Telegram's :meth:`Application.run_polling` manages its own event loop via
    ``run_until_complete``. Wrapping it in :func:`asyncio.run` causes the
    "event loop is already running" error on Windows and inside notebooks. To
    keep initialization async-friendly we run DB routines in their own helper
    loops before/after polling and let PTB own the main loop lifecycle.
    """

    if config.BOT_TOKEN == "PASTE_TOKEN_HERE":
        raise SystemExit("Впиши BOT_TOKEN в config.py")

    asyncio.run(db.init_db())

    application = (
        ApplicationBuilder()
        .token(config.BOT_TOKEN)
        .concurrent_updates(True)
        .build()
    )
    manager = GameManager(application)
    application.bot_data["manager"] = manager
    register_handlers(application, manager)

    try:
        application.run_polling(close_loop=True)
    finally:
        asyncio.run(db.close_pool())


if __name__ == "__main__":
    main()
async def main() -> None:
    if config.BOT_TOKEN == "PASTE_TOKEN_HERE":
        raise SystemExit("Впиши BOT_TOKEN в config.py")
    await db.init_db()
    application = ApplicationBuilder().token(config.BOT_TOKEN).concurrent_updates(True).build()
    manager = GameManager(application)
    application.bot_data["manager"] = manager
    register_handlers(application, manager)
    try:
        await application.run_polling(close_loop=False)
    finally:
        await db.close_pool()
    await application.initialize()
    await application.start()
    await application.updater.start_polling()
    await application.updater.idle()
    await application.stop()
    await db.close_pool()


if __name__ == "__main__":
    asyncio.run(main())
