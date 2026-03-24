import telebot
from flask import Flask, request, jsonify
from flask_cors import CORS
import sqlite3
import threading

# --- ⚙️ CONFIGURATION ---
BOT_TOKEN = "8528934861:AAGlBNp47WUixtqv7T5KvYOnihij7iXiSJU"
ADMIN_CHAT_ID = "8502323375"

bot = telebot.TeleBot(BOT_TOKEN)
app = Flask(__name__)
CORS(app) # HTML theke request allow korar jonno

# --- 🗄️ DATABASE SETUP ---
def init_db():
    conn = sqlite3.connect('quiz_game.db')
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
    return "🔥 Quiz Admin Server is Running!"

@app.route('/api/update_user', methods=['POST'])
def update_user():
    data = request.json
    name = data.get('name')
    points = data.get('points', 0)
    lang = data.get('lang', 'en')

    conn = sqlite3.connect('quiz_game.db')
    cursor = conn.cursor()
    
    # User thakle update hobe, na thakle create hobe
    cursor.execute("SELECT points FROM users WHERE name = ?", (name,))
    user = cursor.fetchone()

    if user:
        cursor.execute("UPDATE users SET points = ?, language = ? WHERE name = ?", (points, lang, name))
    else:
        cursor.execute("INSERT INTO users (name, points, language) VALUES (?, ?, ?)", (name, points, lang))
        # Notun user join korle Telegram notification
        bot.send_message(ADMIN_CHAT_ID, f"🆕 New User Registered!\n👤 Name: {name}\n🌍 Lang: {lang}")

    conn.commit()
    conn.close()
    return jsonify({"status": "success", "message": "Data Saved!"})


# --- 🤖 TELEGRAM BOT COMMANDS ---
@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    if str(message.chat.id) != str(ADMIN_CHAT_ID):
        bot.reply_to(message, "❌ You are not the authorized Admin!")
        return
    
    help_text = (
        "👑 Welcome to Quiz Admin Panel Bot!\n\n"
        "Commands:\n"
        "📊 /stats - See total users and top scores\n"
        "👥 /users - List all registered users\n"
        "📢 /broadcast [msg] - Send message to admin"
    )
    bot.reply_to(message, help_text)

@bot.message_handler(commands=['stats'])
def get_stats(message):
    if str(message.chat.id) != str(ADMIN_CHAT_ID): return

    conn = sqlite3.connect('quiz_game.db')
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*), SUM(points) FROM users")
    total_users, total_points = cursor.fetchone()
    conn.close()

    bot.reply_to(message, f"📊 **App Overview**:\n👥 Total Players: {total_users}\n💰 Points Distributed: {total_points or 0}")

@bot.message_handler(commands=['users'])
def list_users(message):
    if str(message.chat.id) != str(ADMIN_CHAT_ID): return

    conn = sqlite3.connect('quiz_game.db')
    cursor = conn.cursor()
    cursor.execute("SELECT name, points FROM users ORDER BY points DESC LIMIT 10")
    users = cursor.fetchall()
    conn.close()

    if not users:
        bot.reply_to(message, "No users found in database.")
        return

    user_list = "🏆 **Top 10 Players leaderboard:**\n\n"
    for i, user in enumerate(users, 1):
        user_list += f"{i}. {user[0]} — {user[1]} pts\n"
    
    bot.reply_to(message, user_list)


# --- 🏃‍♂️ RUN BOTH (BOT & FLASK) ---
def run_bot():
    bot.polling(none_stop=True)

if __name__ == '__main__':
    # Bot ke background a run korar jonno threading
    threading.Thread(target=run_bot).start()
    app.run(host='0.0.0.0', port=5000)
