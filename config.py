"""Configuration for Mafia Telegram bot."""
from __future__ import annotations

BOT_TOKEN: str = "PASTE_TOKEN_HERE"

SQLITE_DB_PATH = "mafia.sqlite"
SQLITE_ISOLATION_LEVEL = None

NIGHT_DURATION: int = 60
DAY_DURATION: int = 60
VOTE_DURATION: int = 30
COUNTDOWN_STEP: int = 5

MIN_PLAYERS: int = 5
MAX_PLAYERS: int = 10
MAX_BOTS: int = 6

POINTS_WIN: int = 50
POINTS_LOSE: int = 10
POINTS_KILL: int = 5
POINTS_SAVE: int = 5

MAFIA_EXTRA_THRESHOLD: int = 8

ALLOW_MAYOR: bool = True
ALLOW_PETRUSHKA: bool = True
ALLOW_BUKOVEL: bool = True
ALLOW_DEPUTY: bool = True
ALLOW_CONSILGIERE: bool = True

BOTS_HERD_CHANCE: float = 0.45

SHOP_ITEMS = [
    {
        "code": "ACTIVE_ROLE_10",
        "name_uk": "Гарантована активна роль на 10 ігор",
        "description_uk": "Мафіозна підписка: наступні 10 ігор отримуєш активну роль.",
        "cost_points": 150,
        "effect_type": "active_role",
        "effect_value": 10,
    },
]
