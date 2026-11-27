"""Deterministic dispatch notice engine (Requirement 4). No LLM, no network.

Every notice is built from string templates filled with numbers from the planner
(allocation + overflow + crew assignment + forecast), in English or Bangla:

  * SMS: a primary single-message version (EN <= 160 GSM-7 chars; BN is UCS-2 so the
    primary BN SMS is kept <= 70 chars per part and reported with its part count) plus a
    longer multi-part version.
  * WhatsApp: *bold* formatting, minimal emoji.
  * Commissioner brief: standalone A4 HTML with print CSS (works offline, print-to-PDF),
    plus a real PDF when the optional `reportlab` package is importable.

Each notice gets a stable dispatch_id = hash(origin, target week, ward, team, channel, lang),
so regenerating the same week's plan never creates duplicate notices.
"""
from __future__ import annotations

import hashlib
import html
from datetime import datetime, timezone
from urllib.parse import quote

from . import config as C

TEAMS = ("saline", "spraying", "bed")
TEAM_NAMES = {"en": {"saline": "Saline & kits team", "spraying": "Spraying team", "bed": "Hospital bed team",
                     "commissioner": "Ward commissioner"},
              "bn": {"saline": "স্যালাইন ও কিট দল", "spraying": "স্প্রে দল", "bed": "হাসপাতাল বেড দল",
                     "commissioner": "ওয়ার্ড কমিশনার"}}
RISK_BN = {"Critical": "সংকটপূর্ণ", "High": "উচ্চ", "Medium": "মাঝারি", "Low": "নিম্ন"}
LEVEL_BN = {"OK": "পর্যাপ্ত", "WARNING": "সতর্কতা", "CRITICAL": "সংকট"}
_BN_DIGITS = str.maketrans("0123456789", "০১২৩৪৫৬৭৮৯")


def bn_num(x) -> str:
    return str(x).translate(_BN_DIGITS)


def dispatch_id(*parts) -> str:
    return "DW-" + hashlib.sha1("|".join(str(p) for p in parts).encode("utf-8")).hexdigest()[:10].upper()


def ward_context(plan: dict, ward_id: str) -> dict:
    """Collect everything a notice needs about one ward from a planner result."""
    a = next((w for w in plan["allocation"]["wards"] if w["ward_id"] == ward_id), None)
    if a is None:
        raise ValueError(f"Unknown ward {ward_id}")
    o = next((w for w in plan["overflow"]["wards"] if w["ward_id"] == ward_id), {})
    out_t = [t for t in plan["overflow"]["transfers"] if t["from_ward"] == ward_id]
    in_t = [t for t in plan["overflow"]["transfers"] if t["to_ward"] == ward_id]
    trend = plan.get("trends", {}).get(ward_id, [])
    return {"origin": plan["origin"], "target_date": plan["target_date"], "horizon": plan["horizon"],
            "source": plan.get("source", "model"), "ward": a, "beds": o, "transfers_out": out_t,
            "transfers_in": in_t, "trend": trend}


def _alloc_line(w, s, lang):
    req, got = w["required"][s], w["allocated"][s]
    if lang == "bn":
        return f"{C.SUPPLY_LABELS_BN[s]}: {bn_num(got)}/{bn_num(req)}"
    return f"{C.SUPPLY_LABELS[s]}: {got}/{req}"


def sms(ctx: dict, team: str, lang: str = "en") -> dict:
    w, b = ctx["ward"], ctx["beds"]
    did = dispatch_id(ctx["origin"], ctx["target_date"], w["ward_id"], team, "sms", lang)
    cases = round(w["predicted_cases"], 1)
    alert = w["deficit_level"] != "OK"
    if lang == "bn":
        risk = RISK_BN.get(w["risk"], w["risk"])
        if team == "saline":
            short = (f"ডেঙ্গু {w['ward_id']} ঝুঁকি {risk}। স্যালাইন {bn_num(w['allocated']['saline_bags'])}/"
                     f"{bn_num(w['required']['saline_bags'])}, কিট {bn_num(w['allocated']['diagnostic_kits'])}")
        elif team == "spraying":
            short = (f"ডেঙ্গু {w['ward_id']} ঝুঁকি {risk}। স্প্রে দল {bn_num(w['crews_assigned'])}"
                     f"/{bn_num(w['crews_needed'])}, ক্রম {bn_num(w.get('spray_sequence') or '-')}")
        else:
            short = (f"ডেঙ্গু {w['ward_id']} বেড চাহিদা {bn_num(b.get('bed_demand', 0))}, "
                     f"ঘাটতি {bn_num(b.get('deficit', 0))}, স্থানান্তর {bn_num(b.get('sent', 0))}")
        long = [f"[{did}] ডেঙ্গু ওয়াচ নির্দেশনা - {TEAM_NAMES['bn'][team]}",
                f"ওয়ার্ড {w['ward_id']} ({w['city']}), সপ্তাহ {bn_num(ctx['target_date'])}",
                f"পূর্বাভাস: {bn_num(cases)} রোগী, ঝুঁকি {risk}",
                *[_alloc_line(w, s, "bn") for s in ("saline_bags", "diagnostic_kits", "hospital_beds")],
                f"স্প্রে দল: {bn_num(w['crews_assigned'])}/{bn_num(w['crews_needed'])}"]
        if alert:
            long.append(f"ঘাটতি সতর্কতা ({LEVEL_BN[w['deficit_level']]}): {bn_num(w['fulfilment_pct'])}% সরবরাহ")
        for t in ctx["transfers_out"]:
            long.append(f"রোগী স্থানান্তর: {bn_num(t['patients'])} জন -> {t['to_ward']}")
        limit = 70
    else:
        flag = " DEFICIT!" if (w["deficit"]["saline_bags"] > 0 or w["deficit"]["diagnostic_kits"] > 0) else ""
        if team == "saline":
            short = (f"DengueWatch {w['ward_id']} {w['risk']}: {cases} cases wk {ctx['target_date']}. "
                     f"Saline {w['allocated']['saline_bags']}/{w['required']['saline_bags']}, "
                     f"kits {w['allocated']['diagnostic_kits']}/{w['required']['diagnostic_kits']}.{flag} Ref {did}")
        elif team == "spraying":
            short = (f"DengueWatch {w['ward_id']} {w['risk']}: {cases} cases. Spray crews "
                     f"{w['crews_assigned']}/{w['crews_needed']}, order #{w.get('spray_sequence') or '-'}."
                     f"{' CREW SHORTFALL!' if w['crew_deficit'] > 0 else ''} Ref {did}")
        else:
            moves = "; ".join(f"{t['patients']}->{t['to_ward']}" for t in ctx["transfers_out"][:2])
            short = (f"DengueWatch {w['ward_id']} beds need {b.get('bed_demand', 0)}, cap {b.get('effective_capacity', 0)}, "
                     f"deficit {b.get('deficit', 0)}.{' Route ' + moves + '.' if moves else ''} Ref {did}")
        long = [f"[{did}] Dengue Watch dispatch - {TEAM_NAMES['en'][team]}",
                f"Ward {w['ward_id']} ({w['city']}), week of {ctx['target_date']}",
                f"Predicted cases: {cases} (risk {w['risk']}, +/-{w.get('uncertainty_cases', '')})",
                *[_alloc_line(w, s, "en") for s in ("saline_bags", "diagnostic_kits", "hospital_beds")],
                f"Spraying crews assigned: {w['crews_assigned']}/{w['crews_needed']}"
                + (f" (sequence #{w['spray_sequence']})" if w.get("spray_sequence") else "")]
        if alert:
            long.append(f"DEFICIT ALERT ({w['deficit_level']}): only {w['fulfilment_pct']:.0f}% can be supplied. {w['what_got_cut']}")
        for t in ctx["transfers_out"]:
            long.append(f"Transfer {t['patients']} patient(s) to {t['to_ward']}")
        for t in ctx["transfers_in"]:
            long.append(f"Receive {t['patients']} patient(s) from {t['from_ward']}")
        long.append("Reply ACK to confirm.")
        limit = 160
    if len(short) > limit and lang == "en":
        short = short[:limit - 1] + "…"
    body = "\n".join(long)
    per_part = 153 if lang == "en" else 67
    return {"dispatch_id": did, "channel": "sms", "team": team, "lang": lang, "short": short,
            "short_chars": len(short), "long": body, "long_parts": max(1, -(-len(body) // per_part)),
            "encoding": "GSM-7" if lang == "en" else "UCS-2"}


def whatsapp(ctx: dict, team: str, lang: str = "en") -> dict:
    w, b = ctx["ward"], ctx["beds"]
    did = dispatch_id(ctx["origin"], ctx["target_date"], w["ward_id"], team, "whatsapp", lang)
    bn = lang == "bn"
    n = bn_num if bn else str
    L = (lambda en, bnx: bnx) if bn else (lambda en, bnx: en)
    lines = [f"*{L('Dengue Watch dispatch', 'ডেঙ্গু ওয়াচ নির্দেশনা')}* - {TEAM_NAMES[lang][team]}",
             f"{L('Ward', 'ওয়ার্ড')}: *{w['ward_id']}* ({w['city']})",
             f"{L('Week', 'সপ্তাহ')}: {n(ctx['target_date'])}",
             f"{L('Predicted cases', 'পূর্বাভাসিত রোগী')}: *{n(round(w['predicted_cases'], 1))}* "
             f"({L('risk', 'ঝুঁকি')} *{RISK_BN.get(w['risk'], w['risk']) if bn else w['risk']}*)", ""]
    lines.append(f"*{L('Supplies (allocated / required)', 'সরবরাহ (বরাদ্দ / প্রয়োজন)')}*")
    for s in ("saline_bags", "diagnostic_kits", "hospital_beds"):
        mark = "" if w["deficit"][s] <= 0 else (" ⚠️" if not bn else " ⚠️")
        lines.append(f"• {_alloc_line(w, s, lang)}{mark}")
    lines.append(f"• {L('Spraying crews', 'স্প্রে দল')}: {n(w['crews_assigned'])}/{n(w['crews_needed'])}"
                 + (f" ({L('order', 'ক্রম')} #{n(w['spray_sequence'])})" if w.get("spray_sequence") else ""))
    if w["deficit_level"] != "OK":
        lines += ["", f"⚠️ *{L('DEFICIT ALERT', 'ঘাটতি সতর্কতা')} ({LEVEL_BN[w['deficit_level']] if bn else w['deficit_level']})*: "
                      f"{n(w['fulfilment_pct'])}% {L('fulfilled', 'সরবরাহ সম্ভব')}"]
    if team in ("bed",) or ctx["transfers_out"] or ctx["transfers_in"]:
        lines += ["", f"*{L('Hospital beds', 'হাসপাতাল বেড')}*: {L('demand', 'চাহিদা')} {n(b.get('bed_demand', 0))}, "
                      f"{L('capacity', 'ধারণক্ষমতা')} {n(b.get('effective_capacity', 0))}, {L('net deficit', 'নিট ঘাটতি')} {n(b.get('net_deficit', 0))}"]
        for t in ctx["transfers_out"]:
            lines.append(f"→ {L('Send', 'পাঠান')} {n(t['patients'])} {L('patient(s) to', 'জন রোগী')} {t['to_ward']}")
        for t in ctx["transfers_in"]:
            lines.append(f"← {L('Receive', 'গ্রহণ')} {n(t['patients'])} {L('patient(s) from', 'জন রোগী')} {t['from_ward']}")
    lines += ["", f"_{L('Ref', 'রেফ')} {did}. {L('Reply ACK to confirm.', 'নিশ্চিত করতে ACK লিখুন।')}_"]
    return {"dispatch_id": did, "channel": "whatsapp", "team": team, "lang": lang, "text": "\n".join(lines)}


def deep_links(phone: str, text: str) -> dict:
    """Click-to-send links: work without any API key (the officer taps 'send')."""
    digits = "".join(ch for ch in (phone or "") if ch.isdigit())
    return {"whatsapp": f"https://wa.me/{digits}?text={quote(text)}", "sms": f"sms:{phone}?body={quote(text)}"}


_CSS = """
@page{size:A4;margin:14mm}
body{font-family:'DM Sans','Noto Sans Bengali','Segoe UI',Arial,sans-serif;color:#132b3b;margin:0;font-size:12px}
.wrap{max-width:780px;margin:auto;padding:18px}
header{display:flex;justify-content:space-between;align-items:flex-start;border-bottom:3px solid #0c9b83;padding-bottom:10px}
h1{font-size:20px;margin:0}h2{font-size:14px;margin:18px 0 6px;color:#071b2c}
.tag{display:inline-block;padding:3px 8px;border-radius:12px;font-weight:700;font-size:11px}
.Critical{background:#fde2e2;color:#a12626}.High{background:#fdebd6;color:#9a5a10}.Medium{background:#fff6d6;color:#7a6510}.Low{background:#dff6f0;color:#087c68}
.OK{background:#dff6f0;color:#087c68}.WARNING{background:#fdebd6;color:#9a5a10}.CRITICAL{background:#fde2e2;color:#a12626}
table{width:100%;border-collapse:collapse;margin-top:4px}th,td{border:1px solid #d9e3e7;padding:6px 8px;text-align:left}
th{background:#f4f7f8;font-size:11px;text-transform:uppercase;letter-spacing:.04em}
.alert{border:2px solid #d85d5d;background:#fff5f5;padding:8px 10px;border-radius:6px;margin-top:10px}
.muted{color:#718392;font-size:10px}.sig{margin-top:28px;display:flex;justify-content:space-between}
.sig div{border-top:1px solid #132b3b;width:40%;padding-top:4px;font-size:11px}
@media print{.noprint{display:none}}
"""


def brief_html(ctx: dict, lang: str = "en") -> str:
    w, b = ctx["ward"], ctx["beds"]
    bn = lang == "bn"
    e = html.escape
    n = bn_num if bn else str
    T = (lambda en, bnx: bnx) if bn else (lambda en, bnx: en)
    did = dispatch_id(ctx["origin"], ctx["target_date"], w["ward_id"], "commissioner", "brief", lang)
    risk_txt = RISK_BN.get(w["risk"], w["risk"]) if bn else w["risk"]
    trend_rows = "".join(f"<tr><td>{n(t['target_date'])}</td><td>+{n(t['horizon'])} {T('wk', 'সপ্তাহ')}</td>"
                         f"<td>{n(t['predicted_cases'])}</td><td><span class='tag {t['risk']}'>"
                         f"{e(RISK_BN.get(t['risk'], t['risk']) if bn else t['risk'])}</span></td></tr>" for t in ctx["trend"])
    labels = C.SUPPLY_LABELS_BN if bn else C.SUPPLY_LABELS
    sup_rows = "".join(f"<tr><td>{labels[s]}</td><td>{n(w['required'][s])}</td><td>{n(w['allocated'][s])}</td>"
                       f"<td>{n(w['deficit'][s])}</td><td>{n(round(w['fulfilment'][s] * 100))}%</td></tr>"
                       for s in ("saline_bags", "diagnostic_kits", "hospital_beds"))
    moves = "".join(f"<tr><td>{T('Send', 'পাঠান')}</td><td>{e(t['to_ward'])}</td><td>{n(t['patients'])}</td></tr>" for t in ctx["transfers_out"]) + \
        "".join(f"<tr><td>{T('Receive', 'গ্রহণ')}</td><td>{e(t['from_ward'])}</td><td>{n(t['patients'])}</td></tr>" for t in ctx["transfers_in"])
    alert = ""
    if w["deficit_level"] != "OK":
        alert = (f"<div class='alert'><b>{T('SUPPLY DEFICIT ALERT', 'সরবরাহ ঘাটতি সতর্কতা')} "
                 f"({e(LEVEL_BN[w['deficit_level']] if bn else w['deficit_level'])})</b>: "
                 f"{T('only', 'মাত্র')} {n(w['fulfilment_pct'])}% {T('of demand can be supplied at the current regional stock level.', 'চাহিদা বর্তমান আঞ্চলিক মজুদে পূরণ সম্ভব।')} "
                 f"{e(w['what_got_cut'])}</div>")
    if b.get("net_deficit", 0) > 0:
        alert += (f"<div class='alert'><b>{T('BED SURGE', 'বেড সংকট')}</b>: {n(b['net_deficit'])} "
                  f"{T('patients cannot be placed inside the city pool - escalate to regional command.', 'রোগী শহরের ভেতরে স্থান পাচ্ছে না - আঞ্চলিক কমান্ডে জানান।')}</div>")
    src = T("ML forecast (Gradient Boosting, Poisson)", "এমএল পূর্বাভাস") if ctx["source"] == "model" else \
        T("Deterministic seasonal FALLBACK forecast", "নির্ধারিত মৌসুমি বিকল্প পূর্বাভাস")
    return f"""<!doctype html><html lang="{lang}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{T('Commissioner brief', 'কমিশনার ব্রিফ')} {e(w['ward_id'])} {e(ctx['target_date'])}</title><style>{_CSS}</style></head><body><div class="wrap">
<header><div><div class="muted">DENGUE WATCH · {T('WARD COMMISSIONER BRIEF', 'ওয়ার্ড কমিশনার ব্রিফ')}</div>
<h1>{e(w['ward_id'])} · {e(w['city'])}</h1>
<div>{T('Planning week', 'পরিকল্পনা সপ্তাহ')}: <b>{n(ctx['target_date'])}</b> ({T('data up to', 'তথ্য পর্যন্ত')} {n(ctx['origin'])})</div></div>
<div style="text-align:right"><span class="tag {w['risk']}">{T('RISK', 'ঝুঁকি')}: {e(risk_txt)}</span><br>
<span class="tag {w['deficit_level']}" style="margin-top:6px">{T('SUPPLY', 'সরবরাহ')}: {e(LEVEL_BN[w['deficit_level']] if bn else w['deficit_level'])}</span>
<div class="muted" style="margin-top:6px">Ref {did}</div></div></header>
<h2>1. {T('Predicted cases', 'পূর্বাভাসিত রোগী')}</h2>
<p><b>{n(round(w['predicted_cases'], 1))}</b> {T('expected cases in the planning week', 'জন রোগী প্রত্যাশিত')} (±{n(w.get('uncertainty_cases', ''))} {T('typical model error', 'সাধারণ মডেল ত্রুটি')}). {T('Priority rank', 'অগ্রাধিকার ক্রম')} {n(w['priority_rank'])}.</p>
<table><tr><th>{T('Week', 'সপ্তাহ')}</th><th>{T('Horizon', 'সময়')}</th><th>{T('Cases', 'রোগী')}</th><th>{T('Risk', 'ঝুঁকি')}</th></tr>{trend_rows}</table>
<h2>2. {T('Supplies: allocated vs required', 'সরবরাহ: বরাদ্দ বনাম প্রয়োজন')}</h2>
<table><tr><th>{T('Item', 'সামগ্রী')}</th><th>{T('Required', 'প্রয়োজন')}</th><th>{T('Allocated', 'বরাদ্দ')}</th><th>{T('Deficit', 'ঘাটতি')}</th><th>{T('Fulfilled', 'পূরণ')}</th></tr>{sup_rows}</table>
{alert}
<h2>3. {T('Vector control: spraying teams', 'মশা নিয়ন্ত্রণ: স্প্রে দল')}</h2>
<p>{T('Assigned', 'বরাদ্দ')} <b>{n(w['crews_assigned'])}</b> {T('of', '/')} {n(w['crews_needed'])} {T('crews needed', 'দল প্রয়োজন')}
{(T('; spraying sequence', '; স্প্রে ক্রম') + ' #' + n(w['spray_sequence'])) if w.get('spray_sequence') else ''}.</p>
<h2>4. {T('Hospital beds and overflow', 'হাসপাতাল বেড ও স্থানান্তর')}</h2>
<p>{T('Bed demand', 'বেড চাহিদা')} {n(b.get('bed_demand', 0))} · {T('assumed capacity', 'অনুমিত ধারণক্ষমতা')} {n(b.get('effective_capacity', 0))} ·
{T('deficit', 'ঘাটতি')} {n(b.get('deficit', 0))} · {T('remaining headroom', 'অবশিষ্ট খালি বেড')} {n(b.get('remaining_headroom', 0))}</p>
{('<table><tr><th>' + T('Action', 'কাজ') + '</th><th>' + T('Ward', 'ওয়ার্ড') + '</th><th>' + T('Patients', 'রোগী') + '</th></tr>' + moves + '</table>') if moves else '<p class="muted">' + T('No transfers needed.', 'কোনো স্থানান্তর প্রয়োজন নেই।') + '</p>'}
<div class="sig"><div>{T('Ward commissioner', 'ওয়ার্ড কমিশনার')}</div><div>{T('Health officer', 'স্বাস্থ্য কর্মকর্তা')}</div></div>
<p class="muted">{T('Source', 'উৎস')}: {src}. {T('Generated offline by Dengue Watch from local models and templates. Bed capacity is an assumed, editable baseline. Research prototype, not an official alert.', 'স্থানীয় মডেল ও টেমপ্লেট থেকে অফলাইনে তৈরি। বেড ধারণক্ষমতা অনুমিত। গবেষণা প্রোটোটাইপ, সরকারি সতর্কবার্তা নয়।')}
{T('Generated', 'তৈরি')} {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}.</p>
<p class="noprint"><button onclick="window.print()">{T('Print / Save as PDF', 'প্রিন্ট / PDF সংরক্ষণ')}</button></p>
</div></body></html>"""


def brief_pdf(ctx: dict) -> bytes | None:
    """Real PDF via reportlab if installed; otherwise None (use the HTML print path)."""
    try:
        from io import BytesIO
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfgen import canvas
    except Exception:
        return None
    w, b = ctx["ward"], ctx["beds"]
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    y = 800
    def line(txt, size=10, dy=16):
        nonlocal y
        c.setFont("Helvetica-Bold" if size > 11 else "Helvetica", size)
        c.drawString(50, y, txt)
        y -= dy
    line("Dengue Watch - Ward Commissioner Brief", 16, 24)
    line(f"{w['ward_id']} ({w['city']})  week of {ctx['target_date']}  ref "
         f"{dispatch_id(ctx['origin'], ctx['target_date'], w['ward_id'], 'commissioner', 'brief', 'en')}")
    line(f"Predicted cases: {w['predicted_cases']:.1f}   Risk: {w['risk']}   Priority rank: {w['priority_rank']}")
    line("Supplies (allocated / required / deficit):", 12, 18)
    for s in ("saline_bags", "diagnostic_kits", "hospital_beds"):
        line(f"   {C.SUPPLY_LABELS[s]}: {w['allocated'][s]} / {w['required'][s]} / {w['deficit'][s]}")
    if w["deficit_level"] != "OK":
        line(f"DEFICIT ALERT ({w['deficit_level']}): {w['fulfilment_pct']:.0f}% fulfilled. {w['what_got_cut']}", 10)
    line(f"Spraying crews: {w['crews_assigned']} of {w['crews_needed']}"
         + (f"  (sequence #{w['spray_sequence']})" if w.get("spray_sequence") else ""))
    line(f"Beds: demand {b.get('bed_demand', 0)}, capacity {b.get('effective_capacity', 0)}, net deficit {b.get('net_deficit', 0)}")
    for t in ctx["transfers_out"]:
        line(f"   Send {t['patients']} patient(s) to {t['to_ward']}")
    for t in ctx["transfers_in"]:
        line(f"   Receive {t['patients']} patient(s) from {t['from_ward']}")
    line("Bed capacity is an assumed, editable baseline. Research prototype.", 8)
    c.showPage()
    c.save()
    return buf.getvalue()


def notices_for_ward(plan: dict, ward_id: str, langs=("en", "bn")) -> list[dict]:
    """All channel x team x language notices for one ward."""
    ctx = ward_context(plan, ward_id)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    out = []
    for lang in langs:
        for team in TEAMS:
            s = sms(ctx, team, lang)
            out.append({**s, "ward_id": ward_id, "timestamp": ts, "body": s["short"], "status": "queued"})
            wa = whatsapp(ctx, team, lang)
            out.append({**wa, "ward_id": ward_id, "timestamp": ts, "body": wa["text"], "status": "queued"})
    return out
