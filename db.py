"""Async SQLite access layer."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import aiosqlite

import config

_DB: aiosqlite.Connection | None = None
_LOCK = asyncio.Lock()


async def init_db() -> aiosqlite.Connection:
    global _DB
    if _DB is None:
        db_path = Path(config.SQLITE_DB_PATH)
        _DB = await aiosqlite.connect(db_path, isolation_level=config.SQLITE_ISOLATION_LEVEL)
        await _DB.execute("PRAGMA foreign_keys=ON;")
        await _setup_schema()
    return _DB


async def _setup_schema() -> None:
    assert _DB is not None
    await _DB.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER UNIQUE,
            username TEXT,
            first_seen_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            total_points INTEGER DEFAULT 0,
            total_games INTEGER DEFAULT 0,
            total_wins INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS games (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            group_chat_id INTEGER,
            started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            ended_at TIMESTAMP NULL,
            winner_side TEXT,
            bukovel INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS game_players (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            game_id INTEGER,
            user_id INTEGER NULL,
            is_bot INTEGER DEFAULT 0,
            name TEXT,
            role TEXT,
            is_alive INTEGER DEFAULT 1,
            extra TEXT NULL,
            FOREIGN KEY(game_id) REFERENCES games(id) ON DELETE CASCADE,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE SET NULL
        );

        CREATE TABLE IF NOT EXISTS shop_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT UNIQUE,
            name_uk TEXT,
            description_uk TEXT,
            cost_points INTEGER,
            effect_type TEXT,
            effect_value INTEGER
        );

        CREATE TABLE IF NOT EXISTS purchases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            item_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY(item_id) REFERENCES shop_items(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS user_buffs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            buff_type TEXT,
            remaining_games INTEGER,
            parameters TEXT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        """
    )
    await _seed_shop()


async def _seed_shop() -> None:
    assert _DB is not None
    for item in config.SHOP_ITEMS:
        await _DB.execute(
            "INSERT OR IGNORE INTO shop_items(code, name_uk, description_uk, cost_points, effect_type, effect_value)"
            " VALUES(?,?,?,?,?,?)",
            (
                item["code"],
                item["name_uk"],
                item["description_uk"],
                item["cost_points"],
                item["effect_type"],
                item["effect_value"],
            ),
        )
    await _DB.commit()


async def close_pool() -> None:
    global _DB
    if _DB:
        await _DB.close()
        _DB = None


async def fetch_user_by_tg(telegram_id: int) -> Optional[Dict[str, Any]]:
    await init_db()
    async with _LOCK:
        cursor = await _DB.execute(
            "SELECT id, username, total_points, total_games, total_wins FROM users WHERE telegram_id=?",
            (telegram_id,),
        )
        row = await cursor.fetchone()
        await cursor.close()
    if not row:
        return None
    return {
        "id": row[0],
        "username": row[1],
        "total_points": row[2],
        "total_games": row[3],
        "total_wins": row[4],
    }


async def register_user(telegram_id: int, username: str | None) -> Dict[str, Any]:
    await init_db()
    async with _LOCK:
        await _DB.execute("INSERT OR IGNORE INTO users(telegram_id, username) VALUES(?,?)", (telegram_id, username))
        await _DB.commit()
    user = await fetch_user_by_tg(telegram_id)
    assert user is not None
    return user


async def update_points_by_user_id(user_id: int, delta: int, win: bool) -> None:
    await init_db()
    async with _LOCK:
        await _DB.execute(
            "UPDATE users SET total_points = total_points + ?, total_games = total_games + 1, total_wins = total_wins + ? WHERE id=?",
            (delta, 1 if win else 0, user_id),
        )
        await _DB.commit()


async def create_game(group_chat_id: int, bukovel: bool) -> int:
    await init_db()
    async with _LOCK:
        cursor = await _DB.execute(
            "INSERT INTO games(group_chat_id, bukovel) VALUES(?,?)",
            (group_chat_id, int(bukovel)),
        )
        await _DB.commit()
        return cursor.lastrowid


async def end_game(game_id: int, winner_side: str) -> None:
    await init_db()
    async with _LOCK:
        await _DB.execute(
            "UPDATE games SET ended_at=CURRENT_TIMESTAMP, winner_side=? WHERE id=?",
            (winner_side, game_id),
        )
        await _DB.commit()


async def add_game_player(game_id: int, user_id: Optional[int], name: str, role: str, is_bot: bool) -> int:
    await init_db()
    async with _LOCK:
        cursor = await _DB.execute(
            "INSERT INTO game_players(game_id, user_id, is_bot, name, role) VALUES(?,?,?,?,?)",
            (game_id, user_id, int(is_bot), name, role),
        )
        await _DB.commit()
        return cursor.lastrowid


async def update_game_player_status(game_id: int, name: str, alive: bool) -> None:
    await init_db()
    async with _LOCK:
        await _DB.execute("UPDATE game_players SET is_alive=? WHERE game_id=? AND name=?", (int(alive), game_id, name))
        await _DB.commit()


async def load_active_game(group_chat_id: int) -> Optional[Tuple[int, bool, List[Dict[str, Any]]]]:
    await init_db()
    async with _LOCK:
        cursor = await _DB.execute(
            "SELECT id, bukovel FROM games WHERE group_chat_id=? AND ended_at IS NULL ORDER BY id DESC LIMIT 1",
            (group_chat_id,),
        )
        row = await cursor.fetchone()
        await cursor.close()
        if not row:
            return None
        game_id, bukovel = row
        p_cursor = await _DB.execute(
            "SELECT name, role, is_bot, is_alive, user_id FROM game_players WHERE game_id=?",
            (game_id,),
        )
        p_rows = await p_cursor.fetchall()
        await p_cursor.close()
    players: List[Dict[str, Any]] = []
    for name, role, is_bot, alive, user_id in p_rows:
        players.append({"name": name, "role": role, "is_bot": bool(is_bot), "is_alive": bool(alive), "user_id": user_id})
    return game_id, bool(bukovel), players


async def list_shop_items() -> List[Dict[str, Any]]:
    await init_db()
    async with _LOCK:
        cursor = await _DB.execute("SELECT id, code, name_uk, description_uk, cost_points, effect_type, effect_value FROM shop_items")
        rows = await cursor.fetchall()
        await cursor.close()
    return [
        {
            "id": row[0],
            "code": row[1],
            "name_uk": row[2],
            "description_uk": row[3],
            "cost_points": row[4],
            "effect_type": row[5],
            "effect_value": row[6],
        }
        for row in rows
    ]


async def purchase_item(user_id: int, item_code: str) -> str:
    await init_db()
    async with _LOCK:
        cursor = await _DB.execute(
            "SELECT id, cost_points, effect_type, effect_value FROM shop_items WHERE code=?",
            (item_code,),
        )
        item = await cursor.fetchone()
        await cursor.close()
        if not item:
            return "Нема такого товару."
        item_id, cost, effect_type, effect_value = item
        bal_cursor = await _DB.execute("SELECT total_points FROM users WHERE id=?", (user_id,))
        row = await bal_cursor.fetchone()
        await bal_cursor.close()
        if not row or row[0] < cost:
            return "Не вистачає очок."
        await _DB.execute("UPDATE users SET total_points = total_points - ? WHERE id=?", (cost, user_id))
        await _DB.execute("INSERT INTO purchases(user_id, item_id) VALUES(?,?)", (user_id, item_id))
        if effect_type == "active_role":
            await _DB.execute(
                "INSERT INTO user_buffs(user_id, buff_type, remaining_games, parameters) VALUES(?,?,?,?)",
                (user_id, effect_type, effect_value, None),
            )
        await _DB.commit()
        return "Купівля оформлена."


async def get_user_buffs(user_id: int) -> List[Dict[str, Any]]:
    await init_db()
    async with _LOCK:
        cursor = await _DB.execute("SELECT id, buff_type, remaining_games, parameters FROM user_buffs WHERE user_id=?", (user_id,))
        rows = await cursor.fetchall()
        await cursor.close()
    return [
        {
            "id": row[0],
            "buff_type": row[1],
            "remaining_games": row[2],
            "parameters": json.loads(row[3]) if row[3] else None,
        }
        for row in rows
    ]


async def consume_active_role_buff(user_id: int) -> bool:
    await init_db()
    async with _LOCK:
        cursor = await _DB.execute(
            "SELECT id, remaining_games FROM user_buffs WHERE user_id=? AND buff_type='active_role' AND remaining_games>0 ORDER BY id ASC LIMIT 1",
            (user_id,),
        )
        row = await cursor.fetchone()
        await cursor.close()
        if not row:
            return False
        buff_id, remaining = row
        await _DB.execute("UPDATE user_buffs SET remaining_games = remaining_games - 1 WHERE id=?", (buff_id,))
        await _DB.commit()
    return True


async def close_consumed_buffs() -> None:
    await init_db()
    async with _LOCK:
        await _DB.execute("DELETE FROM user_buffs WHERE remaining_games <= 0")
        await _DB.commit()
