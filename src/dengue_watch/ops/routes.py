"""HTTP routes for Phase 2. app.py delegates here with ONE hook per verb.

Public read-only engine endpoints (no login needed, so judges can hit them directly):
  GET  /api/ops/health                     offline self-check
  GET  /api/ops/forecast                   ward forecasts (+ upcoming-week High/Medium/Low)
  GET  /api/alloc                          constrained allocation  (?stock_pct=30..100&crews=&origin=&horizon=&buffer=&equity=)
  GET  /api/overflow                       intra-city bed overflow routing
  GET  /api/simulate                       recommended crew deployment + ROI ranking (?crews=)
  POST /api/simulate                       simulate a chosen deployment {deployment:{ward:crews}, crew_cap}
  GET  /api/dispatch/<ward>                notices (?lang=en|bn&format=json|sms|whatsapp|html|pdf)
Authenticated platform endpoints: /api/ops/{login,logout,me,settings,plan,plan/generate,tasks,
  tasks/<id>,progress,inbox,inbox/<id>/read,notify/retry,outbox,hospital,capacity,transfers/<id>,
  audit,export/<kind>.<fmt>,briefs,batch}
"""
from __future__ import annotations

import csv
import io
import json
import os
import re
import threading
import time
import traceback
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.parse import parse_qs, unquote

from . import auth, db, notify, simulator, tasks
from . import config as C
from . import dispatch as D
from . import forecast_bridge as FB

ROOT = Path(__file__).resolve().parents[3]
WEB_OPS = ROOT / "web" / "ops"
MAX_OPS_BODY = 256 * 1024
COOKIE = "dw_session"
_READY = {"ok": False, "error": None}
PREFIXES = ("/api/ops/", "/api/alloc", "/api/overflow", "/api/simulate", "/api/dispatch")


def init(app_module) -> None:
    """Called once from app.py: wire the bridge, create + seed the DB, warm caches."""
    FB.init(app_module)
    try:
        db.init_db()
        static = FB.ward_static()
        db.seed_demo([{"ward_id": w, "city": r.city} for w, r in static.iterrows()])
        s = db.get_settings()
        FB.set_force_fallback(bool(s.get("force_fallback")))
        notify.OFFLINE_SIM["on"] = bool(s.get("offline_sim", False))
        _READY["ok"] = True
    except Exception as exc:
        _READY["error"] = f"{type(exc).__name__}: {exc}"
        print(f"[ops] init failed: {_READY['error']}")
        traceback.print_exc()

    def warm():
        try:
            tasks.current_plan()
            simulator.response_curves(db.get_settings().get("origin"))
        except Exception as exc:
            print(f"[ops] warm-up skipped: {exc}")
    threading.Thread(target=warm, daemon=True).start()


def handles(path: str) -> bool:
    if path.startswith(PREFIXES):
        return True
    return path in ("/ops", "/ops/") or (path.startswith("/ops/") and "." not in path.rsplit("/", 1)[-1])


class Reply(Exception):
    def __init__(self, status, body, ctype="application/json; charset=utf-8", headers=None):
        self.status, self.body, self.ctype, self.headers = status, body, ctype, headers or []


def _send(h, status, body, ctype="application/json; charset=utf-8", headers=None):
    if isinstance(body, (bytes, bytearray)):
        raw = bytes(body)
    elif ctype.startswith("application/json"):
        raw = json.dumps(body, ensure_ascii=False, default=str).encode("utf-8")
    else:
        raw = str(body).encode("utf-8")
    h.send_response(status)
    h.send_header("Content-Type", ctype)
    h.send_header("Content-Length", str(len(raw)))
    h.send_header("Cache-Control", "no-store")
    h.send_header("X-Content-Type-Options", "nosniff")
    for k, v in headers or []:
        h.send_header(k, v)
    h.end_headers()
    h.wfile.write(raw)


def _err(status, msg):
    raise Reply(status, {"error": msg})


def _qp(params, key, default=None, cast=str):
    v = params.get(key, [None])[0]
    if v in (None, ""):
        return default
    try:
        return cast(v)
    except (TypeError, ValueError):
        _err(400, f"{key} has an invalid value")


def _overrides(params) -> dict:
    o = {"origin": _qp(params, "origin"), "horizon": _qp(params, "horizon", None, int),
         "stock_pct": _qp(params, "stock_pct", None, float), "total_crews": _qp(params, "crews", None, int),
         "buffer": _qp(params, "buffer", None, float)}
    eq = _qp(params, "equity")
    if eq is not None:
        o["equity"] = eq not in ("0", "false", "no")
    if o["horizon"] is not None and not 1 <= o["horizon"] <= 4:
        _err(400, "horizon must be 1-4 weeks")
    if o["stock_pct"] is not None and not C.STOCK_PCT_MIN <= o["stock_pct"] <= C.STOCK_PCT_MAX:
        _err(400, "stock_pct must be between 30 and 100")
    if o["total_crews"] is not None and not 0 <= o["total_crews"] <= 500:
        _err(400, "crews must be between 0 and 500")
    if o["buffer"] is not None and not 0 <= o["buffer"] <= 1:
        _err(400, "buffer must be between 0 and 1 (e.g. 0.1 = +10%)")
    return {k: v for k, v in o.items() if v is not None}


def _session(h):
    raw = h.headers.get("Cookie") or ""
    try:
        c = SimpleCookie(raw)
    except Exception:
        return None, None
    tok = c.get(COOKIE)
    if not tok:
        return None, None
    nonce = auth.parse_token(tok.value)
    if not nonce:
        return None, None
    s = db.q("SELECT user_id, expires_at FROM sessions WHERE nonce=?", (nonce,), one=True)
    if not s or s["expires_at"] < time.time():
        return None, None
    u = db.user_by_id(s["user_id"])
    return (u, nonce) if u else (None, None)


def _require(h, method, roles=None):
    u, nonce = _session(h)
    if not u:
        _err(401, "Please log in")
    if method == "POST" and not auth.check_csrf(nonce, h.headers.get("X-CSRF-Token")):
        _err(403, "Missing or invalid CSRF token")
    if roles and u["role"] not in roles:
        _err(403, "Your role cannot do this")
    return u


def _cookie_header(value: str, max_age: int, secure: bool) -> tuple:
    return ("Set-Cookie", f"{COOKIE}={value}; Path=/; Max-Age={max_age}; HttpOnly; SameSite=Lax" + ("; Secure" if secure else ""))


def dispatch(h, method: str, parsed) -> None:
    path = parsed.path
    params = parse_qs(parsed.query)
    try:
        if path in ("/ops", "/ops/") or (path.startswith("/ops/") and "." not in path.rsplit("/", 1)[-1]):
            name = path.rstrip("/").rsplit("/", 1)[-1]
            name = "index" if name in ("ops", "") else name
            target = WEB_OPS / f"{name}.html"
            if not re.fullmatch(r"[a-z_]+", name) or not target.is_file():
                _err(404, "Not found")
            return _send(h, 200, target.read_bytes(), "text/html; charset=utf-8")
        if not _READY["ok"] and path not in ("/api/ops/health",) and not path.startswith(("/api/alloc", "/api/overflow", "/api/simulate", "/api/dispatch", "/api/ops/forecast")):
            _err(503, f"Operations database unavailable: {_READY['error']}")
        body = {}
        if method == "POST":
            length = int(h.headers.get("Content-Length", "0") or 0)
            if length > MAX_OPS_BODY:
                _err(413, "Request body too large")
            if length:
                try:
                    body = json.loads(h.rfile.read(length).decode("utf-8"))
                except (ValueError, UnicodeDecodeError):
                    _err(400, "Invalid JSON")
            if not isinstance(body, dict):
                _err(400, "JSON body must be an object")
        out = _route(h, method, path, params, body)
        if isinstance(out, Reply):
            raise out
        return _send(h, 200, out)
    except Reply as r:
        return _send(h, r.status, r.body, r.ctype, r.headers)
    except PermissionError as exc:
        return _send(h, 403, {"error": str(exc)})
    except ValueError as exc:
        return _send(h, 400, {"error": str(exc)})
    except Exception as exc:
        print(f"[ops] {method} {path} failed: {exc}")
        traceback.print_exc()
        return _send(h, 500, {"error": "Operation failed", "detail": str(exc)[:200]})


def _ward_city() -> dict:
    return FB.ward_static().city.to_dict()


def _route(h, method, path, params, body):
    if path == "/api/ops/health":
        return health()
    if path == "/api/ops/forecast" and method == "GET":
        return FB.forecast_payload(_qp(params, "origin") or db.get_settings().get("origin"))
    if path == "/api/alloc" and method == "GET":
        p = tasks.current_plan(_overrides(params))
        return {"origin": p["origin"], "target_date": p["target_date"], "source": p["source"],
                "risk_counts": p["risk_counts"], **p["allocation"]}
    if path == "/api/overflow" and method == "GET":
        p = tasks.current_plan(_overrides(params))
        return {"origin": p["origin"], "target_date": p["target_date"], **p["overflow"]}
    if path == "/api/simulate":
        origin = (body.get("origin") if method == "POST" else _qp(params, "origin")) or db.get_settings().get("origin")
        if method == "GET":
            crews = _qp(params, "crews", C.DEFAULT_SIM_CREWS, int)
            if not 0 <= crews <= 240:
                _err(400, "crews must be between 0 and 240")
            wards = [w for w in (_qp(params, "wards") or "").split(",") if w] or None
            return simulator.recommend(crews, origin, wards=wards)
        dep = body.get("deployment") or {}
        if not isinstance(dep, dict):
            _err(400, "deployment must be an object {ward_id: crews}")
        cap = body.get("crew_cap")
        return simulator.simulate(dep, origin, crew_cap=int(cap) if cap is not None else None)
    if path.startswith("/api/dispatch/") and method == "GET":
        return _dispatch_endpoint(unquote(path[len("/api/dispatch/"):]), params)

    if path == "/api/ops/login" and method == "POST":
        ip = h.client_address[0]
        if not auth.login_allowed(ip):
            _err(429, "Too many login attempts - wait a few minutes")
        u = db.user_by_name(str(body.get("username", "")).strip())
        if not u or not auth.verify_password(str(body.get("password", "")), u["pw_hash"]):
            db.audit({"username": str(body.get("username", ""))[:40], "role": "?"}, "login_failed", {"ip": ip})
            _err(401, "Wrong username or password")
        nonce = auth.new_nonce()
        exp = time.time() + auth.SESSION_TTL
        db.x("INSERT INTO sessions(nonce, user_id, expires_at, created_at) VALUES (?,?,?,?)", (nonce, u["id"], exp, db.now()))
        db.x("DELETE FROM sessions WHERE expires_at < ?", (time.time(),))
        db.audit(u, "login", {"ip": ip})
        secure = (h.headers.get("X-Forwarded-Proto") == "https")
        raise Reply(200, {"user": auth.public_user(u), "csrf": auth.csrf_for(nonce)},
                    headers=[_cookie_header(auth.make_token(nonce, exp), auth.SESSION_TTL, secure)])
    if path == "/api/ops/logout" and method == "POST":
        u, nonce = _session(h)
        if nonce:
            db.x("DELETE FROM sessions WHERE nonce=?", (nonce,))
            db.audit(u, "logout")
        raise Reply(200, {"ok": True}, headers=[_cookie_header("", 0, False)])
    if path == "/api/ops/me":
        u, nonce = _session(h)
        if not u:
            _err(401, "Not logged in")
        return {"user": auth.public_user(u), "csrf": auth.csrf_for(nonce)}

    if path == "/api/ops/settings":
        if method == "GET":
            _require(h, method)
            s = db.get_settings()
            s.pop("_secret", None)
            return s | {"live_adapters": notify.live_adapters()}
        u = _require(h, method, ("super_admin",))
        return update_settings(u, body)
    if path == "/api/ops/plan" and method == "GET":
        u = _require(h, method)
        return scoped_plan(u, tasks.current_plan())
    if path == "/api/ops/plan/generate" and method == "POST":
        u = _require(h, method, ("super_admin", "commissioner", "secretary"))
        return tasks.generate(u, body.get("ward_ids"))
    if path == "/api/ops/tasks":
        if method == "GET":
            u = _require(h, method)
            return {"tasks": tasks.list_tasks(u, _qp(params, "week"), _qp(params, "all") == "1")}
        u = _require(h, method)
        return tasks.create_task(u, body, _ward_city())
    m = re.fullmatch(r"/api/ops/tasks/(\d+)", path)
    if m and method == "POST":
        u = _require(h, method)
        return tasks.update_task(u, int(m.group(1)), body)
    if path == "/api/ops/progress":
        u = _require(h, method)
        return tasks.progress(u, _qp(params, "week"))
    if path == "/api/ops/inbox" and method == "GET":
        u = _require(h, method)
        rows = db.q("SELECT o.*, t.status AS task_status, t.type AS task_type, t.sequence AS task_sequence "
                    "FROM outbox o LEFT JOIN tasks t ON t.id=o.task_id WHERE o.recipient=? AND o.channel='in_app' "
                    "ORDER BY o.id DESC LIMIT 300", (u["username"],))
        links = {(r["dispatch_id"]): r["link"] for r in db.q(
            "SELECT dispatch_id, link FROM outbox WHERE recipient=? AND channel!='in_app'", (u["username"],))}
        for r in rows:
            r["unread"] = r["status"] != "read"
        return {"messages": rows, "unread": sum(r["unread"] for r in rows), "links": links}
    m = re.fullmatch(r"/api/ops/inbox/(\d+|all)/read", path)
    if m and method == "POST":
        u = _require(h, method)
        if m.group(1) == "all":
            db.x("UPDATE outbox SET status='read', read_at=? WHERE recipient=? AND channel='in_app' AND status!='read'",
                 (db.now(), u["username"]))
        else:
            db.x("UPDATE outbox SET status='read', read_at=? WHERE id=? AND recipient=?", (db.now(), int(m.group(1)), u["username"]))
        return {"ok": True}
    if path == "/api/ops/notify/retry" and method == "POST":
        u = _require(h, method, ("super_admin", "commissioner", "secretary"))
        res = notify.retry_queued()
        db.audit(u, "retry_queued", res)
        return res | {"status_counts": notify.status_counts()}
    if path == "/api/ops/outbox" and method == "GET":
        u = _require(h, method, ("super_admin", "commissioner", "secretary"))
        where, args = ("1=1", []) if u["role"] == "super_admin" else ("ward_id=?", [u["ward_id"]])
        return {"messages": db.q(f"SELECT * FROM outbox WHERE {where} ORDER BY id DESC LIMIT 400", args),
                "status_counts": notify.status_counts(), "live_adapters": notify.live_adapters()}
    if path == "/api/ops/hospital" and method == "GET":
        u = _require(h, method)
        return hospital_view(u, tasks.current_plan())
    if path == "/api/ops/capacity" and method == "POST":
        u = _require(h, method, ("super_admin", "hospital"))
        wc = _ward_city()
        ward = body.get("ward_id")
        if ward not in wc:
            _err(400, "Unknown ward")
        if u["role"] == "hospital" and wc[ward] != u["city"]:
            _err(403, "You can only edit wards in your city")
        cap = body.get("capacity")
        occ = body.get("occupied")
        cap = None if cap in (None, "") else int(cap)
        occ = None if occ in (None, "") else int(occ)
        if (cap is not None and not 0 <= cap <= 5000) or (occ is not None and not 0 <= occ <= 5000):
            _err(400, "capacity / occupied must be 0-5000")
        db.set_capacity(ward, cap, occ, u["username"])
        db.audit(u, "update_capacity", {"ward_id": ward, "capacity": cap, "occupied": occ})
        tasks.clear_cache()
        return {"ok": True, "ward_id": ward}
    m = re.fullmatch(r"/api/ops/transfers/(\d+)", path)
    if m and method == "POST":
        u = _require(h, method, ("super_admin", "hospital", "bed_team"))
        t = db.q("SELECT * FROM transfers WHERE id=?", (int(m.group(1)),), one=True)
        if not t or (u["role"] != "super_admin" and t["city"] != u["city"]):
            _err(404, "Transfer not found in your city")
        decision = body.get("decision")
        if decision not in ("accept", "decline"):
            _err(400, "decision must be accept or decline")
        if decision == "decline" and not body.get("reason"):
            _err(400, "A reason is required to decline")
        db.x("UPDATE transfers SET status=?, reason=?, decided_by=?, decided_at=? WHERE id=?",
             ("accepted" if decision == "accept" else "declined", str(body.get("reason", ""))[:300], u["username"], db.now(), t["id"]))
        db.audit(u, f"transfer_{decision}", {"transfer_id": t["id"], "reason": body.get("reason")})
        return {"ok": True}
    if path == "/api/ops/audit" and method == "GET":
        u = _require(h, method, ("super_admin", "commissioner", "secretary"))
        if u["role"] == "super_admin":
            rows = db.q("SELECT * FROM audit ORDER BY id DESC LIMIT 300")
        else:
            rows = db.q("SELECT * FROM audit WHERE username IN (SELECT username FROM users WHERE ward_id=?) "
                        "OR detail LIKE ? ORDER BY id DESC LIMIT 200", (u["ward_id"], f"%{u['ward_id']}%"))
        return {"audit": rows}
    m = re.fullmatch(r"/api/ops/export/(allocation|overflow|tasks|dispatch)\.(csv|json)", path)
    if m and method == "GET":
        u = _require(h, method)
        return export(u, m.group(1), m.group(2))
    if path == "/api/ops/briefs" and method == "GET":
        u = _require(h, method)
        return briefs_bundle(u, _qp(params, "lang", "en"))
    if path == "/api/ops/batch" and method == "POST":
        u = _require(h, method)
        return batch(u, body.get("actions") or [])
    _err(404, "Not found")


NETWORK_PATTERNS = ("urllib.request", "import requests", "http.client", "create_connection", "openai", "anthropic",
                    "httpx", "aiohttp", "smtplib")
CORE_MODULES = ["ops/config.py", "ops/forecast_bridge.py", "ops/allocation.py", "ops/overflow.py", "ops/simulator.py",
                "ops/dispatch.py", "ops/planner.py", "ops/tasks.py", "ops/db.py", "ops/auth.py", "features.py",
                "chatbot.py", "knowledge.py", "future.py"]


def self_check() -> dict:
    """Static scan: core math / templates must contain no network-capable code."""
    base = Path(__file__).resolve().parents[1]
    hits = []
    for rel in CORE_MODULES:
        p = base / rel
        if p.exists():
            src = p.read_text(encoding="utf-8")
            hits += [f"{rel}: {pat}" for pat in NETWORK_PATTERNS if pat in src]
    optional = [f"ops/notify.py: {pat}" for pat in NETWORK_PATTERNS if pat in (base / "ops/notify.py").read_text(encoding="utf-8")]
    return {"core_modules_scanned": len(CORE_MODULES), "core_network_code": hits,
            "optional_live_delivery_code": optional,
            "note": "Network code exists ONLY in optional notification adapters, which run only when configured "
                    "via env vars and online; everything else is local."}


def health() -> dict:
    sc = self_check()
    app = FB._APP
    return {"status": "ok" if _READY["ok"] else "degraded", "offline_capable": not sc["core_network_code"],
            "external_calls": sc["core_network_code"], "self_check": sc,
            "models_loaded": len(getattr(app, "MODELS", {}) or {}), "db_ready": _READY["ok"], "db_error": _READY["error"],
            "forecast_source": "fallback" if FB.FORCE_FALLBACK["on"] else "model",
            "offline_sim": notify.OFFLINE_SIM["on"], "live_adapters": notify.live_adapters(),
            "llm_used": False, "time": db.now()}


def update_settings(u, body) -> dict:
    allowed = {"origin": str, "horizon": int, "stock_pct": float, "total_crews": int, "buffer": float,
               "equity": bool, "stock_override": dict, "force_fallback": bool, "escalation_hours": float, "offline_sim": bool}
    changed = {}
    for k, cast in allowed.items():
        if k in body:
            v = body[k]
            if cast is bool:
                v = bool(v)
            elif cast is dict:
                v = {s: int(n) for s, n in (v or {}).items() if s in ("saline_bags", "diagnostic_kits", "hospital_beds") and n not in (None, "")}
            else:
                v = cast(v)
            changed[k] = v
    if "stock_pct" in changed and not C.STOCK_PCT_MIN <= changed["stock_pct"] <= C.STOCK_PCT_MAX:
        raise ValueError("stock_pct must be between 30 and 100")
    if "horizon" in changed and not 1 <= changed["horizon"] <= 4:
        raise ValueError("horizon must be 1-4")
    if "total_crews" in changed and not 0 <= changed["total_crews"] <= 500:
        raise ValueError("total_crews must be 0-500")
    if "origin" in changed:
        changed["origin"] = FB.snap_origin(changed["origin"]).strftime("%Y-%m-%d")
    for k, v in changed.items():
        db.set_setting(k, v)
    if "force_fallback" in changed:
        FB.set_force_fallback(changed["force_fallback"])
    if "offline_sim" in changed:
        notify.OFFLINE_SIM["on"] = changed["offline_sim"]
    tasks.clear_cache()
    db.audit(u, "update_settings", changed)
    return db.get_settings() | {"live_adapters": notify.live_adapters()}


def scoped_plan(u, p) -> dict:
    alloc = dict(p["allocation"])
    wards = auth.visible_wards(u, alloc["wards"])
    ids = {w["ward_id"] for w in wards}
    cities = {w["city"] for w in wards}
    ovf = p["overflow"]
    full = u["role"] == "super_admin"
    return {"origin": p["origin"], "target_date": p["target_date"], "horizon": p["horizon"], "source": p["source"],
            "settings": p["settings"], "risk_counts": p["risk_counts"],
            "allocation": {**alloc, "wards": wards, "warnings": [w for w in alloc["warnings"] if w["ward_id"] in ids]}
            if not full else alloc,
            "overflow": {**ovf, "wards": [w for w in ovf["wards"] if w["city"] in cities],
                         "transfers": [t for t in ovf["transfers"] if t["city"] in cities],
                         "cities": [c for c in ovf["cities"] if c["city"] in cities],
                         "alerts": [a for a in ovf["alerts"] if a["city"] in cities]} if not full else ovf,
            "trends": {k: v for k, v in p["trends"].items() if k in ids},
            "uncertainty_note": "± values are the held-out mean absolute error of the horizon model (results.json)."}


def hospital_view(u, p) -> dict:
    sp = scoped_plan(u, p)
    cities = {c["city"] for c in sp["overflow"]["cities"]}
    tr = db.q("SELECT * FROM transfers WHERE week=? ORDER BY city, status, id", (p["target_date"],))
    tr = [t for t in tr if u["role"] == "super_admin" or t["city"] in cities]
    caps, occ = db.capacities()
    for w in sp["overflow"]["wards"]:
        w["capacity_overridden"] = w["ward_id"] in caps
    from .allocation import demand_for_cases
    trends = {w["ward_id"]: [{**t, "beds": demand_for_cases(t["predicted_cases"])["hospital_beds"]}
                             for t in p["trends"].get(w["ward_id"], [])] for w in sp["overflow"]["wards"]}
    return {"week": p["target_date"], "origin": p["origin"], "overflow": sp["overflow"], "transfers": tr,
            "trends": trends,
            "capacity_note": sp["overflow"]["summary"]["capacity_note"]}


def _dispatch_endpoint(ward, params):
    p = tasks.current_plan(_overrides(params))
    lang = _qp(params, "lang", "en")
    if lang not in ("en", "bn"):
        _err(400, "lang must be en or bn")
    fmt = _qp(params, "format", "json")
    ctx = D.ward_context(p, ward)
    if fmt == "html":
        raise Reply(200, D.brief_html(ctx, lang), "text/html; charset=utf-8")
    if fmt == "pdf":
        pdf = D.brief_pdf(ctx)
        if pdf is None:
            raise Reply(200, D.brief_html(ctx, lang), "text/html; charset=utf-8",
                        headers=[("X-PDF-Fallback", "reportlab not installed - use browser Print > Save as PDF")])
        raise Reply(200, pdf, "application/pdf", headers=[("Content-Disposition", f'inline; filename="brief_{ward}.pdf"')])
    if fmt in ("sms", "whatsapp"):
        fn = D.sms if fmt == "sms" else D.whatsapp
        texts = [fn(ctx, t, lang) for t in D.TEAMS]
        raise Reply(200, "\n\n-----\n\n".join(x.get("long") or x.get("text") for x in texts), "text/plain; charset=utf-8")
    sms = [D.sms(ctx, t, lang) for t in D.TEAMS]
    wa = [D.whatsapp(ctx, t, lang) for t in D.TEAMS]
    for s, w in zip(sms, wa):
        s["link"] = D.deep_links("", s["short"])["sms"]
        w["link"] = D.deep_links("", w["text"])["whatsapp"]
    return {"ward_id": ward, "target_date": p["target_date"], "source": p["source"], "sms": sms, "whatsapp": wa,
            "brief_url": f"/api/dispatch/{ward}?format=html&lang={lang}"}


def export(u, kind, fmt):
    p = scoped_plan(u, tasks.current_plan())
    if kind == "allocation":
        rows = [{"ward_id": w["ward_id"], "city": w["city"], "risk": w["risk"], "predicted_cases": w["predicted_cases"],
                 "priority_rank": w["priority_rank"], "density": w["population_density_sqkm"],
                 **{f"{s}_required": w["required"][s] for s in w["required"]},
                 **{f"{s}_allocated": w["allocated"][s] for s in w["allocated"]},
                 **{f"{s}_deficit": w["deficit"][s] for s in w["deficit"]},
                 "fulfilment_pct": w["fulfilment_pct"], "deficit_level": w["deficit_level"],
                 "crews_needed": w["crews_needed"], "crews_assigned": w["crews_assigned"], "spray_sequence": w["spray_sequence"]}
                for w in p["allocation"]["wards"]]
    elif kind == "overflow":
        rows = [{k: w[k] for k in ("ward_id", "city", "bed_demand", "capacity", "occupied", "effective_capacity", "deficit",
                                   "headroom", "sent", "received", "net_deficit", "remaining_headroom", "status")}
                for w in p["overflow"]["wards"]] + \
               [{"ward_id": f"TRANSFER {t['from_ward']} -> {t['to_ward']}", "city": t["city"], "sent": t["patients"]}
                for t in p["overflow"]["transfers"]]
    elif kind == "tasks":
        rows = [{k: (json.dumps(v) if isinstance(v, (dict, list)) else v) for k, v in t.items()} for t in tasks.list_tasks(u, None, True)]
    else:
        where, args = tasks.scope_sql(u)
        rows = db.q(f"SELECT * FROM outbox WHERE ward_id IN (SELECT ward_id FROM tasks WHERE {where}) ORDER BY id", args) \
            if u["role"] != "super_admin" else db.q("SELECT * FROM outbox ORDER BY id")
    name = f"dengue_watch_{kind}_{p['target_date']}.{fmt}"
    if fmt == "json":
        raise Reply(200, json.dumps(rows, ensure_ascii=False, default=str, indent=1), "application/json; charset=utf-8",
                    headers=[("Content-Disposition", f'attachment; filename="{name}"')])
    buf = io.StringIO()
    cols = []
    for r in rows:
        cols += [k for k in r if k not in cols]
    wr = csv.DictWriter(buf, fieldnames=cols or ["empty"])
    wr.writeheader()
    for r in rows:
        wr.writerow(r)
    raise Reply(200, "﻿" + buf.getvalue(), "text/csv; charset=utf-8", headers=[("Content-Disposition", f'attachment; filename="{name}"')])


def briefs_bundle(u, lang):
    p = tasks.current_plan()
    wards = auth.visible_wards(u, p["allocation"]["wards"])
    pages = []
    for w in sorted(wards, key=lambda w: w["priority_rank"]):
        html = D.brief_html(D.ward_context(p, w["ward_id"]), lang)
        inner = html.split("<body>", 1)[1].rsplit("</body>", 1)[0]
        pages.append(f'<section style="page-break-after:always">{inner}</section>')
    head = D.brief_html(D.ward_context(p, wards[0]["ward_id"]), lang).split("<body>", 1)[0] if wards else "<html><body>"
    raise Reply(200, head.replace("<title>", "<title>All briefs - ") + "<body>" + "".join(pages) + "</body></html>",
                "text/html; charset=utf-8")


def batch(u, actions) -> dict:
    """Replay actions queued while offline. Each action has an idempotency key."""
    results = []
    for a in actions[:200]:
        key = str(a.get("key", ""))[:100]
        if not key:
            results.append({"ok": False, "error": "missing key"})
            continue
        prev = db.q("SELECT result FROM idempotency WHERE key=?", (f"{u['id']}:{key}",), one=True)
        if prev:
            results.append({"key": key, "ok": True, "duplicate": True})
            continue
        try:
            if a.get("type") == "task_update":
                tasks.update_task(u, int(a["id"]), a.get("changes") or {})
            elif a.get("type") == "inbox_read":
                db.x("UPDATE outbox SET status='read', read_at=? WHERE id=? AND recipient=?", (db.now(), int(a["id"]), u["username"]))
            else:
                raise ValueError("unknown action type")
            db.x("INSERT OR IGNORE INTO idempotency(key, created_at, result) VALUES (?,?,?)", (f"{u['id']}:{key}", db.now(), "ok"))
            results.append({"key": key, "ok": True})
        except Exception as exc:
            results.append({"key": key, "ok": False, "error": str(exc)})
    db.audit(u, "offline_replay", {"actions": len(actions), "ok": sum(r.get("ok", False) for r in results)})
    return {"results": results}
