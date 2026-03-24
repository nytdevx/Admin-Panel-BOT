"""
QuizMaster Pro — Telegram Admin Bot
Single-file, production-ready implementation using aiogram 3.x + aiohttp + aiosqlite
"""

import asyncio
import json
import logging
import math
import os
from datetime import datetime, date
from typing import Optional

import aiosqlite
from aiohttp import web
from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    BufferedInputFile,
)
from dotenv import load_dotenv

load_dotenv()

# ─────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────
BOT_TOKEN       = os.getenv("BOT_TOKEN", "")
ADMIN_CHAT_ID   = int(os.getenv("ADMIN_CHAT_ID", "0"))
WEBAPP_SECRET   = os.getenv("WEBAPP_SECRET", "secret")
PORT            = int(os.getenv("PORT", "8000"))
DB_PATH         = "quizmaster.db"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger(__name__)

USERS_PER_PAGE = 5

# ─────────────────────────────────────────────
# Rank emoji map
# ─────────────────────────────────────────────
RANK_EMOJI = {
    "rookie":   "⭐",
    "scholar":  "📘",
    "pro":      "🔷",
    "master":   "👑",
    "legend":   "🏆",
}

SUBJECT_EMOJI = {
    "physics":   "⚛️",
    "chemistry": "🧪",
    "biology":   "🧬",
    "bangla":    "🇧🇩",
    "english":   "🔤",
    "ict":       "💻",
    "gk":        "🌐",
}

def rank_emoji(rank: str) -> str:
    return RANK_EMOJI.get(rank.lower(), "🎖️")

def subject_emoji(subject: str) -> str:
    return SUBJECT_EMOJI.get(subject.lower(), "📖")

def fmt_lang(lang: str) -> str:
    return "English" if lang.lower() == "en" else "Bengali" if lang.lower() == "bn" else lang

# ─────────────────────────────────────────────
# FSM States
# ─────────────────────────────────────────────
class SearchState(StatesGroup):
    waiting_for_query = State()

# ─────────────────────────────────────────────
# Database helpers
# ─────────────────────────────────────────────
async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                name          TEXT NOT NULL UNIQUE,
                lang          TEXT DEFAULT 'en',
                total_pts     INTEGER DEFAULT 0,
                total_solved  INTEGER DEFAULT 0,
                total_correct INTEGER DEFAULT 0,
                rank          TEXT DEFAULT 'Rookie',
                registered_at TEXT NOT NULL,
                last_seen     TEXT NOT NULL
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS subject_stats (
                id      INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                subject TEXT NOT NULL,
                pts     INTEGER DEFAULT 0,
                solved  INTEGER DEFAULT 0,
                correct INTEGER DEFAULT 0,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
                UNIQUE(user_id, subject)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS events (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type   TEXT NOT NULL,
                user_name    TEXT NOT NULL,
                details_json TEXT,
                created_at   TEXT NOT NULL
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
        # Default setting: notifications ON
        await db.execute("""
            INSERT OR IGNORE INTO settings (key, value) VALUES ('notifications', '1')
        """)
        await db.commit()
    log.info("Database initialised.")


async def get_setting(key: str) -> str:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT value FROM settings WHERE key=?", (key,)) as cur:
            row = await cur.fetchone()
            return row[0] if row else ""


async def set_setting(key: str, value: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value)
        )
        await db.commit()


async def upsert_user(name: str, lang: str, now: str):
    """Insert new user or update last_seen on re-registration."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT id FROM users WHERE name=?", (name,)) as cur:
            row = await cur.fetchone()
        if row is None:
            await db.execute(
                "INSERT INTO users (name, lang, registered_at, last_seen) VALUES (?, ?, ?, ?)",
                (name, lang, now, now),
            )
        else:
            await db.execute(
                "UPDATE users SET last_seen=?, lang=? WHERE name=?",
                (now, lang, name),
            )
        await db.commit()


async def update_user_stats(
    name: str,
    lang: str,
    total_pts: int,
    total_solved: int,
    total_correct: int,
    rank: str,
    now: str,
    subjects: dict,
):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT id FROM users WHERE name=?", (name,)) as cur:
            row = await cur.fetchone()
        if row is None:
            await db.execute(
                """INSERT INTO users
                   (name, lang, total_pts, total_solved, total_correct, rank, registered_at, last_seen)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (name, lang, total_pts, total_solved, total_correct, rank, now, now),
            )
            async with db.execute("SELECT last_insert_rowid()") as cur2:
                user_id = (await cur2.fetchone())[0]
        else:
            user_id = row[0]
            await db.execute(
                """UPDATE users SET lang=?, total_pts=?, total_solved=?, total_correct=?,
                   rank=?, last_seen=? WHERE id=?""",
                (lang, total_pts, total_solved, total_correct, rank, now, user_id),
            )

        for subject, stats in subjects.items():
            await db.execute(
                """INSERT INTO subject_stats (user_id, subject, pts, solved, correct)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(user_id, subject)
                   DO UPDATE SET pts=excluded.pts, solved=excluded.solved, correct=excluded.correct""",
                (user_id, subject, stats.get("pts", 0), stats.get("solved", 0), stats.get("correct", 0)),
            )
        await db.commit()


async def update_user_rank(name: str, total_pts: int, rank: str, now: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE users SET total_pts=?, rank=?, last_seen=? WHERE name=?",
            (total_pts, rank, now, name),
        )
        await db.commit()


async def touch_user_last_seen(name: str, now: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET last_seen=? WHERE name=?", (now, name))
        await db.commit()


async def log_event(event_type: str, user_name: str, details: dict, now: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO events (event_type, user_name, details_json, created_at) VALUES (?, ?, ?, ?)",
            (event_type, user_name, json.dumps(details), now),
        )
        await db.commit()


async def get_all_users(offset: int = 0, limit: int = USERS_PER_PAGE):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM users ORDER BY total_pts DESC LIMIT ? OFFSET ?", (limit, offset)
        ) as cur:
            return await cur.fetchall()


async def count_users() -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM users") as cur:
            return (await cur.fetchone())[0]


async def get_user_by_id(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM users WHERE id=?", (user_id,)) as cur:
            return await cur.fetchone()


async def get_user_subjects(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM subject_stats WHERE user_id=? ORDER BY pts DESC", (user_id,)
        ) as cur:
            return await cur.fetchall()


async def delete_user(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM subject_stats WHERE user_id=?", (user_id,))
        await db.execute("DELETE FROM users WHERE id=?", (user_id,))
        await db.commit()


async def search_users(query: str):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM users WHERE LOWER(name) LIKE ? ORDER BY total_pts DESC",
            (f"%{query.lower()}%",),
        ) as cur:
            return await cur.fetchall()


async def get_leaderboard(limit: int = 10):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM users ORDER BY total_pts DESC LIMIT ?", (limit,)
        ) as cur:
            return await cur.fetchall()


async def get_today_events():
    today = date.today().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM events WHERE created_at LIKE ? ORDER BY created_at ASC",
            (f"{today}%",),
        ) as cur:
            return await cur.fetchall()


async def count_new_today() -> int:
    today = date.today().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT COUNT(*) FROM users WHERE registered_at LIKE ?", (f"{today}%",)
        ) as cur:
            return (await cur.fetchone())[0]


async def count_active_today() -> int:
    today = date.today().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT COUNT(*) FROM users WHERE last_seen LIKE ?", (f"{today}%",)
        ) as cur:
            return (await cur.fetchone())[0]


async def count_quizzes_today() -> int:
    today = date.today().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT COUNT(*) FROM events WHERE event_type='quiz_end' AND created_at LIKE ?",
            (f"{today}%",),
        ) as cur:
            return (await cur.fetchone())[0]


async def total_quizzes() -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT COUNT(*) FROM events WHERE event_type='quiz_end'"
        ) as cur:
            return (await cur.fetchone())[0]


async def total_points_awarded() -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COALESCE(SUM(total_pts), 0) FROM users") as cur:
            return (await cur.fetchone())[0]


async def rank_distribution() -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT LOWER(rank), COUNT(*) FROM users GROUP BY LOWER(rank)"
        ) as cur:
            rows = await cur.fetchall()
            return {r[0]: r[1] for r in rows}


async def export_all_data() -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row

        async with db.execute("SELECT * FROM users") as cur:
            users = [dict(r) for r in await cur.fetchall()]

        async with db.execute("SELECT * FROM subject_stats") as cur:
            subjects = [dict(r) for r in await cur.fetchall()]

        async with db.execute("SELECT * FROM events") as cur:
            events = [dict(r) for r in await cur.fetchall()]

    return {"users": users, "subject_stats": subjects, "events": events}


async def clear_all_data():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM subject_stats")
        await db.execute("DELETE FROM users")
        await db.execute("DELETE FROM events")
        await db.commit()

# ─────────────────────────────────────────────
# Keyboard builders
# ─────────────────────────────────────────────
def main_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="👥 All Users",       callback_data="menu:users:0"),
            InlineKeyboardButton(text="📊 Stats Overview",  callback_data="menu:stats"),
        ],
        [
            InlineKeyboardButton(text="🏆 Leaderboard",     callback_data="menu:leaderboard"),
            InlineKeyboardButton(text="🔍 Search User",     callback_data="menu:search"),
        ],
        [
            InlineKeyboardButton(text="📅 Today's Activity", callback_data="menu:today"),
            InlineKeyboardButton(text="⚙️ Settings",         callback_data="menu:settings"),
        ],
    ])


def users_list_kb(page: int, total: int) -> InlineKeyboardMarkup:
    total_pages = max(1, math.ceil(total / USERS_PER_PAGE))
    nav_row = [
        InlineKeyboardButton(
            text="◀️ Prev",
            callback_data=f"menu:users:{max(0, page - 1)}" if page > 0 else "noop",
        ),
        InlineKeyboardButton(
            text=f"📄 {page + 1}/{total_pages}",
            callback_data="noop",
        ),
        InlineKeyboardButton(
            text="Next ▶️",
            callback_data=f"menu:users:{page + 1}" if (page + 1) < total_pages else "noop",
        ),
    ]
    return InlineKeyboardMarkup(inline_keyboard=[
        nav_row,
        [InlineKeyboardButton(text="🔙 Back to Menu", callback_data="menu:main")],
    ])


def user_profile_kb(user_id: int, page: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🗑️ Delete User",   callback_data=f"user:delete:{user_id}"),
            InlineKeyboardButton(text="🔙 Back to List",  callback_data=f"menu:users:{page}"),
        ],
    ])


def confirm_delete_kb(user_id: int, page: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Yes, Delete",  callback_data=f"user:confirm_delete:{user_id}:{page}"),
            InlineKeyboardButton(text="❌ Cancel",       callback_data=f"user:profile:{user_id}:{page}"),
        ],
    ])


def settings_kb(notif_on: bool) -> InlineKeyboardMarkup:
    notif_label = "🔔 Notifications: ON" if notif_on else "🔕 Notifications: OFF"
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=notif_label,          callback_data="settings:toggle_notif")],
        [InlineKeyboardButton(text="🧹 Clear All Data",  callback_data="settings:clear_confirm")],
        [InlineKeyboardButton(text="📤 Export Data as JSON", callback_data="settings:export")],
        [InlineKeyboardButton(text="🔙 Back",            callback_data="menu:main")],
    ])


def confirm_clear_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Yes, Clear All", callback_data="settings:clear_execute"),
            InlineKeyboardButton(text="❌ Cancel",         callback_data="menu:settings"),
        ],
    ])


def back_to_menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Back to Menu", callback_data="menu:main")],
    ])


def search_results_kb(users, page: int = 0) -> InlineKeyboardMarkup:
    rows = []
    for u in users:
        rows.append([
            InlineKeyboardButton(
                text=f"👤 {u['name']}",
                callback_data=f"user:profile:{u['id']}:{page}",
            )
        ])
    rows.append([InlineKeyboardButton(text="🔙 Back to Menu", callback_data="menu:main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)

# ─────────────────────────────────────────────
# Message formatters
# ─────────────────────────────────────────────
def accuracy(correct: int, solved: int) -> str:
    if solved == 0:
        return "N/A"
    return f"{round(correct / solved * 100)}%"


def format_user_profile(user, subjects) -> str:
    re = rank_emoji(user["rank"])
    acc = accuracy(user["total_correct"], user["total_solved"])
    reg = user["registered_at"]
    seen = user["last_seen"]
    lang = fmt_lang(user["lang"] or "en")

    lines = [
        f"👤 <b>Name:</b> {user['name']}",
        f"🌐 <b>Language:</b> {lang}",
        f"🎖️ <b>Rank:</b> {user['rank'].title()} {re}",
        f"💰 <b>Total Points:</b> {user['total_pts']}",
        f"✅ <b>Total Solved:</b> {user['total_solved']}",
        f"🎯 <b>Accuracy:</b> {acc}",
        "",
        "📚 <b>Subject Breakdown:</b>",
    ]
    for s in subjects:
        se = subject_emoji(s["subject"])
        s_acc = accuracy(s["correct"], s["solved"])
        lines.append(
            f"  {se} <b>{s['subject'].title():<10}</b> → {s['pts']} pts | "
            f"{s['solved']} solved | {s_acc} acc"
        )
    if not subjects:
        lines.append("  — No quiz sessions yet —")

    lines += [
        "",
        f"🕐 <b>Registered:</b> {reg}",
        f"📅 <b>Last Seen:</b>  {seen}",
    ]
    return "\n".join(lines)


async def format_users_page(page: int):
    offset = page * USERS_PER_PAGE
    users = await get_all_users(offset=offset, limit=USERS_PER_PAGE)
    total = await count_users()
    total_pages = max(1, math.ceil(total / USERS_PER_PAGE))

    lines = [f"👥 <b>All Users</b> — Page {page + 1}/{total_pages}\n"]
    for i, u in enumerate(users, start=offset + 1):
        re = rank_emoji(u["rank"])
        acc = accuracy(u["total_correct"], u["total_solved"])
        lines.append(
            f"{i}. <b>{u['name']}</b> — {u['rank'].title()} {re}\n"
            f"   💰 {u['total_pts']} pts | 🎯 {acc}\n"
        )

    # Add clickable user buttons
    user_buttons = [
        [InlineKeyboardButton(
            text=f"👤 {u['name']}",
            callback_data=f"user:profile:{u['id']}:{page}"
        )]
        for u in users
    ]
    total_pgs = max(1, math.ceil(total / USERS_PER_PAGE))
    nav_row = [
        InlineKeyboardButton(
            text="◀️ Prev",
            callback_data=f"menu:users:{max(0, page - 1)}" if page > 0 else "noop",
        ),
        InlineKeyboardButton(text=f"📄 {page + 1}/{total_pgs}", callback_data="noop"),
        InlineKeyboardButton(
            text="Next ▶️",
            callback_data=f"menu:users:{page + 1}" if (page + 1) < total_pgs else "noop",
        ),
    ]
    user_buttons.append(nav_row)
    user_buttons.append([InlineKeyboardButton(text="🔙 Back to Menu", callback_data="menu:main")])
    kb = InlineKeyboardMarkup(inline_keyboard=user_buttons)

    return "\n".join(lines), kb


async def format_stats_overview() -> str:
    total = await count_users()
    new_today = await count_new_today()
    active_today = await count_active_today()
    total_q = await total_quizzes()
    total_pts = await total_points_awarded()
    dist = await rank_distribution()

    ranks_order = ["rookie", "scholar", "pro", "master", "legend"]
    dist_lines = []
    for r in ranks_order:
        count = dist.get(r, 0)
        if count:
            dist_lines.append(f"  {rank_emoji(r)} {r.title():<8}: {count} users")

    return (
        "📊 <b>QuizMaster Pro — Overview</b>\n\n"
        f"👥 <b>Total Users:</b> {total}\n"
        f"🆕 <b>New Today:</b> {new_today}\n"
        f"📲 <b>Active Today:</b> {active_today}\n"
        f"🏆 <b>Total Quizzes Played:</b> {total_q}\n"
        f"💰 <b>Total Points Awarded:</b> {total_pts:,}\n\n"
        "🎖️ <b>Rank Distribution:</b>\n" + "\n".join(dist_lines or ["  — No users yet —"])
    )


async def format_leaderboard() -> str:
    users = await get_leaderboard()
    medals = ["🥇", "🥈", "🥉"]
    lines = ["🏆 <b>Leaderboard — Top 10</b>\n"]
    for i, u in enumerate(users, start=1):
        medal = medals[i - 1] if i <= 3 else f"{i}."
        re = rank_emoji(u["rank"])
        lines.append(f"{medal} <b>{u['name']}</b> — {u['total_pts']} pts {re} {u['rank'].title()}")
    if not users:
        lines.append("— No users yet —")
    return "\n".join(lines)


async def format_today_activity() -> str:
    events = await get_today_events()
    today_str = date.today().strftime("%b %d, %Y")
    lines = [f"📅 <b>Today's Activity — {today_str}</b>\n"]

    for ev in events:
        t = ev["created_at"][11:16]  # HH:MM
        details = json.loads(ev["details_json"] or "{}")
        et = ev["event_type"]

        if et == "register":
            lang = fmt_lang(details.get("lang", "en"))
            lines.append(f"🆕 {t} — New user: <b>{ev['user_name']}</b> ({lang})")
        elif et == "returning":
            pts = details.get("totalPts", 0)
            rank = details.get("rank", "")
            lines.append(f"📲 {t} — Returning: <b>{ev['user_name']}</b> ({pts} pts, {rank})")
        elif et == "milestone":
            pts = details.get("totalPts", 0)
            rank = details.get("rank", "")
            lines.append(f"🏆 {t} — Milestone: <b>{ev['user_name']}</b> reached {pts} pts → {rank}")
        elif et == "quiz_end":
            subj = details.get("sessionSubject", "?").title()
            score = details.get("sessionScore", 0)
            correct = details.get("sessionCorrect", 0)
            wrong = details.get("sessionWrong", 0)
            total_q = correct + wrong
            lines.append(
                f"🎯 {t} — Quiz ended: <b>{ev['user_name']}</b> | {subj} | "
                f"{correct}/{total_q} | +{score} pts"
            )

    if len(lines) == 1:
        lines.append("— No activity today —")
    return "\n".join(lines)

# ─────────────────────────────────────────────
# Bot + Dispatcher
# ─────────────────────────────────────────────
bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
)
dp = Dispatcher(storage=MemoryStorage())

# ─────────────────────────────────────────────
# Command handlers
# ─────────────────────────────────────────────
@dp.message(Command("start", "menu"))
async def cmd_start(message: Message):
    if message.from_user.id != ADMIN_CHAT_ID:
        await message.answer("⛔ Unauthorised.")
        return
    await message.answer(
        "👋 <b>Welcome to QuizMaster Pro Admin Panel</b>\n\nChoose an option below:",
        reply_markup=main_menu_kb(),
    )

# ─────────────────────────────────────────────
# Callback: main navigation
# ─────────────────────────────────────────────
@dp.callback_query(F.data == "noop")
async def cb_noop(cb: CallbackQuery):
    await cb.answer()


@dp.callback_query(F.data == "menu:main")
async def cb_main_menu(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.message.edit_text(
        "👋 <b>QuizMaster Pro Admin Panel</b>\n\nChoose an option below:",
        reply_markup=main_menu_kb(),
    )
    await cb.answer()


@dp.callback_query(F.data.startswith("menu:users:"))
async def cb_users_page(cb: CallbackQuery):
    page = int(cb.data.split(":")[2])
    text, kb = await format_users_page(page)
    await cb.message.edit_text(text, reply_markup=kb)
    await cb.answer()


@dp.callback_query(F.data == "menu:stats")
async def cb_stats(cb: CallbackQuery):
    text = await format_stats_overview()
    await cb.message.edit_text(text, reply_markup=back_to_menu_kb())
    await cb.answer()


@dp.callback_query(F.data == "menu:leaderboard")
async def cb_leaderboard(cb: CallbackQuery):
    text = await format_leaderboard()
    await cb.message.edit_text(text, reply_markup=back_to_menu_kb())
    await cb.answer()


@dp.callback_query(F.data == "menu:search")
async def cb_search_prompt(cb: CallbackQuery, state: FSMContext):
    await state.set_state(SearchState.waiting_for_query)
    await cb.message.edit_text(
        "🔍 <b>Search User</b>\n\nType a name to search:",
        reply_markup=back_to_menu_kb(),
    )
    await cb.answer()


@dp.callback_query(F.data == "menu:today")
async def cb_today(cb: CallbackQuery):
    text = await format_today_activity()
    await cb.message.edit_text(text, reply_markup=back_to_menu_kb())
    await cb.answer()


@dp.callback_query(F.data == "menu:settings")
async def cb_settings(cb: CallbackQuery):
    notif = await get_setting("notifications")
    await cb.message.edit_text(
        "⚙️ <b>Settings</b>",
        reply_markup=settings_kb(notif_on=(notif == "1")),
    )
    await cb.answer()

# ─────────────────────────────────────────────
# Callback: user profile
# ─────────────────────────────────────────────
@dp.callback_query(F.data.startswith("user:profile:"))
async def cb_user_profile(cb: CallbackQuery):
    parts = cb.data.split(":")
    user_id = int(parts[2])
    page    = int(parts[3]) if len(parts) > 3 else 0

    user = await get_user_by_id(user_id)
    if not user:
        await cb.answer("User not found.", show_alert=True)
        return

    subjects = await get_user_subjects(user_id)
    text = format_user_profile(user, subjects)
    await cb.message.edit_text(text, reply_markup=user_profile_kb(user_id, page))
    await cb.answer()


@dp.callback_query(F.data.startswith("user:delete:"))
async def cb_delete_confirm(cb: CallbackQuery):
    parts = cb.data.split(":")
    user_id = int(parts[2])
    page    = int(parts[3]) if len(parts) > 3 else 0

    user = await get_user_by_id(user_id)
    name = user["name"] if user else "Unknown"
    await cb.message.edit_text(
        f"⚠️ Are you sure you want to delete <b>{name}</b>?\nThis action cannot be undone.",
        reply_markup=confirm_delete_kb(user_id, page),
    )
    await cb.answer()


@dp.callback_query(F.data.startswith("user:confirm_delete:"))
async def cb_delete_execute(cb: CallbackQuery):
    parts = cb.data.split(":")
    user_id = int(parts[2])
    page    = int(parts[3]) if len(parts) > 3 else 0

    user = await get_user_by_id(user_id)
    name = user["name"] if user else "Unknown"
    await delete_user(user_id)

    text, kb = await format_users_page(page)
    await cb.message.edit_text(
        f"✅ <b>{name}</b> has been deleted.\n\n" + text, reply_markup=kb
    )
    await cb.answer("User deleted.")

# ─────────────────────────────────────────────
# Callback: settings
# ─────────────────────────────────────────────
@dp.callback_query(F.data == "settings:toggle_notif")
async def cb_toggle_notif(cb: CallbackQuery):
    current = await get_setting("notifications")
    new_val = "0" if current == "1" else "1"
    await set_setting("notifications", new_val)
    status = "enabled ✅" if new_val == "1" else "disabled 🔕"
    await cb.answer(f"Notifications {status}.", show_alert=True)
    await cb.message.edit_reply_markup(reply_markup=settings_kb(notif_on=(new_val == "1")))


@dp.callback_query(F.data == "settings:clear_confirm")
async def cb_clear_confirm(cb: CallbackQuery):
    await cb.message.edit_text(
        "⚠️ <b>Are you sure?</b>\n\nThis will permanently delete ALL users, stats, and events.",
        reply_markup=confirm_clear_kb(),
    )
    await cb.answer()


@dp.callback_query(F.data == "settings:clear_execute")
async def cb_clear_execute(cb: CallbackQuery):
    await clear_all_data()
    await cb.message.edit_text(
        "🧹 All data has been cleared.",
        reply_markup=back_to_menu_kb(),
    )
    await cb.answer("Data cleared.", show_alert=True)


@dp.callback_query(F.data == "settings:export")
async def cb_export(cb: CallbackQuery):
    await cb.answer("Preparing export…")
    data = await export_all_data()
    json_bytes = json.dumps(data, indent=2, ensure_ascii=False).encode("utf-8")
    filename = f"quizmaster_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    await bot.send_document(
        chat_id=ADMIN_CHAT_ID,
        document=BufferedInputFile(json_bytes, filename=filename),
        caption="📤 QuizMaster Pro — Full Data Export",
    )

# ─────────────────────────────────────────────
# FSM: search
# ─────────────────────────────────────────────
@dp.message(SearchState.waiting_for_query)
async def handle_search(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_CHAT_ID:
        return
    await state.clear()
    query = message.text.strip()
    users = await search_users(query)

    if not users:
        await message.answer(
            f"🔍 No users found matching <b>{query}</b>.",
            reply_markup=back_to_menu_kb(),
        )
        return

    lines = [f"🔍 <b>Search results for \"{query}\":</b> {len(users)} found\n"]
    for u in users:
        re = rank_emoji(u["rank"])
        acc = accuracy(u["total_correct"], u["total_solved"])
        lines.append(f"• <b>{u['name']}</b> — {u['rank'].title()} {re} | 💰 {u['total_pts']} pts | 🎯 {acc}")

    await message.answer(
        "\n".join(lines),
        reply_markup=search_results_kb(users),
    )

# ─────────────────────────────────────────────
# Auto-notification helper
# ─────────────────────────────────────────────
async def notify_admin(text: str):
    notif = await get_setting("notifications")
    if notif != "1":
        return
    try:
        await bot.send_message(ADMIN_CHAT_ID, text)
    except Exception as e:
        log.error(f"Failed to send admin notification: {e}")

# ─────────────────────────────────────────────
# aiohttp webhook handler — receives web app data
# ─────────────────────────────────────────────
async def handle_webapp_webhook(request: web.Request) -> web.Response:
    # Verify secret header
    secret = request.headers.get("X-Secret", "")
    if secret != WEBAPP_SECRET:
        log.warning("Unauthorized webhook attempt.")
        return web.json_response({"error": "Unauthorized"}, status=401)

    try:
        data = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)

    event   = data.get("event", "")
    name    = data.get("name", "Unknown")
    now     = data.get("time", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    log.info(f"Received event: {event} from {name}")

    try:
        if event == "register":
            lang = data.get("lang", "en")
            await upsert_user(name, lang, now)
            await log_event("register", name, {"lang": lang}, now)
            await notify_admin(
                f"🆕 <b>New User Registered!</b>\n"
                f"👤 {name}\n"
                f"🌐 Language: {fmt_lang(lang)}\n"
                f"📅 {now}"
            )

        elif event == "returning":
            total_pts = data.get("totalPts", 0)
            rank      = data.get("rank", "Rookie")
            await touch_user_last_seen(name, now)
            await log_event("returning", name, {"totalPts": total_pts, "rank": rank}, now)
            # (returning users don't trigger a notification by default — add if desired)

        elif event == "milestone":
            total_pts = data.get("totalPts", 0)
            rank      = data.get("rank", "Rookie")
            await update_user_rank(name, total_pts, rank, now)
            await log_event("milestone", name, {"totalPts": total_pts, "rank": rank}, now)
            await notify_admin(
                f"🏆 <b>Milestone Reached!</b>\n"
                f"👤 {name}\n"
                f"💰 Points: {total_pts}\n"
                f"🎖️ New Rank: {rank.title()} {rank_emoji(rank)}"
            )

        elif event == "quiz_end":
            lang          = data.get("lang", "en")
            total_pts     = data.get("totalPts", 0)
            total_solved  = data.get("totalSolved", 0)
            total_correct = data.get("totalCorrect", 0)
            rank          = data.get("rank", "Rookie")
            subjects      = data.get("subjects", {})
            session_subj  = data.get("sessionSubject", "?")
            session_score = data.get("sessionScore", 0)
            session_corr  = data.get("sessionCorrect", 0)
            session_wrong = data.get("sessionWrong", 0)

            await update_user_stats(name, lang, total_pts, total_solved, total_correct, rank, now, subjects)
            await log_event("quiz_end", name, {
                "sessionSubject": session_subj,
                "sessionScore":   session_score,
                "sessionCorrect": session_corr,
                "sessionWrong":   session_wrong,
                "totalPts":       total_pts,
                "rank":           rank,
            }, now)

            se = subject_emoji(session_subj)
            re = rank_emoji(rank)
            total_q = session_corr + session_wrong
            await notify_admin(
                f"🎯 <b>Quiz Session Ended</b>\n"
                f"👤 {name} | {se} {session_subj.title()}\n"
                f"✅ {session_corr}/{total_q} correct | +{session_score} pts\n"
                f"💰 Total: {total_pts} pts | {re} {rank.title()}"
            )

        else:
            log.warning(f"Unknown event type: {event}")
            return web.json_response({"error": "Unknown event"}, status=400)

    except Exception as e:
        log.exception(f"Error processing event '{event}': {e}")
        return web.json_response({"error": "Internal error"}, status=500)

    return web.json_response({"ok": True})


# ─────────────────────────────────────────────
# aiohttp handler — Telegram bot webhook
# ─────────────────────────────────────────────
async def handle_telegram_webhook(request: web.Request) -> web.Response:
    from aiogram.types import Update
    try:
        body = await request.json()
        update = Update.model_validate(body)
        await dp.feed_update(bot=bot, update=update)
    except Exception as e:
        log.exception(f"Telegram webhook error: {e}")
    return web.Response(text="ok")


# ─────────────────────────────────────────────
# App startup / shutdown
# ─────────────────────────────────────────────
async def on_startup(app: web.Application):
    await init_db()
    # Register Telegram webhook
    webhook_url = os.getenv("WEBHOOK_URL", "")
    if webhook_url:
        await bot.set_webhook(f"{webhook_url}/webhook/bot")
        log.info(f"Telegram webhook set: {webhook_url}/webhook/bot")
    else:
        log.warning("WEBHOOK_URL not set — Telegram webhook not registered.")

    # Notify admin on startup
    try:
        await bot.send_message(
            ADMIN_CHAT_ID,
            "✅ <b>QuizMaster Pro Admin Bot started!</b>\n\nSend /menu to open the panel.",
        )
    except Exception as e:
        log.error(f"Could not send startup message: {e}")


async def on_shutdown(app: web.Application):
    await bot.delete_webhook()
    await bot.session.close()
    log.info("Bot shut down.")


# ─────────────────────────────────────────────
# Main entry point
# ─────────────────────────────────────────────
def create_app() -> web.Application:
    app = web.Application()
    app.router.add_post("/webhook/bot",      handle_telegram_webhook)
    app.router.add_post("/webhook/quizapp",  handle_webapp_webhook)
    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)
    return app


if __name__ == "__main__":
    app = create_app()
    web.run_app(app, host="0.0.0.0", port=PORT)
