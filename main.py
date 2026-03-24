import os
import logging
from datetime import datetime
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    KeyboardButton,
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ConversationHandler,
    ContextTypes,
    filters,
)
import database as db

# ─── Logging ────────────────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ─── Config ─────────────────────────────────────────────────────────────────
BOT_TOKEN   = os.environ.get("BOT_TOKEN2", "")
ADMIN_ID    = int(os.environ.get("ADMIN_ID", "0"))

# ─── Conversation states ─────────────────────────────────────────────────────
(
    STATE_USER_DETAIL,
    STATE_SET_POINTS,
    STATE_REGISTER_NAME,
    STATE_REGISTER_DONE,
) = range(4)

# ─── Helpers ─────────────────────────────────────────────────────────────────

def is_admin(update: Update) -> bool:
    return update.effective_user.id == ADMIN_ID


def rank_label(pts: int) -> str:
    ranks = [
        (4000, "🏆 Legend"),
        (1500, "👑 Master"),
        (600,  "🔷 Pro"),
        (200,  "📘 Scholar"),
        (0,    "⭐ Rookie"),
    ]
    for threshold, label in ranks:
        if pts >= threshold:
            return label
    return "⭐ Rookie"


def build_main_menu() -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton("👥 Total Users", callback_data="total_users")],
        [InlineKeyboardButton("📊 Statistics",  callback_data="stats")],
        [InlineKeyboardButton("🔄 Refresh",     callback_data="refresh_main")],
    ]
    return InlineKeyboardMarkup(buttons)


def build_user_list_keyboard(page: int = 0, page_size: int = 8) -> InlineKeyboardMarkup:
    users    = db.get_all_users()
    total    = len(users)
    start    = page * page_size
    end      = start + page_size
    chunk    = users[start:end]

    buttons = []
    for u in chunk:
        ban_icon = "🚫" if u.get("banned") else "✅"
        label    = f"{ban_icon} {u['name'][:20]}  •  {u['points']} pts"
        buttons.append([InlineKeyboardButton(label, callback_data=f"user_detail:{u['telegram_id']}")])

    # Pagination row
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"userlist:{page-1}"))
    if end < total:
        nav.append(InlineKeyboardButton("Next ➡️", callback_data=f"userlist:{page+1}"))
    if nav:
        buttons.append(nav)

    buttons.append([InlineKeyboardButton("🏠 Back to Menu", callback_data="main_menu")])
    return InlineKeyboardMarkup(buttons)


def build_user_detail_keyboard(telegram_id: str) -> InlineKeyboardMarkup:
    user    = db.get_user(telegram_id)
    ban_lbl = "🔓 Unban User" if user and user.get("banned") else "🚫 Ban User"
    buttons = [
        [InlineKeyboardButton("➕ Add Points",    callback_data=f"addpts:{telegram_id}")],
        [InlineKeyboardButton("➖ Remove Points", callback_data=f"subpts:{telegram_id}")],
        [InlineKeyboardButton("✏️ Set Points",    callback_data=f"setpts:{telegram_id}")],
        [InlineKeyboardButton(ban_lbl,            callback_data=f"ban:{telegram_id}")],
        [InlineKeyboardButton("🗑️ Delete User",   callback_data=f"delete:{telegram_id}")],
        [InlineKeyboardButton("🔙 Back to Users", callback_data="total_users")],
        [InlineKeyboardButton("🏠 Back to Menu",  callback_data="main_menu")],
    ]
    return InlineKeyboardMarkup(buttons)


def user_detail_text(telegram_id: str) -> str:
    u = db.get_user(telegram_id)
    if not u:
        return "❌ User not found."

    status = "🚫 BANNED" if u.get("banned") else "✅ Active"

    return (
        f"👤 Name: {u['name']}\n"
        f"🆔 ID: {telegram_id}\n"
        f"💰 Points: {u['points']}\n"
        f"🎖 Rank: {rank_label(u['points'])}\n"
        f"📊 Status: {status}"
    )


# ─── Command Handlers ────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user

    # Admin flow
    if is_admin(update):
        users     = db.get_all_users()
        total     = len(users)
        banned    = sum(1 for u in users if u.get("banned"))
        total_pts = sum(u["points"] for u in users)
        await update.message.reply_text(
            f"🤖 <b>QuizMaster Pro — Admin Panel</b>\n\n"
            f"👥 Total Users : <b>{total}</b>\n"
            f"🚫 Banned      : <b>{banned}</b>\n"
            f"💰 Total Pts   : <b>{total_pts}</b>",
            parse_mode="HTML",
            reply_markup=build_main_menu(),
        )
        return ConversationHandler.END

    # Existing user flow
    existing = db.get_user(str(user.id))
    if existing:
        if existing.get("banned"):
            await update.message.reply_text("🚫 You have been banned from using this bot.")
            return ConversationHandler.END
        await update.message.reply_text(
            f"👋 Welcome back, <b>{existing['name']}</b>!\n"
            f"💰 Your points: <b>{existing['points']}</b>\n"
            f"🎖️ Rank: {rank_label(existing['points'])}",
            parse_mode="HTML",
        )
        return ConversationHandler.END

    # New user
    await update.message.reply_text(
        "👋 Welcome to <b>QuizMaster Pro</b>!\n\n"
        "Please enter your <b>full name</b> to register:",
        parse_mode="HTML",
    )
    return STATE_REGISTER_NAME


async def register_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    name = update.message.text.strip()
    if len(name) < 2:
        await update.message.reply_text("⚠️ Name must be at least 2 characters. Try again:")
        return STATE_REGISTER_NAME

    user = update.effective_user
    db.upsert_user(str(user.id), {
        "name": name,
        "points": 0,
        "banned": False,
        "registered_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
    })

    await update.message.reply_text(
        f"✅ Registered successfully!\n\n"
        f"👤 Name: <b>{name}</b>\n"
        f"🎖️ Rank: ⭐ Rookie\n\n"
        f"You can now use the QuizMaster Pro web app. Good luck! 🚀",
        parse_mode="HTML",
    )

    # Notify admin
    await context.bot.send_message(
        chat_id=ADMIN_ID,
        text=(
            f"🆕 <b>New User Registered</b>\n\n"
            f"👤 Name: <b>{name}</b>\n"
            f"🆔 ID: <code>{user.id}</code>\n"
            f"📅 Time: {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        ),
        parse_mode="HTML",
    )
    return ConversationHandler.END


# ─── Callback Query Handler ──────────────────────────────────────────────────

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if not is_admin(update):
        await query.edit_message_text("⛔ Admin only.")
        return

    data = query.data

    # ── Main menu ─────────────────────────────────────────────────────────────
    if data in ("main_menu", "refresh_main"):
        users     = db.get_all_users()
        total     = len(users)
        banned    = sum(1 for u in users if u.get("banned"))
        total_pts = sum(u["points"] for u in users)
        await query.edit_message_text(
            f"🤖 <b>QuizMaster Pro — Admin Panel</b>\n\n"
            f"👥 Total Users : <b>{total}</b>\n"
            f"🚫 Banned      : <b>{banned}</b>\n"
            f"💰 Total Pts   : <b>{total_pts}</b>",
            parse_mode="HTML",
            reply_markup=build_main_menu(),
        )

    # ── Statistics ────────────────────────────────────────────────────────────
    elif data == "stats":
        users  = db.get_all_users()
        if not users:
            text = "📊 No users yet."
        else:
            top5 = sorted(users, key=lambda u: u["points"], reverse=True)[:5]
            lines = [f"📊 <b>Top 5 Users</b>\n"]
            for i, u in enumerate(top5, 1):
                lines.append(f"{i}. {u['name']} — {u['points']} pts ({rank_label(u['points'])})")
            text = "\n".join(lines)
        back = InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back to Menu", callback_data="main_menu")]])
        await query.edit_message_text(text, parse_mode="HTML", reply_markup=back)

    # ── User list ─────────────────────────────────────────────────────────────
    elif data == "total_users" or data.startswith("userlist:"):
        page = 0
        if data.startswith("userlist:"):
            page = int(data.split(":")[1])
        users = db.get_all_users()
        await query.edit_message_text(
            f"👥 <b>All Users</b> ({len(users)} total)\n\nSelect a user to manage:",
            parse_mode="HTML",
            reply_markup=build_user_list_keyboard(page),
        )

    # ── User detail ───────────────────────────────────────────────────────────
    elif data.startswith("user_detail:"):
        tid = data.split(":", 1)[1]
        await query.edit_message_text(
            user_detail_text(tid),
            parse_mode="HTML",
            reply_markup=build_user_detail_keyboard(tid),
        )

    # ── Ban / Unban ───────────────────────────────────────────────────────────
    elif data.startswith("ban:"):
        tid        = data.split(":", 1)[1]
        new_status = db.toggle_ban(tid)
        action     = "🚫 Banned" if new_status else "🔓 Unbanned"
        u          = db.get_user(tid)
        name       = u["name"] if u else tid
        await query.edit_message_text(
            f"{action}: <b>{name}</b>\n\n" + user_detail_text(tid),
            parse_mode="HTML",
            reply_markup=build_user_detail_keyboard(tid),
        )

    # ── Delete user ───────────────────────────────────────────────────────────
    elif data.startswith("delete:"):
        tid  = data.split(":", 1)[1]
        u    = db.get_user(tid)
        name = u["name"] if u else tid
        confirm_kb = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ Yes, Delete", callback_data=f"confirm_delete:{tid}"),
                InlineKeyboardButton("❌ Cancel",      callback_data=f"user_detail:{tid}"),
            ]
        ])
        await query.edit_message_text(
            f"⚠️ Are you sure you want to delete <b>{name}</b>?\n"
            f"This action cannot be undone.",
            parse_mode="HTML",
            reply_markup=confirm_kb,
        )

    elif data.startswith("confirm_delete:"):
        tid  = data.split(":", 1)[1]
        u    = db.get_user(tid)
        name = u["name"] if u else tid
        db.delete_user(tid)
        await query.edit_message_text(
            f"🗑️ User <b>{name}</b> has been deleted.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Back to Users", callback_data="total_users")],
                [InlineKeyboardButton("🏠 Back to Menu",  callback_data="main_menu")],
            ]),
        )

    # ── Add / Remove / Set points ─────────────────────────────────────────────
    elif data.startswith(("addpts:", "subpts:", "setpts:")):
        action, tid               = data.split(":", 1)
        context.user_data["pts_action"] = action
        context.user_data["pts_target"] = tid
        prompts = {
            "addpts": "➕ How many points to <b>add</b>?",
            "subpts": "➖ How many points to <b>remove</b>?",
            "setpts": "✏️ Set points to exactly:",
        }
        back_kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Cancel", callback_data=f"user_detail:{tid}")]
        ])
        await query.edit_message_text(
            prompts[action] + "\n\nSend a number:",
            parse_mode="HTML",
            reply_markup=back_kb,
        )
        return STATE_SET_POINTS


async def handle_set_points(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update):
        return ConversationHandler.END

    text   = update.message.text.strip()
    action = context.user_data.get("pts_action")
    tid    = context.user_data.get("pts_target")

    if not text.lstrip("-").isdigit():
        await update.message.reply_text("⚠️ Please send a valid number.")
        return STATE_SET_POINTS

    amount = int(text)
    u      = db.get_user(tid)
    if not u:
        await update.message.reply_text("❌ User not found.")
        return ConversationHandler.END

    current = u["points"]
    if action == "addpts":
        new_pts = current + abs(amount)
    elif action == "subpts":
        new_pts = max(0, current - abs(amount))
    else:  # setpts
        new_pts = max(0, amount)

    db.set_points(tid, new_pts)
    u = db.get_user(tid)

    await update.message.reply_text(
        f"✅ Points updated for <b>{u['name']}</b>\n"
        f"Old: {current} pts → New: <b>{new_pts} pts</b>\n"
        f"🎖️ Rank: {rank_label(new_pts)}",
        parse_mode="HTML",
        reply_markup=build_user_detail_keyboard(tid),
    )
    return ConversationHandler.END


# ─── Webhook / Polling chooser ───────────────────────────────────────────────

def main():
    if not BOT_TOKEN:
        raise ValueError("BOT_TOKEN environment variable is not set.")

    app = Application.builder().token(BOT_TOKEN).build()

    conv = ConversationHandler(
        entry_points=[CommandHandler("start", cmd_start)],
        states={
            STATE_REGISTER_NAME: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, register_name)
            ],
            STATE_SET_POINTS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_set_points),
                CallbackQueryHandler(handle_callback),
            ],
        },
        fallbacks=[CommandHandler("start", cmd_start)],
        per_message=False,
    )

    app.add_handler(conv)
    app.add_handler(CallbackQueryHandler(handle_callback))

    logger.info("Bot is running...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
    
