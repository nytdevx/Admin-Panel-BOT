# bot.py
# ============================================================
# Telegram Earning Bot - Full Production Version
# Features: Tasks, Wallet, Withdraw, Referral, Daily Bonus,
#           Profile, Leaderboard, Multi-language, Admin Tools
# Deploy: Railway (long polling)
# ============================================================

import os
import sys
import logging
import sqlite3
import random
import string
from datetime import datetime, timedelta
from typing import Optional
from dotenv import load_dotenv

load_dotenv()

from telegram import (
    Update,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    KeyboardButton,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    ConversationHandler,
    filters,
)
from telegram.constants import ParseMode

# ============================================================
# LOGGING SETUP
# ============================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)

# ============================================================
# ENVIRONMENT / CONFIG
# ============================================================
BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
BOT_USERNAME: str = os.getenv("BOT_USERNAME", "YourBot")

# Admin IDs (can extend via env)
_admin_env = os.getenv("ADMIN_IDS", "8499435987,8502323375")
ADMIN_IDS: list[int] = [int(x.strip()) for x in _admin_env.split(",") if x.strip()]

# Reward config (can be overridden by DB settings)
MIN_WITHDRAW: float = float(os.getenv("MIN_WITHDRAW", "1.0"))
DAILY_BONUS_AMOUNT: float = float(os.getenv("DAILY_BONUS_AMOUNT", "0.10"))
REFERRAL_BONUS: float = float(os.getenv("REFERRAL_BONUS", "0.05"))
TASK_REWARD: float = float(os.getenv("TASK_REWARD", "0.10"))

TASK_PASSWORD = "DIN1KAL2"
DB_PATH = os.getenv("DB_PATH", "bot_data.db")

if not BOT_TOKEN:
    logger.critical("BOT_TOKEN is not set. Exiting.")
    sys.exit(1)

# ============================================================
# CONVERSATION STATES
# ============================================================
(
    MAIN_MENU,
    TASK_MENU,
    TASK_CONFIRM,
    WALLET_MENU,
    WITHDRAW_MENU,
    WITHDRAW_BINANCE_ADDRESS,
    WITHDRAW_BKASH_NUMBER,
    REFERRAL_MENU,
    REFERRAL_LIST,
    DAILY_BONUS,
    PROFILE_MENU,
    SETTINGS_MENU,
    LANG_SELECT,
) = range(13)

# ============================================================
# MULTI-LANGUAGE STRINGS
# ============================================================
STRINGS = {
    "en": {
        # Welcome
        "welcome": (
            "👤 *Admin - Samuel Johnson* 📈\n"
            "━━━━━━━━━━━━━━━━\n"
            "Hi Sir, Welcome to Our Project..\n\n"
            "Select an option below 👇"
        ),
        # Main menu buttons
        "btn_task": "✅ Task",
        "btn_wallet": "💰 Wallet",
        "btn_withdraw": "💸 Withdraw",
        "btn_referral": "👥 Referral",
        "btn_daily": "🎁 Daily Bonus",
        "btn_profile": "👤 Profile",
        "btn_settings": "⚙️ Settings",
        "btn_back": "🔙 Back",
        "btn_cancel": "❌ Cancel",
        "btn_refresh": "🔄 Refresh Wallet",
        "btn_my_referrals": "📋 My Referrals",
        "btn_done": "✅ Done",
        "btn_leaderboard": "🏆 Leaderboard",
        "btn_lang": "🌐 Language",
        # Task
        "task_menu_header": "✅ *Task Menu*\nChoose a task to complete:",
        "task_hopenity_btn": "📝 Create Hopenity Account — $0.10",
        "task_msg": (
            "📋 *New Task*\n\n"
            "🔤 First Name: `{first}`\n"
            "🔤 Last Name: `{last}`\n"
            "👤 Username: `{username}`\n"
            "🔑 Password: `{password}`\n\n"
            "Complete the task then tap ✅ Done"
        ),
        "task_already": "⚠️ You've already completed this task and earned your reward.",
        "task_done": "🎉 Task completed! *$0.10* has been added to your wallet.\n💰 New Balance: *${balance:.2f}*",
        "task_cancelled": "❌ Task cancelled. Returning to main menu.",
        # Wallet
        "wallet_msg": (
            "💰 *Your Wallet*\n"
            "━━━━━━━━━━━━━━━━\n"
            "💵 Balance: *${balance:.2f} USDT*\n"
            "📅 Updated: {time}"
        ),
        # Withdraw
        "withdraw_menu": "💸 *Withdraw*\nChoose your payment method:",
        "withdraw_binance_ask": "🏦 *Binance Withdrawal*\n\nPlease send your *USDT BEP-20* wallet address:",
        "withdraw_bkash_ask": "📱 *Bkash Withdrawal*\n\nPlease send your *Bkash number*:",
        "withdraw_low": "⚠️ *Insufficient Balance*\n\nMinimum withdrawal: *${min:.2f} USDT*\nYour balance: *${balance:.2f} USDT*",
        "withdraw_success": (
            "✅ *Withdrawal Request Submitted!*\n\n"
            "💳 Method: {method}\n"
            "💵 Amount: *${amount:.2f} USDT*\n"
            "🕐 Request Time: {time}\n\n"
            "Your wallet has been reset to $0.00.\n"
            "Admin will process your request shortly."
        ),
        "withdraw_deducted": "💸 *Wallet Update*\n\n${amount:.2f} USDT has been deducted.\n💰 New Balance: *$0.00*",
        "withdraw_invalid_addr": "⚠️ Invalid address. Please send a valid wallet address.",
        "withdraw_invalid_bkash": "⚠️ Invalid number. Please send your Bkash number.",
        # Referral
        "referral_msg": (
            "👥 *Your Referral Info*\n"
            "━━━━━━━━━━━━━━━━\n"
            "🔗 Your Link:\n`{link}`\n\n"
            "👤 Total Referrals: *{count}*\n"
            "💵 Referral Earnings: *${earnings:.2f}*\n\n"
            "Share your link and earn *$0.05* per referral!"
        ),
        "referral_list_header": "📋 *Your Referred Users:*\n",
        "referral_list_empty": "😔 You haven't referred anyone yet.",
        "referral_bonus_notify": "🎉 *Referral Bonus!*\n\nSomeone joined using your link!\n💵 +${amount:.2f} USDT added to your wallet.\n💰 New Balance: *${balance:.2f}*",
        "referral_self": "⚠️ You cannot refer yourself.",
        # Daily bonus
        "daily_success": "🎁 *Daily Bonus Claimed!*\n\n💵 +${amount:.2f} USDT added!\n💰 New Balance: *${balance:.2f}*",
        "daily_already": "⏳ *Already Claimed!*\n\nNext bonus in: *{hours}h {minutes}m {seconds}s*",
        # Profile
        "profile_msg": (
            "👤 *Your Profile*\n"
            "━━━━━━━━━━━━━━━━\n"
            "📛 Name: {name}\n"
            "👤 Username: @{username}\n"
            "🆔 Telegram ID: `{user_id}`\n"
            "💰 Balance: *${balance:.2f} USDT*\n"
            "👥 Referrals: *{referrals}*\n"
            "💵 Referral Earnings: *${ref_earn:.2f}*\n"
            "📅 Joined: {joined}\n"
            "🎁 Last Bonus: {last_bonus}"
        ),
        # Leaderboard
        "leaderboard_balance": "🏆 *Top 10 — Balance Leaderboard*\n━━━━━━━━━━━━━━━━\n",
        "leaderboard_referrals": "🏆 *Top 10 — Referral Leaderboard*\n━━━━━━━━━━━━━━━━\n",
        # Errors / misc
        "unknown_cmd": "🤷 I didn't understand that. Please use the menu buttons below.",
        "admin_only": "🚫 This command is for admins only.",
        "user_not_found": "❌ User not found.",
        "balance_added": "✅ *${amount:.2f} USDT* added to user `{uid}`.\nNew balance: *${balance:.2f}*",
        "balance_set": "✅ Balance set to *${amount:.2f} USDT* for user `{uid}`.",
        "lang_select": "🌐 *Select Language:*",
        "lang_changed": "✅ Language changed to English!",
        "settings_menu": (
            "⚙️ *Admin Settings*\n"
            "━━━━━━━━━━━━━━━━\n"
            "Current config:\n"
            "• Task Reward: *${task:.2f}*\n"
            "• Referral Bonus: *${ref:.2f}*\n"
            "• Daily Bonus: *${daily:.2f}*\n"
            "• Min Withdraw: *${min_w:.2f}*\n\n"
            "Commands to change:\n"
            "`/setconfig task <amount>`\n"
            "`/setconfig referral <amount>`\n"
            "`/setconfig daily <amount>`\n"
            "`/setconfig minwithdraw <amount>`"
        ),
        "not_applicable": "N/A",
    },
    "bn": {
        # Welcome
        "welcome": (
            "👤 *অ্যাডমিন - Samuel Johnson* 📈\n"
            "━━━━━━━━━━━━━━━━\n"
            "স্বাগতম! আমাদের প্রজেক্টে আপনাকে স্বাগত জানাই..\n\n"
            "নিচের অপশন থেকে বেছে নিন 👇"
        ),
        "btn_task": "✅ টাস্ক",
        "btn_wallet": "💰 ওয়ালেট",
        "btn_withdraw": "💸 উইথড্র",
        "btn_referral": "👥 রেফারেল",
        "btn_daily": "🎁 ডেইলি বোনাস",
        "btn_profile": "👤 প্রোফাইল",
        "btn_settings": "⚙️ সেটিংস",
        "btn_back": "🔙 ব্যাক",
        "btn_cancel": "❌ বাতিল",
        "btn_refresh": "🔄 ওয়ালেট রিফ্রেশ",
        "btn_my_referrals": "📋 আমার রেফারেলস",
        "btn_done": "✅ সম্পন্ন",
        "btn_leaderboard": "🏆 লিডারবোর্ড",
        "btn_lang": "🌐 ভাষা",
        "task_menu_header": "✅ *টাস্ক মেনু*\nএকটি টাস্ক বেছে নিন:",
        "task_hopenity_btn": "📝 Hopenity অ্যাকাউন্ট তৈরি করুন — $০.১০",
        "task_msg": (
            "📋 *নতুন টাস্ক*\n\n"
            "🔤 প্রথম নাম: `{first}`\n"
            "🔤 শেষ নাম: `{last}`\n"
            "👤 ইউজারনেম: `{username}`\n"
            "🔑 পাসওয়ার্ড: `{password}`\n\n"
            "টাস্ক সম্পন্ন করুন তারপর ✅ সম্পন্ন বাটন চাপুন"
        ),
        "task_already": "⚠️ আপনি ইতিমধ্যে এই টাস্কটি সম্পন্ন করেছেন।",
        "task_done": "🎉 টাস্ক সম্পন্ন! *$০.১০* আপনার ওয়ালেটে যোগ হয়েছে।\n💰 নতুন ব্যালেন্স: *${balance:.2f}*",
        "task_cancelled": "❌ টাস্ক বাতিল করা হয়েছে। মূল মেনুতে ফিরে যাচ্ছি।",
        "wallet_msg": (
            "💰 *আপনার ওয়ালেট*\n"
            "━━━━━━━━━━━━━━━━\n"
            "💵 ব্যালেন্স: *${balance:.2f} USDT*\n"
            "📅 আপডেট: {time}"
        ),
        "withdraw_menu": "💸 *উইথড্র*\nপেমেন্ট পদ্ধতি বেছে নিন:",
        "withdraw_binance_ask": "🏦 *Binance উইথড্র*\n\nআপনার *USDT BEP-20* ওয়ালেট ঠিকানা পাঠান:",
        "withdraw_bkash_ask": "📱 *Bkash উইথড্র*\n\nআপনার *Bkash নম্বর* পাঠান:",
        "withdraw_low": "⚠️ *অপর্যাপ্ত ব্যালেন্স*\n\nসর্বনিম্ন উইথড্র: *${min:.2f} USDT*\nআপনার ব্যালেন্স: *${balance:.2f} USDT*",
        "withdraw_success": (
            "✅ *উইথড্র অনুরোধ জমা হয়েছে!*\n\n"
            "💳 পদ্ধতি: {method}\n"
            "💵 পরিমাণ: *${amount:.2f} USDT*\n"
            "🕐 অনুরোধের সময়: {time}\n\n"
            "আপনার ওয়ালেট $০.০০ তে রিসেট হয়েছে।\n"
            "অ্যাডমিন শীঘ্রই প্রক্রিয়া করবেন।"
        ),
        "withdraw_deducted": "💸 *ওয়ালেট আপডেট*\n\n${amount:.2f} USDT কেটে নেওয়া হয়েছে।\n💰 নতুন ব্যালেন্স: *$০.০০*",
        "withdraw_invalid_addr": "⚠️ অবৈধ ঠিকানা। একটি বৈধ ওয়ালেট ঠিকানা পাঠান।",
        "withdraw_invalid_bkash": "⚠️ অবৈধ নম্বর। আপনার Bkash নম্বর পাঠান।",
        "referral_msg": (
            "👥 *আপনার রেফারেল তথ্য*\n"
            "━━━━━━━━━━━━━━━━\n"
            "🔗 আপনার লিংক:\n`{link}`\n\n"
            "👤 মোট রেফারেল: *{count}*\n"
            "💵 রেফারেল আয়: *${earnings:.2f}*\n\n"
            "লিংক শেয়ার করুন এবং প্রতি রেফারেলে *$০.০৫* উপার্জন করুন!"
        ),
        "referral_list_header": "📋 *আপনার রেফার করা ইউজাররা:*\n",
        "referral_list_empty": "😔 আপনি এখনো কাউকে রেফার করেননি।",
        "referral_bonus_notify": "🎉 *রেফারেল বোনাস!*\n\nকেউ আপনার লিংক দিয়ে যোগ দিয়েছে!\n💵 +${amount:.2f} USDT আপনার ওয়ালেটে যোগ হয়েছে।\n💰 নতুন ব্যালেন্স: *${balance:.2f}*",
        "referral_self": "⚠️ আপনি নিজেকে রেফার করতে পারবেন না।",
        "daily_success": "🎁 *ডেইলি বোনাস পাওয়া গেছে!*\n\n💵 +${amount:.2f} USDT যোগ হয়েছে!\n💰 নতুন ব্যালেন্স: *${balance:.2f}*",
        "daily_already": "⏳ *ইতিমধ্যে নেওয়া হয়েছে!*\n\nপরবর্তী বোনাস: *{hours}ঘ {minutes}মি {seconds}সে*",
        "profile_msg": (
            "👤 *আপনার প্রোফাইল*\n"
            "━━━━━━━━━━━━━━━━\n"
            "📛 নাম: {name}\n"
            "👤 ইউজারনেম: @{username}\n"
            "🆔 টেলিগ্রাম ID: `{user_id}`\n"
            "💰 ব্যালেন্স: *${balance:.2f} USDT*\n"
            "👥 রেফারেল: *{referrals}*\n"
            "💵 রেফারেল আয়: *${ref_earn:.2f}*\n"
            "📅 যোগদান: {joined}\n"
            "🎁 শেষ বোনাস: {last_bonus}"
        ),
        "leaderboard_balance": "🏆 *শীর্ষ ১০ — ব্যালেন্স লিডারবোর্ড*\n━━━━━━━━━━━━━━━━\n",
        "leaderboard_referrals": "🏆 *শীর্ষ ১০ — রেফারেল লিডারবোর্ড*\n━━━━━━━━━━━━━━━━\n",
        "unknown_cmd": "🤷 বুঝতে পারিনি। নিচের মেনু বাটন ব্যবহার করুন।",
        "admin_only": "🚫 এই কমান্ড শুধুমাত্র অ্যাডমিনদের জন্য।",
        "user_not_found": "❌ ইউজার পাওয়া যায়নি।",
        "balance_added": "✅ *${amount:.2f} USDT* ইউজার `{uid}` এ যোগ হয়েছে।\nনতুন ব্যালেন্স: *${balance:.2f}*",
        "balance_set": "✅ ইউজার `{uid}` এর ব্যালেন্স *${amount:.2f} USDT* এ সেট হয়েছে।",
        "lang_select": "🌐 *ভাষা বেছে নিন:*",
        "lang_changed": "✅ ভাষা বাংলায় পরিবর্তন করা হয়েছে!",
        "settings_menu": (
            "⚙️ *অ্যাডমিন সেটিংস*\n"
            "━━━━━━━━━━━━━━━━\n"
            "বর্তমান কনফিগ:\n"
            "• টাস্ক রিওয়ার্ড: *${task:.2f}*\n"
            "• রেফারেল বোনাস: *${ref:.2f}*\n"
            "• ডেইলি বোনাস: *${daily:.2f}*\n"
            "• সর্বনিম্ন উইথড্র: *${min_w:.2f}*\n\n"
            "পরিবর্তন করতে:\n"
            "`/setconfig task <পরিমাণ>`\n"
            "`/setconfig referral <পরিমাণ>`\n"
            "`/setconfig daily <পরিমাণ>`\n"
            "`/setconfig minwithdraw <পরিমাণ>`"
        ),
        "not_applicable": "প্রযোজ্য নয়",
    },
}


def t(user_id: int, key: str, **kwargs) -> str:
    """
    Translate a string key for a given user.
    Falls back to English if key is missing in selected language.
    """
    lang = get_user_lang(user_id)
    string = STRINGS.get(lang, STRINGS["en"]).get(key) or STRINGS["en"].get(key, key)
    if kwargs:
        try:
            return string.format(**kwargs)
        except KeyError:
            return string
    return string


# ============================================================
# DATABASE SETUP
# ============================================================

def get_db() -> sqlite3.Connection:
    """Return a thread-safe SQLite connection with row_factory."""
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def init_db() -> None:
    """Create all tables if they don't exist."""
    conn = get_db()
    cur = conn.cursor()

    # Users table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            full_name TEXT NOT NULL,
            username TEXT DEFAULT '',
            balance REAL DEFAULT 0.0,
            referred_by INTEGER DEFAULT NULL,
            join_date TEXT NOT NULL,
            last_daily_bonus_at TEXT DEFAULT NULL,
            total_referral_earnings REAL DEFAULT 0.0,
            language TEXT DEFAULT 'en'
        )
    """)

    # Transactions table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            type TEXT NOT NULL,
            amount REAL NOT NULL,
            description TEXT DEFAULT '',
            created_at TEXT NOT NULL
        )
    """)

    # Task completions table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS task_completions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            task_name TEXT NOT NULL,
            completed_at TEXT NOT NULL,
            UNIQUE(user_id, task_name)
        )
    """)

    # Withdrawals table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS withdrawals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            method TEXT NOT NULL,
            address TEXT NOT NULL,
            amount REAL NOT NULL,
            status TEXT DEFAULT 'pending',
            created_at TEXT NOT NULL
        )
    """)

    # Daily bonus claims table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS daily_bonus_claims (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            claimed_at TEXT NOT NULL
        )
    """)

    # Referrals table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS referrals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            referrer_id INTEGER NOT NULL,
            referred_id INTEGER NOT NULL,
            bonus_paid REAL NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(referred_id)
        )
    """)

    # Settings table (admin-configurable)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """)

    # Insert default settings if not present
    defaults = [
        ("task_reward", str(TASK_REWARD)),
        ("referral_bonus", str(REFERRAL_BONUS)),
        ("daily_bonus", str(DAILY_BONUS_AMOUNT)),
        ("min_withdraw", str(MIN_WITHDRAW)),
    ]
    for key, val in defaults:
        cur.execute(
            "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
            (key, val),
        )

    conn.commit()
    conn.close()
    logger.info("Database initialized successfully.")


# ============================================================
# SETTINGS HELPERS
# ============================================================

def get_setting(key: str) -> float:
    """Fetch a numeric setting from DB, falling back to env defaults."""
    conn = get_db()
    row = conn.execute(
        "SELECT value FROM settings WHERE key = ?", (key,)
    ).fetchone()
    conn.close()
    if row:
        try:
            return float(row["value"])
        except ValueError:
            pass
    # Fallback to module-level constants
    fallbacks = {
        "task_reward": TASK_REWARD,
        "referral_bonus": REFERRAL_BONUS,
        "daily_bonus": DAILY_BONUS_AMOUNT,
        "min_withdraw": MIN_WITHDRAW,
    }
    return fallbacks.get(key, 0.0)


def set_setting(key: str, value: float) -> None:
    """Update a setting value in DB."""
    conn = get_db()
    conn.execute(
        "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
        (key, str(value)),
    )
    conn.commit()
    conn.close()


# ============================================================
# USER HELPERS
# ============================================================

def get_user(user_id: int) -> Optional[sqlite3.Row]:
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM users WHERE user_id = ?", (user_id,)
    ).fetchone()
    conn.close()
    return row


def create_user(
    user_id: int,
    full_name: str,
    username: str,
    referred_by: Optional[int] = None,
) -> None:
    """Insert a new user into the database."""
    conn = get_db()
    now = datetime.utcnow().isoformat()
    conn.execute(
        """INSERT OR IGNORE INTO users
           (user_id, full_name, username, balance, referred_by, join_date,
            last_daily_bonus_at, total_referral_earnings, language)
           VALUES (?, ?, ?, 0.0, ?, ?, NULL, 0.0, 'en')""",
        (user_id, full_name, username or "", referred_by, now),
    )
    conn.commit()
    conn.close()


def update_balance(user_id: int, delta: float) -> float:
    """Add delta (can be negative) to user balance. Returns new balance."""
    conn = get_db()
    conn.execute(
        "UPDATE users SET balance = balance + ? WHERE user_id = ?",
        (delta, user_id),
    )
    conn.commit()
    row = conn.execute(
        "SELECT balance FROM users WHERE user_id = ?", (user_id,)
    ).fetchone()
    conn.close()
    return row["balance"] if row else 0.0


def set_balance(user_id: int, amount: float) -> None:
    conn = get_db()
    conn.execute(
        "UPDATE users SET balance = ? WHERE user_id = ?", (amount, user_id)
    )
    conn.commit()
    conn.close()


def get_user_lang(user_id: int) -> str:
    """Return user's preferred language code."""
    conn = get_db()
    row = conn.execute(
        "SELECT language FROM users WHERE user_id = ?", (user_id,)
    ).fetchone()
    conn.close()
    if row:
        return row["language"] if row["language"] in STRINGS else "en"
    return "en"


def set_user_lang(user_id: int, lang: str) -> None:
    conn = get_db()
    conn.execute(
        "UPDATE users SET language = ? WHERE user_id = ?", (lang, user_id)
    )
    conn.commit()
    conn.close()


def log_transaction(
    user_id: int, tx_type: str, amount: float, description: str = ""
) -> None:
    """Record a transaction in the transactions table."""
    conn = get_db()
    conn.execute(
        """INSERT INTO transactions (user_id, type, amount, description, created_at)
           VALUES (?, ?, ?, ?, ?)""",
        (user_id, tx_type, amount, description, datetime.utcnow().isoformat()),
    )
    conn.commit()
    conn.close()


def get_referral_count(user_id: int) -> int:
    conn = get_db()
    row = conn.execute(
        "SELECT COUNT(*) as cnt FROM referrals WHERE referrer_id = ?", (user_id,)
    ).fetchone()
    conn.close()
    return row["cnt"] if row else 0


def get_referred_users(user_id: int) -> list:
    conn = get_db()
    rows = conn.execute(
        """SELECT u.full_name, u.username, r.created_at
           FROM referrals r
           JOIN users u ON r.referred_id = u.user_id
           WHERE r.referrer_id = ?
           ORDER BY r.created_at DESC""",
        (user_id,),
    ).fetchall()
    conn.close()
    return rows


def has_completed_task(user_id: int, task_name: str) -> bool:
    conn = get_db()
    row = conn.execute(
        "SELECT id FROM task_completions WHERE user_id = ? AND task_name = ?",
        (user_id, task_name),
    ).fetchone()
    conn.close()
    return row is not None


def mark_task_complete(user_id: int, task_name: str) -> None:
    conn = get_db()
    conn.execute(
        """INSERT OR IGNORE INTO task_completions (user_id, task_name, completed_at)
           VALUES (?, ?, ?)""",
        (user_id, task_name, datetime.utcnow().isoformat()),
    )
    conn.commit()
    conn.close()


def can_claim_daily(user_id: int) -> tuple[bool, Optional[timedelta]]:
    """
    Returns (can_claim, time_remaining).
    time_remaining is None if can_claim is True.
    """
    user = get_user(user_id)
    if not user or not user["last_daily_bonus_at"]:
        return True, None
    last = datetime.fromisoformat(user["last_daily_bonus_at"])
    now = datetime.utcnow()
    diff = now - last
    if diff >= timedelta(hours=24):
        return True, None
    remaining = timedelta(hours=24) - diff
    return False, remaining


def update_daily_bonus_time(user_id: int) -> None:
    conn = get_db()
    conn.execute(
        "UPDATE users SET last_daily_bonus_at = ? WHERE user_id = ?",
        (datetime.utcnow().isoformat(), user_id),
    )
    conn.commit()
    conn.close()


def referral_already_rewarded(referred_id: int) -> bool:
    conn = get_db()
    row = conn.execute(
        "SELECT id FROM referrals WHERE referred_id = ?", (referred_id,)
    ).fetchone()
    conn.close()
    return row is not None


def record_referral(referrer_id: int, referred_id: int, bonus: float) -> None:
    conn = get_db()
    conn.execute(
        """INSERT OR IGNORE INTO referrals
           (referrer_id, referred_id, bonus_paid, created_at)
           VALUES (?, ?, ?, ?)""",
        (referrer_id, referred_id, bonus, datetime.utcnow().isoformat()),
    )
    conn.execute(
        "UPDATE users SET total_referral_earnings = total_referral_earnings + ? WHERE user_id = ?",
        (bonus, referrer_id),
    )
    conn.commit()
    conn.close()


def store_withdrawal(
    user_id: int, method: str, address: str, amount: float
) -> None:
    conn = get_db()
    conn.execute(
        """INSERT INTO withdrawals (user_id, method, address, amount, status, created_at)
           VALUES (?, ?, ?, ?, 'pending', ?)""",
        (user_id, method, address, amount, datetime.utcnow().isoformat()),
    )
    conn.commit()
    conn.close()


# ============================================================
# RANDOM ACCOUNT GENERATION
# ============================================================

FIRST_NAMES = [
    "James", "John", "Robert", "Michael", "William", "David", "Richard",
    "Joseph", "Thomas", "Charles", "Emma", "Olivia", "Ava", "Isabella",
    "Sophia", "Mia", "Charlotte", "Amelia", "Harper", "Evelyn",
    "Liam", "Noah", "Oliver", "Elijah", "Lucas", "Mason", "Logan",
    "Ethan", "Aiden", "Jackson",
]

LAST_NAMES = [
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Miller", "Davis",
    "Garcia", "Rodriguez", "Wilson", "Martinez", "Anderson", "Taylor",
    "Thomas", "Hernandez", "Moore", "Martin", "Jackson", "Thompson", "White",
    "Lopez", "Lee", "Gonzalez", "Harris", "Clark", "Lewis", "Robinson",
    "Walker", "Perez", "Hall",
]

USERNAME_ADJECTIVES = [
    "cool", "fast", "smart", "bright", "sharp", "bold", "wild", "calm",
    "swift", "brave", "dark", "light", "super", "mega", "ultra",
]

USERNAME_NOUNS = [
    "wolf", "eagle", "tiger", "falcon", "shark", "viper", "lion",
    "hawk", "bear", "panther", "phoenix", "dragon", "comet", "storm",
]


def generate_random_account() -> dict:
    """Generate a random first name, last name, and username."""
    first = random.choice(FIRST_NAMES)
    last = random.choice(LAST_NAMES)
    adj = random.choice(USERNAME_ADJECTIVES)
    noun = random.choice(USERNAME_NOUNS)
    num = random.randint(10, 9999)
    username = f"{adj}_{noun}{num}"
    return {"first": first, "last": last, "username": username, "password": TASK_PASSWORD}


# ============================================================
# KEYBOARD BUILDERS
# ============================================================

def main_menu_keyboard(user_id: int) -> ReplyKeyboardMarkup:
    buttons = [
        [t(user_id, "btn_task"), t(user_id, "btn_wallet")],
        [t(user_id, "btn_withdraw"), t(user_id, "btn_referral")],
        [t(user_id, "btn_daily"), t(user_id, "btn_profile")],
        [t(user_id, "btn_leaderboard"), t(user_id, "btn_lang")],
    ]
    return ReplyKeyboardMarkup(buttons, resize_keyboard=True)


def task_menu_keyboard(user_id: int) -> ReplyKeyboardMarkup:
    buttons = [
        [t(user_id, "task_hopenity_btn")],
        [t(user_id, "btn_back")],
    ]
    return ReplyKeyboardMarkup(buttons, resize_keyboard=True)


def task_confirm_keyboard(user_id: int) -> ReplyKeyboardMarkup:
    buttons = [
        [t(user_id, "btn_done"), t(user_id, "btn_cancel")],
        [t(user_id, "btn_back")],
    ]
    return ReplyKeyboardMarkup(buttons, resize_keyboard=True)


def wallet_keyboard(user_id: int) -> ReplyKeyboardMarkup:
    buttons = [
        [t(user_id, "btn_refresh")],
        [t(user_id, "btn_back")],
    ]
    return ReplyKeyboardMarkup(buttons, resize_keyboard=True)


def withdraw_menu_keyboard(user_id: int) -> ReplyKeyboardMarkup:
    buttons = [
        ["🏦 Binance", "📱 Bkash"],
        [t(user_id, "btn_cancel"), t(user_id, "btn_back")],
    ]
    return ReplyKeyboardMarkup(buttons, resize_keyboard=True)


def back_cancel_keyboard(user_id: int) -> ReplyKeyboardMarkup:
    buttons = [
        [t(user_id, "btn_back"), t(user_id, "btn_cancel")],
    ]
    return ReplyKeyboardMarkup(buttons, resize_keyboard=True)


def referral_keyboard(user_id: int) -> ReplyKeyboardMarkup:
    buttons = [
        [t(user_id, "btn_my_referrals")],
        [t(user_id, "btn_back")],
    ]
    return ReplyKeyboardMarkup(buttons, resize_keyboard=True)


def back_keyboard(user_id: int) -> ReplyKeyboardMarkup:
    buttons = [[t(user_id, "btn_back")]]
    return ReplyKeyboardMarkup(buttons, resize_keyboard=True)


def lang_keyboard() -> ReplyKeyboardMarkup:
    buttons = [
        ["🇬🇧 English", "🇧🇩 বাংলা"],
    ]
    return ReplyKeyboardMarkup(buttons, resize_keyboard=True)


# ============================================================
# ADMIN NOTIFICATION HELPER
# ============================================================

async def notify_admins(context: ContextTypes.DEFAULT_TYPE, message: str) -> None:
    """Send a message to all configured admin IDs."""
    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_message(
                chat_id=admin_id,
                text=message,
                parse_mode=ParseMode.MARKDOWN,
            )
        except Exception as e:
            logger.warning(f"Failed to notify admin {admin_id}: {e}")


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


# ============================================================
# /start HANDLER
# ============================================================

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Handle /start command, register user, handle referral."""
    user = update.effective_user
    user_id = user.id
    full_name = user.full_name or "Unknown"
    username = user.username or ""

    # Check if this is a new user
    existing = get_user(user_id)
    is_new = existing is None

    # Parse referral parameter
    referred_by: Optional[int] = None
    if context.args:
        try:
            ref_id = int(context.args[0])
            if ref_id != user_id:
                referred_by = ref_id
            else:
                # Self-referral attempt
                await update.message.reply_text(
                    t(user_id, "referral_self"),
                    parse_mode=ParseMode.MARKDOWN,
                )
        except (ValueError, TypeError):
            pass

    if is_new:
        # Register new user
        create_user(user_id, full_name, username, referred_by)
        logger.info(f"New user registered: {user_id} ({full_name})")

        # Notify admins about new user
        join_time = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
        ref_info = f"Referred by: `{referred_by}`" if referred_by else "No referral"
        admin_msg = (
            f"🆕 *New User Joined!*\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"📛 Name: {full_name}\n"
            f"👤 Username: @{username or 'N/A'}\n"
            f"🆔 ID: `{user_id}`\n"
            f"📅 Joined: {join_time}\n"
            f"🔗 {ref_info}"
        )
        await notify_admins(context, admin_msg)

        # Handle referral reward
        if referred_by and not referral_already_rewarded(user_id):
            referrer = get_user(referred_by)
            if referrer:
                bonus = get_setting("referral_bonus")
                new_bal = update_balance(referred_by, bonus)
                record_referral(referred_by, user_id, bonus)
                log_transaction(
                    referred_by, "referral_bonus", bonus,
                    f"Referral bonus for user {user_id}"
                )
                # Notify referrer
                try:
                    await context.bot.send_message(
                        chat_id=referred_by,
                        text=t(
                            referred_by, "referral_bonus_notify",
                            amount=bonus, balance=new_bal
                        ),
                        parse_mode=ParseMode.MARKDOWN,
                    )
                except Exception as e:
                    logger.warning(f"Could not notify referrer {referred_by}: {e}")
    else:
        # Returning user — update name in case it changed
        conn = get_db()
        conn.execute(
            "UPDATE users SET full_name = ?, username = ? WHERE user_id = ?",
            (full_name, username, user_id),
        )
        conn.commit()
        conn.close()

    # Send welcome message
    await update.message.reply_text(
        t(user_id, "welcome"),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=main_menu_keyboard(user_id),
    )
    return MAIN_MENU


# ============================================================
# MAIN MENU HANDLER
# ============================================================

async def main_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Route button presses from the main menu."""
    user_id = update.effective_user.id
    text = update.message.text.strip()

    # Match against translated button labels
    if text == t(user_id, "btn_task"):
        return await show_task_menu(update, context)
    elif text == t(user_id, "btn_wallet"):
        return await show_wallet(update, context)
    elif text == t(user_id, "btn_withdraw"):
        return await show_withdraw_menu(update, context)
    elif text == t(user_id, "btn_referral"):
        return await show_referral(update, context)
    elif text == t(user_id, "btn_daily"):
        return await claim_daily_bonus(update, context)
    elif text == t(user_id, "btn_profile"):
        return await show_profile(update, context)
    elif text == t(user_id, "btn_leaderboard"):
        return await show_leaderboard(update, context)
    elif text == t(user_id, "btn_lang"):
        return await show_language_select(update, context)
    else:
        await update.message.reply_text(
            t(user_id, "unknown_cmd"),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=main_menu_keyboard(user_id),
        )
        return MAIN_MENU


# ============================================================
# TASK SYSTEM
# ============================================================

async def show_task_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    await update.message.reply_text(
        t(user_id, "task_menu_header"),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=task_menu_keyboard(user_id),
    )
    return TASK_MENU


async def task_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    text = update.message.text.strip()

    if text == t(user_id, "btn_back"):
        # Return to main menu
        await update.message.reply_text(
            t(user_id, "welcome"),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=main_menu_keyboard(user_id),
        )
        return MAIN_MENU

    if text == t(user_id, "task_hopenity_btn"):
        # Check if already completed
        if has_completed_task(user_id, "hopenity_account"):
            await update.message.reply_text(
                t(user_id, "task_already"),
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=task_menu_keyboard(user_id),
            )
            return TASK_MENU

        # Generate random account details
        account = generate_random_account()
        context.user_data["current_task"] = "hopenity_account"
        context.user_data["task_account"] = account

        msg = t(
            user_id, "task_msg",
            first=account["first"],
            last=account["last"],
            username=account["username"],
            password=account["password"],
        )
        await update.message.reply_text(
            msg,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=task_confirm_keyboard(user_id),
        )
        return TASK_CONFIRM

    await update.message.reply_text(
        t(user_id, "unknown_cmd"),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=task_menu_keyboard(user_id),
    )
    return TASK_MENU


async def task_confirm_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    text = update.message.text.strip()

    if text == t(user_id, "btn_cancel"):
        await update.message.reply_text(
            t(user_id, "task_cancelled"),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=main_menu_keyboard(user_id),
        )
        return MAIN_MENU

    if text == t(user_id, "btn_back"):
        await show_task_menu(update, context)
        return TASK_MENU

    if text == t(user_id, "btn_done"):
        task_name = context.user_data.get("current_task", "hopenity_account")

        # Double-check not already completed (race-condition guard)
        if has_completed_task(user_id, task_name):
            await update.message.reply_text(
                t(user_id, "task_already"),
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=main_menu_keyboard(user_id),
            )
            return MAIN_MENU

        reward = get_setting("task_reward")
        new_balance = update_balance(user_id, reward)
        mark_task_complete(user_id, task_name)
        log_transaction(user_id, "task_reward", reward, f"Task: {task_name}")

        await update.message.reply_text(
            t(user_id, "task_done", balance=new_balance),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=main_menu_keyboard(user_id),
        )

        # Notify admins
        u = update.effective_user
        admin_msg = (
            f"✅ *Task Completed*\n"
            f"👤 {u.full_name} (@{u.username or 'N/A'})\n"
            f"🆔 `{user_id}`\n"
            f"📋 Task: {task_name}\n"
            f"💵 Reward: ${reward:.2f}\n"
            f"💰 New Balance: ${new_balance:.2f}"
        )
        await notify_admins(context, admin_msg)
        return MAIN_MENU

    await update.message.reply_text(
        t(user_id, "unknown_cmd"),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=task_confirm_keyboard(user_id),
    )
    return TASK_CONFIRM


# ============================================================
# WALLET SYSTEM
# ============================================================

async def show_wallet(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    user = get_user(user_id)
    balance = user["balance"] if user else 0.0
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

    await update.message.reply_text(
        t(user_id, "wallet_msg", balance=balance, time=now),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=wallet_keyboard(user_id),
    )
    return WALLET_MENU


async def wallet_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    text = update.message.text.strip()

    if text == t(user_id, "btn_back"):
        await update.message.reply_text(
            t(user_id, "welcome"),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=main_menu_keyboard(user_id),
        )
        return MAIN_MENU

    if text == t(user_id, "btn_refresh"):
        return await show_wallet(update, context)

    await update.message.reply_text(
        t(user_id, "unknown_cmd"),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=wallet_keyboard(user_id),
    )
    return WALLET_MENU


# ============================================================
# WITHDRAW SYSTEM
# ============================================================

async def show_withdraw_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    await update.message.reply_text(
        t(user_id, "withdraw_menu"),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=withdraw_menu_keyboard(user_id),
    )
    return WITHDRAW_MENU


async def withdraw_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    text = update.message.text.strip()
    min_w = get_setting("min_withdraw")

    if text == t(user_id, "btn_back") or text == t(user_id, "btn_cancel"):
        await update.message.reply_text(
            t(user_id, "welcome"),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=main_menu_keyboard(user_id),
        )
        return MAIN_MENU

    if text in ("🏦 Binance", "📱 Bkash"):
        # Check balance first
        user = get_user(user_id)
        balance = user["balance"] if user else 0.0

        if balance <= 0 or balance < min_w:
            await update.message.reply_text(
                t(user_id, "withdraw_low", min=min_w, balance=balance),
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=withdraw_menu_keyboard(user_id),
            )
            return WITHDRAW_MENU

        context.user_data["withdraw_method"] = text
        context.user_data["withdraw_amount"] = balance

        if text == "🏦 Binance":
            await update.message.reply_text(
                t(user_id, "withdraw_binance_ask"),
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=back_cancel_keyboard(user_id),
            )
            return WITHDRAW_BINANCE_ADDRESS
        else:
            await update.message.reply_text(
                t(user_id, "withdraw_bkash_ask"),
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=back_cancel_keyboard(user_id),
            )
            return WITHDRAW_BKASH_NUMBER

    await update.message.reply_text(
        t(user_id, "unknown_cmd"),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=withdraw_menu_keyboard(user_id),
    )
    return WITHDRAW_MENU


async def withdraw_binance_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    text = update.message.text.strip()

    if text == t(user_id, "btn_back"):
        return await show_withdraw_menu(update, context)
    if text == t(user_id, "btn_cancel"):
        await update.message.reply_text(
            t(user_id, "welcome"),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=main_menu_keyboard(user_id),
        )
        return MAIN_MENU

    # Basic validation — address should be non-empty and reasonably long
    if len(text) < 10:
        await update.message.reply_text(
            t(user_id, "withdraw_invalid_addr"),
            parse_mode=ParseMode.MARKDOWN,
        )
        return WITHDRAW_BINANCE_ADDRESS

    await _process_withdrawal(update, context, "Binance (USDT BEP-20)", text)
    return MAIN_MENU


async def withdraw_bkash_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    text = update.message.text.strip()

    if text == t(user_id, "btn_back"):
        return await show_withdraw_menu(update, context)
    if text == t(user_id, "btn_cancel"):
        await update.message.reply_text(
            t(user_id, "welcome"),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=main_menu_keyboard(user_id),
        )
        return MAIN_MENU

    # Basic validation for Bkash number (digits, reasonable length)
    digits = text.replace("+", "").replace("-", "").replace(" ", "")
    if not digits.isdigit() or len(digits) < 8:
        await update.message.reply_text(
            t(user_id, "withdraw_invalid_bkash"),
            parse_mode=ParseMode.MARKDOWN,
        )
        return WITHDRAW_BKASH_NUMBER

    await _process_withdrawal(update, context, "Bkash", text)
    return MAIN_MENU


async def _process_withdrawal(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    method: str,
    address: str,
) -> None:
    """Core withdrawal processing shared by Binance and Bkash flows."""
    user_id = update.effective_user.id
    u = update.effective_user
    amount = context.user_data.get("withdraw_amount", 0.0)

    # Store withdrawal record
    store_withdrawal(user_id, method, address, amount)
    log_transaction(user_id, "withdrawal", -amount, f"Withdraw via {method}")

    # Reset user balance to 0
    set_balance(user_id, 0.0)

    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

    # Send confirmation to user
    await update.message.reply_text(
        t(user_id, "withdraw_success", method=method, amount=amount, time=now),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=main_menu_keyboard(user_id),
    )

    # Send wallet deduction message
    await update.message.reply_text(
        t(user_id, "withdraw_deducted", amount=amount),
        parse_mode=ParseMode.MARKDOWN,
    )

    # Notify admins
    admin_msg = (
        f"💸 *New Withdrawal Request*\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"📛 Name: {u.full_name}\n"
        f"👤 Username: @{u.username or 'N/A'}\n"
        f"🆔 ID: `{user_id}`\n"
        f"💳 Method: {method}\n"
        f"📬 Address: `{address}`\n"
        f"💵 Amount: *${amount:.2f} USDT*\n"
        f"🕐 Time: {now}"
    )
    await notify_admins(context, admin_msg)


# ============================================================
# REFERRAL SYSTEM
# ============================================================

async def show_referral(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    user = get_user(user_id)
    if not user:
        return MAIN_MENU

    ref_link = f"[t.me](https://t.me/{BOT_USERNAME}?start={user_id})"
    count = get_referral_count(user_id)
    earnings = user["total_referral_earnings"]

    await update.message.reply_text(
        t(user_id, "referral_msg", link=ref_link, count=count, earnings=earnings),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=referral_keyboard(user_id),
    )
    return REFERRAL_MENU


async def referral_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    text = update.message.text.strip()

    if text == t(user_id, "btn_back"):
        await update.message.reply_text(
            t(user_id, "welcome"),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=main_menu_keyboard(user_id),
        )
        return MAIN_MENU

    if text == t(user_id, "btn_my_referrals"):
        referred = get_referred_users(user_id)
        if not referred:
            msg = t(user_id, "referral_list_empty")
        else:
            header = t(user_id, "referral_list_header")
            lines = []
            for i, r in enumerate(referred, 1):
                uname = f"@{r['username']}" if r["username"] else t(user_id, "not_applicable")
                lines.append(f"{i}. {r['full_name']} ({uname})")
            msg = header + "\n".join(lines)

        await update.message.reply_text(
            msg,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=referral_keyboard(user_id),
        )
        return REFERRAL_MENU

    await update.message.reply_text(
        t(user_id, "unknown_cmd"),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=referral_keyboard(user_id),
    )
    return REFERRAL_MENU


# ============================================================
# DAILY BONUS SYSTEM
# ============================================================

async def claim_daily_bonus(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    can_claim, remaining = can_claim_daily(user_id)

    if not can_claim:
        total_seconds = int(remaining.total_seconds())
        hours, remainder = divmod(total_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        await update.message.reply_text(
            t(user_id, "daily_already", hours=hours, minutes=minutes, seconds=seconds),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=main_menu_keyboard(user_id),
        )
        return MAIN_MENU

    bonus = get_setting("daily_bonus")
    new_balance = update_balance(user_id, bonus)
    update_daily_bonus_time(user_id)
    log_transaction(user_id, "daily_bonus", bonus, "Daily bonus claim")

    # Record in daily_bonus_claims table
    conn = get_db()
    conn.execute(
        "INSERT INTO daily_bonus_claims (user_id, claimed_at) VALUES (?, ?)",
        (user_id, datetime.utcnow().isoformat()),
    )
    conn.commit()
    conn.close()

    await update.message.reply_text(
        t(user_id, "daily_success", amount=bonus, balance=new_balance),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=main_menu_keyboard(user_id),
    )
    return MAIN_MENU


# ============================================================
# PROFILE SYSTEM
# ============================================================

async def show_profile(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    user = get_user(user_id)
    if not user:
        await update.message.reply_text(t(user_id, "user_not_found"))
        return MAIN_MENU

    ref_count = get_referral_count(user_id)
    username = user["username"] or t(user_id, "not_applicable")
    joined = user["join_date"][:10] if user["join_date"] else t(user_id, "not_applicable")
    last_bonus = (
        user["last_daily_bonus_at"][:16].replace("T", " ") + " UTC"
        if user["last_daily_bonus_at"]
        else t(user_id, "not_applicable")
    )

    await update.message.reply_text(
        t(
            user_id, "profile_msg",
            name=user["full_name"],
            username=username,
            user_id=user_id,
            balance=user["balance"],
            referrals=ref_count,
            ref_earn=user["total_referral_earnings"],
            joined=joined,
            last_bonus=last_bonus,
        ),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=back_keyboard(user_id),
    )
    return PROFILE_MENU


async def profile_menu_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    text = update.message.text.strip()

    if text == t(user_id, "btn_back"):
        await update.message.reply_text(
            t(user_id, "welcome"),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=main_menu_keyboard(user_id),
        )
        return MAIN_MENU

    await update.message.reply_text(
        t(user_id, "unknown_cmd"),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=back_keyboard(user_id),
    )
    return PROFILE_MENU


# ============================================================
# LEADERBOARD SYSTEM
# ============================================================

async def show_leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Show two leaderboards: top balance and top referrals."""
    user_id = update.effective_user.id
    conn = get_db()

    # Top 10 by balance
    top_balance = conn.execute(
        "SELECT full_name, username, balance FROM users ORDER BY balance DESC LIMIT 10"
    ).fetchall()

    # Top 10 by referrals
    top_refs = conn.execute(
        """SELECT u.full_name, u.username, COUNT(r.id) as ref_count
           FROM users u
           LEFT JOIN referrals r ON u.user_id = r.referrer_id
           GROUP BY u.user_id
           ORDER BY ref_count DESC
           LIMIT 10"""
    ).fetchall()
    conn.close()

    # Build balance leaderboard message
    balance_msg = t(user_id, "leaderboard_balance")
    medals = ["🥇", "🥈", "🥉"]
    for i, row in enumerate(top_balance):
        medal = medals[i] if i < 3 else f"{i+1}."
        uname = f"@{row['username']}" if row["username"] else row["full_name"]
        balance_msg += f"{medal} {uname} — *${row['balance']:.2f}*\n"

    # Build referral leaderboard message
    ref_msg = t(user_id, "leaderboard_referrals")
    for i, row in enumerate(top_refs):
        medal = medals[i] if i < 3 else f"{i+1}."
        uname = f"@{row['username']}" if row["username"] else row["full_name"]
        ref_msg += f"{medal} {uname} — *{row['ref_count']} referrals*\n"

    full_msg = balance_msg + "\n" + ref_msg

    await update.message.reply_text(
        full_msg,
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=main_menu_keyboard(user_id),
    )
    return MAIN_MENU


async def cmd_leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Command-based leaderboard trigger."""
    await show_leaderboard(update, context)


# ============================================================
# LANGUAGE SELECTION
# ============================================================

async def show_language_select(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    await update.message.reply_text(
        t(user_id, "lang_select"),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=lang_keyboard(),
    )
    return LANG_SELECT


async def lang_select_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    user_id = update.effective_user.id
    text = update.message.text.strip()

    if "English" in text:
        set_user_lang(user_id, "en")
        await update.message.reply_text(
            STRINGS["en"]["lang_changed"],
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=main_menu_keyboard(user_id),
        )
    elif "বাংলা" in text:
        set_user_lang(user_id, "bn")
        await update.message.reply_text(
            STRINGS["bn"]["lang_changed"],
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=main_menu_keyboard(user_id),
        )
    else:
        await update.message.reply_text(
            t(user_id, "lang_select"),
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=lang_keyboard(),
        )
        return LANG_SELECT

    return MAIN_MENU


# ============================================================
# ADMIN COMMANDS
# ============================================================

async def cmd_addbalance(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/addbalance <user_id> <amount>"""
    admin_id = update.effective_user.id
    if not is_admin(admin_id):
        await update.message.reply_text(t(admin_id, "admin_only"))
        return

    if len(context.args) != 2:
        await update.message.reply_text("Usage: `/addbalance <user_id> <amount>`", parse_mode=ParseMode.MARKDOWN)
        return

    try:
        target_id = int(context.args[0])
        amount = float(context.args[1])
    except ValueError:
        await update.message.reply_text("❌ Invalid arguments. User ID must be integer, amount must be number.")
        return

    user = get_user(target_id)
    if not user:
        await update.message.reply_text(t(admin_id, "user_not_found"))
        return

    new_balance = update_balance(target_id, amount)
    log_transaction(target_id, "admin_add", amount, f"Admin {admin_id} added balance")

    await update.message.reply_text(
        t(admin_id, "balance_added", amount=amount, uid=target_id, balance=new_balance),
        parse_mode=ParseMode.MARKDOWN,
    )

    # Notify the target user
    try:
        await context.bot.send_message(
            chat_id=target_id,
            text=(
                f"💰 *Balance Update!*\n\n"
                f"*${amount:.2f} USDT* has been added to your wallet by admin.\n"
                f"💵 New Balance: *${new_balance:.2f} USDT*"
            ),
            parse_mode=ParseMode.MARKDOWN,
        )
    except Exception as e:
        logger.warning(f"Could not notify user {target_id}: {e}")


async def cmd_setbalance(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/setbalance <user_id> <amount>"""
    admin_id = update.effective_user.id
    if not is_admin(admin_id):
        await update.message.reply_text(t(admin_id, "admin_only"))
        return

    if len(context.args) != 2:
        await update.message.reply_text("Usage: `/setbalance <user_id> <amount>`", parse_mode=ParseMode.MARKDOWN)
        return

    try:
        target_id = int(context.args[0])
        amount = float(context.args[1])
    except ValueError:
        await update.message.reply_text("❌ Invalid arguments.")
        return

    if not get_user(target_id):
        await update.message.reply_text(t(admin_id, "user_not_found"))
        return

    set_balance(target_id, amount)
    log_transaction(target_id, "admin_set", amount, f"Admin {admin_id} set balance")
    await update.message.reply_text(
        t(admin_id, "balance_set", uid=target_id, amount=amount),
        parse_mode=ParseMode.MARKDOWN,
    )


async def cmd_balance(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/balance <user_id>"""
    admin_id = update.effective_user.id
    if not is_admin(admin_id):
        await update.message.reply_text(t(admin_id, "admin_only"))
        return

    if len(context.args) != 1:
        await update.message.reply_text("Usage: `/balance <user_id>`", parse_mode=ParseMode.MARKDOWN)
        return

    try:
        target_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Invalid user ID.")
        return

    user = get_user(target_id)
    if not user:
        await update.message.reply_text(t(admin_id, "user_not_found"))
        return

    await update.message.reply_text(
        f"💰 Balance for `{target_id}` (*{user['full_name']}*): *${user['balance']:.2f} USDT*",
        parse_mode=ParseMode.MARKDOWN,
    )


async def cmd_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/user <user_id>"""
    admin_id = update.effective_user.id
    if not is_admin(admin_id):
        await update.message.reply_text(t(admin_id, "admin_only"))
        return

    if len(context.args) != 1:
        await update.message.reply_text("Usage: `/user <user_id>`", parse_mode=ParseMode.MARKDOWN)
        return

    try:
        target_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Invalid user ID.")
        return

    user = get_user(target_id)
    if not user:
        await update.message.reply_text(t(admin_id, "user_not_found"))
        return

    ref_count = get_referral_count(target_id)
    await update.message.reply_text(
        f"👤 *User Info*\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"📛 Name: {user['full_name']}\n"
        f"👤 Username: @{user['username'] or 'N/A'}\n"
        f"🆔 ID: `{target_id}`\n"
        f"💰 Balance: *${user['balance']:.2f} USDT*\n"
        f"👥 Referrals: *{ref_count}*\n"
        f"💵 Referral Earnings: *${user['total_referral_earnings']:.2f}*\n"
        f"📅 Joined: {user['join_date'][:10]}\n"
        f"🔗 Referred by: `{user['referred_by'] or 'None'}`",
        parse_mode=ParseMode.MARKDOWN,
    )


async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/stats — show platform statistics"""
    admin_id = update.effective_user.id
    if not is_admin(admin_id):
        await update.message.reply_text(t(admin_id, "admin_only"))
        return

    conn = get_db()
    total_users = conn.execute("SELECT COUNT(*) as c FROM users").fetchone()["c"]
    total_balance = conn.execute("SELECT COALESCE(SUM(balance),0) as s FROM users").fetchone()["s"]
    total_withdrawals = conn.execute("SELECT COUNT(*) as c FROM withdrawals").fetchone()["c"]
    total_withdraw_amount = conn.execute(
        "SELECT COALESCE(SUM(amount),0) as s FROM withdrawals WHERE status='pending'"
    ).fetchone()["s"]
    total_tasks = conn.execute("SELECT COUNT(*) as c FROM task_completions").fetchone()["c"]
    total_referral_rewards = conn.execute(
        "SELECT COALESCE(SUM(bonus_paid),0) as s FROM referrals"
    ).fetchone()["s"]
    total_daily_claims = conn.execute(
        "SELECT COUNT(*) as c FROM daily_bonus_claims"
    ).fetchone()["c"]
    conn.close()

    await update.message.reply_text(
        f"📊 *Platform Statistics*\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"👥 Total Users: *{total_users}*\n"
        f"💰 Total Balance (all users): *${total_balance:.2f} USDT*\n"
        f"💸 Total Withdrawals: *{total_withdrawals}* (${total_withdraw_amount:.2f})\n"
        f"✅ Total Tasks Completed: *{total_tasks}*\n"
        f"👥 Total Referral Rewards: *${total_referral_rewards:.2f}*\n"
        f"🎁 Total Daily Bonus Claims: *{total_daily_claims}*",
        parse_mode=ParseMode.MARKDOWN,
    )


async def cmd_withdraws(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/withdraws — show recent withdrawal requests"""
    admin_id = update.effective_user.id
    if not is_admin(admin_id):
        await update.message.reply_text(t(admin_id, "admin_only"))
        return

    conn = get_db()
    rows = conn.execute(
        """SELECT w.id, w.user_id, u.full_name, u.username,
                  w.method, w.address, w.amount, w.status, w.created_at
           FROM withdrawals w
           JOIN users u ON w.user_id = u.user_id
           ORDER BY w.created_at DESC
           LIMIT 15"""
    ).fetchall()
    conn.close()

    if not rows:
        await update.message.reply_text("📭 No withdrawal requests yet.")
        return

    msg = "💸 *Recent Withdrawals* (last 15)\n━━━━━━━━━━━━━━━━\n"
    for row in rows:
        uname = f"@{row['username']}" if row["username"] else row["full_name"]
        msg += (
            f"\n#{row['id']} | {uname} (`{row['user_id']}`)\n"
            f"  💳 {row['method']} | 💵 ${row['amount']:.2f} | {row['status'].upper()}\n"
            f"  📬 `{row['address']}`\n"
            f"  🕐 {row['created_at'][:16]}\n"
        )

    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)


async def cmd_users(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/users — show user stats and recent users"""
    admin_id = update.effective_user.id
    if not is_admin(admin_id):
        await update.message.reply_text(t(admin_id, "admin_only"))
        return

    conn = get_db()
    total = conn.execute("SELECT COUNT(*) as c FROM users").fetchone()["c"]
    recent = conn.execute(
        "SELECT full_name, username, user_id, join_date FROM users ORDER BY join_date DESC LIMIT 10"
    ).fetchall()
    conn.close()

    msg = f"👥 *Total Users: {total}*\n━━━━━━━━━━━━━━━━\n*Recent 10:*\n"
    for u in recent:
        uname = f"@{u['username']}" if u["username"] else "N/A"
        msg += f"• {u['full_name']} ({uname}) — `{u['user_id']}`\n"

    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN)


async def cmd_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/broadcast <message> — send message to all users"""
    admin_id = update.effective_user.id
    if not is_admin(admin_id):
        await update.message.reply_text(t(admin_id, "admin_only"))
        return

    if not context.args:
        await update.message.reply_text(
            "Usage: `/broadcast <your message>`", parse_mode=ParseMode.MARKDOWN
        )
        return

    message = " ".join(context.args)
    conn = get_db()
    users = conn.execute("SELECT user_id FROM users").fetchall()
    conn.close()

    success = 0
    failed = 0
    for user in users:
        try:
            await context.bot.send_message(
                chat_id=user["user_id"],
                text=f"📢 *Announcement*\n\n{message}",
                parse_mode=ParseMode.MARKDOWN,
            )
            success += 1
        except Exception:
            failed += 1

    await update.message.reply_text(
        f"📢 Broadcast complete!\n✅ Sent: {success}\n❌ Failed: {failed}"
    )


async def cmd_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/admin — show admin help panel"""
    admin_id = update.effective_user.id
    if not is_admin(admin_id):
        await update.message.reply_text(t(admin_id, "admin_only"))
        return

    await update.message.reply_text(
        "🛠 *Admin Panel*\n"
        "━━━━━━━━━━━━━━━━\n"
        "*User Management:*\n"
        "`/addbalance <id> <amount>` — Add balance\n"
        "`/setbalance <id> <amount>` — Set balance\n"
        "`/balance <id>` — Check balance\n"
        "`/user <id>` — View user info\n"
        "`/users` — List recent users\n\n"
        "*Statistics:*\n"
        "`/stats` — Platform stats\n"
        "`/withdraws` — Recent withdrawals\n"
        "`/leaderboard` — View leaderboard\n\n"
        "*Broadcasting:*\n"
        "`/broadcast <msg>` — Message all users\n\n"
        "*Settings:*\n"
        "`/setconfig task <amount>`\n"
        "`/setconfig referral <amount>`\n"
        "`/setconfig daily <amount>`\n"
        "`/setconfig minwithdraw <amount>`",
        parse_mode=ParseMode.MARKDOWN,
    )


# ============================================================
# SETTINGS SYSTEM (Admin)
# ============================================================

async def cmd_setconfig(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/setconfig <key> <value> — update bot settings"""
    admin_id = update.effective_user.id
    if not is_admin(admin_id):
        await update.message.reply_text(t(admin_id, "admin_only"))
        return

    if len(context.args) != 2:
        await update.message.reply_text(
            "Usage: `/setconfig <key> <value>`\n"
            "Keys: `task`, `referral`, `daily`, `minwithdraw`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    key_map = {
        "task": "task_reward",
        "referral": "referral_bonus",
        "daily": "daily_bonus",
        "minwithdraw": "min_withdraw",
    }

    raw_key = context.args[0].lower()
    db_key = key_map.get(raw_key)
    if not db_key:
        await update.message.reply_text(
            f"❌ Unknown key `{raw_key}`. Use: `task`, `referral`, `daily`, `minwithdraw`",
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    try:
        value = float(context.args[1])
    except ValueError:
        await update.message.reply_text("❌ Value must be a number.")
        return

    set_setting(db_key, value)
    await update.message.reply_text(
        f"✅ *{raw_key}* updated to *${value:.2f}*",
        parse_mode=ParseMode.MARKDOWN,
    )


async def cmd_showconfig(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """/showconfig — display current bot settings"""
    admin_id = update.effective_user.id
    if not is_admin(admin_id):
        await update.message.reply_text(t(admin_id, "admin_only"))
        return

    await update.message.reply_text(
        t(
            admin_id, "settings_menu",
            task=get_setting("task_reward"),
            ref=get_setting("referral_bonus"),
            daily=get_setting("daily_bonus"),
            min_w=get_setting("min_withdraw"),
        ),
        parse_mode=ParseMode.MARKDOWN,
    )


# ============================================================
# FALLBACK / UNKNOWN TEXT HANDLER (outside conversation)
# ============================================================

async def unknown_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle any message that falls outside a ConversationHandler state."""
    user_id = update.effective_user.id
    await update.message.reply_text(
        t(user_id, "unknown_cmd"),
        parse_mode=ParseMode.MARKDOWN,
        reply_markup=main_menu_keyboard(user_id),
    )


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log errors and notify admin optionally."""
    logger.error(f"Exception while handling update: {context.error}", exc_info=context.error)


# ============================================================
# APPLICATION SETUP & MAIN
# ============================================================

def build_application() -> Application:
    """Build and configure the bot application."""
    app = Application.builder().token(BOT_TOKEN).build()

    # ---- Conversation Handler ----
    # This single ConversationHandler manages all user flows
    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("start", cmd_start),
        ],
        states={
            MAIN_MENU: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, main_menu_handler),
            ],
            TASK_MENU: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, task_menu_handler),
            ],
            TASK_CONFIRM: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, task_confirm_handler),
            ],
            WALLET_MENU: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, wallet_menu_handler),
            ],
            WITHDRAW_MENU: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, withdraw_menu_handler),
            ],
            WITHDRAW_BINANCE_ADDRESS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, withdraw_binance_handler),
            ],
            WITHDRAW_BKASH_NUMBER: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, withdraw_bkash_handler),
            ],
            REFERRAL_MENU: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, referral_menu_handler),
            ],
            PROFILE_MENU: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, profile_menu_handler),
            ],
            LANG_SELECT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, lang_select_handler),
            ],
        },
        fallbacks=[
            CommandHandler("start", cmd_start),
            MessageHandler(filters.TEXT & ~filters.COMMAND, unknown_text_handler),
        ],
        # Persist conversation state across bot restarts (optional)
        allow_reentry=True,
    )

    app.add_handler(conv_handler)

    # ---- Standalone Command Handlers (work from any state) ----
    app.add_handler(CommandHandler("leaderboard", cmd_leaderboard))
    app.add_handler(CommandHandler("addbalance", cmd_addbalance))
    app.add_handler(CommandHandler("setbalance", cmd_setbalance))
    app.add_handler(CommandHandler("balance", cmd_balance))
    app.add_handler(CommandHandler("user", cmd_user))
    app.add_handler(CommandHandler("stats", cmd_stats))
    app.add_handler(CommandHandler("withdraws", cmd_withdraws))
    app.add_handler(CommandHandler("users", cmd_users))
    app.add_handler(CommandHandler("broadcast", cmd_broadcast))
    app.add_handler(CommandHandler("admin", cmd_admin))
    app.add_handler(CommandHandler("setconfig", cmd_setconfig))
    app.add_handler(CommandHandler("showconfig", cmd_showconfig))

    # ---- Error Handler ----
    app.add_error_handler(error_handler)

    return app


def main() -> None:
    logger.info("Starting bot...")
    init_db()
    app = build_application()
    logger.info(f"Bot running. Admin IDs: {ADMIN_IDS}")
    # Long polling — works perfectly on Railway
    app.run_polling(
        allowed_updates=Update.ALL_TYPES,
        drop_pending_updates=True,
    )


if __name__ == "__main__":
    main()
