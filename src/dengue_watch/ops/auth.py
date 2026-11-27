"""Stdlib-only authentication: PBKDF2 passwords, HMAC-signed session tokens, CSRF, rate limit.

* Passwords: PBKDF2-HMAC-SHA256, per-user random 16-byte salt, stored as
  "pbkdf2_sha256$<iterations>$<salt hex>$<hash hex>"; compared with hmac.compare_digest.
* Session: cookie dw_session = "<nonce>.<expiry>.<hmac(secret, nonce|expiry)>", HttpOnly,
  SameSite=Lax (Secure behind HTTPS). The nonce is also stored server side so logout
  really revokes the session.
* CSRF: every state-changing POST must send X-CSRF-Token = hmac(secret, "csrf|" + nonce)
  (returned by /api/ops/login and /api/ops/me). A cross-site form cannot read it.
* Login rate limit: LOGIN_LIMIT attempts per IP per LOGIN_WINDOW seconds.
* Secret: env OPS_SECRET, otherwise a random secret generated once and kept in the DB.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import threading
import time

ITERATIONS = 120_000
SESSION_TTL = 12 * 3600
LOGIN_LIMIT, LOGIN_WINDOW = 10, 300
_ATTEMPTS: dict = {}
_LOCK = threading.Lock()
_SECRET = {"v": None}

ROLE_LABELS = {"super_admin": "Super admin", "commissioner": "Ward commissioner", "secretary": "Commissioner's secretary",
               "saline_team": "Saline team", "spraying_team": "Spraying team", "bed_team": "Hospital bed team",
               "hospital": "Hospital manager"}
TEAM_ROLES = {"saline_team": "saline", "spraying_team": "spraying", "bed_team": "bed_routing"}
HOME = {"super_admin": "/ops/admin.html", "commissioner": "/ops/commissioner.html", "secretary": "/ops/commissioner.html",
        "saline_team": "/ops/team.html", "spraying_team": "/ops/team.html", "bed_team": "/ops/team.html",
        "hospital": "/ops/hospital.html"}


def hash_password(password: str, iterations: int = ITERATIONS) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"pbkdf2_sha256${iterations}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, iters, salt, digest = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt), int(iters))
        return hmac.compare_digest(dk.hex(), digest)
    except Exception:
        return False


def secret() -> bytes:
    if _SECRET["v"] is None:
        env = os.getenv("OPS_SECRET")
        if env:
            _SECRET["v"] = env.encode("utf-8")
        else:
            from . import db
            row = db.q("SELECT value FROM settings WHERE key='_secret'", one=True)
            if row is None:
                val = secrets.token_hex(32)
                db.x("INSERT OR IGNORE INTO settings(key, value) VALUES ('_secret', ?)", (f'"{val}"',))
                row = db.q("SELECT value FROM settings WHERE key='_secret'", one=True)
            _SECRET["v"] = row["value"].strip('"').encode("utf-8")
    return _SECRET["v"]


def _sign(msg: str) -> str:
    return hmac.new(secret(), msg.encode("utf-8"), hashlib.sha256).hexdigest()


def make_token(nonce: str, expires: float) -> str:
    return f"{nonce}.{int(expires)}.{_sign(f'{nonce}|{int(expires)}')}"


def parse_token(token: str):
    """Return nonce if signature valid and not expired, else None."""
    try:
        nonce, exp, sig = token.split(".")
        if not hmac.compare_digest(sig, _sign(f"{nonce}|{exp}")):
            return None
        if float(exp) < time.time():
            return None
        return nonce
    except Exception:
        return None


def csrf_for(nonce: str) -> str:
    return _sign(f"csrf|{nonce}")


def check_csrf(nonce: str, token: str | None) -> bool:
    return bool(token) and hmac.compare_digest(csrf_for(nonce), token)


def login_allowed(ip: str) -> bool:
    now = time.time()
    with _LOCK:
        hits = [t for t in _ATTEMPTS.get(ip, []) if now - t < LOGIN_WINDOW]
        _ATTEMPTS[ip] = hits
        if len(hits) >= LOGIN_LIMIT:
            return False
        hits.append(now)
        if len(_ATTEMPTS) > 5000:
            _ATTEMPTS.clear()
        return True


def new_nonce() -> str:
    return secrets.token_urlsafe(18)


# ----------------------------------------------------------------- scoping
def can_see_ward(user: dict, ward_id: str, ward_city: str) -> bool:
    role = user["role"]
    if role == "super_admin":
        return True
    if role in ("commissioner", "secretary"):
        return user.get("ward_id") == ward_id
    return user.get("city") == ward_city


def visible_wards(user: dict, wards: list[dict]) -> list[dict]:
    return [w for w in wards if can_see_ward(user, w["ward_id"], w["city"])]


def public_user(u: dict) -> dict:
    return {k: u.get(k) for k in ("id", "username", "role", "ward_id", "city", "display_name", "lang")} | {
        "role_label": ROLE_LABELS.get(u["role"], u["role"]), "home": HOME.get(u["role"], "/ops/")}
