"""Game engine for Mafia bot."""
from __future__ import annotations

import asyncio
import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from telegram import CallbackQuery, Chat, Message, Update
from telegram.constants import ChatType, ParseMode
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

import config
import db
import visual


@dataclass
class PlayerState:
    name: str
    user_id: Optional[int]
    is_bot: bool
    role: str = "civil"
    alive: bool = True
    self_heal_used: bool = False
    pending_action: Optional[int] = None
    potato_ready: bool = False
    potato_used: bool = False
    vote_choice: Optional[int] = None

    def label(self) -> str:
        if self.user_id:
            return visual.mention(self.name, self.user_id)
        return self.name


@dataclass
class GameState:
    chat_id: int
    game_id: int
    bukovel: bool
    players: Dict[int, PlayerState] = field(default_factory=dict)
    phase: str = "lobby"
    round_no: int = 0
    lobby_message_id: Optional[int] = None
    countdown_task: Optional[asyncio.Task] = None
    votings: Dict[int, int] = field(default_factory=dict)
    current_timer_message: Optional[Message] = None
    started: bool = False

    def alive_players(self) -> Dict[int, PlayerState]:
        return {pid: p for pid, p in self.players.items() if p.alive}

    def mafia_side(self) -> List[int]:
        return [pid for pid, p in self.players.items() if p.alive and p.role in {"don", "mafia", "consigliere"}]

    def civil_side(self) -> List[int]:
        return [pid for pid, p in self.players.items() if p.alive and p.role not in {"don", "mafia", "consigliere"}]


class GameManager:
    def __init__(self, application: Application):
        self.app = application
        self.games: Dict[int, GameState] = {}
        self.lock = asyncio.Lock()

    async def ensure_game(self, chat_id: int) -> GameState:
        async with self.lock:
            if chat_id in self.games:
                return self.games[chat_id]
            loaded = await db.load_active_game(chat_id)
            if loaded:
                game_id, bukovel, players = loaded
                state = GameState(chat_id=chat_id, game_id=game_id, bukovel=bukovel, phase="day", started=True)
                for idx, row in enumerate(players, start=1):
                    state.players[idx] = PlayerState(
                        name=row["name"],
                        user_id=row.get("user_id"),
                        is_bot=row["is_bot"],
                        role=row["role"],
                        alive=row["is_alive"],
                    )
                self.games[chat_id] = state
                return state
            state = GameState(chat_id=chat_id, game_id=0, bukovel=False)
            self.games[chat_id] = state
            return state

    async def start_new_game(self, chat: Chat, bukovel: bool = False) -> GameState:
        state = await self.ensure_game(chat.id)
        state.players.clear()
        state.phase = "lobby"
        state.round_no = 0
        state.started = False
        state.bukovel = bukovel
        state.game_id = await db.create_game(chat.id, bukovel)
        return state

    async def add_player(self, chat_id: int, user_id: int, name: str) -> Optional[str]:
        state = await self.ensure_game(chat_id)
        if state.phase != "lobby":
            return "Гра вже йде. Чекай наступну."
        if len(state.players) >= config.MAX_PLAYERS:
            return "Переповнено. Чекай, поки когось з'їдять."
        if any(p.user_id == user_id for p in state.players.values()):
            return "Ти вже в грі."
        pid = max(state.players.keys(), default=0) + 1
        state.players[pid] = PlayerState(name=name, user_id=user_id, is_bot=False)
        return None

    async def add_bot(self, chat_id: int) -> Optional[str]:
        state = await self.ensure_game(chat_id)
        if state.phase != "lobby":
            return "Пізно. М'ясо вже смажиться."
        if len(state.players) >= config.MAX_PLAYERS:
            return "Переповнено."
        if sum(1 for p in state.players.values() if p.is_bot) >= config.MAX_BOTS:
            return "Ботів забагато, ще групу поламають."
        name = random.choice(visual.BOT_NAMES)
        pid = max(state.players.keys(), default=0) + 1
        state.players[pid] = PlayerState(name=name, user_id=None, is_bot=True)
        return None

    async def list_players(self, chat_id: int) -> Tuple[List[str], List[str]]:
        state = await self.ensure_game(chat_id)
        players = [p.label() for p in state.players.values() if not p.is_bot]
        bots = [p.label() for p in state.players.values() if p.is_bot]
        return players, bots

    async def can_start(self, chat_id: int) -> bool:
        state = await self.ensure_game(chat_id)
        return len(state.players) >= config.MIN_PLAYERS

    async def assign_roles(self, state: GameState) -> None:
        count = len(state.players)
        roles: List[str] = []
        roles.append("don")
        if count >= 8:
            roles.append("mafia")
        roles.extend([
            "doctor",
            "detective",
            "deputy",
            "consigliere",
            "executioner",
        ])
        if config.ALLOW_MAYOR:
            roles.append("mayor")
        if config.ALLOW_PETRUSHKA:
            roles.append("petrushka")
        while len(roles) < count:
            roles.append("civil")
        random.shuffle(roles)
        human_ids = [pid for pid, p in state.players.items() if not p.is_bot]
        if "detective" in roles and human_ids:
            # force detective to be human
            det_index = roles.index("detective")
            target_pid = random.choice(human_ids)
            pid_list = list(state.players.keys())
            swap_index = pid_list.index(target_pid)
            roles[det_index], roles[swap_index] = roles[swap_index], roles[det_index]
        pid_order = list(state.players.keys())
        # Guarantee active role buffs are honored by replacing civils when needed.
        active_pool = [
            "don",
            "mafia",
            "doctor",
            "detective",
            "executioner",
            "mayor",
            "petrushka",
            "consigliere",
        ]
        for idx, pid in enumerate(pid_order):
            role = roles[idx]
            player = state.players[pid]
            if player.user_id and await db.consume_active_role_buff(player.user_id):
                if role == "civil":
                    role = random.choice(active_pool)
                    roles[idx] = role
            player.role = role
            if state.bukovel and role == "civil":
                player.potato_ready = True
            await db.add_game_player(state.game_id, player.user_id, player.name, role, player.is_bot)
        state.started = True

    async def send_roles(self, state: GameState, context: ContextTypes.DEFAULT_TYPE) -> None:
        for player in state.players.values():
            if player.is_bot or not player.user_id:
                continue
            try:
                await context.bot.send_message(
                    chat_id=player.user_id,
                    text=visual.get_role_dm_text(player.role),
                    parse_mode=ParseMode.HTML,
                )
            except Exception:
                continue

    async def start_game(self, chat: Chat, context: ContextTypes.DEFAULT_TYPE) -> str:
        state = await self.ensure_game(chat.id)
        if state.phase != "lobby":
            return "Гра вже йде."
        if len(state.players) < config.MIN_PLAYERS:
            return "Мало м'яса. Треба ще людей."
        await self.assign_roles(state)
        await self.send_roles(state, context)
        if state.bukovel:
            await context.bot.send_message(chat.id, visual.bukovel_intro())
        await self.start_night(state, context)
        return "Стартуємо"

    async def start_night(self, state: GameState, context: ContextTypes.DEFAULT_TYPE) -> None:
        state.phase = "night"
        state.round_no += 1
        await context.bot.send_animation(chat_id=state.chat_id, animation="night.gif", caption=visual.night_intro())
        await self._schedule_countdown(state, context, config.NIGHT_DURATION)
        await self._request_night_actions(state, context)

    async def _schedule_countdown(self, state: GameState, context: ContextTypes.DEFAULT_TYPE, duration: int) -> None:
        if state.countdown_task:
            state.countdown_task.cancel()
        state.countdown_task = asyncio.create_task(self._run_timer(state, context, duration))

    async def _run_timer(self, state: GameState, context: ContextTypes.DEFAULT_TYPE, duration: int) -> None:
        remaining = duration
        message: Optional[Message] = None
        while remaining >= 0 and state.phase != "ended":
            text = visual.get_phase_timer_text(state.phase, remaining)
            if message is None:
                message = await context.bot.send_message(state.chat_id, text, parse_mode=ParseMode.HTML)
                state.current_timer_message = message
            else:
                try:
                    await message.edit_text(text, parse_mode=ParseMode.HTML)
                except Exception:
                    pass
            await asyncio.sleep(config.COUNTDOWN_STEP)
            remaining -= config.COUNTDOWN_STEP
        if state.phase == "night":
            await self.resolve_night(state, context)
        elif state.phase == "day":
            await self.start_vote(state, context)
        elif state.phase == "vote":
            await self.finish_vote(state, context)

    async def _request_night_actions(self, state: GameState, context: ContextTypes.DEFAULT_TYPE) -> None:
        alive_ids = list(state.alive_players().keys())
        for pid, player in state.players.items():
            if not player.alive:
                continue
            if player.is_bot:
                await self._auto_action(pid, state)
                continue
            actionable = player.role in {"don", "mafia", "doctor", "detective", "deputy", "consigliere", "petrushka"}
            if actionable:
                kb = visual.build_night_action_keyboard(player.role, [i for i in alive_ids if i != pid])
                try:
                    await context.bot.send_message(
                        chat_id=player.user_id,
                        text=visual.night_action_log(player.role),
                        reply_markup=kb,
                    )
                except Exception:
                    pass
            elif state.bukovel and player.potato_ready and not player.potato_used:
                kb = visual.build_night_action_keyboard("potato", [i for i in alive_ids if i != pid])
                await context.bot.send_message(chat_id=player.user_id, text="Кидай картоплю?", reply_markup=kb)

    async def handle_action(self, query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not query.data or not query.data.startswith("act:"):
            return
        target = int(query.data.split(":")[1])
        user_id = query.from_user.id
        for state in self.games.values():
            for pid, player in state.players.items():
                if player.user_id == user_id and player.alive and state.phase == "night":
                    player.pending_action = target if target >= 0 else None
                    await query.answer("Прийнято")
                    try:
                        await query.edit_message_text(visual.night_action_log(player.role))
                    except Exception:
                        pass
                    return
        await query.answer("Не на часі", show_alert=True)

    async def _auto_action(self, pid: int, state: GameState) -> None:
        player = state.players[pid]
        alive = [i for i in state.alive_players().keys() if i != pid]
        if not alive:
            return
        if player.role in {"don", "mafia"}:
            player.pending_action = random.choice(alive)
        elif player.role == "doctor":
            player.pending_action = random.choice(alive)
        elif player.role in {"consigliere", "deputy"}:
            player.pending_action = random.choice(alive)
        elif player.role == "petrushka" and not player.potato_used:
            player.pending_action = random.choice(alive)

    async def resolve_night(self, state: GameState, context: ContextTypes.DEFAULT_TYPE) -> None:
        kills: List[int] = []
        saved: List[int] = []
        don = next((pid for pid, p in state.players.items() if p.alive and p.role == "don" and p.pending_action), None)
        mafia_killer = next((pid for pid, p in state.players.items() if p.alive and p.role == "mafia" and p.pending_action), None)
        if don:
            kills.append(state.players[don].pending_action)
        elif mafia_killer:
            kills.append(state.players[mafia_killer].pending_action)
        doc = next((pid for pid, p in state.players.items() if p.alive and p.role == "doctor" and p.pending_action), None)
        if doc:
            saved.append(state.players[doc].pending_action)
        detective = next((pid for pid, p in state.players.items() if p.alive and p.role == "detective" and p.pending_action), None)
        if detective:
            kills.append(state.players[detective].pending_action)
        for pid, player in state.players.items():
            if player.alive and state.bukovel and player.potato_ready and not player.potato_used and player.pending_action:
                if random.random() < 0.5:
                    kills.append(player.pending_action)
                    await context.bot.send_message(state.chat_id, visual.potato_throw(state.players[player.pending_action].label()))
                player.potato_used = True
        for pid, player in state.players.items():
            if player.alive and player.role == "petrushka" and player.pending_action:
                target_id = player.pending_action
                target = state.players.get(target_id)
                if target and target.alive:
                    choices = [r for r in visual.ROLE_LABELS.keys() if r != "detective"]
                    target.role = random.choice(choices)
        final_kills = [k for k in kills if k is not None and k not in saved]
        killed_names: List[str] = []
        for victim in final_kills:
            if victim in state.players and state.players[victim].alive:
                state.players[victim].alive = False
                killed_names.append(state.players[victim].label())
                await db.update_game_player_status(state.game_id, state.players[victim].name, False)
        saved_names = [state.players[s].label() for s in saved if s in state.players]
        event = "everyone_alive" if not killed_names else "event"
        await context.bot.send_animation(state.chat_id, animation="morning.gif", caption=visual.morning_report(event, killed_names, saved_names))
        alive_labels = [p.label() for p in state.players.values() if p.alive]
        dead_labels = [p.label() for p in state.players.values() if not p.alive]
        await context.bot.send_message(state.chat_id, visual.format_stats_block(alive_labels, dead_labels))
        await self.check_win(state, context)
        if state.phase != "ended":
            await self.start_day(state, context)

    async def start_day(self, state: GameState, context: ContextTypes.DEFAULT_TYPE) -> None:
        state.phase = "day"
        await self._schedule_countdown(state, context, config.DAY_DURATION)

    async def start_vote(self, state: GameState, context: ContextTypes.DEFAULT_TYPE) -> None:
        state.phase = "vote"
        state.votings.clear()
        await context.bot.send_animation(state.chat_id, animation="vote.gif", caption=visual.vote_intro())
        await context.bot.send_message(state.chat_id, "Будемо когось різати сьогодні?", reply_markup=visual.build_vote_keyboard())
        await self._schedule_countdown(state, context, config.VOTE_DURATION)

    async def vote_callback(self, query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE) -> None:
        if query.data not in {"vote_yes", "vote_no"}:
            return
        chat_id = query.message.chat.id if query.message else None
        if chat_id is None:
            return
        state = self.games.get(chat_id)
        if not state or state.phase != "vote":
            return
        vote = 1 if query.data == "vote_yes" else 0
        state.votings[query.from_user.id] = vote
        await query.answer("Голос враховано")

    async def finish_vote(self, state: GameState, context: ContextTypes.DEFAULT_TYPE) -> None:
        yes = sum(state.votings.values())
        no = len(state.votings) - yes
        if yes <= no:
            await context.bot.send_message(state.chat_id, visual.event_text("night_no_kick"))
            await self.start_night(state, context)
            return
        alive = [pid for pid, p in state.players.items() if p.alive]
        if not alive:
            await self.start_night(state, context)
            return
        victim = random.choice(alive)
        target = state.players[victim]
        if target.role == "executioner" and random.random() < 0.5:
            await context.bot.send_message(state.chat_id, visual.event_text("rope_break"))
        else:
            target.alive = False
            await db.update_game_player_status(state.game_id, target.name, False)
            await context.bot.send_message(state.chat_id, f"{target.label()} повис. {visual.event_text('night_kicked')}")
        await self.check_win(state, context)
        if state.phase != "ended":
            await self.start_night(state, context)

    async def check_win(self, state: GameState, context: ContextTypes.DEFAULT_TYPE) -> None:
        mafia_alive = len(state.mafia_side())
        civil_alive = len(state.civil_side())
        if mafia_alive == 0:
            await context.bot.send_animation(state.chat_id, animation="lost_mafia.gif", caption=visual.event_text("event_civil_won"))
            await db.end_game(state.game_id, "civil")
            state.phase = "ended"
        elif mafia_alive >= civil_alive:
            await context.bot.send_animation(state.chat_id, animation="lost_civil.gif", caption=visual.event_text("event_mafia_win"))
            await db.end_game(state.game_id, "mafia")
            state.phase = "ended"

    async def cancel_game(self, chat_id: int) -> str:
        state = await self.ensure_game(chat_id)
        state.phase = "ended"
        state.players.clear()
        return "Гру зупинено."


async def command_newgame(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_chat.type not in (ChatType.SUPERGROUP, ChatType.GROUP):
        await update.message.reply_text("Ця команда лише в групі.")
        return
    manager: GameManager = context.bot_data["manager"]
    bukovel = config.ALLOW_BUKOVEL and random.random() < 0.25
    state = await manager.start_new_game(update.effective_chat, bukovel)
    players, bots = await manager.list_players(update.effective_chat.id)
    msg = await update.message.reply_text(
        visual.lobby_text(state.game_id, players, bots),
        reply_markup=visual.build_join_keyboard(can_add_bot=True, can_start=False),
        parse_mode=ParseMode.HTML,
    )
    state.lobby_message_id = msg.message_id


async def command_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    manager: GameManager = context.bot_data["manager"]
    text = await manager.cancel_game(update.effective_chat.id)
    await update.message.reply_text(text)


async def command_status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    manager: GameManager = context.bot_data["manager"]
    state = await manager.ensure_game(update.effective_chat.id)
    alive = [p.label() for p in state.players.values() if p.alive]
    dead = [p.label() for p in state.players.values() if not p.alive]
    await update.message.reply_text(
        f"Стан: {visual.PHASE_TITLES.get(state.phase, state.phase)}\n" + visual.format_stats_block(alive, dead),
        parse_mode=ParseMode.HTML,
    )


async def command_start_dm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await db.register_user(update.effective_user.id, update.effective_user.username)
    await update.message.reply_text("Привіт, ти зареєстрований. Чекай інструкцій у групі.")


async def command_profile(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    info = await db.fetch_user_by_tg(update.effective_user.id)
    if not info:
        await update.message.reply_text("Ти ще не бачив смерті в цій грі.")
        return
    buffs = await db.get_user_buffs(info["id"])
    buffs_text = "\n".join([f"{b['buff_type']} ({b['remaining_games']} ігор)" for b in buffs]) or "Нічого нема"
    await update.message.reply_text(
        f"Очки: {info['total_points']}\nІгор: {info['total_games']}\nПеремог: {info['total_wins']}\nБафів: {buffs_text}"
    )


async def command_shop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    items = await db.list_shop_items()
    await update.message.reply_text("Лавка з бонусами:", reply_markup=visual.build_shop_keyboard(items))


async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not query:
        return
    data = query.data or ""
    manager: GameManager = context.bot_data["manager"]
    if data.startswith("join"):
        state = await manager.ensure_game(query.message.chat.id)
        err = await manager.add_player(query.message.chat.id, query.from_user.id, query.from_user.full_name)
        players, bots = await manager.list_players(query.message.chat.id)
        can_start = await manager.can_start(query.message.chat.id)
        await query.edit_message_text(
            visual.lobby_text(state.game_id, players, bots),
            reply_markup=visual.build_join_keyboard(
                can_add_bot=len(bots) < config.MAX_BOTS and len(players) + len(bots) < config.MAX_PLAYERS,
                can_start=can_start,
            ),
            parse_mode=ParseMode.HTML,
        )
        await query.answer(err or "Ти в грі. Роби /start в особисті повідомлення.")
    elif data.startswith("add_bot"):
        err = await manager.add_bot(query.message.chat.id)
        state = await manager.ensure_game(query.message.chat.id)
        players, bots = await manager.list_players(query.message.chat.id)
        can_start = await manager.can_start(query.message.chat.id)
        await query.edit_message_text(
            visual.lobby_text(state.game_id, players, bots),
            reply_markup=visual.build_join_keyboard(
                can_add_bot=len(bots) < config.MAX_BOTS and len(players) + len(bots) < config.MAX_PLAYERS,
                can_start=can_start,
            ),
            parse_mode=ParseMode.HTML,
        )
        await query.answer(err or "Бот доданий. Готуйте лопати.")
    elif data.startswith("start_game"):
        can_start = await manager.can_start(query.message.chat.id)
        if not can_start:
            await query.answer("Мало гравців", show_alert=True)
            return
        await manager.start_game(query.message.chat, context)
        await query.answer("Починаємо")
    elif data.startswith("shop:"):
        user = await db.fetch_user_by_tg(query.from_user.id)
        if not user:
            await query.answer("Спочатку /start в особисті", show_alert=True)
            return
        result = await db.purchase_item(user["id"], data.split(":")[1])
        await query.answer(result, show_alert=True)
    elif data.startswith("vote_"):
        await manager.vote_callback(query, context)
    elif data.startswith("act:"):
        await manager.handle_action(query, context)


async def moderate_messages(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if not message:
        return
    chat_id = message.chat.id
    manager: GameManager = context.bot_data.get("manager")
    if not manager or chat_id not in manager.games:
        return
    state = manager.games[chat_id]
    if message.from_user and any(
        p.user_id == message.from_user.id and not p.alive for p in state.players.values() if p.user_id
    ):
        try:
            await message.delete()
        except Exception:
            pass
    if state.phase == "night":
        try:
            await message.delete()
        except Exception:
            pass


def register_handlers(app: Application, manager: GameManager) -> None:
    app.add_handler(CommandHandler("newgame", command_newgame))
    app.add_handler(CommandHandler("cancelgame", command_cancel))
    app.add_handler(CommandHandler("status", command_status))
    app.add_handler(CommandHandler("start", command_start_dm))
    app.add_handler(CommandHandler("profile", command_profile))
    app.add_handler(CommandHandler("shop", command_shop))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(CallbackQueryHandler(manager.handle_action, pattern=r"^act:"))
    app.add_handler(CallbackQueryHandler(manager.vote_callback, pattern=r"^vote_"))
    app.add_handler(MessageHandler(filters.ChatType.GROUPS, moderate_messages))
