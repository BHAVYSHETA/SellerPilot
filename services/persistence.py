import json
from pathlib import Path
from datetime import datetime, timedelta, timezone
from werkzeug.security import generate_password_hash, check_password_hash

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

USERS_FILE = DATA_DIR / "users.json"
COSTS_FILE = DATA_DIR / "product_costs.json"
SUBSCRIPTIONS_FILE = DATA_DIR / "subscriptions.json"


def _load(path, default):
    if not path.exists():
        path.write_text(json.dumps(default, indent=4), encoding="utf-8")
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default


def _save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=4), encoding="utf-8")


def load_users():
    return _load(USERS_FILE, {})


def save_users(users):
    _save(USERS_FILE, users)


def create_user(email, password):
    email = email.strip().lower()
    users = load_users()
    if email in users:
        raise ValueError("An account with this email already exists.")
    now = datetime.now(timezone.utc)
    users[email] = {
        "email": email,
        "password_hash": generate_password_hash(password),
        "created_at": now.isoformat(),
        "trial_ends_at": (now + timedelta(days=7)).isoformat(),
        "plan": "trial",
    }
    save_users(users)
    return users[email]


def authenticate_user(email, password):
    users = load_users()
    user = users.get(email.strip().lower())
    if not user or not check_password_hash(user["password_hash"], password):
        return None
    return user


def ensure_demo_user(email, password):
    users = load_users()
    email = email.lower()
    if email not in users:
        now = datetime.now(timezone.utc)
        users[email] = {
            "email": email,
            "password_hash": generate_password_hash(password),
            "created_at": now.isoformat(),
            "trial_ends_at": (now + timedelta(days=7)).isoformat(),
            "plan": "trial",
        }
        save_users(users)
    return users[email]


def get_user(email):
    return load_users().get(email.strip().lower())


def user_access(email):
    user = get_user(email)
    if not user:
        return {"plan": "unknown", "active": False, "days_left": 0}

    if user.get("plan") in {"premium_monthly", "premium_yearly"}:
        return {"plan": user["plan"], "active": True, "days_left": None}

    try:
        ends = datetime.fromisoformat(user["trial_ends_at"])
        if ends.tzinfo is None:
            ends = ends.replace(tzinfo=timezone.utc)
        seconds = (ends - datetime.now(timezone.utc)).total_seconds()
        days_left = max(0, int((seconds + 86399) // 86400))
    except (KeyError, ValueError, TypeError):
        days_left = 0

    active = days_left > 0
    return {"plan": "trial" if active else "free", "active": active, "days_left": days_left}


def activate_plan(email, plan):
    if plan not in {"premium_monthly", "premium_yearly"}:
        raise ValueError("Invalid premium plan.")
    users = load_users()
    key = email.strip().lower()
    if key not in users:
        raise ValueError("User account not found.")
    users[key]["plan"] = plan
    users[key]["subscription_activated_at"] = datetime.now(timezone.utc).isoformat()
    save_users(users)
    return users[key]


def load_costs():
    return _load(COSTS_FILE, {})


def save_costs(costs):
    _save(COSTS_FILE, costs)


def get_product_cost(email, sku):
    costs = load_costs()
    return costs.get(email.strip().lower(), {}).get(str(sku).strip())


def set_product_cost(email, sku, cost):
    key = email.strip().lower()
    sku = str(sku).strip()
    costs = load_costs()
    costs.setdefault(key, {})[sku] = round(float(cost), 2)
    save_costs(costs)
    return costs[key][sku]


def load_subscriptions():
    return _load(SUBSCRIPTIONS_FILE, {})


def save_subscriptions(data):
    _save(SUBSCRIPTIONS_FILE, data)
