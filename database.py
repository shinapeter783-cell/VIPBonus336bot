import os
import json
import time
import threading
from datetime import date, timedelta

DB_PATH = os.getenv("DB_PATH", "data.json")
LOCK = threading.Lock()


def _empty_user(user_id: int):
    return {
        "id": user_id,
        "points": 0,
        "spins_total": 0,
        "last_spin_date": None,
        "last_daily_date": None,
        "streak": 0,
        "referred_by": None,
        "referrals": [],
        "used_promos": [],
        "created_at": int(time.time()),
        "username": None,
        "first_name": None,
    }


def _load():
    if not os.path.exists(DB_PATH):
        return {"users": {}}
    try:
        with open(DB_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {"users": {}}


def _save(data):
    tmp = DB_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, DB_PATH)


def get_user(user_id: int):
    with LOCK:
        data = _load()
        uid = str(user_id)
        if uid not in data["users"]:
            data["users"][uid] = _empty_user(user_id)
            _save(data)
        return data["users"][uid]


def update_user(user_id: int, **fields):
    with LOCK:
        data = _load()
        uid = str(user_id)
        if uid not in data["users"]:
            data["users"][uid] = _empty_user(user_id)
        data["users"][uid].update(fields)
        _save(data)
        return data["users"][uid]


def add_points(user_id: int, amount: int):
    with LOCK:
        data = _load()
        uid = str(user_id)
        if uid not in data["users"]:
            data["users"][uid] = _empty_user(user_id)
        data["users"][uid]["points"] = data["users"][uid].get("points", 0) + amount
        _save(data)
        return data["users"][uid]["points"]


def get_leaderboard(limit=10):
    with LOCK:
        data = _load()
        users = list(data["users"].values())
    users.sort(key=lambda u: u.get("points", 0), reverse=True)
    return users[:limit]


def get_all_users():
    with LOCK:
        data = _load()
        return list(data["users"].values())


def total_points_in_system():
    with LOCK:
        data = _load()
        return sum(u.get("points", 0) for u in data["users"].values())


def today_str():
    return date.today().isoformat()


def yesterday_str():
    return (date.today() - timedelta(days=1)).isoformat()
