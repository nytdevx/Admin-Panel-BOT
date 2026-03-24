import json
import os

DB_FILE = "users.json"

def load_db() -> dict:
    if not os.path.exists(DB_FILE):
        return {}
    with open(DB_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_db(data: dict):
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def get_user(telegram_id: str) -> dict | None:
    db = load_db()
    return db.get(str(telegram_id))

def upsert_user(telegram_id: str, payload: dict):
    """Insert or update a user record."""
    db = load_db()
    uid = str(telegram_id)
    if uid not in db:
        db[uid] = {
            "telegram_id": uid,
            "name": "",
            "points": 0,
            "banned": False,
            "registered_at": payload.get("registered_at", ""),
        }
    db[uid].update(payload)
    save_db(db)

def get_all_users() -> list[dict]:
    db = load_db()
    return list(db.values())

def set_points(telegram_id: str, points: int):
    db = load_db()
    uid = str(telegram_id)
    if uid in db:
        db[uid]["points"] = max(0, points)
        save_db(db)
        return True
    return False

def toggle_ban(telegram_id: str) -> bool:
    """Returns new ban status."""
    db = load_db()
    uid = str(telegram_id)
    if uid in db:
        db[uid]["banned"] = not db[uid].get("banned", False)
        save_db(db)
        return db[uid]["banned"]
    return False

def delete_user(telegram_id: str) -> bool:
    db = load_db()
    uid = str(telegram_id)
    if uid in db:
        del db[uid]
        save_db(db)
        return True
    return False
  
