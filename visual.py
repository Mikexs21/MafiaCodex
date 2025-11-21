"""Presentation helpers and Ukrainian flavor text."""
from __future__ import annotations

import random
from typing import Iterable, List

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

BOT_NAMES = [
    "🤖 Іннокентій Зриватель",
    "🤖 Микола Могила",
    "🤖 Сусід-алкоголік",
    "🤖 Тракторист Петьо",
    "🤖 Бабка з базару",
    "🤖 Дядько з лопатою",
    "🤖 Йосип Бетон",
    "🤖 Пацюк в кєпці",
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
    "lobby": "Реєстрація",
    "night": "Ніч",
    "day": "День",
    "vote": "Голосування",
    "ended": "Фініш",
}


def mention(name: str, user_id: int | None = None) -> str:
    if user_id:
        return f"<a href=\"tg://user?id={user_id}\">{name}</a>"
    return name


def build_join_keyboard(can_add_bot: bool, can_start: bool) -> InlineKeyboardMarkup:
    buttons = [[InlineKeyboardButton("Доєднатися в гру", callback_data="join")]]
    if can_add_bot:
        buttons.append([InlineKeyboardButton("Додати бота 🤖", callback_data="add_bot")])
    if can_start:
        buttons.append([InlineKeyboardButton("Почати гру", callback_data="start_game")])
    return InlineKeyboardMarkup(buttons)


def build_night_action_keyboard(role: str, players: List[tuple[int, str]]) -> InlineKeyboardMarkup:
    rows: List[List[InlineKeyboardButton]] = []
    for pid, name in players:
        rows.append([InlineKeyboardButton(name, callback_data=f"act:{role}:{pid}")])
    if not rows:
        rows.append([InlineKeyboardButton("Пропустити", callback_data=f"act:{role}:-1")])
    return InlineKeyboardMarkup(rows)


def build_vote_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Так, вішати", callback_data="vote_yes")],
            [InlineKeyboardButton("Ні, шкода", callback_data="vote_no")],
        ]
    )


def build_nomination_keyboard(candidates: List[tuple[int, str]]) -> InlineKeyboardMarkup:
    rows: List[List[InlineKeyboardButton]] = []
    for pid, name in candidates:
        rows.append([InlineKeyboardButton(name, callback_data=f"nom:{pid}")])
    if not rows:
        rows.append([InlineKeyboardButton("Нема підозр", callback_data="nom:-1")])
    return InlineKeyboardMarkup(rows)


def build_confirmation_keyboard(victim_name: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(f"Так, {victim_name} на мотузку", callback_data="confirm_yes")],
            [InlineKeyboardButton("Ні, хай живе", callback_data="confirm_no")],
        ]
    )


def build_shop_keyboard(items: List[dict]) -> InlineKeyboardMarkup:
    buttons = []
    for item in items:
        caption = f"{item['name_uk']} ({item['cost_points']} очок)"
        buttons.append([InlineKeyboardButton(caption, callback_data=f"shop:{item['code']}")])
    return InlineKeyboardMarkup(buttons)


def get_role_dm_text(role: str, extra: str | None = None) -> str:
    base = {
        "don": "Ти Дон. Керуєш різаниною. Кожної ночі вибираєш жертву.",
        "mafia": "Ти Мафія. Слухайся Дона, якщо його немає – різай сам.",
        "doctor": "Ти Лікар. Клей бинти кому хочеш. Сам себе можеш латати лише раз.",
        "detective": "Ти Детектив Кішкель. Перевіряй ролі або зроби один постріл з пістоля.",
        "deputy": "Ти Заступник детектива. Нюхай, перевіряй, але без ствола.",
        "consigliere": "Ти Консильєрі. Вночі дізнаєшся ролі і шепочеш мафії.",
        "mayor": "Ти Мер. Твій голос рахується за двох. Мовчи про це.",
        "executioner": "Ти Палач. Петля тебе слухається. Один раз може врятувати тебе самого.",
        "civil": "Ти Мирний селюк. Пий самогон і панікуй в чаті.",
        "petrushka": "Ти Петрушка. Раз за гру міняєш комусь роль на випадкову (без детектива).",
    }.get(role, "Незнана роль, але точно смердить пригодами.")
    return base + (f"\n\n{extra}" if extra else "")


def get_phase_timer_text(phase: str, seconds_left: int) -> str:
    title = PHASE_TITLES.get(phase, phase)
    return f"⏳ <b>{title}</b>: {seconds_left} с"


def lobby_text(game_id: int, players: Iterable[str], bots: Iterable[str]) -> str:
    player_lines = "\n".join(players) or "—"
    bot_lines = "\n".join(bots) or "—"
    return (
        f"Гра #{game_id}\nФаза: Реєстрація\n\n"
        f"Люди:\n{player_lines}\n\n"
        f"Боти:\n{bot_lines}\n"
        "Тисни кнопку, поки мотузка не скрипить."
    )


def night_intro() -> str:
    return "<i>Місто засинає. Хтось точить сокиру, хтось хропе під стіл.</i>"


def morning_intro() -> str:
    return "<b>Ранок.</b> Хто не прокинувся – тому вже не треба."


def morning_report(killed: List[str], saved: List[str]) -> str:
    if not killed and not saved:
        return "Всі живі. Мабуть, Дон перепив самогону."
    parts: List[str] = []
    if killed:
        parts.append("Померли: " + ", ".join(killed))
    if saved:
        parts.append("Лікар витягнув з того світу: " + ", ".join(saved))
    return "\n".join(parts)


def format_stats_block(alive: List[str], dead: List[str]) -> str:
    alive_block = "\n".join(alive) or "ніхто"
    dead_block = "\n".join(dead) or "ніхто"
    return f"Живі:\n{alive_block}\n\nТрупи:\n{dead_block}"


def vote_intro() -> str:
    return "Час голосування. Мотузка чекає."


def night_action_log(role: str) -> str:
    mapping = {
        "don": "Дон вже вибрав, чия хата згорить.",
        "mafia": "Мафія шепоче, кого підрізати.",
        "doctor": "Лікар шукає, кому клеїти бинти.",
        "detective": "Детектив нишпорить в темряві.",
        "deputy": "Заступник нюхає сліди.",
        "consigliere": "Консильєрі збирає досьє.",
        "petrushka": "Петрушка готує рольовий сюрприз.",
        "potato": "Картопля летить, тримай голову!",
    }
    return mapping.get(role, "Хтось там щось мутить...")


def bukovel_intro() -> str:
    return "Наша гра проходить в Буковелі. Мирні мають картоплю. Використовуйте раціонально!"


def potato_throw(name: str) -> str:
    return f"🥔 Хтось кинув картоплю в <b>{name}</b>…"


def event_text(code: str) -> str:
    mapping = {
        "doc_saved": "Лікар примотав бинтом. Жертва живе.",
        "don_dead_mafia_alive": "Дона прибрали, але мафія ще дихає. Один бере на себе ніж.",
        "don_dead_no_mafia": "Дон здох, мафії нема. Мирні гуляють на весіллі.",
        "doc_dead": "Лікаря прибили. Тепер лікувати буде ветеринар.",
        "detective_dead": "Детектива закатали. Сліди холонуть.",
        "civil_dead": "Мирний упав без шелеста. Хрест йому і самогоннику.",
        "event_mafia_win": "Мафія захопила місто. Мирні йдуть копати буряки.",
        "event_civil_won": "Мафію винесли. Мирні п'ють квас за перемогу.",
        "night_no_kick": "Цього разу мотузку не змочили. Побачимо, що буде вночі.",
        "night_kicked": "Мотузка затягнулась. Далі по сцені – тиша.",
        "rope_break": "Петля тріснула, як старий шнурок. Жертва живе!",
    }
    return mapping.get(code, "Сталась подія, але слів нема.")


def bot_phrase() -> str:
    phrases = [
        "Я б довірився козі більше, ніж вам, люди.",
        "Мені пахне оселедцем від Дона.",
        "Док, бери бинти. Буде кров.",
        "Навіть бот бачить, хто мафія.",
        "Щось ви всі підозрілі, як ковбаса без м'яса.",
    ]
    return random.choice(phrases)


def format_log(now: str, game_id: int, round_no: int, role: str, action: str) -> str:
    return f"[{now}] [GAME {game_id}] [ROUND {round_no}] {role.upper()}: {action}"


__all__ = [
    "BOT_NAMES",
    "ROLE_LABELS",
    "PHASE_TITLES",
    "mention",
    "build_join_keyboard",
    "build_night_action_keyboard",
    "build_vote_keyboard",
    "build_nomination_keyboard",
    "build_confirmation_keyboard",
    "build_shop_keyboard",
    "get_role_dm_text",
    "get_phase_timer_text",
    "lobby_text",
    "night_intro",
    "morning_intro",
    "morning_report",
    "format_stats_block",
    "vote_intro",
    "night_action_log",
    "bukovel_intro",
    "potato_throw",
    "event_text",
    "bot_phrase",
    "format_log",
]
