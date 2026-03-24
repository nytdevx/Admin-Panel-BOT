import telebot
from flask import Flask, request, jsonify
from flask_cors import CORS
import sqlite3
import threading
import os

# --- ⚙️ CONFIGURATION ---
BOT_TOKEN = "8528934861:AAGlBNp47WUixtqv7T5KvYOnihij7iXiSJU"
ADMIN_CHAT_ID = "8502323375"

bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)
CORS(app)

# --- 🗄️ DATABASE SETUP ---
DB_FILE = 'quiz_game.db'

def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE,
            points INTEGER DEFAULT 0,
            language TEXT
        )
    ''')
    conn.commit()
    conn.close()

init_db()

# --- 🌐 WEB API FOR HTML APP ---
@app.route('/')
def home():
    return "🔥 Quiz Admin Server is running perfectly on Railway!"

@app.route('/api/update_user', methods=['POST'])
def update_user():
    data = request.json
    name = data.get('name')
    points = data.get('points', 0)
    lang = data.get('lang', 'en')

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    cursor.execute("SELECT points FROM users WHERE name = ?", (name,))
    user = cursor.fetchone()

    if user:
        cursor.execute("UPDATE users SET points = ?, language = ? WHERE name = ?", (points, lang, name))
    else:
        cursor.execute("INSERT INTO users (name, points, language) VALUES (?, ?, ?)", (name, points, lang))
        bot.send_message(ADMIN_CHAT_ID, f"🆕 New User Registered!\n👤 Name: {name}\n🌍 Lang: {lang}")

    conn.commit()
    conn.close()
    return jsonify({"status": "success", "message": "Data Saved!"})


# --- 🤖 TELEGRAM BOT COMMANDS ---
@bot.message_handler(commands=['start', 'stats'])
def get_stats(message):
    if str(message.chat.id) != str(ADMIN_CHAT_ID):
        bot.reply_to(message, "❌ Unauthorized Access!")
        return

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*), SUM(points) FROM users")
    total_users, total_points = cursor.fetchone()
    conn.close()

    stats_msg = (
        "👑 **Admin Panel Overview**\n"
        f"👥 Total Players: {total_users}\n"
        f"💰 Points Distributed: {total_points or 0}"
    )
    bot.reply_to(message, stats_msg)

@bot.message_handler(commands=['users'])
def list_users(message):
    if str(message.chat.id) != str(ADMIN_CHAT_ID): return

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT name, points FROM users ORDER BY points DESC LIMIT 10")
    users = cursor.fetchall()
    conn.close()

    if not users:
        bot.reply_to(message, "No users yet.")
        return

    user_list = "🏆 **Leaderboard (Top 10):**\n\n"
    for i, user in enumerate(users, 1):
        user_list += f"{i}. {user[0]} — {user[1]} pts\n"
    
    bot.reply_to(message, user_list)


# --- 🏃‍♂️ RUN BOTH (BOT & FLASK) ---
def run_bot():
    bot.infinity_polling(timeout=10, long_polling_timeout=5)

if __name__ == '__main__':
    # Threading the bot polling to run in parallel with Flask
    bot_thread = threading.Thread(target=run_bot)
    bot_thread.daemon = True
    bot_thread.start()
    
    # Railway passes the port as an environment variable
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
