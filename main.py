import os
import sys
import time
import logging
import sqlite3
import platform
import threading
import traceback
from datetime import datetime, timedelta

import psutil
import telebot
from telebot import types
from telebot.apihelper import ApiTelegramException

# ─────────────────────────────────────────────
# ENVIRONMENT VARIABLES
# ─────────────────────────────────────────────
ADMIN_BOT_TOKEN = os.environ.get("ADMIN_BOT_TOKEN", "")
OWNER_ID        = int(os.environ.get("OWNER_ID", "0"))
DATABASE_NAME   = os.environ.get("DATABASE_NAME", "multi_bot.db")

if not ADMIN_BOT_TOKEN:
    sys.exit("[FATAL] ADMIN_BOT_TOKEN is not set. Exiting.")
if not OWNER_ID:
    sys.exit("[FATAL] OWNER_ID is not set. Exiting.")

# ─────────────────────────────────────────────
# LOGGING SETUP
# ─────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("admin_bot.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("AdminBot")

# ─────────────────────────────────────────────
# GLOBAL STATE
# ─────────────────────────────────────────────
# Tracks running child bot threads: {bot_id: {"thread": ..., "start_time": ..., "bot": ...}}
child_bots: dict = {}

# Per-user FSM state: {user_id: {"state": str, ...}}
user_states: dict = {}

# System start time for uptime calculation
SYSTEM_START = time.time()


# ═══════════════════════════════════════════════════════════════
# DATABASE LAYER
# ═══════════════════════════════════════════════════════════════

class Database:
    """Thread-safe SQLite wrapper for the admin system."""

    def __init__(self, db_name: str):
        self.db_name = db_name
        self._local = threading.local()
        self._init_schema()

    # ── Connection management ────────────────────────────────

    def _conn(self) -> sqlite3.Connection:
        """Return a per-thread connection (creates one if needed)."""
        if not hasattr(self._local, "connection"):
            self._local.connection = sqlite3.connect(
                self.db_name, check_same_thread=False
            )
            self._local.connection.row_factory = sqlite3.Row
            self._local.connection.execute("PRAGMA journal_mode=WAL;")
        return self._local.connection

    def _execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        conn = self._conn()
        cur  = conn.execute(sql, params)
        conn.commit()
        return cur

    def _fetchall(self, sql: str, params: tuple = ()) -> list:
        return self._conn().execute(sql, params).fetchall()

    def _fetchone(self, sql: str, params: tuple = ()):
        return self._conn().execute(sql, params).fetchone()

    # ── Schema ───────────────────────────────────────────────

    def _init_schema(self):
        """Create all tables if they do not exist."""
        stmts = [
            """
            CREATE TABLE IF NOT EXISTS bots (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                token       TEXT    UNIQUE NOT NULL,
                bot_name    TEXT    NOT NULL,
                username    TEXT    NOT NULL,
                added_at    TEXT    DEFAULT (datetime('now')),
                is_active   INTEGER DEFAULT 1
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS users (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                bot_id     INTEGER NOT NULL,
                user_id    INTEGER NOT NULL,
                username   TEXT,
                first_name TEXT,
                joined_at  TEXT    DEFAULT (datetime('now')),
                UNIQUE(bot_id, user_id),
                FOREIGN KEY (bot_id) REFERENCES bots(id) ON DELETE CASCADE
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS broadcast_history (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                admin_id     INTEGER NOT NULL,
                message_text TEXT,
                sent_count   INTEGER DEFAULT 0,
                fail_count   INTEGER DEFAULT 0,
                broadcast_at TEXT    DEFAULT (datetime('now'))
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS logs (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                level      TEXT NOT NULL,
                source     TEXT NOT NULL,
                message    TEXT NOT NULL,
                created_at TEXT DEFAULT (datetime('now'))
            )
            """,
        ]
        for stmt in stmts:
            self._execute(stmt)
        logger.info("Database schema initialised: %s", self.db_name)

    # ── Bot CRUD ─────────────────────────────────────────────

    def add_bot(self, token: str, bot_name: str, username: str) -> bool:
        try:
            self._execute(
                "INSERT INTO bots (token, bot_name, username) VALUES (?, ?, ?)",
                (token, bot_name, username),
            )
            self.write_log("INFO", "Database", f"Bot added: @{username}")
            return True
        except sqlite3.IntegrityError:
            return False  # Token already exists

    def remove_bot(self, bot_id: int) -> bool:
        cur = self._execute("DELETE FROM bots WHERE id = ?", (bot_id,))
        self.write_log("INFO", "Database", f"Bot removed: id={bot_id}")
        return cur.rowcount > 0

    def get_all_bots(self) -> list:
        return self._fetchall("SELECT * FROM bots ORDER BY added_at")

    def get_bot_by_id(self, bot_id: int):
        return self._fetchone("SELECT * FROM bots WHERE id = ?", (bot_id,))

    def get_bot_by_token(self, token: str):
        return self._fetchone("SELECT * FROM bots WHERE token = ?", (token,))

    def set_bot_active(self, bot_id: int, active: bool):
        self._execute(
            "UPDATE bots SET is_active = ? WHERE id = ?",
            (1 if active else 0, bot_id),
        )

    # ── User CRUD ────────────────────────────────────────────

    def register_user(self, bot_id: int, user_id: int, username: str, first_name: str):
        """Insert or ignore a child-bot user."""
        self._execute(
            """
            INSERT OR IGNORE INTO users (bot_id, user_id, username, first_name)
            VALUES (?, ?, ?, ?)
            """,
            (bot_id, user_id, username or "", first_name or ""),
        )

    def get_users_by_bot(self, bot_id: int) -> list:
        return self._fetchall(
            "SELECT * FROM users WHERE bot_id = ?", (bot_id,)
        )

    def get_all_users(self) -> list:
        return self._fetchall("SELECT * FROM users")

    def count_users_per_bot(self) -> list:
        return self._fetchall(
            """
            SELECT b.id, b.bot_name, b.username, COUNT(u.id) AS user_count
            FROM bots b
            LEFT JOIN users u ON b.id = u.bot_id
            GROUP BY b.id
            ORDER BY b.bot_name
            """
        )

    # ── Broadcast history ────────────────────────────────────

    def log_broadcast(
        self, admin_id: int, message_text: str, sent: int, failed: int
    ):
        self._execute(
            """
            INSERT INTO broadcast_history
                (admin_id, message_text, sent_count, fail_count)
            VALUES (?, ?, ?, ?)
            """,
            (admin_id, message_text or "", sent, failed),
        )

    # ── System logs ──────────────────────────────────────────

    def write_log(self, level: str, source: str, message: str):
        self._execute(
            "INSERT INTO logs (level, source, message) VALUES (?, ?, ?)",
            (level, source, message),
        )

    def get_recent_logs(self, limit: int = 50) -> list:
        return self._fetchall(
            "SELECT * FROM logs ORDER BY created_at DESC LIMIT ?", (limit,)
        )


# ─── Initialise global DB instance ──────────────────────────
db = Database(DATABASE_NAME)


# ═══════════════════════════════════════════════════════════════
# UTILITY HELPERS
# ═══════════════════════════════════════════════════════════════

def format_uptime(seconds: float) -> str:
    """Convert elapsed seconds to a human-readable string."""
    delta  = timedelta(seconds=int(seconds))
    days   = delta.days
    hours, remainder = divmod(delta.seconds, 3600)
    minutes, secs    = divmod(remainder, 60)
    parts = []
    if days:    parts.append(f"{days}d")
    if hours:   parts.append(f"{hours}h")
    if minutes: parts.append(f"{minutes}m")
    parts.append(f"{secs}s")
    return " ".join(parts)


def check_token_online(token: str) -> bool:
    """Validate a bot token by calling getMe."""
    try:
        tmp = telebot.TeleBot(token, threaded=False)
        tmp.get_me()
        return True
    except Exception:
        return False


def get_server_info() -> str:
    """Return a formatted string of current server metrics."""
    cpu     = psutil.cpu_percent(interval=1)
    ram     = psutil.virtual_memory()
    disk    = psutil.disk_usage("/")
    sys_up  = format_uptime(time.time() - psutil.boot_time())
    bot_up  = format_uptime(time.time() - SYSTEM_START)

    return (
        "🖥️  *Server Information*\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🔥 *CPU Usage   :* `{cpu}%`\n"
        f"🧠 *RAM Usage   :* `{ram.percent}%` "
        f"({ram.used // 1024**2} MB / {ram.total // 1024**2} MB)\n"
        f"💾 *Disk Usage  :* `{disk.percent}%` "
        f"({disk.used // 1024**3} GB / {disk.total // 1024**3} GB)\n"
        f"🐍 *Python      :* `{platform.python_version()}`\n"
        f"🖥️  *OS          :* `{platform.system()} {platform.release()}`\n"
        f"⏱️  *System Up   :* `{sys_up}`\n"
        f"🤖 *Bot Up      :* `{bot_up}`\n"
    )


def owner_only(func):
    """Decorator – silently ignores non-owner messages."""
    def wrapper(message, *args, **kwargs):
        if message.from_user.id != OWNER_ID:
            logger.warning(
                "Unauthorised access attempt by user_id=%s", message.from_user.id
            )
            return
        return func(message, *args, **kwargs)
    return wrapper


# ═══════════════════════════════════════════════════════════════
# CHILD BOT SYSTEM
# ═══════════════════════════════════════════════════════════════

def build_child_bot(bot_row) -> telebot.TeleBot:
    """
    Create and configure a TeleBot instance for a child bot.
    Registers a /start handler that stores new users in the DB.
    """
    bot_id    = bot_row["id"]
    bot_name  = bot_row["bot_name"]
    token     = bot_row["token"]

    child = telebot.TeleBot(token, threaded=True)

    @child.message_handler(commands=["start"])
    def on_start(msg: types.Message):
        uid  = msg.from_user.id
        uname = msg.from_user.username or ""
        fname = msg.from_user.first_name or ""
        db.register_user(bot_id, uid, uname, fname)
        logger.info("[%s] New user registered: uid=%s", bot_name, uid)
        child.reply_to(msg, f"👋 Hello, {fname}!\nWelcome to {bot_name}.")

    return child


def start_child_bot(bot_row):
    """Start a child bot in a background daemon thread."""
    bot_id   = bot_row["id"]
    bot_name = bot_row["bot_name"]

    if bot_id in child_bots:
        logger.info("[%s] Already running – skipping.", bot_name)
        return

    child = build_child_bot(bot_row)

    def run():
        logger.info("[%s] Starting polling …", bot_name)
        while True:
            try:
                child.infinity_polling(
                    timeout=20,
                    long_polling_timeout=15,
                    logger_level=logging.WARNING,
                )
            except Exception as exc:
                msg = f"[{bot_name}] Polling crashed: {exc}"
                logger.error(msg)
                db.write_log("ERROR", bot_name, msg)
                time.sleep(5)

    t = threading.Thread(target=run, name=f"child_{bot_id}", daemon=True)
    t.start()

    child_bots[bot_id] = {
        "thread":     t,
        "start_time": time.time(),
        "bot":        child,
        "bot_name":   bot_name,
    }
    db.set_bot_active(bot_id, True)
    logger.info("[%s] Thread started (id=%s).", bot_name, bot_id)


def stop_child_bot(bot_id: int):
    """Stop a child bot's polling loop and remove from registry."""
    entry = child_bots.pop(bot_id, None)
    if entry:
        try:
            entry["bot"].stop_polling()
        except Exception:
            pass
        db.set_bot_active(bot_id, False)
        logger.info("Child bot id=%s stopped.", bot_id)


def restart_all_child_bots():
    """Stop every child bot then restart them all from the database."""
    for bot_id in list(child_bots.keys()):
        stop_child_bot(bot_id)
    time.sleep(2)
    for row in db.get_all_bots():
        start_child_bot(row)


# ═══════════════════════════════════════════════════════════════
# ADMIN BOT – KEYBOARDS
# ═══════════════════════════════════════════════════════════════

def main_keyboard() -> types.ReplyKeyboardMarkup:
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    buttons = [
        "1️⃣ Broadcast",    "2️⃣ Total Users",
        "3️⃣ Bot Status",   "4️⃣ Restart Bots",
        "5️⃣ Bot List",     "6️⃣ Add Bot",
        "7️⃣ Remove Bot",   "8️⃣ Bot Uptime",
        "9️⃣ Server Info",  "🔟 Help",
    ]
    kb.add(*[types.KeyboardButton(b) for b in buttons])
    return kb


def cancel_keyboard() -> types.ReplyKeyboardMarkup:
    kb = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=1)
    kb.add(types.KeyboardButton("❌ Cancel"))
    return kb


# ═══════════════════════════════════════════════════════════════
# ADMIN BOT – INSTANCE
# ═══════════════════════════════════════════════════════════════

admin_bot = telebot.TeleBot(ADMIN_BOT_TOKEN, threaded=True)


# ═══════════════════════════════════════════════════════════════
# ADMIN BOT – HANDLERS
# ═══════════════════════════════════════════════════════════════

# ── /start ──────────────────────────────────────────────────

@admin_bot.message_handler(commands=["start"])
@owner_only
def handle_start(msg: types.Message):
    db.write_log("INFO", "AdminBot", f"Owner opened panel (uid={msg.from_user.id})")
    admin_bot.send_message(
        msg.chat.id,
        "👋 *Welcome Admin*\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "This is your *Professional Multi Bot Controller Panel*\n\n"
        "You can manage all your Telegram bots from here.\n"
        "Use the buttons below to get started. ⬇️",
        parse_mode="Markdown",
        reply_markup=main_keyboard(),
    )


# ─────────────────────────────────────────────────────────────
# General message router  (handles both keyboard buttons and
# multi-step FSM states in one place)
# ─────────────────────────────────────────────────────────────

@admin_bot.message_handler(func=lambda m: True, content_types=["text", "photo"])
@owner_only
def route_message(msg: types.Message):
    uid   = msg.from_user.id
    state = user_states.get(uid, {}).get("state", "")
    text  = (msg.text or "").strip()

    # ── Global cancel ──────────────────────────────────────
    if text == "❌ Cancel":
        user_states.pop(uid, None)
        admin_bot.send_message(
            msg.chat.id, "↩️ Cancelled.", reply_markup=main_keyboard()
        )
        return

    # ── FSM states ─────────────────────────────────────────
    if state == "awaiting_broadcast":
        _handle_broadcast_message(msg)
        return
    if state == "awaiting_new_bot_token":
        _handle_add_bot_token(msg)
        return
    if state == "awaiting_remove_bot_id":
        _handle_remove_bot_id(msg)
        return

    # ── Keyboard buttons ───────────────────────────────────
    handlers = {
        "1️⃣ Broadcast":   _cmd_broadcast,
        "2️⃣ Total Users":  _cmd_total_users,
        "3️⃣ Bot Status":   _cmd_bot_status,
        "4️⃣ Restart Bots": _cmd_restart_bots,
        "5️⃣ Bot List":     _cmd_bot_list,
        "6️⃣ Add Bot":      _cmd_add_bot,
        "7️⃣ Remove Bot":   _cmd_remove_bot,
        "8️⃣ Bot Uptime":   _cmd_bot_uptime,
        "9️⃣ Server Info":  _cmd_server_info,
        "🔟 Help":         _cmd_help,
    }
    fn = handlers.get(text)
    if fn:
        fn(msg)


# ═══════════════════════════════════════════════════════════════
# FEATURE HANDLERS
# ═══════════════════════════════════════════════════════════════

# ── 1. BROADCAST ─────────────────────────────────────────────

def _cmd_broadcast(msg: types.Message):
    uid = msg.from_user.id
    user_states[uid] = {"state": "awaiting_broadcast"}
    admin_bot.send_message(
        msg.chat.id,
        "📢 *Broadcast Message*\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "Send the message (text or photo+caption) you want to broadcast "
        "to *all users* of *all bots*.\n\n"
        "Press ❌ *Cancel* to abort.",
        parse_mode="Markdown",
        reply_markup=cancel_keyboard(),
    )


def _handle_broadcast_message(msg: types.Message):
    uid = msg.from_user.id
    user_states.pop(uid, None)

    all_users = db.get_all_users()
    if not all_users:
        admin_bot.send_message(
            msg.chat.id,
            "⚠️ No users found in the database.",
            reply_markup=main_keyboard(),
        )
        return

    sent = failed = 0
    status_msg = admin_bot.send_message(
        msg.chat.id, "📤 Broadcasting … please wait."
    )
    broadcast_text = msg.caption or msg.text or "[media]"

    for row in all_users:
        target_uid = row["user_id"]
        try:
            if msg.photo:
                admin_bot.send_photo(
                    target_uid,
                    msg.photo[-1].file_id,
                    caption=msg.caption or "",
                )
            else:
                admin_bot.send_message(target_uid, msg.text)
            sent += 1
        except ApiTelegramException as e:
            logger.warning("Broadcast failed for uid=%s: %s", target_uid, e)
            failed += 1
        except Exception as e:
            logger.error("Unexpected broadcast error uid=%s: %s", target_uid, e)
            failed += 1

    db.log_broadcast(uid, broadcast_text, sent, failed)
    db.write_log("INFO", "Broadcast", f"sent={sent} failed={failed}")

    admin_bot.edit_message_text(
        f"✅ *Broadcast Complete*\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"✅ Sent   : `{sent}`\n"
        f"❌ Failed : `{failed}`",
        msg.chat.id,
        status_msg.message_id,
        parse_mode="Markdown",
    )
    admin_bot.send_message(
        msg.chat.id, "↩️ Back to panel.", reply_markup=main_keyboard()
    )


# ── 2. TOTAL USERS ────────────────────────────────────────────

def _cmd_total_users(msg: types.Message):
    rows  = db.count_users_per_bot()
    total = sum(r["user_count"] for r in rows)

    if not rows:
        admin_bot.send_message(
            msg.chat.id,
            "ℹ️ No bots registered yet.",
            reply_markup=main_keyboard(),
        )
        return

    lines = ["👥 *User Statistics*\n━━━━━━━━━━━━━━━━━━━━"]
    for r in rows:
        lines.append(f"🤖 *{r['bot_name']}* (@{r['username']}): `{r['user_count']}` users")
    lines.append(f"\n📊 *Total Users : `{total}`*")

    admin_bot.send_message(
        msg.chat.id, "\n".join(lines), parse_mode="Markdown", reply_markup=main_keyboard()
    )


# ── 3. BOT STATUS ─────────────────────────────────────────────

def _cmd_bot_status(msg: types.Message):
    bots = db.get_all_bots()
    if not bots:
        admin_bot.send_message(
            msg.chat.id, "ℹ️ No bots registered.", reply_markup=main_keyboard()
        )
        return

    wait_msg = admin_bot.send_message(msg.chat.id, "🔄 Checking bot statuses …")
    lines    = ["🔍 *Bot Status Check*\n━━━━━━━━━━━━━━━━━━━━"]

    for bot in bots:
        online = check_token_online(bot["token"])
        icon   = "🟢 Online" if online else "🔴 Offline"
        lines.append(f"{icon} — *{bot['bot_name']}* (@{bot['username']})")

    admin_bot.edit_message_text(
        "\n".join(lines),
        msg.chat.id,
        wait_msg.message_id,
        parse_mode="Markdown",
    )
    admin_bot.send_message(
        msg.chat.id, "↩️ Back to panel.", reply_markup=main_keyboard()
    )


# ── 4. RESTART BOTS ──────────────────────────────────────────

def _cmd_restart_bots(msg: types.Message):
    wait_msg = admin_bot.send_message(msg.chat.id, "♻️ Restarting all bots …")
    db.write_log("INFO", "AdminBot", "Owner triggered restart of all bots")

    def do_restart():
        restart_all_child_bots()
        count = len(child_bots)
        admin_bot.edit_message_text(
            f"✅ *Restart Complete*\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🤖 `{count}` bot(s) are now running.",
            msg.chat.id,
            wait_msg.message_id,
            parse_mode="Markdown",
        )
        admin_bot.send_message(
            msg.chat.id, "↩️ Back to panel.", reply_markup=main_keyboard()
        )

    threading.Thread(target=do_restart, daemon=True).start()


# ── 5. BOT LIST ───────────────────────────────────────────────

def _cmd_bot_list(msg: types.Message):
    bots = db.get_all_bots()
    if not bots:
        admin_bot.send_message(
            msg.chat.id, "ℹ️ No bots registered.", reply_markup=main_keyboard()
        )
        return

    lines = ["📋 *Registered Bots*\n━━━━━━━━━━━━━━━━━━━━"]
    for bot in bots:
        running = "🟢 Running" if bot["id"] in child_bots else "🔴 Stopped"
        lines.append(
            f"*ID:* `{bot['id']}`\n"
            f"*Name:* {bot['bot_name']}\n"
            f"*Username:* @{bot['username']}\n"
            f"*Status:* {running}\n"
            f"*Added:* `{bot['added_at']}`\n"
            "─────────────────────"
        )

    admin_bot.send_message(
        msg.chat.id, "\n".join(lines), parse_mode="Markdown", reply_markup=main_keyboard()
    )


# ── 6. ADD BOT ────────────────────────────────────────────────

def _cmd_add_bot(msg: types.Message):
    uid = msg.from_user.id
    user_states[uid] = {"state": "awaiting_new_bot_token"}
    admin_bot.send_message(
        msg.chat.id,
        "➕ *Add New Bot*\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "Please send the *bot token* of the bot you want to add.\n\n"
        "_You can get a token from @BotFather._\n\n"
        "Press ❌ *Cancel* to abort.",
        parse_mode="Markdown",
        reply_markup=cancel_keyboard(),
    )


def _handle_add_bot_token(msg: types.Message):
    uid   = msg.from_user.id
    token = (msg.text or "").strip()
    user_states.pop(uid, None)

    # Validate token format
    if ":" not in token or len(token) < 30:
        admin_bot.send_message(
            msg.chat.id,
            "❌ Invalid token format. Please try again.",
            reply_markup=main_keyboard(),
        )
        return

    wait_msg = admin_bot.send_message(msg.chat.id, "🔄 Validating token …")

    try:
        tmp    = telebot.TeleBot(token, threaded=False)
        info   = tmp.get_me()
        result = db.add_bot(token, info.first_name, info.username)

        if not result:
            admin_bot.edit_message_text(
                "⚠️ This bot is *already registered*.",
                msg.chat.id,
                wait_msg.message_id,
                parse_mode="Markdown",
            )
        else:
            # Start the child bot immediately
            new_row = db.get_bot_by_token(token)
            start_child_bot(new_row)
            db.write_log("INFO", "AdminBot", f"New bot added: @{info.username}")
            admin_bot.edit_message_text(
                f"✅ *Bot Added Successfully!*\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"🤖 *Name:* {info.first_name}\n"
                f"👤 *Username:* @{info.username}\n"
                f"🟢 *Status:* Running",
                msg.chat.id,
                wait_msg.message_id,
                parse_mode="Markdown",
            )
    except ApiTelegramException:
        admin_bot.edit_message_text(
            "❌ *Invalid token.* Telegram rejected it.",
            msg.chat.id,
            wait_msg.message_id,
            parse_mode="Markdown",
        )

    admin_bot.send_message(
        msg.chat.id, "↩️ Back to panel.", reply_markup=main_keyboard()
    )


# ── 7. REMOVE BOT ────────────────────────────────────────────

def _cmd_remove_bot(msg: types.Message):
    bots = db.get_all_bots()
    if not bots:
        admin_bot.send_message(
            msg.chat.id, "ℹ️ No bots to remove.", reply_markup=main_keyboard()
        )
        return

    uid = msg.from_user.id
    user_states[uid] = {"state": "awaiting_remove_bot_id"}

    lines = ["🗑️ *Remove Bot*\n━━━━━━━━━━━━━━━━━━━━\nSend the *Bot ID* to remove:\n"]
    for bot in bots:
        lines.append(f"• `{bot['id']}` — *{bot['bot_name']}* (@{bot['username']})")

    admin_bot.send_message(
        msg.chat.id,
        "\n".join(lines),
        parse_mode="Markdown",
        reply_markup=cancel_keyboard(),
    )


def _handle_remove_bot_id(msg: types.Message):
    uid = msg.from_user.id
    user_states.pop(uid, None)

    try:
        bot_id = int((msg.text or "").strip())
    except ValueError:
        admin_bot.send_message(
            msg.chat.id, "❌ Invalid ID. Please enter a number.", reply_markup=main_keyboard()
        )
        return

    row = db.get_bot_by_id(bot_id)
    if not row:
        admin_bot.send_message(
            msg.chat.id, f"❌ No bot found with ID `{bot_id}`.",
            parse_mode="Markdown", reply_markup=main_keyboard()
        )
        return

    bot_name = row["bot_name"]
    stop_child_bot(bot_id)
    db.remove_bot(bot_id)
    db.write_log("INFO", "AdminBot", f"Bot removed: id={bot_id} name={bot_name}")

    admin_bot.send_message(
        msg.chat.id,
        f"✅ *Bot Removed*\n"
        f"🤖 *{bot_name}* has been removed from the system.",
        parse_mode="Markdown",
        reply_markup=main_keyboard(),
    )


# ── 8. BOT UPTIME ─────────────────────────────────────────────

def _cmd_bot_uptime(msg: types.Message):
    if not child_bots:
        admin_bot.send_message(
            msg.chat.id,
            "ℹ️ No bots are currently running.",
            reply_markup=main_keyboard(),
        )
        return

    lines = ["⏱️ *Bot Uptime*\n━━━━━━━━━━━━━━━━━━━━"]
    for bot_id, entry in child_bots.items():
        elapsed = time.time() - entry["start_time"]
        lines.append(
            f"🤖 *{entry['bot_name']}* — `{format_uptime(elapsed)}`"
        )

    admin_bot.send_message(
        msg.chat.id, "\n".join(lines), parse_mode="Markdown", reply_markup=main_keyboard()
    )


# ── 9. SERVER INFO ────────────────────────────────────────────

def _cmd_server_info(msg: types.Message):
    admin_bot.send_message(
        msg.chat.id,
        get_server_info(),
        parse_mode="Markdown",
        reply_markup=main_keyboard(),
    )


# ── 10. HELP ──────────────────────────────────────────────────

def _cmd_help(msg: types.Message):
    help_text = (
        "📖 *Help & Feature Guide*\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "1️⃣ *Broadcast*\n"
        "   Send a text or photo message to all users of all bots.\n\n"
        "2️⃣ *Total Users*\n"
        "   View user count per bot and overall total.\n\n"
        "3️⃣ *Bot Status*\n"
        "   Check whether each bot token is online or offline.\n\n"
        "4️⃣ *Restart Bots*\n"
        "   Safely restart all running child bot processes.\n\n"
        "5️⃣ *Bot List*\n"
        "   View all registered bots with their details.\n\n"
        "6️⃣ *Add Bot*\n"
        "   Add a new bot by providing its BotFather token.\n\n"
        "7️⃣ *Remove Bot*\n"
        "   Permanently remove a bot from the system.\n\n"
        "8️⃣ *Bot Uptime*\n"
        "   See how long each bot has been running.\n\n"
        "9️⃣ *Server Info*\n"
        "   View CPU, RAM, disk usage, and system uptime.\n\n"
        "🔐 *Security:* Only the registered OWNER can access this panel.\n"
        "📝 *Logs:* All admin actions are stored in the database.\n"
    )
    admin_bot.send_message(
        msg.chat.id, help_text, parse_mode="Markdown", reply_markup=main_keyboard()
    )


# ═══════════════════════════════════════════════════════════════
# GLOBAL ERROR HANDLER
# ═══════════════════════════════════════════════════════════════

@admin_bot.middleware_handler(update_types=["message"])
def log_incoming(bot_instance, update):
    """Log every incoming message for audit purposes."""
    if update.message and update.message.from_user:
        uid  = update.message.from_user.id
        text = update.message.text or "[non-text]"
        logger.debug("Incoming message uid=%s text=%r", uid, text[:60])


def handle_polling_error(exc: Exception):
    err = traceback.format_exc()
    logger.error("Admin bot polling error: %s\n%s", exc, err)
    db.write_log("ERROR", "AdminBot", str(exc))


# ═══════════════════════════════════════════════════════════════
# BOOT SEQUENCE
# ═══════════════════════════════════════════════════════════════

def boot():
    """Load all persisted bots and start their polling threads."""
    bots = db.get_all_bots()
    logger.info("Booting %d child bot(s) from database …", len(bots))
    for row in bots:
        try:
            start_child_bot(row)
        except Exception as e:
            logger.error("Failed to start bot id=%s: %s", row["id"], e)
            db.write_log("ERROR", "Boot", f"Failed to start bot id={row['id']}: {e}")


# ═══════════════════════════════════════════════════════════════
# ENTRY POINT
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    logger.info("=" * 60)
    logger.info("  Multi Bot Admin Controller  –  Starting …")
    logger.info("  Owner ID  : %s", OWNER_ID)
    logger.info("  Database  : %s", DATABASE_NAME)
    logger.info("=" * 60)

    # Start all previously registered child bots
    boot()

    # Notify owner on (re)start
    try:
        admin_bot.send_message(
            OWNER_ID,
            "🚀 *Admin Bot started successfully!*\n"
            f"⏱️ `{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`\n"
            f"🤖 `{len(child_bots)}` child bot(s) running.",
            parse_mode="Markdown",
            reply_markup=main_keyboard(),
        )
    except Exception as e:
        logger.warning("Could not send startup notification: %s", e)

    # Run admin bot with auto-retry on connection errors
    logger.info("Admin bot is now polling …")
    while True:
        try:
            admin_bot.infinity_polling(
                timeout=30,
                long_polling_timeout=25,
                logger_level=logging.WARNING,
                allowed_updates=["message"],
            )
        except Exception as exc:
            handle_polling_error(exc)
            logger.info("Restarting admin bot polling in 10 s …")
            time.sleep(10)
