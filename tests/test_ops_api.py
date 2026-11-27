"""End-to-end API tests through the real HTTP handler: auth, scoping, plan, tasks, hospital, dispatch."""
import http.client
import json
import threading
from http.server import ThreadingHTTPServer

import pytest


@pytest.fixture(scope="module")
def server():
    import app
    srv = ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield srv.server_address[1]
    srv.shutdown()


class Client:
    def __init__(self, port):
        self.port, self.cookie, self.csrf = port, None, None

    def req(self, method, path, body=None, csrf=True):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=120)
        headers = {"Content-Type": "application/json"}
        if self.cookie:
            headers["Cookie"] = self.cookie
        if csrf and self.csrf:
            headers["X-CSRF-Token"] = self.csrf
        c.request(method, path, body=json.dumps(body) if body is not None else None, headers=headers)
        r = c.getresponse()
        raw = r.read()
        sc = r.getheader("Set-Cookie")
        if sc:
            self.cookie = sc.split(";", 1)[0]
        ctype = r.getheader("Content-Type") or ""
        return r.status, (json.loads(raw) if ctype.startswith("application/json") else raw.decode("utf-8"))

    def login(self, user, pw="demo1234"):
        st, b = self.req("POST", "/api/ops/login", {"username": user, "password": pw})
        assert st == 200, b
        self.csrf = b["csrf"]
        return b["user"]


def test_existing_endpoints_still_work(server):
    c = Client(server)
    st, b = c.req("GET", "/api/health")
    assert st == 200 and b["models_loaded"] == 13
    st, b = c.req("GET", "/api/risk?city=Dhaka%20North&horizon=3")
    assert st == 200 and len(b["wards"]) == 20
    st, _ = c.req("GET", "/")
    assert st == 200


def test_public_engine_endpoints(server):
    c = Client(server)
    st, h = c.req("GET", "/api/ops/health")
    assert st == 200 and h["offline_capable"] and h["external_calls"] == []
    for pct in (100, 30):
        st, a = c.req("GET", f"/api/alloc?stock_pct={pct}&crews=25")
        assert st == 200 and len(a["wards"]) == 60
        assert all(t["allocated"] <= t["available"] for t in a["totals"].values())
    assert c.req("GET", "/api/alloc?stock_pct=10")[0] == 400
    st, o = c.req("GET", "/api/overflow")
    assert st == 200 and "cities" in o
    st, d = c.req("GET", "/api/dispatch/DNCC_Ward_01?lang=bn")
    assert st == 200 and d["sms"] and d["whatsapp"]
    st, html = c.req("GET", "/api/dispatch/DNCC_Ward_01?format=html")
    assert st == 200 and "Predicted cases" in html and "spraying" in html.lower()


def test_login_rejects_bad_password(server):
    c = Client(server)
    st, _ = c.req("POST", "/api/ops/login", {"username": "admin", "password": "wrong"})
    assert st == 401


def test_csrf_required(server):
    c = Client(server)
    c.login("comm_dncc01")
    st, _ = c.req("POST", "/api/ops/plan/generate", {}, csrf=False)
    assert st == 403


def test_commissioner_scope_and_idempotent_plan(server):
    c = Client(server)
    u = c.login("comm_dncc01")
    assert u["ward_id"] == "DNCC_Ward_01"
    st, p = c.req("GET", "/api/ops/plan")
    assert st == 200 and {w["ward_id"] for w in p["allocation"]["wards"]} == {"DNCC_Ward_01"}
    st, g1 = c.req("POST", "/api/ops/plan/generate", {})
    assert st == 200 and g1["created"] + g1["updated"] >= 1
    st, g2 = c.req("POST", "/api/ops/plan/generate", {})      # re-run: updates, never duplicates
    assert st == 200 and g2["created"] == 0 and g2["updated"] == g1["created"] + g1["updated"]
    st, t = c.req("GET", "/api/ops/tasks")
    assert all(x["ward_id"] == "DNCC_Ward_01" for x in t["tasks"])
    # cannot create a task for another ward
    st, _ = c.req("POST", "/api/ops/tasks", {"ward_id": "DSCC_Ward_02", "type": "other", "description": "x"})
    assert st == 403
    # another ward's commissioner cannot touch this ward's task
    other = Client(server)
    other.login("comm_dscc02")
    tid = t["tasks"][0]["id"]
    assert other.req("POST", f"/api/ops/tasks/{tid}", {"status": "done"})[0] == 403


def test_full_flow_team_progress_hospital(server):
    admin = Client(server)
    admin.login("admin", "admin1234")
    st, _ = admin.req("POST", "/api/ops/settings", {"stock_pct": 50, "total_crews": 30})
    assert st == 200
    st, g = admin.req("POST", "/api/ops/plan/generate", {})
    assert st == 200 and g["wards"] == 60

    team = Client(server)
    team.login("spray_dncc")
    st, tl = team.req("GET", "/api/ops/tasks")
    spray = [t for t in tl["tasks"] if t["type"] == "spraying"]
    assert spray and all(t["city"] == "Dhaka North" for t in spray)
    seq = [t["sequence"] for t in spray]
    assert seq == sorted(seq)
    order = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}
    risks = [order[t["risk"]] for t in spray]
    assert risks == sorted(risks), "spraying order must be High before Medium before Low"
    st, inbox = team.req("GET", "/api/ops/inbox")
    assert st == 200 and inbox["unread"] > 0
    # team cannot cancel
    assert team.req("POST", f"/api/ops/tasks/{spray[0]['id']}", {"status": "cancelled"})[0] == 403
    for s in ("acknowledged", "in_progress", "done"):
        st, _ = team.req("POST", f"/api/ops/tasks/{spray[0]['id']}", {"status": s, "proof": {"houses_sprayed": 120}})
        assert st == 200
    comm = Client(server)
    comm.login(f"comm_dncc{spray[0]['ward_id'].rsplit('_', 1)[-1]}")
    st, pr = comm.req("GET", "/api/ops/progress")
    assert st == 200 and pr["done"] >= 1 and pr["pct"] > 0

    hosp = Client(server)
    hosp.login("hosp_dncc")
    st, hv = hosp.req("GET", "/api/ops/hospital")
    assert st == 200 and all(w["city"] == "Dhaka North" for w in hv["overflow"]["wards"])
    st, _ = hosp.req("POST", "/api/ops/capacity", {"ward_id": "DNCC_Ward_01", "capacity": 9, "occupied": 2})
    assert st == 200
    assert hosp.req("POST", "/api/ops/capacity", {"ward_id": "DSCC_Ward_01", "capacity": 9})[0] == 403
    if hv["transfers"]:
        tid = hv["transfers"][0]["id"]
        assert hosp.req("POST", f"/api/ops/transfers/{tid}", {"decision": "decline"})[0] == 400
        assert hosp.req("POST", f"/api/ops/transfers/{tid}", {"decision": "accept"})[0] == 200


def test_offline_replay_is_idempotent(server):
    team = Client(server)
    team.login("saline_dncc")
    st, tl = team.req("GET", "/api/ops/tasks")
    tid = tl["tasks"][0]["id"]
    acts = [{"key": "k-1", "type": "task_update", "id": tid, "changes": {"status": "acknowledged"}}]
    st, r1 = team.req("POST", "/api/ops/batch", {"actions": acts})
    st, r2 = team.req("POST", "/api/ops/batch", {"actions": acts})
    assert r1["results"][0]["ok"] and r2["results"][0].get("duplicate")


def test_exports_and_simulator(server):
    admin = Client(server)
    admin.login("admin", "admin1234")
    st, csv = admin.req("GET", "/api/ops/export/allocation.csv")
    assert st == 200 and "saline_bags_allocated" in csv
    st, sim = admin.req("GET", "/api/simulate?crews=6")
    assert st == 200 and sum(sim["recommended_deployment"].values()) <= 6
    st, s2 = admin.req("POST", "/api/simulate", {"deployment": {"DNCC_Ward_01": 2}, "crew_cap": 5})
    assert st == 200 and s2["crews_used"] == 2
