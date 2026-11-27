"""Task lifecycle: plan -> tasks -> notices -> team updates -> progress.

Status flow: assigned -> acknowledged -> in_progress -> done   (or blocked / cancelled)

Auto mode (`generate`): builds tasks from the engines for every ward in the user's
scope, ordered Critical -> High -> Medium -> Low, with notices attached. Each auto task
has auto_key = "<week>|<ward>|<type>", so re-running the same week UPDATES the open
tasks instead of duplicating them (and leaves acknowledged / finished work untouched
except for refreshed quantities).
Manual mode: commissioner / secretary / super admin can create, edit, reassign,
cancel or override tasks; overrides record who and why.
"""
from __future__ import annotations

import json
import threading
from datetime import datetime, timedelta, timezone

from . import auth, db, dispatch as D, notify, planner
from . import config as C

TYPE_TEAM = {"saline": "saline_team", "spraying": "spraying_team", "bed_routing": "bed_team", "other": None}
TEAM_TYPE = {v: k for k, v in TYPE_TEAM.items() if v}
DISPATCH_TEAM = {"saline": "saline", "spraying": "spraying", "bed_routing": "bed", "other": "saline"}
STATUSES = ("assigned", "acknowledged", "in_progress", "done", "blocked", "cancelled")
TEAM_ALLOWED = {"acknowledged", "in_progress", "done", "blocked"}
RISK_IDX = {k: i for i, k in enumerate(C.RISK_ORDER)}

_PLAN_CACHE: dict = {}
_PLAN_LOCK = threading.Lock()


def _parse(ts: str):
    return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def plan_settings(overrides: dict | None = None) -> dict:
    s = db.get_settings()
    for k, v in (overrides or {}).items():
        if v is not None:
            s[k] = v
    return s


def current_plan(overrides: dict | None = None) -> dict:
    s = plan_settings(overrides)
    caps, occ = db.capacities()
    key = json.dumps([s.get("origin"), s.get("horizon"), s.get("stock_pct"), s.get("total_crews"), s.get("buffer"),
                      s.get("equity"), s.get("stock_override"), caps, occ, s.get("force_fallback")], sort_keys=True, default=str)
    with _PLAN_LOCK:
        if key in _PLAN_CACHE:
            return _PLAN_CACHE[key]
    from . import forecast_bridge as FB
    FB.set_force_fallback(bool(s.get("force_fallback")))
    p = planner.plan(origin=s.get("origin"), horizon=int(s.get("horizon", 1)), stock_pct=float(s.get("stock_pct", 100)),
                     total_crews=int(s.get("total_crews", C.DEFAULT_TOTAL_CREWS)), buffer=float(s.get("buffer", 0)),
                     full_stock_override=s.get("stock_override") or None, capacities=caps, occupied=occ,
                     equity=bool(s.get("equity", True)))
    p["settings"] = {k: s.get(k) for k in ("origin", "horizon", "stock_pct", "total_crews", "buffer", "equity",
                                           "stock_override", "force_fallback")}
    with _PLAN_LOCK:
        _PLAN_CACHE[key] = p
        if len(_PLAN_CACHE) > 30:
            _PLAN_CACHE.pop(next(iter(_PLAN_CACHE)))
    return p


def clear_cache() -> None:
    with _PLAN_LOCK:
        _PLAN_CACHE.clear()


def _recipients(team_role: str, city: str) -> list[dict]:
    return db.q("SELECT username, phone, lang FROM users WHERE role=? AND city=? AND active=1", (team_role, city))


def _task_payloads(p: dict, ward: dict) -> list[tuple[str, dict]]:
    """(type, payload) pairs the engines imply for one ward."""
    out = []
    ctx = D.ward_context(p, ward["ward_id"])
    b = ctx["beds"]
    out.append(("saline", {"saline_bags": ward["allocated"]["saline_bags"], "saline_required": ward["required"]["saline_bags"],
                           "diagnostic_kits": ward["allocated"]["diagnostic_kits"],
                           "kits_required": ward["required"]["diagnostic_kits"],
                           "deficit_level": ward["deficit_level"], "fulfilment_pct": ward["fulfilment_pct"],
                           "predicted_cases": ward["predicted_cases"]}))
    if ward["crews_needed"] > 0:
        out.append(("spraying", {"crews_assigned": ward["crews_assigned"], "crews_needed": ward["crews_needed"],
                                 "global_sequence": ward.get("spray_sequence"), "density": ward["population_density_sqkm"],
                                 "predicted_cases": ward["predicted_cases"]}))
    if b.get("bed_demand", 0) > 0 or ctx["transfers_out"] or ctx["transfers_in"]:
        out.append(("bed_routing", {"bed_demand": b.get("bed_demand", 0), "capacity": b.get("effective_capacity", 0),
                                    "beds_allocated": ward["allocated"]["hospital_beds"],
                                    "deficit": b.get("deficit", 0), "net_deficit": b.get("net_deficit", 0),
                                    "send": [{"to": t["to_ward"], "patients": t["patients"]} for t in ctx["transfers_out"]],
                                    "receive": [{"from": t["from_ward"], "patients": t["patients"]} for t in ctx["transfers_in"]]}))
    return out


def generate(user: dict, ward_ids: list[str] | None = None, send: bool = True) -> dict:
    """Auto mode: create/update this week's tasks for the user's wards. Idempotent."""
    p = current_plan()
    week = p["target_date"]
    rows = auth.visible_wards(user, p["allocation"]["wards"])
    if ward_ids:
        rows = [w for w in rows if w["ward_id"] in set(ward_ids)]
    rows.sort(key=lambda w: (RISK_IDX.get(w["risk"], 9), -w["priority_score"], w["ward_id"]))
    city_seq: dict = {}
    for w in sorted(p["allocation"]["wards"], key=lambda w: (RISK_IDX.get(w["risk"], 9), -w["priority_score"], w["ward_id"])):
        if w["crews_needed"] > 0:
            city_seq.setdefault(w["city"], []).append(w["ward_id"])
    created = updated = notices = 0
    ts = db.now()
    for w in rows:
        for ttype, payload in _task_payloads(p, w):
            key = f"{week}|{w['ward_id']}|{ttype}"
            seq = city_seq.get(w["city"], []).index(w["ward_id"]) + 1 if ttype == "spraying" else None
            prio = RISK_IDX.get(w["risk"], 9) * 1000 + w["priority_rank"]
            due = (datetime.now(timezone.utc) + timedelta(days=C.TASK_DUE_DAYS.get(ttype, 3))).strftime("%Y-%m-%dT%H:%M:%SZ")
            cur = db.q("SELECT id, status FROM tasks WHERE auto_key=?", (key,), one=True)
            if cur:
                db.x("UPDATE tasks SET payload=?, risk=?, priority=?, sequence=?, updated_at=? WHERE id=?",
                     (json.dumps(payload), w["risk"], prio, seq, ts, cur["id"]))
                tid = cur["id"]
                updated += 1
            else:
                tid = db.x("INSERT INTO tasks(auto_key, week, ward_id, city, type, payload, risk, priority, sequence, status,"
                           " source, created_by, assigned_team, created_at, updated_at, due_at)"
                           " VALUES (?,?,?,?,?,?,?,?,?,'assigned','auto',?,?,?,?,?)",
                           (key, week, w["ward_id"], w["city"], ttype, json.dumps(payload), w["risk"], prio, seq,
                            user["username"], TYPE_TEAM[ttype], ts, ts, due))
                created += 1
            if send:
                notices += notify_task(p, tid)
        ctx = D.ward_context(p, w["ward_id"])
        for t in ctx["transfers_out"]:
            db.x("INSERT INTO transfers(week, city, from_ward, to_ward, patients, created_at) VALUES (?,?,?,?,?,?) "
                 "ON CONFLICT(week, from_ward, to_ward) DO UPDATE SET patients=excluded.patients "
                 "WHERE transfers.status='pending'",
                 (week, t["city"], t["from_ward"], t["to_ward"], t["patients"], ts))
    db.audit(user, "generate_plan", {"week": week, "wards": len(rows), "created": created, "updated": updated,
                                     "stock_pct": p["allocation"]["stock_pct"], "crews": p["allocation"]["total_crews"]})
    return {"week": week, "wards": len(rows), "created": created, "updated": updated, "notices": notices,
            "source": p["source"]}


def notify_task(p: dict, task_id: int) -> int:
    t = db.q("SELECT * FROM tasks WHERE id=?", (task_id,), one=True)
    if not t or t["status"] in ("cancelled",):
        return 0
    team = DISPATCH_TEAM.get(t["type"], "saline")
    try:
        ctx = D.ward_context(p, t["ward_id"])
    except ValueError:
        return 0
    role = t["assigned_team"] or TYPE_TEAM.get(t["type"]) or "saline_team"
    recips = _recipients(role, t["city"])
    n = 0
    for lang in ("en", "bn"):
        rl = [r for r in recips if (r.get("lang") or "en") == lang]
        if not rl:
            continue
        s = D.sms(ctx, team, lang)
        wa = D.whatsapp(ctx, team, lang)
        n += notify.enqueue({"dispatch_id": s["dispatch_id"], "task_id": task_id, "ward_id": t["ward_id"], "team": team,
                             "channel": "sms", "lang": lang, "body": s["short"]}, rl)
        n += notify.enqueue({"dispatch_id": wa["dispatch_id"], "task_id": task_id, "ward_id": t["ward_id"], "team": team,
                             "channel": "whatsapp", "lang": lang, "body": wa["text"]}, rl)
    if t["type"] == "bed_routing":
        hs = _recipients("hospital", t["city"])
        if hs:
            s = D.sms(ctx, "bed", "en")
            n += notify.enqueue({"dispatch_id": s["dispatch_id"], "task_id": task_id, "ward_id": t["ward_id"],
                                 "team": "bed", "channel": "sms", "lang": "en", "body": s["long"]}, hs)
    return n


def _decorate(t: dict, hours: float) -> dict:
    t = dict(t)
    t["payload"] = json.loads(t["payload"] or "{}")
    now = datetime.now(timezone.utc)
    flags = []
    if t["status"] == "assigned" and t["created_at"] and now - _parse(t["created_at"]) > timedelta(hours=hours):
        flags.append("not_acknowledged")
    if t["due_at"] and t["status"] not in ("done", "cancelled") and now > _parse(t["due_at"]):
        flags.append("overdue")
    if t["status"] == "blocked":
        flags.append("blocked")
    t["escalations"] = flags
    t["escalated"] = bool(flags)
    return t


def scope_sql(user: dict) -> tuple[str, list]:
    role = user["role"]
    if role == "super_admin":
        return "1=1", []
    if role in ("commissioner", "secretary"):
        return "ward_id=?", [user["ward_id"]]
    if role in TEAM_TYPE:
        return "city=? AND assigned_team=?", [user["city"], role]
    if role == "hospital":
        return "city=? AND type='bed_routing'", [user["city"]]
    return "0=1", []


def list_tasks(user: dict, week: str | None = None, include_cancelled: bool = False) -> list[dict]:
    where, args = scope_sql(user)
    if week:
        where += " AND week=?"
        args.append(week)
    if not include_cancelled:
        where += " AND status!='cancelled'"
    hours = float(db.get_settings().get("escalation_hours", C.ACK_ESCALATION_HOURS))
    rows = db.q(f"SELECT * FROM tasks WHERE {where} ORDER BY week DESC, CASE type WHEN 'spraying' THEN COALESCE(sequence, 999) ELSE priority END, priority, id", args)
    return [_decorate(r, hours) for r in rows]


def get_task(user: dict, task_id: int) -> dict | None:
    where, args = scope_sql(user)
    return db.q(f"SELECT * FROM tasks WHERE id=? AND {where}", [task_id, *args], one=True)


def update_task(user: dict, task_id: int, changes: dict) -> dict:
    t = get_task(user, task_id)
    if not t:
        raise PermissionError("Task not found or outside your scope")
    role = user["role"]
    sets, args = [], []
    status = changes.get("status")
    if status:
        if status not in STATUSES:
            raise ValueError(f"status must be one of {', '.join(STATUSES)}")
        if role in TEAM_TYPE and status not in TEAM_ALLOWED:
            raise PermissionError("Teams can only acknowledge, start, finish or block tasks")
        if role == "hospital":
            raise PermissionError("Hospital users update capacity and transfers, not task status")
        sets.append("status=?"); args.append(status)
        if status == "acknowledged" and not t["ack_at"]:
            sets.append("ack_at=?"); args.append(db.now())
        if status == "done":
            sets.append("done_at=?"); args.append(db.now())
    if "note" in changes:
        sets.append("note=?"); args.append(str(changes["note"])[:1000])
    if "proof" in changes:
        sets.append("proof=?"); args.append(json.dumps(changes["proof"])[:2000])
    manager = role in ("super_admin", "commissioner", "secretary")
    if any(k in changes for k in ("payload", "assigned_team", "due_at")):
        if not manager:
            raise PermissionError("Only the commissioner, secretary or super admin can edit or reassign tasks")
        if "payload" in changes:
            if not changes.get("override_reason"):
                raise ValueError("override_reason is required when overriding the engine's suggestion")
            sets += ["payload=?", "override_by=?", "override_reason=?", "source=?"]
            args += [json.dumps(changes["payload"]), user["username"], str(changes["override_reason"])[:500], "override"]
        if "assigned_team" in changes:
            if changes["assigned_team"] not in TEAM_TYPE:
                raise ValueError("assigned_team must be saline_team, spraying_team or bed_team")
            sets.append("assigned_team=?"); args.append(changes["assigned_team"])
        if "due_at" in changes:
            sets.append("due_at=?"); args.append(str(changes["due_at"]))
    if not sets:
        raise ValueError("Nothing to update")
    sets.append("updated_at=?"); args.append(db.now())
    db.x(f"UPDATE tasks SET {', '.join(sets)} WHERE id=?", [*args, task_id])
    db.audit(user, "update_task", {"task_id": task_id, **{k: v for k, v in changes.items() if k != "proof"}})
    if "assigned_team" in changes:
        notify_task(current_plan(), task_id)
    hours = float(db.get_settings().get("escalation_hours", C.ACK_ESCALATION_HOURS))
    return _decorate(db.q("SELECT * FROM tasks WHERE id=?", (task_id,), one=True), hours)


def create_task(user: dict, data: dict, ward_city: dict) -> dict:
    if user["role"] not in ("super_admin", "commissioner", "secretary"):
        raise PermissionError("Only the commissioner, secretary or super admin can create tasks")
    ward = data.get("ward_id") or user.get("ward_id")
    if ward not in ward_city:
        raise ValueError("Unknown ward")
    if not auth.can_see_ward(user, ward, ward_city[ward]):
        raise PermissionError("You can only create tasks for your own ward")
    ttype = data.get("type", "other")
    if ttype not in TYPE_TEAM:
        raise ValueError("type must be saline, spraying, bed_routing or other")
    team = data.get("assigned_team") or TYPE_TEAM[ttype] or "saline_team"
    if team not in TEAM_TYPE:
        raise ValueError("assigned_team must be saline_team, spraying_team or bed_team")
    p = current_plan()
    risk = next((w["risk"] for w in p["allocation"]["wards"] if w["ward_id"] == ward), "Low")
    ts = db.now()
    due = (datetime.now(timezone.utc) + timedelta(days=C.TASK_DUE_DAYS.get(ttype, 3))).strftime("%Y-%m-%dT%H:%M:%SZ")
    payload = data.get("payload") or {}
    if data.get("description"):
        payload["description"] = str(data["description"])[:500]
    tid = db.x("INSERT INTO tasks(week, ward_id, city, type, payload, risk, priority, status, source, created_by,"
               " assigned_team, created_at, updated_at, due_at, note) VALUES (?,?,?,?,?,?,?,'assigned','manual',?,?,?,?,?,?)",
               (p["target_date"], ward, ward_city[ward], ttype, json.dumps(payload), risk, RISK_IDX.get(risk, 9) * 1000,
                user["username"], team, ts, ts, due, data.get("note")))
    db.audit(user, "create_task", {"task_id": tid, "ward_id": ward, "type": ttype})
    msg = {"dispatch_id": D.dispatch_id("manual", tid), "task_id": tid, "ward_id": ward, "team": DISPATCH_TEAM[ttype],
           "channel": "in_app", "lang": "en",
           "body": f"New task #{tid} for {ward} ({ttype}) from {user['username']}: {payload.get('description', '')}"}
    notify.enqueue(msg, _recipients(team, ward_city[ward]))
    return db.q("SELECT * FROM tasks WHERE id=?", (tid,), one=True)


def progress(user: dict, week: str | None = None) -> dict:
    tasks = list_tasks(user, week)
    def pct(ts):
        return round(100.0 * sum(t["status"] == "done" for t in ts) / len(ts), 1) if ts else 0.0
    by_type = {k: {"total": sum(t["type"] == k for t in tasks), "done": sum(t["type"] == k and t["status"] == "done" for t in tasks),
                   "pct": pct([t for t in tasks if t["type"] == k])} for k in ("saline", "spraying", "bed_routing", "other")}
    by_ward, by_city = {}, {}
    for t in tasks:
        for bucket, key in ((by_ward, t["ward_id"]), (by_city, t["city"])):
            b = bucket.setdefault(key, {"total": 0, "done": 0})
            b["total"] += 1
            b["done"] += t["status"] == "done"
    for bucket in (by_ward, by_city):
        for b in bucket.values():
            b["pct"] = round(100.0 * b["done"] / b["total"], 1) if b["total"] else 0.0
    lagging = sorted(({"ward_id": k, **v} for k, v in by_ward.items()), key=lambda r: (r["pct"], -r["total"], r["ward_id"]))[:10]
    return {"total": len(tasks), "done": sum(t["status"] == "done" for t in tasks), "pct": pct(tasks),
            "status_counts": {s: sum(t["status"] == s for t in tasks) for s in STATUSES},
            "by_type": by_type, "by_ward": by_ward, "by_city": by_city, "lagging": lagging,
            "escalated": [t for t in tasks if t["escalated"]][:50]}
