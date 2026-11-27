"""SQLite persistence for the operations platform (stdlib sqlite3 only).

The database file (data/ops.db, gitignored) is created and seeded idempotently on
startup, so a clean checkout or a wiped Render disk always comes up working.
Historical data stays in the CSV; the DB only stores operational state:
users, settings, ward capacity overrides, tasks, outbox messages, transfer
requests, audit log and offline-replay idempotency keys.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from . import auth
from . import config as C

ROOT = Path(__file__).resolve().parents[3]
DB_PATH = Path(os.getenv("OPS_DB", ROOT / "data/ops.db"))
_LOCAL = threading.local()
_WRITE_LOCK = threading.RLock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  username TEXT UNIQUE NOT NULL,
  pw_hash TEXT NOT NULL,
  role TEXT NOT NULL,              -- super_admin | commissioner | secretary | saline_team | spraying_team | bed_team | hospital
  ward_id TEXT,                    -- commissioner / secretary scope
  city TEXT,                       -- team / hospital scope
  display_name TEXT,
  phone TEXT,                      -- FAKE placeholder numbers in demo seed
  lang TEXT DEFAULT 'en',
  active INTEGER DEFAULT 1,
  created_at TEXT
);
CREATE TABLE IF NOT EXISTS sessions (
  nonce TEXT PRIMARY KEY, user_id INTEGER NOT NULL, expires_at REAL NOT NULL, created_at TEXT
);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS capacity (
  ward_id TEXT PRIMARY KEY, capacity INTEGER, occupied INTEGER DEFAULT 0, updated_by TEXT, updated_at TEXT
);
CREATE TABLE IF NOT EXISTS tasks (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  auto_key TEXT UNIQUE,            -- week|ward|type for auto tasks (idempotent regeneration)
  week TEXT, ward_id TEXT NOT NULL, city TEXT, type TEXT NOT NULL,
  payload TEXT, risk TEXT, priority INTEGER, sequence INTEGER,
  status TEXT NOT NULL DEFAULT 'assigned',   -- assigned|acknowledged|in_progress|done|blocked|cancelled
  source TEXT DEFAULT 'auto', created_by TEXT, assigned_team TEXT,
  created_at TEXT, updated_at TEXT, due_at TEXT, ack_at TEXT, done_at TEXT,
  note TEXT, proof TEXT, override_by TEXT, override_reason TEXT
);
CREATE INDEX IF NOT EXISTS ix_tasks_ward ON tasks(ward_id, week);
CREATE TABLE IF NOT EXISTS outbox (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  dispatch_id TEXT, task_id INTEGER, ward_id TEXT, team TEXT, channel TEXT, lang TEXT,
  recipient TEXT, phone TEXT, body TEXT, link TEXT,
  status TEXT DEFAULT 'queued',    -- queued|sent|delivered|failed|read
  error TEXT, attempts INTEGER DEFAULT 0, created_at TEXT, sent_at TEXT, read_at TEXT,
  UNIQUE(dispatch_id, recipient, channel)
);
CREATE TABLE IF NOT EXISTS transfers (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  week TEXT, city TEXT, from_ward TEXT, to_ward TEXT, patients INTEGER,
  status TEXT DEFAULT 'pending',   -- pending|accepted|declined
  reason TEXT, decided_by TEXT, decided_at TEXT, created_at TEXT,
  UNIQUE(week, from_ward, to_ward)
);
CREATE TABLE IF NOT EXISTS audit (
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, username TEXT, role TEXT, action TEXT, detail TEXT
);
CREATE TABLE IF NOT EXISTS idempotency (key TEXT PRIMARY KEY, created_at TEXT, result TEXT);
"""

DEFAULT_SETTINGS = {
    "origin": C.DEFAULT_ORIGIN, "horizon": C.DEFAULT_PLAN_HORIZON, "stock_pct": 100,
    "total_crews": C.DEFAULT_TOTAL_CREWS, "buffer": C.DEFAULT_SAFETY_BUFFER, "equity": True,
    "stock_override": {}, "force_fallback": False,
}

CITY_SLUG = {"Dhaka North": "dncc", "Dhaka South": "dscc", "Chattogram": "ccc", "Gazipur": "gcc", "Narayanganj": "ncc"}


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def conn() -> sqlite3.Connection:
    c = getattr(_LOCAL, "conn", None)
    if c is None or getattr(_LOCAL, "path", None) != str(DB_PATH):
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        c = sqlite3.connect(str(DB_PATH), timeout=10, check_same_thread=False)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA foreign_keys=ON")
        _LOCAL.conn, _LOCAL.path = c, str(DB_PATH)
    return c


def q(sql: str, args=(), one=False):
    cur = conn().execute(sql, args)
    rows = [dict(r) for r in cur.fetchall()]
    return (rows[0] if rows else None) if one else rows


def x(sql: str, args=()) -> int:
    with _WRITE_LOCK:
        c = conn()
        cur = c.execute(sql, args)
        c.commit()
        return cur.lastrowid


def init_db() -> None:
    with _WRITE_LOCK:
        c = conn()
        c.executescript(SCHEMA)
        c.commit()
    for k, v in DEFAULT_SETTINGS.items():
        x("INSERT OR IGNORE INTO settings(key, value) VALUES (?, ?)", (k, json.dumps(v)))


def get_settings() -> dict:
    out = dict(DEFAULT_SETTINGS)
    for r in q("SELECT key, value FROM settings"):
        try:
            out[r["key"]] = json.loads(r["value"])
        except ValueError:
            pass
    return out


def set_setting(key: str, value) -> None:
    x("INSERT INTO settings(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
      (key, json.dumps(value)))


def audit(user: dict | None, action: str, detail=None) -> None:
    x("INSERT INTO audit(ts, username, role, action, detail) VALUES (?,?,?,?,?)",
      (now(), (user or {}).get("username", "system"), (user or {}).get("role", "system"), action,
       json.dumps(detail or {}, default=str)))


def fake_phone(n: int) -> str:
    # 01700-000xxx: clearly FAKE placeholder numbers for the demo seed.
    return f"+8801700000{n:03d}"


def seed_demo(wards: list[dict]) -> int:
    """Create demo accounts once (idempotent). wards: [{ward_id, city}].

    Passwords come from env vars when present (ADMIN_PASSWORD, DEMO_PASSWORD);
    the fallbacks are DEMO-ONLY values documented in README.
    """
    if q("SELECT COUNT(*) AS n FROM users", one=True)["n"] > 0:
        return 0
    admin_pw = os.getenv("ADMIN_PASSWORD", "admin1234")
    demo_pw = os.getenv("DEMO_PASSWORD", "demo1234")
    specs = [("admin", admin_pw, "super_admin", None, None, "Regional health officer", "en")]
    for w in sorted(wards, key=lambda w: w["ward_id"]):
        slug = f"{CITY_SLUG.get(w['city'], 'x')}{w['ward_id'].rsplit('_', 1)[-1]}"
        specs.append((f"comm_{slug}", demo_pw, "commissioner", w["ward_id"], w["city"], f"Commissioner {w['ward_id']}", "en"))
        specs.append((f"sec_{slug}", demo_pw, "secretary", w["ward_id"], w["city"], f"Secretary {w['ward_id']}", "bn"))
    for city, slug in CITY_SLUG.items():
        if not any(w["city"] == city for w in wards):
            continue
        specs.append((f"saline_{slug}", demo_pw, "saline_team", None, city, f"Saline team {city}", "bn"))
        specs.append((f"spray_{slug}", demo_pw, "spraying_team", None, city, f"Spraying team {city}", "bn"))
        specs.append((f"beds_{slug}", demo_pw, "bed_team", None, city, f"Bed team {city}", "en"))
        specs.append((f"hosp_{slug}", demo_pw, "hospital", None, city, f"Hospital manager {city}", "en"))
    with ThreadPoolExecutor(max_workers=8) as ex:          # PBKDF2 releases the GIL
        hashes = list(ex.map(lambda s: auth.hash_password(s[1]), specs))
    ts = now()
    with _WRITE_LOCK:
        c = conn()
        c.executemany(
            "INSERT OR IGNORE INTO users(username, pw_hash, role, ward_id, city, display_name, phone, lang, created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            [(s[0], h, s[2], s[3], s[4], s[5], fake_phone(i), s[6], ts) for i, (s, h) in enumerate(zip(specs, hashes))])
        c.commit()
    audit(None, "seed_demo_users", {"users": len(specs)})
    return len(specs)


def user_by_name(username: str):
    return q("SELECT * FROM users WHERE username=? AND active=1", (username,), one=True)


def user_by_id(uid: int):
    return q("SELECT * FROM users WHERE id=? AND active=1", (uid,), one=True)


def capacities() -> tuple[dict, dict]:
    caps, occ = {}, {}
    for r in q("SELECT ward_id, capacity, occupied FROM capacity"):
        if r["capacity"] is not None:
            caps[r["ward_id"]] = int(r["capacity"])
        occ[r["ward_id"]] = int(r["occupied"] or 0)
    return caps, occ


def set_capacity(ward_id: str, capacity, occupied, user: str) -> None:
    x("INSERT INTO capacity(ward_id, capacity, occupied, updated_by, updated_at) VALUES (?,?,?,?,?) "
      "ON CONFLICT(ward_id) DO UPDATE SET capacity=COALESCE(excluded.capacity, capacity), "
      "occupied=COALESCE(excluded.occupied, occupied), updated_by=excluded.updated_by, updated_at=excluded.updated_at",
      (ward_id, capacity, occupied, user, now()))
