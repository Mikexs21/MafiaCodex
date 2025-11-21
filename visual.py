"""All cosmetic text and keyboard helpers in Ukrainian with dark humor."""
from __future__ import annotations

import random
from typing import Iterable, List, Tuple

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

BOT_NAMES = [
    "🤖 Ботяра Пацько",
    "🤖 Тракторист-бот",
    "🤖 Галя з базару",
    "🤖 Дід Панас",
    "🤖 Сусід в тапках",
    "🤖 Бурячок",
    "🤖 Ламповий Славік",
]

ROLE_LABELS = {
    "don": "Дон",
    "mafia": "Мафія",
    "doctor": "Лікар",
    "detective": "Детектив Кішкель",
    "deputy": "Заступник детектива",
    "consigliere": "Консильєрі",
    "mayor": "Мер міста",
    "executioner": "Палач",
    "civil": "Мирний",
    "petrushka": "Петрушка",
}

PHASE_TITLES = {
    "lobby": "Лобі",
    "night": "Ніч",
    "day": "День",
    "vote": "Голосування",
}


def build_join_keyboard(can_add_bot: bool, can_start: bool) -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton("Доєднатися в гру", callback_data="join")],
    ]
    if can_add_bot:
        buttons.append([InlineKeyboardButton("Додати бота 🤖", callback_data="add_bot")])
    if can_start:
        buttons.append([InlineKeyboardButton("Почати гру", callback_data="start_game")])
    return InlineKeyboardMarkup(buttons)


def build_night_action_keyboard(role: str, player_ids: List[int]) -> InlineKeyboardMarkup:
    rows = []
    for pid in player_ids:
        rows.append([InlineKeyboardButton(f"Ціль #{pid}", callback_data=f"act:{pid}")])
    return InlineKeyboardMarkup(rows or [[InlineKeyboardButton("Пропустити", callback_data="act:-1")]])


def build_vote_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Так, тягнемо петлю", callback_data="vote_yes")],
            [InlineKeyboardButton("Ні, хай живе ще день", callback_data="vote_no")],
        ]
    )


def build_shop_keyboard(items: List[dict]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(f"{item['name_uk']} ({item['cost_points']} очок)", callback_data=f"shop:{item['code']}")]
            for item in items
        ]
    )


def get_role_dm_text(role: str, extra: str | None = None) -> str:
    base = {
        "don": "Ти Дон. Вночі обираєш жертву і робиш вигляд, що це не ти.",
        "mafia": "Ти Мафія. Слухайся Дона і не тупи.",
        "doctor": "Ти Лікар. Рятуй кого можеш. Сам себе лікуй лише раз, бо ліків мало.",
        "detective": "Ти Детектив Кішкель. Перевіряй та стріляй один раз, якщо свербить.",
        "deputy": "Ти Заступник детектива. Просто перевіряй і записуй на серветку.",
        "consigliere": "Ти Консильєрі. Шепочи мафії правду про ролі.",
        "mayor": "Ти Мер. Голос рахується за двох, але не виставляй себе дурнем.",
        "executioner": "Ти Палач. Петля слухаєсь тебе краще за всіх.",
        "civil": "Ти Мирний. Лох без діла, просто дивись шоу.",
        "petrushka": "Ти Петрушка. Можеш раз змінити комусь роль і насолити долі.",
    }.get(role, "Роль загадкова, як ковбаса на базарі.")
    return base + (f"\n\n{extra}" if extra else "")


def get_phase_timer_text(phase: str, seconds_left: int) -> str:
    title = PHASE_TITLES.get(phase, phase)
    return f"<b>{title}</b> · лишилось {seconds_left} сек. Не тупи."


def lobby_text(game_id: int, players: Iterable[str], bots: Iterable[str]) -> str:
    player_lines = "\n".join(players) or "—"
    bot_lines = "\n".join(bots) or "—"
    return (
        f"Гра #{game_id}. Лобі відкрито.\n"
        f"Гравці:\n{player_lines}\n\n"
        f"Боти:\n{bot_lines}\n"
        "Тисни кнопку, поки не пізно."
    )


def night_intro() -> str:
    return "<i>Місто засинає... Хтось ще хропе, хтось вже точить ніж.</i>"


def morning_report(event: str, killed: List[str], saved: List[str]) -> str:
    if event == "everyone_alive":
        return "Всі прокинулись. Дон заблукав, або лікар реально шарить."
    parts = []
    if killed:
        parts.append("Померли: " + ", ".join(killed))
    if saved:
        parts.append("Лікар встиг врятувати: " + ", ".join(saved))
    if not parts:
        parts.append("Тиша. Ніби нічого не сталось, але це підозріло.")
    return "\n".join(parts)


def format_stats_block(alive: List[str], dead: List[str]) -> str:
    return f"Живі: {', '.join(alive) or 'ніхто'}\nПомерли: {', '.join(dead) or 'ніхто'}"


def vote_intro() -> str:
    return "Час голосування. Тягнемо когось на гілляку чи відпускаємо?"


def night_action_log(role: str) -> str:
    mapping = {
        "don": "Дон вже вибрав, чия хата згорить.",
        "doctor": "Лікар заклеює комусь рани пластирем з базару.",
        "detective": "Детектив шепоче котові, кого нюхати.",
        "deputy": "Заступник детектива тихо лізе в темряву.",
        "consigliere": "Консильєрі пише мафії аналітику.",
        "petrushka": "Петрушка готує рольову рокіровку.",
    }
    return mapping.get(role, "Хтось там рухається в темряві...")


def bukovel_intro() -> str:
    return (
        "Наша гра проходить в Буковелі. Мирні отримали картоплю."
        " Першої ночі можна кинути нею в будь-кого з 50% шансом вбити."
    )


def potato_throw(name: str) -> str:
    return f"Хтось з мирних кинув картоплю в <b>{name}</b>. Потрапили? Ща перевіримо..."


def event_text(event: str) -> str:
    mapping = {
        "doc_saved": "Лікар таки спас, але шви криві.",
        "don_dead_mafia_alive": "Дона зняли, але мафія ще тут, як таргани. Один з них бере ніж.",
        "don_dead_no_mafia": "Дона прибрали, мафія розбіглась. Мирні шампанять.",
        "doc_dead": "Лікаря прибили. Тепер бинти лишились тільки в аптечці на базарі.",
        "detective_dead": "Детектива замовили. Кішка тепер без роботи.",
        "civil_dead": "Мирний упав. Земля йому пухом і сусідам спокій.",
        "event_mafia_win": "Мафія контролює місто. Мирні йдуть копати буряки.",
        "event_civil_won": "Мафію викосили. Мирні святкують, але ненадовго.",
        "night_no_kick": "Ніхто не пішов на мотузку цього дня. Хтось зітхнув з полегшенням.",
        "night_kicked": "Рішення прийнято. Петля вже скрипить...",
        "rope_break": "Петля тріснула! Палач нервово курить.",
    }
    return mapping.get(event, "Подія настала, але слова закінчились.")


def bot_phrase() -> str:
    phrases = [
        "Я б довірився козі, ніж вам, люди.",
        "Мені здається, що Дон пахне оселедцем.",
        "Док, не забудь купити бинтів.",
        "Хто тут так шумить? Навіть бот не спить.",
        "Ви всі підозрілі, як ковбаса без м'яса.",
    ]
    return random.choice(phrases)


def format_log(now: str, game_id: int, round_no: int, role: str, action: str) -> str:
    return f"[{now}] INFO: [GAME {game_id}] [ROUND {round_no}] [{role}] {action}"


def mention(name: str, user_id: int | None = None) -> str:
    if user_id:
        return f"<a href=\"tg://user?id={user_id}\">{name}</a>"
    return name


__all__ = [
    "build_join_keyboard",
    "build_night_action_keyboard",
    "build_vote_keyboard",
    "build_shop_keyboard",
    "get_role_dm_text",
    "get_phase_timer_text",
    "lobby_text",
    "night_intro",
    "morning_report",
    "format_stats_block",
    "vote_intro",
    "night_action_log",
    "bukovel_intro",
    "potato_throw",
    "event_text",
    "bot_phrase",
    "format_log",
    "mention",
    "BOT_NAMES",
    "ROLE_LABELS",
]
