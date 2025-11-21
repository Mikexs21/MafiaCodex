"""Core game engine for Mafia bot."""
from __future__ import annotations

import asyncio
import datetime as dt
import random
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Tuple

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
    potato_ready: bool = False
    potato_used: bool = False
    night_action: Optional[int] = None
    check_results: List[str] = field(default_factory=list)

    def label(self) -> str:
        return visual.mention(self.name, self.user_id) if not self.is_bot else self.name


@dataclass
class GameState:
    chat_id: int
    game_id: int
    bukovel: bool
    phase: str = "lobby"
    round_no: int = 0
    players: Dict[int, PlayerState] = field(default_factory=dict)
    lobby_message_id: Optional[int] = None
    countdown_task: Optional[asyncio.Task] = None
    timer_message: Optional[Message] = None
    vote_yes_no: Dict[int, bool] = field(default_factory=dict)
    nominations: Dict[int, int] = field(default_factory=dict)
    confirmations: Dict[int, bool] = field(default_factory=dict)
    pending_candidate: Optional[int] = None
    acting_don: Optional[int] = None
    executioner_immunity: bool = True

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
                state = GameState(chat_id=chat_id, game_id=game_id, bukovel=bukovel, phase="day", round_no=1)
                for idx, row in enumerate(players, start=1):
                    state.players[idx] = PlayerState(
                        name=row["name"],
                        user_id=row.get("user_id"),
                        is_bot=row["is_bot"],
                        role=row["role"],
                        alive=row["is_alive"],
                        potato_ready=bukovel and row["role"] == "civil",
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
        state.bukovel = bukovel
        state.game_id = await db.create_game(chat.id, bukovel)
        state.vote_yes_no.clear()
        state.nominations.clear()
        state.confirmations.clear()
        state.pending_candidate = None
        state.executioner_immunity = True
        return state

    async def add_player(self, chat_id: int, user_id: int, name: str) -> Optional[str]:
        state = await self.ensure_game(chat_id)
        if state.phase != "lobby":
            return "Гра вже йде."
        if len(state.players) >= config.MAX_PLAYERS:
            return "Переповнено."
        if any(p.user_id == user_id for p in state.players.values() if not p.is_bot):
            return "Ти вже записаний."
        pid = max(state.players.keys(), default=0) + 1
        state.players[pid] = PlayerState(name=name, user_id=user_id, is_bot=False)
        return None

    async def add_bot(self, chat_id: int) -> Optional[str]:
        state = await self.ensure_game(chat_id)
        if state.phase != "lobby":
            return "Пізно, двері закрились."
        if len(state.players) >= config.MAX_PLAYERS:
            return "Переповнено."
        if sum(1 for p in state.players.values() if p.is_bot) >= config.MAX_BOTS:
            return "Досить блямкання ботів."
        pid = max(state.players.keys(), default=0) + 1
        state.players[pid] = PlayerState(name=random.choice(visual.BOT_NAMES), user_id=None, is_bot=True)
        return None

    async def list_players(self, chat_id: int) -> Tuple[List[str], List[str]]:
        state = await self.ensure_game(chat_id)
        humans = [p.label() for p in state.players.values() if not p.is_bot]
        bots = [p.label() for p in state.players.values() if p.is_bot]
        return humans, bots

    async def can_start(self, chat_id: int) -> bool:
        state = await self.ensure_game(chat_id)
        return len(state.players) >= config.MIN_PLAYERS

    async def assign_roles(self, state: GameState) -> None:
        count = len(state.players)
        roles: List[str] = ["don"]
        if count >= config.MAFIA_EXTRA_THRESHOLD:
            roles.append("mafia")
        roles.extend(["doctor", "detective", "executioner"])
        if config.ALLOW_DEPUTY:
            roles.append("deputy")
        if config.ALLOW_CONSILGIERE:
            roles.append("consigliere")
        if config.ALLOW_MAYOR:
            roles.append("mayor")
        if config.ALLOW_PETRUSHKA:
            roles.append("petrushka")
        while len(roles) < count:
            roles.append("civil")
        random.shuffle(roles)

        human_ids = [pid for pid, p in state.players.items() if not p.is_bot]
        if "detective" in roles and human_ids:
            det_index = roles.index("detective")
            target_pid = random.choice(human_ids)
            pid_list = list(state.players.keys())
            swap_index = pid_list.index(target_pid)
            roles[det_index], roles[swap_index] = roles[swap_index], roles[det_index]

        active_pool = [r for r in roles if r != "civil"] or ["don"]
        pid_order = list(state.players.keys())
        for idx, pid in enumerate(pid_order):
            role = roles[idx]
            player = state.players[pid]
            if player.user_id and await db.consume_active_role_buff(player.user_id) and role == "civil":
                role = random.choice(active_pool)
            player.role = role
            if state.bukovel and role == "civil":
                player.potato_ready = True
            await db.add_game_player(state.game_id, player.user_id, player.name, role, player.is_bot)

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
                pass

    async def start_game(self, chat: Chat, context: ContextTypes.DEFAULT_TYPE) -> str:
        state = await self.ensure_game(chat.id)
        if state.phase != "lobby":
            return "Гра вже йде."
        if len(state.players) < config.MIN_PLAYERS:
            return "Мало людей."
        await self.assign_roles(state)
        await self.send_roles(state, context)
        if state.bukovel:
            await context.bot.send_message(chat.id, visual.bukovel_intro())
        await self.start_night(state, context)
        return "Старт"

    async def start_night(self, state: GameState, context: ContextTypes.DEFAULT_TYPE) -> None:
        state.phase = "night"
        state.round_no += 1
        state.vote_yes_no.clear()
        state.nominations.clear()
        state.confirmations.clear()
        state.pending_candidate = None
        for p in state.players.values():
            p.night_action = None
        await context.bot.send_animation(chat_id=state.chat_id, animation="night.gif", caption=visual.night_intro())
        await self._schedule_timer(state, context, config.NIGHT_DURATION)
        await self._request_night_actions(state, context)

    async def _schedule_timer(self, state: GameState, context: ContextTypes.DEFAULT_TYPE, duration: int) -> None:
        if state.countdown_task:
            state.countdown_task.cancel()
        state.countdown_task = asyncio.create_task(self._run_countdown(state, context, duration))

    async def _run_countdown(self, state: GameState, context: ContextTypes.DEFAULT_TYPE, duration: int) -> None:
        remaining = duration
        while remaining >= 0 and state.phase != "ended":
            text = visual.get_phase_timer_text(state.phase, remaining)
            if state.timer_message is None:
                state.timer_message = await context.bot.send_message(state.chat_id, text, parse_mode=ParseMode.HTML)
            else:
                try:
                    await state.timer_message.edit_text(text, parse_mode=ParseMode.HTML)
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
        alive = list(state.alive_players().keys())
        for pid, player in state.alive_players().items():
            if player.is_bot:
                await self._auto_action(state, pid)
                continue
            actionable = player.role in {"don", "mafia", "doctor", "detective", "deputy", "consigliere", "petrushka"}
            if player.potato_ready and not player.potato_used:
                actionable = True
            if not actionable:
                continue
            targets = [(i, state.players[i].name) for i in alive if i != pid]
            keyboard = visual.build_night_action_keyboard("potato" if player.potato_ready and not player.potato_used else player.role, targets)
            try:
                await context.bot.send_message(
                    chat_id=player.user_id,
                    text=visual.night_action_log(player.role if not player.potato_ready else "potato"),
                    reply_markup=keyboard,
                )
            except Exception:
                pass

    async def _auto_action(self, state: GameState, pid: int) -> None:
        player = state.players[pid]
        alive = [i for i in state.alive_players().keys() if i != pid]
        if not alive:
            return
        if player.role in {"don", "mafia"}:
            player.night_action = random.choice(alive)
        elif player.role == "doctor":
            choice = random.choice(alive)
            if choice == pid and player.self_heal_used:
                choice = random.choice([i for i in alive if i != pid] or alive)
            if choice == pid:
                player.self_heal_used = True
            player.night_action = choice
        elif player.role in {"deputy", "consigliere", "petrushka"}:
            player.night_action = random.choice(alive)
        elif player.potato_ready and not player.potato_used:
            player.night_action = random.choice(alive)

    async def handle_action(self, query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not query.data or not query.data.startswith("act:"):
            return
        parts = query.data.split(":")
        if len(parts) != 3:
            return
        role, target_raw = parts[1], parts[2]
        target = int(target_raw)
        user_id = query.from_user.id
        for state in self.games.values():
            for pid, player in state.alive_players().items():
                if player.user_id == user_id:
                    if state.phase != "night":
                        await query.answer("Не зараз", show_alert=True)
                        return
                    player.night_action = None if target < 0 else target
                    if role == "potato":
                        player.potato_used = True
                    await query.answer("Записано")
                    try:
                        await query.edit_message_text(visual.night_action_log(role))
                    except Exception:
                        pass
                    return
        await query.answer("Не знайдено гру", show_alert=True)

    async def resolve_night(self, state: GameState, context: ContextTypes.DEFAULT_TYPE) -> None:
        if state.phase != "night":
            return
        kills: List[int] = []
        saved: List[int] = []

        don_pid = next((pid for pid, p in state.alive_players().items() if p.role == "don" and p.night_action), None)
        mafia_pid = next((pid for pid, p in state.alive_players().items() if p.role == "mafia" and p.night_action), None)
        acting_killer = don_pid or mafia_pid
        if acting_killer:
            kills.append(state.players[acting_killer].night_action)

        detective_pid = next((pid for pid, p in state.alive_players().items() if p.role == "detective"), None)
        if detective_pid:
            det = state.players[detective_pid]
            if det.night_action is not None:
                target_role = state.players[det.night_action].role if det.night_action in state.players else "невідомо"
                det.check_results.append(f"{state.players[det.night_action].name}: {visual.ROLE_LABELS.get(target_role, target_role)}")
                try:
                    await context.bot.send_message(det.user_id, f"Результат: {det.check_results[-1]}")
                except Exception:
                    pass

        deputy_pid = next((pid for pid, p in state.alive_players().items() if p.role == "deputy" and p.night_action), None)
        if deputy_pid:
            target_role = state.players[state.players[deputy_pid].night_action].role
            try:
                await context.bot.send_message(state.players[deputy_pid].user_id, f"Бачу роль: {visual.ROLE_LABELS.get(target_role, target_role)}")
            except Exception:
                pass

        consigliere_pid = next((pid for pid, p in state.alive_players().items() if p.role == "consigliere" and p.night_action), None)
        if consigliere_pid:
            target_role = state.players[state.players[consigliere_pid].night_action].role
            mafia_players = [pl for pl in state.players.values() if pl.role in {"don", "mafia", "consigliere"} and pl.user_id]
            for mp in mafia_players:
                try:
                    await context.bot.send_message(mp.user_id, f"Консильєрі дізнався: {state.players[consigliere_pid].name} -> {visual.ROLE_LABELS.get(target_role, target_role)}")
                except Exception:
                    pass

        petrushka_pid = next((pid for pid, p in state.alive_players().items() if p.role == "petrushka" and p.night_action), None)
        if petrushka_pid is not None:
            target_pid = state.players[petrushka_pid].night_action
            if target_pid in state.players and state.players[target_pid].alive:
                candidates = [r for r in visual.ROLE_LABELS.keys() if r != "detective"]
                state.players[target_pid].role = random.choice(candidates)
                try:
                    await context.bot.send_message(state.players[target_pid].user_id, "Твоя доля різко змінилась. Роль замінена.")
                except Exception:
                    pass

        doc_pid = next((pid for pid, p in state.alive_players().items() if p.role == "doctor" and p.night_action is not None), None)
        if doc_pid is not None:
            target = state.players[doc_pid].night_action
            saved.append(target)
            if target == doc_pid:
                state.players[doc_pid].self_heal_used = True
            await context.bot.send_message(state.chat_id, visual.night_action_log("doctor"))

        for pid, player in state.alive_players().items():
            if player.potato_used and player.night_action is not None:
                if random.random() < 0.5:
                    kills.append(player.night_action)
                    await context.bot.send_message(state.chat_id, visual.potato_throw(state.players[player.night_action].label()))

        final_kills: List[int] = []
        for victim in kills:
            if victim is None:
                continue
            if victim in saved:
                continue
            if victim not in final_kills:
                final_kills.append(victim)

        killed_names: List[str] = []
        for victim in final_kills:
            target = state.players.get(victim)
            if target and target.alive:
                target.alive = False
                killed_names.append(target.label())
                await db.update_game_player_status(state.game_id, target.name, False)

        saved_names = [state.players[s].label() for s in saved if s in state.players and state.players[s].alive]
        await context.bot.send_animation(state.chat_id, animation="morning.gif", caption=visual.morning_intro())
        await context.bot.send_message(state.chat_id, visual.morning_report(killed_names, saved_names), parse_mode=ParseMode.HTML)
        await context.bot.send_message(state.chat_id, visual.format_stats_block([p.label() for p in state.alive_players().values()], [p.label() for p in state.players.values() if not p.alive]), parse_mode=ParseMode.HTML)
        await self.check_win(state, context)
        if state.phase != "ended":
            await self.start_day(state, context)

    async def start_day(self, state: GameState, context: ContextTypes.DEFAULT_TYPE) -> None:
        state.phase = "day"
        await self._schedule_timer(state, context, config.DAY_DURATION)

    async def start_vote(self, state: GameState, context: ContextTypes.DEFAULT_TYPE) -> None:
        state.phase = "vote"
        state.vote_yes_no.clear()
        state.nominations.clear()
        state.pending_candidate = None
        await context.bot.send_animation(state.chat_id, animation="vote.gif", caption=visual.vote_intro())
        await context.bot.send_message(state.chat_id, "Ріжемо когось?", reply_markup=visual.build_vote_keyboard())
        await self._schedule_timer(state, context, config.VOTE_DURATION)

    async def vote_callback(self, query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE) -> None:
        if query.data not in {"vote_yes", "vote_no"}:
            return
        chat_id = query.message.chat.id if query.message else None
        if chat_id is None:
            return
        state = self.games.get(chat_id)
        if not state or state.phase != "vote":
            return
        vote_yes = query.data == "vote_yes"
        state.vote_yes_no[query.from_user.id] = vote_yes
        await query.answer("Голос зафіксовано")

    async def finish_vote(self, state: GameState, context: ContextTypes.DEFAULT_TYPE) -> None:
        yes = sum(1 for v in state.vote_yes_no.values() if v)
        no = len(state.vote_yes_no) - yes
        if yes <= no:
            await context.bot.send_message(state.chat_id, visual.event_text("night_no_kick"))
            await self.start_night(state, context)
            return
        await self.start_nominations(state, context)

    async def start_nominations(self, state: GameState, context: ContextTypes.DEFAULT_TYPE) -> None:
        alive_ids = list(state.alive_players().keys())
        for pid, player in state.alive_players().items():
            if player.is_bot:
                target = random.choice([i for i in alive_ids if i != pid]) if len(alive_ids) > 1 else None
                if target:
                    state.nominations[pid] = target
                continue
            try:
                keyboard = visual.build_nomination_keyboard([(i, state.players[i].name) for i in alive_ids if i != pid])
                await context.bot.send_message(chat_id=player.user_id, text="Кого висуваєш?", reply_markup=keyboard)
            except Exception:
                pass
        await asyncio.sleep(10)
        await self.pick_nomination(state, context)

    async def handle_nomination(self, query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not query.data or not query.data.startswith("nom:"):
            return
        target = int(query.data.split(":")[1])
        user_id = query.from_user.id
        for state in self.games.values():
            for pid, player in state.alive_players().items():
                if player.user_id == user_id and state.phase == "vote":
                    if target > 0:
                        state.nominations[pid] = target
                    await query.answer("Занотовано")
                    try:
                        await query.edit_message_text("Підозрюваний занесений.")
                    except Exception:
                        pass
                    return

    async def pick_nomination(self, state: GameState, context: ContextTypes.DEFAULT_TYPE) -> None:
        threshold = (len(state.alive_players()) + 1) // 2
        counts: Dict[int, int] = {}
        for target in state.nominations.values():
            counts[target] = counts.get(target, 0) + 1
        if not counts:
            await context.bot.send_message(state.chat_id, visual.event_text("night_no_kick"))
            await self.start_night(state, context)
            return
        candidate, votes = max(counts.items(), key=lambda x: x[1])
        if votes < threshold:
            await context.bot.send_message(state.chat_id, "Ніхто не набрав голосів. Вижили всі.")
            await self.start_night(state, context)
            return
        state.pending_candidate = candidate
        await context.bot.send_message(state.chat_id, f"Підвішуємо {state.players[candidate].label()}? Підтвердіть в особистих.")
        await self.ask_confirmations(state, context)

    async def ask_confirmations(self, state: GameState, context: ContextTypes.DEFAULT_TYPE) -> None:
        state.confirmations.clear()
        candidate = state.pending_candidate
        if candidate is None:
            return
        for pid, player in state.alive_players().items():
            if pid == candidate:
                continue
            if player.is_bot:
                state.confirmations[pid] = random.random() > 0.3
                continue
            try:
                await context.bot.send_message(
                    chat_id=player.user_id,
                    text=f"Чи підтверджуєш страту {state.players[candidate].name}?",
                    reply_markup=visual.build_confirmation_keyboard(state.players[candidate].name),
                )
            except Exception:
                pass
        await asyncio.sleep(10)
        await self.finish_confirmation(state, context)

    async def handle_confirmation(self, query: CallbackQuery, context: ContextTypes.DEFAULT_TYPE) -> None:
        if query.data not in {"confirm_yes", "confirm_no"}:
            return
        user_id = query.from_user.id
        for state in self.games.values():
            if state.phase != "vote":
                continue
            for pid, player in state.alive_players().items():
                if player.user_id == user_id and pid != state.pending_candidate:
                    state.confirmations[pid] = query.data == "confirm_yes"
                    await query.answer("Голос прийнято")
                    try:
                        await query.edit_message_text("Рішення занотоване")
                    except Exception:
                        pass
                    return

    async def finish_confirmation(self, state: GameState, context: ContextTypes.DEFAULT_TYPE) -> None:
        candidate = state.pending_candidate
        if candidate is None:
            await self.start_night(state, context)
            return
        yes = sum(1 for v in state.confirmations.values() if v)
        needed = (len(state.alive_players()) // 2)
        target = state.players[candidate]
        if yes <= needed:
            await context.bot.send_message(state.chat_id, "Не зійшлись. Кандидат живе.")
            await self.start_night(state, context)
            return
        rope_break_chance = 0.5 if target.role == "executioner" and state.executioner_immunity else 0.1
        if any(p.role == "executioner" and p.alive and p != target for p in state.players.values()):
            rope_break_chance = max(0.05, rope_break_chance - 0.2)
        if random.random() < rope_break_chance:
            await context.bot.send_message(state.chat_id, visual.event_text("rope_break"))
            if target.role == "executioner":
                state.executioner_immunity = False
            await self.start_night(state, context)
            return
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
            await self.award_points(state, civil_win=True)
            state.phase = "ended"
        elif mafia_alive >= civil_alive:
            await context.bot.send_animation(state.chat_id, animation="lost_civil.gif", caption=visual.event_text("event_mafia_win"))
            await db.end_game(state.game_id, "mafia")
            await self.award_points(state, civil_win=False)
            state.phase = "ended"

    async def award_points(self, state: GameState, civil_win: bool) -> None:
        for player in state.players.values():
            if player.is_bot or not player.user_id:
                continue
            win = (player.role in {"don", "mafia", "consigliere"} and not civil_win) or (player.role not in {"don", "mafia", "consigliere"} and civil_win)
            delta = config.POINTS_WIN if win else config.POINTS_LOSE
            await db.update_points_by_user_id(player.user_id, delta, win)

    async def cancel_game(self, chat_id: int) -> str:
        state = await self.ensure_game(chat_id)
        state.phase = "ended"
        state.players.clear()
        return "Гру зупинено."


# Handlers
async def command_newgame(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        await update.message.reply_text("Працюю тільки в групах.")
        return
    manager: GameManager = context.bot_data["manager"]
    bukovel = config.ALLOW_BUKOVEL and random.random() < 0.25
    state = await manager.start_new_game(update.effective_chat, bukovel=bukovel)
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
        f"Фаза: {visual.PHASE_TITLES.get(state.phase, state.phase)}\n" + visual.format_stats_block(alive, dead),
        parse_mode=ParseMode.HTML,
    )


async def command_start_dm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await db.register_user(update.effective_user.id, update.effective_user.username)
    await update.message.reply_text("Ти в базі. Чекай ролі в іграх.")


async def command_profile(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    info = await db.fetch_user_by_tg(update.effective_user.id)
    if not info:
        await update.message.reply_text("Ти ще не грав. Зайди в групу з ботом.")
        return
    buffs = await db.get_user_buffs(info["id"])
    buffs_text = "\n".join([f"{b['buff_type']} ({b['remaining_games']} ігор)" for b in buffs]) or "Нічого"
    await update.message.reply_text(
        f"Очки: {info['total_points']}\nІгор: {info['total_games']}\nПеремог: {info['total_wins']}\nБафів: {buffs_text}"
    )


async def command_shop(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    items = await db.list_shop_items()
    await update.message.reply_text("Крамничка бафів:", reply_markup=visual.build_shop_keyboard(items))


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
        await query.answer(err or "Ти в грі. Не забудь /start у приваті.")
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
        await query.answer(err or "Бот доданий.")
    elif data.startswith("start_game"):
        can_start = await manager.can_start(query.message.chat.id)
        if not can_start:
            await query.answer("Мало людей", show_alert=True)
            return
        await manager.start_game(query.message.chat, context)
        await query.answer("Починаємо")
    elif data.startswith("shop:"):
        user = await db.fetch_user_by_tg(query.from_user.id)
        if not user:
            await query.answer("Спершу /start", show_alert=True)
            return
        result = await db.purchase_item(user["id"], data.split(":")[1])
        await query.answer(result, show_alert=True)
    elif data.startswith("vote_"):
        await manager.vote_callback(query, context)
    elif data.startswith("nom:"):
        await manager.handle_nomination(query, context)
    elif data.startswith("confirm_"):
        await manager.handle_confirmation(query, context)


async def moderate_messages(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.effective_message
    if not message:
        return
    chat_id = message.chat.id
    manager: GameManager = context.bot_data.get("manager")
    if not manager or chat_id not in manager.games:
        return
    state = manager.games[chat_id]
    if message.from_user and any(p.user_id == message.from_user.id and not p.alive for p in state.players.values() if p.user_id):
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
    app.add_handler(CallbackQueryHandler(manager.handle_nomination, pattern=r"^nom:"))
    app.add_handler(CallbackQueryHandler(manager.handle_confirmation, pattern=r"^confirm_"))
    app.add_handler(CallbackQueryHandler(manager.vote_callback, pattern=r"^vote_"))
    app.add_handler(MessageHandler(filters.ChatType.GROUPS, moderate_messages))
