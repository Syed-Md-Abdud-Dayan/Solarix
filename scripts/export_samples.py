"""Generate the committed /exports samples from REAL model output (fully offline).

Run:  python scripts/export_samples.py

Scenario: data up to 2019-08-05 (2019 outbreak peak), planning week = +1 week,
regional stock slider at 60%, 40 spraying crews, default equity guard.
Writes SMS / WhatsApp texts (EN + BN), printable HTML briefs (EN + BN), PDF briefs
(EN, if reportlab is installed), allocation / overflow / simulator CSVs.
"""
from __future__ import annotations

import csv
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
os.environ.setdefault("OPS_DB", str(Path(tempfile.mkdtemp()) / "export.db"))   # never touch the runtime DB

import app  # noqa: E402  (loads the 13 local models; also wires the ops bridge)
from dengue_watch.ops import dispatch as D, planner, simulator  # noqa: E402

ORIGIN, STOCK, CREWS = "2019-08-05", 60, 40
OUT = ROOT / "exports"


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def main() -> None:
    p = planner.plan(ORIGIN, stock_pct=STOCK, total_crews=CREWS)
    wards = p["allocation"]["wards"]
    by = {w["ward_id"]: w for w in wards}
    t = p["overflow"]["transfers"]
    picks = []
    def add(w):
        if w and w not in picks:
            picks.append(w)
    add(wards[0]["ward_id"])                                              # top priority ward
    add(next((x["from_ward"] for x in t), None))                          # sends overflow patients
    add(next((x["to_ward"] for x in t), None))                            # receives overflow patients
    add(next((w["ward_id"] for w in wards if w["deficit_level"] == "CRITICAL"), None))   # critical deficit
    add(next((w["ward_id"] for w in wards if w["deficit_level"] == "WARNING"), None))
    add(next((w["ward_id"] for w in wards if w["crew_deficit"] > 0 and w["risk"] in ("High", "Critical")), None))
    add(next((w["ward_id"] for w in reversed(wards) if w["city"] in ("Gazipur", "Narayanganj")), None))

    for old in OUT.glob("**/*"):
        if old.is_file() and "runtime" not in old.parts:
            old.unlink()
    index = []
    for ward in picks:
        ctx = D.ward_context(p, ward)
        for lang in ("en", "bn"):
            for team in D.TEAMS:
                s = D.sms(ctx, team, lang)
                write(OUT / "sms" / f"{ward}_{team}_{lang}.txt",
                      f"# SMS primary ({s['short_chars']} chars, {s['encoding']})\n{s['short']}\n\n"
                      f"# SMS long version ({s['long_parts']} part(s))\n{s['long']}\n")
                w = D.whatsapp(ctx, team, lang)
                write(OUT / "whatsapp" / f"{ward}_{team}_{lang}.txt", w["text"] + "\n")
            write(OUT / "briefs" / f"{ward}_commissioner_brief_{lang}.html", D.brief_html(ctx, lang))
        pdf = D.brief_pdf(ctx)
        if pdf:
            (OUT / "briefs" / f"{ward}_commissioner_brief_en.pdf").write_bytes(pdf)
        a = by[ward]
        index.append(f"| {ward} | {a['city']} | {a['risk']} | {a['predicted_cases']:.1f} | {a['fulfilment_pct']:.0f}% {a['deficit_level']} | "
                     f"{a['crews_assigned']}/{a['crews_needed']} | {ctx['beds'].get('sent', 0)} out / {ctx['beds'].get('received', 0)} in |")

    with open(OUT / "allocation_report.csv", "w", newline="", encoding="utf-8-sig") as f:
        wr = csv.writer(f)
        wr.writerow(["priority_rank", "ward_id", "city", "risk", "predicted_cases", "density", "saline_required", "saline_allocated",
                     "kits_required", "kits_allocated", "beds_required", "beds_allocated", "fulfilment_pct", "deficit_level",
                     "crews_needed", "crews_assigned", "spray_sequence", "what_got_cut"])
        for w in wards:
            wr.writerow([w["priority_rank"], w["ward_id"], w["city"], w["risk"], w["predicted_cases"], w["population_density_sqkm"],
                         w["required"]["saline_bags"], w["allocated"]["saline_bags"], w["required"]["diagnostic_kits"],
                         w["allocated"]["diagnostic_kits"], w["required"]["hospital_beds"], w["allocated"]["hospital_beds"],
                         w["fulfilment_pct"], w["deficit_level"], w["crews_needed"], w["crews_assigned"], w["spray_sequence"], w["what_got_cut"]])
    with open(OUT / "overflow_report.csv", "w", newline="", encoding="utf-8-sig") as f:
        wr = csv.writer(f)
        wr.writerow(["ward_id", "city", "bed_demand", "assumed_capacity", "deficit", "headroom", "sent", "received", "net_deficit",
                     "remaining_headroom", "status"])
        for w in p["overflow"]["wards"]:
            wr.writerow([w["ward_id"], w["city"], w["bed_demand"], w["effective_capacity"], w["deficit"], w["headroom"], w["sent"],
                         w["received"], w["net_deficit"], w["remaining_headroom"], w["status"]])
        wr.writerow([])
        wr.writerow(["TRANSFERS: from_ward", "to_ward", "city", "patients"])
        for x in t:
            wr.writerow([x["from_ward"], x["to_ward"], x["city"], x["patients"]])
    sim = simulator.recommend(10, ORIGIN)
    with open(OUT / "simulator_roi.csv", "w", newline="", encoding="utf-8-sig") as f:
        wr = csv.writer(f)
        wr.writerow(["roi_rank", "ward_id", "cases_prevented_1_crew", "cases_prevented_4_crews", "recommended_crews"])
        for r in sim["roi_ranking"]:
            wr.writerow([r["rank"], r["ward_id"], r["cases_prevented_1_crew"], r["cases_prevented_max"],
                         sim["recommended_deployment"].get(r["ward_id"], 0)])

    s = p["allocation"]["totals"]
    readme = f"""# Dispatch export samples

Generated by `python scripts/export_samples.py` from the real local models, fully offline
(no LLM, no network). Re-running reproduces the same numbers; dispatch IDs are stable hashes.

**Scenario:** data up to {p['origin']} (2019 outbreak peak), planning week **{p['target_date']}**,
regional stock slider **{STOCK}%**, **{CREWS}** spraying crews, equity guard on, source: `{p['source']}`.

| Supply | Required | Available at {STOCK}% | Allocated | Deficit |
|---|---|---|---|---|
""" + "\n".join(f"| {k} | {v['required']} | {v['available']} | {v['allocated']} | {v['deficit']} |" for k, v in s.items()) + f"""

Hospital overflow: {p['overflow']['summary']['patients_routed']} patients routed inside city pools,
{p['overflow']['summary']['unresolved_deficit']} unresolved (city surge). Bed capacity is an assumed, editable baseline.

## Sample wards

| Ward | City | Risk | Predicted cases | Supply | Crews | Bed overflow |
|---|---|---|---|---|---|---|
""" + "\n".join(index) + """

## Files

- `sms/<ward>_<team>_<lang>.txt` - primary single SMS (EN <= 160 GSM-7 chars; BN is UCS-2) + long multi-part version.
- `whatsapp/<ward>_<team>_<lang>.txt` - WhatsApp formatted notice (*bold*, minimal emoji).
- `briefs/<ward>_commissioner_brief_<lang>.html` - printable A4 commissioner brief (open, then Print > Save as PDF).
- `briefs/<ward>_commissioner_brief_en.pdf` - PDF brief (generated when the optional `reportlab` package is installed).
- `allocation_report.csv`, `overflow_report.csv`, `simulator_roi.csv` - full 60-ward tables.

Teams: `saline` = saline & diagnostic-kit distribution, `spraying` = larvicide / fogging crews, `bed` = hospital bed team.
"""
    write(OUT / "README.md", readme)
    print(f"Wrote samples for {len(picks)} wards to {OUT}")


if __name__ == "__main__":
    main()
