"""Configuration for Mafia Telegram bot."""
from __future__ import annotations

BOT_TOKEN: str = "PASTE_TOKEN_HERE"

# SQLite ініціалізація: файл створиться автоматично поруч із кодом.
SQLITE_DB_PATH = "mafia.db"
SQLITE_ISOLATION_LEVEL = None  # autocommit-friendly для частих write-операцій

NIGHT_DURATION: int = 60
DAY_DURATION: int = 60
VOTE_DURATION: int = 30
COUNTDOWN_STEP: int = 5

MIN_PLAYERS: int = 5
MAX_PLAYERS: int = 10
MAX_BOTS: int = 6

POINTS_WIN: int = 50
POINTS_LOSE: int = 10

DEFAULT_ROLE_DISTRIBUTION = {
    "don": 1,
    "mafia": 1,  # adds extra mafia if player count >= 8
    "doctor": 1,
    "detective": 1,
    "deputy": 1,
    "consigliere": 1,
    "mayor": 1,
    "executioner": 1,
    "petrushka": 1,
}

ALLOW_MAYOR: bool = True
ALLOW_PETRUSHKA: bool = True
ALLOW_BUKOVEL: bool = True

BOT_CHATTER_CHANCE: float = 0.25

SHOP_ITEMS = [
    {
        "code": "ACTIVE_ROLE_10",
        "name_uk": "Гарантована активна роль на 10 ігор",
        "description_uk": "Мафіозна підписка: наступні 10 ігор отримуєш активну роль.",
        "cost_points": 150,
        "effect_type": "active_role",
        "effect_value": 10,
    }
]
