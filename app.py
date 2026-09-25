"""
Fiber Capacity Management - demo app
====================================
A working demo of the data standard (v3): every record names "who feeds me",
the app counts utilization, colours every item, runs coverage-checked requests
through GIS approval, and keeps a live request & approval log.

Run locally:   streamlit run app.py
Data:          the CSV files in the data/ folder (one per sheet in the standard)
Note:          this is a demo - changes live only in your browser session.
               Press "Reset demo" in the sidebar to start again.
"""

import math
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pydeck as pdk
import streamlit as st

DATA = Path(__file__).parent / "data"
LAGOS = timezone(timedelta(hours=1))

# ---- rules from the standard (change here to try other values) ----
SEARCH_RADIUS_M = 200      # how far from the address the app looks for FATs
COVERAGE_RADIUS_M = 250    # demo coverage checker: covered if a FAT/FDT is this close
HOLD_DAYS = 7              # approved port is held this long
GPS_LIMIT_M = 100          # installer must be this close to the FAT
FAT_CUSTOMER_PORTS = 8

STATUS_HEX = {"Green": "#1F7A45", "Yellow": "#E6B325", "Orange": "#D9651E", "Red": "#B7322A"}
STATUS_TEXT = {"Green": "#F6F4EF", "Yellow": "#1B2A3D", "Orange": "#1B2A3D", "Red": "#F6F4EF"}
STATUS_RGB = {"Green": [31, 122, 69], "Yellow": [230, 179, 37], "Orange": [217, 101, 30], "Red": [183, 50, 42]}
SEVERITY = {"Green": 0, "Yellow": 1, "Orange": 2, "Red": 3}
MEANING = {"Green": "room available", "Yellow": "nearly full - plan expansion",
           "Orange": "full - new load blocked", "Red": "over capacity - check data"}

PERSONA = {"sales": "K. Ade (Sales)", "gis": "A. Precious (GIS)", "installer": "T. Bello (Installer)"}

st.set_page_config(page_title="Fiber Capacity Management", layout="wide", initial_sidebar_state="expanded")

# =============================================================================
# LOOK AND FEEL
# =============================================================================
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;600;700&family=IBM+Plex+Sans:wght@400;500;600&display=swap');
html, body, [class*="css"], .stMarkdown, .stText, p, li, label { font-family: 'IBM Plex Sans', sans-serif; }
h1, h2, h3, h4 { font-family: 'Space Grotesk', sans-serif !important; letter-spacing: -0.01em; }
[data-testid="stSidebar"] { background: #0F1B2D; }
[data-testid="stSidebar"] * { color: #EAF0F6 !important; }
[data-testid="stSidebar"] [data-baseweb="select"] * { color: #1B2A3D !important; }
[data-testid="stSidebar"] button { background: #172A42 !important; border: 1px solid #3CC8BC !important; }
[data-testid="stSidebar"] button:hover { background: #0E7C74 !important; }
.eyebrow { font-size: 0.8rem; letter-spacing: .18em; text-transform: uppercase; color: #0E7C74; font-weight: 600; margin-bottom: -0.4rem; }
.chip { display:inline-block; padding: 2px 10px; border-radius: 999px; font-size: 0.8rem; font-weight: 600; margin-right: 6px; }
.card { background: #FDFCF9; border: 1px solid #E1E5E1; border-radius: 14px; padding: 14px 16px; margin-bottom: 10px; }
.logbox { background:#0F1B2D; border-radius: 16px; padding: 14px 14px 6px 14px; }
.logtitle { color:#F6F4EF; font-family:'Space Grotesk',sans-serif; font-weight:600; letter-spacing:.08em; font-size:.85rem; }
.logentry { background:#172A42; border-radius:10px; padding:8px 10px; margin:8px 0; border-left:5px solid #7A8797; }
.logentry .t { color:#8FA2B6; font-size:.72rem; }
.logentry .a { color:#F6F4EF; font-weight:600; font-size:.82rem; }
.logentry .d { color:#BFD0E0; font-size:.78rem; }
.step { border-left: 4px solid #0E7C74; padding: 6px 12px; margin: 4px 0; background:#FDFCF9; border-radius: 0 10px 10px 0; }
.step b { font-family:'Space Grotesk',sans-serif; }
</style>
""", unsafe_allow_html=True)


def chip(status, text=None):
    return (f"<span class='chip' style='background:{STATUS_HEX[status]};color:{STATUS_TEXT[status]}'>"
            f"{text or status}</span>")


def now():
    return datetime.now(LAGOS)


# =============================================================================
# DATA: load the sheets once per browser session
# =============================================================================
SHEETS = ["pops", "olts", "odfs", "cabinets", "fdts", "fats", "onus", "cables", "cable_cores",
          "street_list", "estate_list", "demo_addresses"]


def load_data():
    db = {name: pd.read_csv(DATA / f"{name}.csv", dtype=str, keep_default_na=False) for name in SHEETS}
    num = {"olts": ["lat", "lon", "no_of_pon_ports", "capacity_per_pon"], "odfs": ["no_of_trays", "ports_per_tray"],
           "cabinets": ["lat", "lon", "no_of_trays", "ports_per_tray"], "fdts": ["lat", "lon", "customers_per_output"],
           "fats": ["lat", "lon", "fdt_output_port"], "onus": ["lat", "lon", "board", "pon_port", "fat_port"],
           "cables": ["no_of_cores", "length_m"], "cable_cores": ["core_no"], "pops": ["lat", "lon"],
           "demo_addresses": ["lat", "lon"]}
    for sheet, cols in num.items():
        for c in cols:
            db[sheet][c] = pd.to_numeric(db[sheet][c])
    return db


def init_state(force=False):
    if force or "db" not in st.session_state:
        st.session_state.db = load_data()
        st.session_state.requests = []
        st.session_state.log = []
        st.session_state.req_no = 420
        st.session_state.last_result = None
        st.session_state.snapshot = {}
        stamp = now().replace(hour=8, minute=0)
        util = utilization_table()
        for _, r in util[util.status != "Green"].sort_values("sev", ascending=False).iterrows():
            add_log(ALERT_NAME[r.status], "", r.item_id, "System",
                    f"{r.item_type} at {r.used:.0f}/{r.capacity:.0f} ({r.pct:.0f}%) - {MEANING[r.status]}",
                    level=r.status, at=stamp)
        st.session_state.snapshot = dict(zip(util.item_id, util.status))


ALERT_NAME = {"Yellow": "EARLY WARNING", "Orange": "CAPACITY ALERT", "Red": "CRITICAL ALERT"}


def add_log(action, request_id, item, by, note, level="info", at=None):
    st.session_state.log.insert(0, {"time": (at or now()).strftime("%d %b %H:%M"), "action": action,
                                    "request": request_id, "item": item, "by": by, "note": note, "level": level})


# =============================================================================
# THE TREE: "who feeds me?"
# =============================================================================
def D():
    return st.session_state.db


def fat_row(fat_id):
    f = D()["fats"]
    return f[f.fat_id == fat_id].iloc[0]


def path_up_from_fat(fat_id):
    """FAT -> upstream FATs -> FDT (output) -> cabinets -> ODF -> OLT -> POP."""
    steps, seen = [], set()
    cur = fat_id
    while cur and cur not in seen:
        seen.add(cur)
        r = fat_row(cur)
        if r.upstream_fat_id:
            steps.append((cur, f"FAT {r.ratio} · fed by {r.upstream_fat_id}, port 9"))
            cur = r.upstream_fat_id
        else:
            steps.append((cur, f"FAT {r.ratio} · fed by {r.fdt_id}, output {int(r.fdt_output_port)}"))
            steps += path_up_from_fdt(r.fdt_id)
            break
    return steps


def path_up_from_fdt(fdt_id):
    db = D()
    fdt = db["fdts"][db["fdts"].fdt_id == fdt_id].iloc[0]
    steps = [(fdt_id, f"FDT {fdt.ratio} · fed by {fdt.fed_from_id}")]
    ftype, fid = fdt.fed_from_type, fdt.fed_from_id
    for _ in range(10):
        if ftype == "Cabinet":
            cab = db["cabinets"][db["cabinets"].cabinet_id == fid].iloc[0]
            steps.append((fid, f"Cabinet · fed by {cab.fed_from_id}"))
            ftype, fid = cab.fed_from_type, cab.fed_from_id
        elif ftype == "ODF":
            odf = db["odfs"][db["odfs"].odf_id == fid].iloc[0]
            steps.append((fid, f"ODF · patched from {odf.olt_id}"))
            olt = db["olts"][db["olts"].olt_id == odf.olt_id].iloc[0]
            steps.append((olt.olt_id, f"OLT · in {olt.pop_id}"))
            break
    return steps


def olt_of_fat(fat_id):
    for item, _ in path_up_from_fat(fat_id):
        if item.startswith("OLT"):
            return item
    return None


def fats_below(item_id):
    db = D()
    fats, fdts, cabs = db["fats"], db["fdts"], db["cabinets"]
    if item_id.startswith("FAT"):
        out, todo = [], [item_id]
        while todo:
            f = todo.pop()
            out.append(f)
            todo += fats[fats.upstream_fat_id == f].fat_id.tolist()
        return out
    if item_id.startswith("FDT"):
        return fats[fats.fdt_id == item_id].fat_id.tolist()
    if item_id.startswith("CAB") or item_id.startswith("ODF"):
        feeders, found_fdts, todo = set(), [], [item_id]
        while todo:
            x = todo.pop()
            feeders.add(x)
            todo += cabs[(cabs.fed_from_id == x)].cabinet_id.tolist()
        found_fdts = fdts[fdts.fed_from_id.isin(feeders)].fdt_id.tolist()
        return fats[fats.fdt_id.isin(found_fdts)].fat_id.tolist()
    if item_id.startswith("OLT"):
        odfs = db["odfs"][db["odfs"].olt_id == item_id].odf_id.tolist()
        return sorted({f for o in odfs for f in fats_below(o)})
    if item_id.startswith("CBL"):
        cab = db["cables"][db["cables"].cable_id == item_id].iloc[0]
        return fats_below(cab.to_id)
    return []


def active_onus():
    o = D()["onus"]
    return o[o.status == "Active"]


# =============================================================================
# UTILIZATION (counted, never typed)
# =============================================================================
def colour_of(pct):
    if pct > 100.0001:
        return "Red"
    if pct >= 99.9999:
        return "Orange"
    if pct >= 80:
        return "Yellow"
    return "Green"


def held_ports():
    return [(r["assigned_fat"], r["assigned_port"], r["request_id"])
            for r in st.session_state.requests if r["status"] == "Approved"]


def fat_usage():
    db = D()
    cust = active_onus().groupby("fat_id").size()
    held = pd.Series([h[0] for h in held_ports()], dtype=str).value_counts()
    f = db["fats"].copy()
    f["customers"] = f.fat_id.map(cust).fillna(0).astype(int)
    f["held"] = f.fat_id.map(held).fillna(0).astype(int)
    f["used"] = f.customers + f.held
    f["capacity"] = FAT_CUSTOMER_PORTS
    return f


def chain_usage():
    f = fat_usage()
    lim = D()["fdts"].set_index("fdt_id").customers_per_output
    c = f.groupby(["fdt_id", "fdt_output_port"]).agg(used=("used", "sum"), fats=("fat_id", list)).reset_index()
    c["capacity"] = c.fdt_id.map(lim)
    c["chain_id"] = c.fdt_id + " out " + c.fdt_output_port.astype(int).astype(str)
    return c


def utilization_table():
    db = D()
    rows = []
    f = fat_usage()
    for _, r in f.iterrows():
        rows.append(("FAT", r.fat_id, r.street, r.estate, r.used, r.capacity))
    ch = chain_usage()
    for _, r in ch.iterrows():
        fd = db["fdts"][db["fdts"].fdt_id == r.fdt_id].iloc[0]
        rows.append(("FAT chain", r.chain_id, fd.street, "", r.used, r.capacity))
    for _, fd in db["fdts"].iterrows():
        outs = int(fd.ratio.split(":")[1])
        used = ch[ch.fdt_id == fd.fdt_id].used.sum()
        rows.append(("FDT", fd.fdt_id, fd.street, "", used, outs * fd.customers_per_output))
    cores = db["cable_cores"].merge(db["cables"], on="cable_id")
    used_cores = cores[cores.status == "Used"]
    for _, cab in db["cabinets"].iterrows():
        inc = used_cores[(used_cores.to_id == cab.cabinet_id) & (used_cores.end_port != "")]
        outg = used_cores[(used_cores.from_id == cab.cabinet_id) & (used_cores.start_port != "")]
        rows.append(("Cabinet", cab.cabinet_id, cab.street, "", len(inc) + len(outg), cab.no_of_trays * cab.ports_per_tray))
    for _, o in db["odfs"].iterrows():
        u = used_cores[(used_cores.from_id == o.odf_id) & (used_cores.start_port != "")]
        rows.append(("ODF", o.odf_id, "", "", len(u), o.no_of_trays * o.ports_per_tray))
    for _, c in db["cables"].iterrows():
        u = used_cores[used_cores.cable_id == c.cable_id]
        rows.append(("Cable", c.cable_id, "", "", len(u), c.no_of_cores))
    for _, o in db["olts"].iterrows():
        n = len(active_onus()[active_onus().olt_id == o.olt_id]) + len(held_ports())
        rows.append(("OLT", o.olt_id, "", "", n, o.no_of_pon_ports * o.capacity_per_pon))
    t = pd.DataFrame(rows, columns=["item_type", "item_id", "street", "estate", "used", "capacity"])
    t["pct"] = (100 * t.used / t.capacity).round(1)
    t["status"] = t.pct.apply(colour_of)
    t["sev"] = t.status.map(SEVERITY)
    return t


def available_on_fat(fat_id):
    f = fat_usage().set_index("fat_id").loc[fat_id]
    ch = chain_usage()
    c = ch[(ch.fdt_id == f.fdt_id) & (ch.fdt_output_port == f.fdt_output_port)].iloc[0]
    util = utilization_table().set_index("item_id")
    olt = olt_of_fat(fat_id)
    fat_free = int(f.capacity - f.used)
    chain_free = int(c.capacity - c.used)
    olt_free = int(util.loc[olt, "capacity"] - util.loc[olt, "used"]) if olt else 0
    avail = max(0, min(fat_free, chain_free, olt_free))
    if avail > 0:
        reason = "OK"
    elif fat_free <= 0:
        reason = "FAT full"
    elif chain_free <= 0:
        reason = f"Chain {c.chain_id} full ({int(c.used)}/{int(c.capacity)})"
    else:
        reason = "OLT full"
    return avail, fat_free, chain_free, reason


def free_ports(fat_id):
    used = set(active_onus()[active_onus().fat_id == fat_id].fat_port.astype(int))
    used |= {int(h[1]) for h in held_ports() if h[0] == fat_id}
    return [p for p in range(1, FAT_CUSTOMER_PORTS + 1) if p not in used]


def check_alerts(request_id=""):
    """Compare every item's colour with the last snapshot; log an alert when it gets worse."""
    util = utilization_table()
    snap = st.session_state.snapshot
    for _, r in util.iterrows():
        before = snap.get(r.item_id, "Green")
        if SEVERITY[r.status] > SEVERITY[before]:
            add_log(ALERT_NAME[r.status], request_id, r.item_id, "System",
                    f"{r.item_type} now {r.used:.0f}/{r.capacity:.0f} ({r.pct:.0f}%) - {MEANING[r.status]}",
                    level=r.status)
        elif SEVERITY[r.status] < SEVERITY[before] and r.status == "Green":
            add_log("ALERT CLEARED", request_id, r.item_id, "System", f"back to {r.pct:.0f}%", level="Green")
    st.session_state.snapshot = dict(zip(util.item_id, util.status))


# =============================================================================
# REQUESTS: coverage -> suggestions -> GIS approval -> installation
# =============================================================================
def distance_m(lat1, lon1, lat2, lon2):
    r = 6371000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = (math.sin(math.radians(lat2 - lat1) / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2)
    return 2 * r * math.asin(math.sqrt(a))


def coverage_check(lat, lon):
    """Demo stand-in for the company's coverage checker."""
    pts = pd.concat([D()["fats"][["lat", "lon"]], D()["fdts"][["lat", "lon"]]])
    nearest = min(distance_m(lat, lon, a, b) for a, b in zip(pts.lat, pts.lon))
    return nearest <= COVERAGE_RADIUS_M


def suggest_fats(lat, lon):
    rows = []
    for _, f in D()["fats"].iterrows():
        d = distance_m(lat, lon, f.lat, f.lon)
        if d <= SEARCH_RADIUS_M:
            avail, fat_free, chain_free, reason = available_on_fat(f.fat_id)
            rows.append({"FAT": f.fat_id, "Street": f.street, "Distance (m)": round(d),
                         "Free on FAT": fat_free, "Free on chain": chain_free, "Available": avail, "Reason": reason})
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    return df.sort_values(["Available", "Distance (m)"], ascending=[False, True]).reset_index(drop=True)


def find_request(rid):
    return next(r for r in st.session_state.requests if r["request_id"] == rid)


def submit_request(kind, customer, street, estate, lat, lon, relocate_cust=""):
    st.session_state.req_no += 1
    rid = f"REQ-2026-{st.session_state.req_no:04d}"
    by = PERSONA["sales"]
    req = {"request_id": rid, "type": kind, "customer": customer, "relocate_cust": relocate_cust,
           "street": street, "estate": estate, "lat": lat, "lon": lon, "submitted_by": by,
           "submitted_at": now().strftime("%d %b %H:%M"), "status": "Submitted", "coverage": "",
           "suggestions": [], "assigned_fat": "", "assigned_port": "", "decided_by": "", "reason": "",
           "hold_until": ""}
    st.session_state.requests.insert(0, req)
    add_log("SUBMITTED", rid, "", by, f"{kind} · {customer} · {street}", level="info")
    covered = coverage_check(lat, lon)
    req["coverage"] = "Covered" if covered else "Not covered"
    add_log("COVERAGE CHECKED", rid, "", "Coverage checker", req["coverage"], level="info")
    if not covered:
        req["status"] = "No coverage"
        add_log("NO COVERAGE", rid, "", "Coverage checker", f"{street} not covered · added to demand list", level="Red")
        return rid
    sug = suggest_fats(lat, lon)
    ok = sug[sug.Available > 0] if not sug.empty else sug
    req["suggestions"] = ok.FAT.tolist()[:3] if not ok.empty else []
    req["status"] = "With GIS"
    if req["suggestions"]:
        add_log("SUGGESTED", rid, ", ".join(req["suggestions"]), "App",
                f"{len(ok)} FAT(s) within {SEARCH_RADIUS_M} m with room", level="info")
    else:
        req["reason"] = "Covered, no capacity"
        add_log("COVERED, NO CAPACITY", rid, "", "App", f"No FAT within {SEARCH_RADIUS_M} m has room", level="Orange")
    return rid


def approve(rid, fat_id, port):
    req = find_request(rid)
    by = PERSONA["gis"]
    if by == req["submitted_by"]:
        raise ValueError("Nobody can approve their own request.")
    avail, _, _, reason = available_on_fat(fat_id)
    if avail <= 0:
        raise ValueError(f"Blocked: {fat_id} has no real room ({reason}).")
    if port not in free_ports(fat_id):
        raise ValueError(f"Port {port} on {fat_id} is not free.")
    before = fat_usage().set_index("fat_id").loc[fat_id]
    req.update(status="Approved", assigned_fat=fat_id, assigned_port=int(port), decided_by=by,
               hold_until=(now() + timedelta(days=HOLD_DAYS)).strftime("%d %b"))
    add_log("APPROVED", rid, f"{fat_id} P{port}", by,
            f"Port held until {req['hold_until']} · FAT {int(before.used)}/8 → {int(before.used) + 1}/8", level="Green")
    check_alerts(rid)


def reject(rid, reason):
    req = find_request(rid)
    req.update(status="Rejected", decided_by=PERSONA["gis"], reason=reason)
    add_log("REJECTED", rid, "", PERSONA["gis"], reason, level="Orange")


def install(rid, scanned_fat, port, serial, gps_m, photo):
    req = find_request(rid)
    by = PERSONA["installer"]
    errors = []
    if scanned_fat != req["assigned_fat"]:
        errors.append(f"Scanned {scanned_fat}, but GIS approved {req['assigned_fat']}.")
    if int(port) != int(req["assigned_port"]):
        errors.append(f"Port {port} chosen, but GIS reserved port {req['assigned_port']}.")
    if gps_m > GPS_LIMIT_M:
        errors.append(f"You are {gps_m} m from the FAT (limit {GPS_LIMIT_M} m).")
    if not photo:
        errors.append("A photo of the FAT port is required.")
    onus = D()["onus"]
    if serial.strip() == "" or (onus.onu_serial == serial.strip()).any():
        errors.append("ONU serial is empty or already registered to another customer.")
    if errors:
        raise ValueError(" ".join(errors))
    f = fat_row(scanned_fat)
    olt = olt_of_fat(scanned_fat)
    pon = {"FDT-0021": 1, "FDT-0022": 2, "FDT-0023": 3}.get(f.fdt_id, 1)
    if req["type"] == "Relocation":
        idx = onus.index[onus.cust_id == req["relocate_cust"]][0]
        old = f"{onus.at[idx, 'fat_id']} P{int(onus.at[idx, 'fat_port'])}"
        for col, val in {"fat_id": scanned_fat, "fat_port": int(port), "street": req["street"], "estate": req["estate"],
                         "lat": req["lat"], "lon": req["lon"], "onu_serial": serial.strip(), "pon_port": pon}.items():
            onus.at[idx, col] = val
        req["status"] = "Installed"
        add_log("INSTALLED", rid, f"{scanned_fat} P{port}", by, f"Relocation of {req['relocate_cust']} · photo ✓ · GPS {gps_m} m", level="Green")
        add_log("OLD PORT FREED", rid, old, "System", "Previous port released on relocation", level="info")
    else:
        new_id = f"C{int(onus.cust_id.str[1:].astype(int).max()) + 1}"
        new = {"cust_id": new_id, "onu_serial": serial.strip(), "customer_name": req["customer"], "street": req["street"],
               "estate": req["estate"], "lat": req["lat"], "lon": req["lon"], "olt_id": olt, "board": 1, "pon_port": pon,
               "fat_id": scanned_fat, "fat_port": int(port), "activation_date": now().strftime("%Y-%m-%d"), "status": "Active"}
        D()["onus"] = pd.concat([onus, pd.DataFrame([new])], ignore_index=True)
        req["status"] = "Installed"
        add_log("INSTALLED", rid, f"{scanned_fat} P{port}", by, f"New customer {new_id} · photo ✓ · GPS {gps_m} m", level="Green")
    check_alerts(rid)


# =============================================================================
# SHARED UI PIECES
# =============================================================================
LOG_COLOURS = {"Green": "#1F7A45", "Yellow": "#E6B325", "Orange": "#D9651E", "Red": "#B7322A", "info": "#3CC8BC"}


def render_log():
    reqs = st.session_state.requests
    waiting = sum(r["status"] == "With GIS" for r in reqs)
    held = sum(r["status"] == "Approved" for r in reqs)
    entries = "".join(
        f"<div class='logentry' style='border-left-color:{LOG_COLOURS.get(e['level'], '#7A8797')}'>"
        f"<div class='t'>{e['time']} · {e['by']}</div>"
        f"<div class='a'>{e['action']}{' · ' + e['request'] if e['request'] else ''}{' · ' + e['item'] if e['item'] else ''}</div>"
        f"<div class='d'>{e['note']}</div></div>"
        for e in st.session_state.log[:40])
    st.markdown(
        f"<div class='logbox'><div class='logtitle'>REQUEST &amp; APPROVAL LOG</div>"
        f"<div style='margin:8px 0 2px 0'>{chip('Yellow', f'Waiting for GIS · {waiting}')}"
        f"<span class='chip' style='background:#3CC8BC;color:#0F1B2D'>Ports held · {held}</span></div>"
        f"<div style='max-height:760px; overflow-y:auto; padding-right:4px'>{entries}</div></div>",
        unsafe_allow_html=True)
    if st.session_state.log:
        st.download_button("Export log (CSV)", pd.DataFrame(st.session_state.log).to_csv(index=False),
                           "request_approval_log.csv", width="stretch")


def styled(df, col="Status"):
    def paint(v):
        return f"background-color:{STATUS_HEX[v]}; color:{STATUS_TEXT[v]}; font-weight:600" if v in STATUS_HEX else ""
    return df.style.map(paint, subset=[col])


def util_display(t):
    out = t.rename(columns={"item_type": "Type", "item_id": "Item", "street": "Street", "estate": "Estate",
                            "used": "Used", "capacity": "Capacity", "pct": "Utilization %", "status": "Status"})
    out = out[["Type", "Item", "Street", "Estate", "Used", "Capacity", "Utilization %", "Status"]]
    out["Used"] = out["Used"].astype(int)
    out["Capacity"] = out["Capacity"].astype(int)
    return out


def header(eyebrow, title, persona=None):
    st.markdown(f"<div class='eyebrow'>{eyebrow}</div>", unsafe_allow_html=True)
    st.markdown(f"## {title}")
    if persona:
        st.caption(f"You are acting as **{persona}**")


# =============================================================================
# PAGES
# =============================================================================
def page_dashboard():
    header("Live network", "Capacity dashboard")
    util = utilization_table()
    red = util[util.status == "Red"]
    orange = util[util.status == "Orange"]
    yellow = util[util.status == "Yellow"]
    if len(red):
        st.error(f"**Critical:** {', '.join(red.item_id)} over capacity. Likely a data error or an illegal connection.")
    if len(orange):
        st.warning(f"**Full:** {', '.join(orange.item_id)}. New load is blocked on these.")
    if len(yellow):
        st.info(f"**Nearly full (80%+):** {', '.join(yellow.item_id)}. Plan expansion.")

    onus = active_onus()
    olt = util[util.item_type == "OLT"].iloc[0]
    fats = util[util.item_type == "FAT"]
    free_total = sum(available_on_fat(f)[0] for f in fats.item_id)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Active customers", len(onus))
    c2.metric("OLT utilization", f"{olt.pct:.0f}%", f"{int(olt.used)} of {int(olt.capacity)}", delta_color="off")
    c3.metric("Ports really available", free_total, "after the tightest point rule", delta_color="off")
    c4.metric("Items needing attention", int((util.status != "Green").sum()), "yellow, orange or red", delta_color="inverse")

    st.markdown("#### Network map")
    render_map(util)
    st.markdown(" ".join(chip(s, f"{s}: {MEANING[s]}") for s in STATUS_HEX)
                + "<span class='chip' style='background:#0F1B2D;color:#F6F4EF'>Cabinet / FDT</span>",
                unsafe_allow_html=True)

    st.markdown("#### Utilization of every item")
    f1, f2, f3, f4 = st.columns(4)
    types = f1.multiselect("Type", sorted(util.item_type.unique()), default=["FAT", "FAT chain", "FDT", "Cabinet", "ODF", "OLT"])
    streets = f2.multiselect("Street", sorted(s for s in util.street.unique() if s))
    estates = f3.multiselect("Estate", sorted(e for e in util.estate.unique() if e))
    colours = f4.multiselect("Colour", list(STATUS_HEX))
    t = util.copy()
    if types:
        t = t[t.item_type.isin(types)]
    if streets:
        t = t[t.street.isin(streets)]
    if estates:
        t = t[t.estate.isin(estates)]
    if colours:
        t = t[t.status.isin(colours)]
    t = t.sort_values(["sev", "pct"], ascending=False)
    st.dataframe(styled(util_display(t)), width="stretch", hide_index=True,
                 column_config={"Utilization %": st.column_config.ProgressColumn(min_value=0, max_value=120, format="%.0f%%")})

    st.markdown("#### By street and by estate (FATs)")
    fu = fat_usage()
    a, b = st.columns(2)
    for col, key, label in [(a, "street", "Street"), (b, "estate", "Estate")]:
        g = fu.groupby(key).agg(FATs=("fat_id", "count"), Customers=("customers", "sum"), Used=("used", "sum"),
                                Capacity=("capacity", "sum")).reset_index().rename(columns={key: label})
        g["Utilization %"] = (100 * g.Used / g.Capacity).round(0)
        g["Status"] = g["Utilization %"].apply(colour_of)
        col.dataframe(styled(g.drop(columns=["Used"])), width="stretch", hide_index=True)


def render_map(util):
    db = D()
    status = dict(zip(util.item_id, util.status))
    fats = fat_usage()
    fats["status"] = fats.fat_id.map(status)
    fats["color"] = fats.status.map(STATUS_RGB)
    fats["label"] = fats.apply(lambda r: f"{r.fat_id} ({r.ratio}) · {r.street}\n{r.used}/8 · {r.status}", axis=1)
    boxes = pd.concat([
        db["fdts"].assign(item=db["fdts"].fdt_id, kind="FDT")[["item", "kind", "lat", "lon", "street"]],
        db["cabinets"].assign(item=db["cabinets"].cabinet_id, kind="Cabinet")[["item", "kind", "lat", "lon", "street"]]])
    boxes["label"] = boxes.apply(lambda r: f"{r['item']} ({r['kind']}) · {r['street']}\n{status.get(r['item'], '')}", axis=1)
    lines = []
    pos = {r.fat_id: (r.lon, r.lat) for r in fats.itertuples()}
    pos.update({r.item: (r.lon, r.lat) for r in boxes.itertuples()})
    for r in fats.itertuples():
        up = r.upstream_fat_id or r.fdt_id
        if up in pos:
            lines.append({"from": pos[up], "to": pos[r.fat_id]})
    for r in db["fdts"].itertuples():
        if r.fed_from_id in pos:
            lines.append({"from": pos[r.fed_from_id], "to": pos[r.fdt_id]})
    for r in db["cabinets"].itertuples():
        if r.fed_from_id in pos:
            lines.append({"from": pos[r.fed_from_id], "to": pos[r.cabinet_id]})
    layers = [
        pdk.Layer("LineLayer", pd.DataFrame(lines), get_source_position="from", get_target_position="to",
                  get_color=[14, 124, 116, 160], get_width=3),
        pdk.Layer("ScatterplotLayer", boxes, get_position=["lon", "lat"], get_fill_color=[15, 27, 45],
                  get_radius=14, pickable=True, stroked=True, get_line_color=[255, 255, 255], line_width_min_pixels=2),
        pdk.Layer("ScatterplotLayer", fats, get_position=["lon", "lat"], get_fill_color="color",
                  get_radius=11, pickable=True, stroked=True, get_line_color=[255, 255, 255], line_width_min_pixels=2),
    ]
    view = pdk.ViewState(latitude=6.6040, longitude=3.3570, zoom=15.2, pitch=0)
    st.pydeck_chart(pdk.Deck(layers=layers, initial_view_state=view, tooltip={"text": "{label}"}, map_style="light"),
                    width="stretch", height=440)


def page_search():
    header("Ask the network", "Search and trace")
    t1, t2, t3 = st.tabs(["Trace a customer", "Who is affected?", "Find capacity"])
    onus = active_onus()
    with t1:
        options = [f"{r.cust_id} · {r.customer_name} · {r.street}" for r in onus.itertuples()]
        pick = st.selectbox("Customer", options, index=min(24, len(options) - 1))
        cid = pick.split(" · ")[0]
        o = onus[onus.cust_id == cid].iloc[0]
        steps = [(cid, f"ONU {o.onu_serial} · on {o.fat_id}, port {int(o.fat_port)}")] + path_up_from_fat(o.fat_id)
        st.markdown("Reading **from the customer up to the source**, one \"who feeds me?\" link at a time:")
        for item, text in steps:
            st.markdown(f"<div class='step'><b>{item}</b> &nbsp; {text}</div>", unsafe_allow_html=True)
        traced = olt_of_fat(o.fat_id)
        if traced == o.olt_id:
            st.success(f"SmartOLT check: SmartOLT says {o.olt_id} board {int(o.board)} PON {int(o.pon_port)}, and the tree agrees.")
        else:
            st.error(f"SmartOLT mismatch: SmartOLT says {o.olt_id}, the tree traces to {traced}.")
    with t2:
        db = D()
        items = (db["fats"].fat_id.tolist() + db["fdts"].fdt_id.tolist() + db["cabinets"].cabinet_id.tolist()
                 + db["cables"].cable_id.tolist() + db["odfs"].odf_id.tolist())
        item = st.selectbox("If this item fails…", items, index=1)
        fl = fats_below(item)
        aff = onus[onus.fat_id.isin(fl)]
        a, b, c = st.columns(3)
        a.metric("Customers affected", len(aff))
        b.metric("FATs affected", len(fl))
        c.metric("Streets affected", aff.street.nunique())
        if len(aff):
            g = aff.groupby(["fat_id", "street", "estate"]).size().reset_index(name="Customers")
            st.dataframe(g.rename(columns={"fat_id": "FAT", "street": "Street", "estate": "Estate"}),
                         width="stretch", hide_index=True)
    with t3:
        db = D()
        c1, c2, c3 = st.columns(3)
        est = c1.selectbox("Estate", ["Any"] + db["estate_list"].estate_name.tolist())
        strt = c2.selectbox("Street", ["Any"] + db["street_list"].street_name.tolist())
        need = c3.number_input("At least this many free ports", 1, 8, 1)
        rows = []
        for f in db["fats"].itertuples():
            if (est == "Any" or f.estate == est) and (strt == "Any" or f.street == strt):
                avail, fat_free, chain_free, reason = available_on_fat(f.fat_id)
                rows.append({"FAT": f.fat_id, "Street": f.street, "Estate": f.estate, "Free on FAT": fat_free,
                             "Free on chain": chain_free, "Available": avail, "Reason": reason,
                             "Status": "Green" if avail >= need else "Orange"})
        df = pd.DataFrame(rows)
        if df.empty:
            st.info("No FATs match these filters.")
        else:
            df = df.sort_values("Available", ascending=False)
            st.caption("Available = the smallest free space on the path (FAT, its chain, the OLT).")
            st.dataframe(styled(df), width="stretch", hide_index=True)


def page_request():
    header("Sales", "New request", PERSONA["sales"])
    db = D()
    st.markdown("Every new customer or relocation starts here. The app runs the **coverage checker** first, "
                "then suggests FATs within reach that have real room.")
    kind = st.radio("Request type", ["New customer", "Relocation"], horizontal=True)
    with st.form("req"):
        reloc = ""
        if kind == "Relocation":
            onus = active_onus()
            pick = st.selectbox("Customer who is moving", [f"{r.cust_id} · {r.customer_name} · {r.fat_id}" for r in onus.itertuples()])
            reloc = pick.split(" · ")[0]
            name = pick.split(" · ")[1]
        else:
            name = st.text_input("Customer name", "Mr. Bello")
        addr = st.selectbox("Address (new address for a relocation)", db["demo_addresses"].label.tolist() + ["Custom location"])
        c1, c2, c3, c4 = st.columns(4)
        street = c1.selectbox("Street (custom)", db["street_list"].street_name.tolist())
        estate = c2.selectbox("Estate (custom)", db["estate_list"].estate_name.tolist())
        lat = c3.number_input("Latitude (custom)", value=6.6069, format="%.5f")
        lon = c4.number_input("Longitude (custom)", value=3.3552, format="%.5f")
        go = st.form_submit_button("Submit request", type="primary")
    if go:
        if addr != "Custom location":
            a = db["demo_addresses"][db["demo_addresses"].label == addr].iloc[0]
            street, estate, lat, lon = a.street, a.estate, float(a.lat), float(a.lon)
        rid = submit_request(kind, name, street, estate, lat, lon, reloc)
        st.session_state.last_result = rid
    rid = st.session_state.get("last_result")
    if rid:
        req = find_request(rid)
        st.markdown(f"#### {rid} · {req['type']} · {req['customer']}")
        if req["status"] == "No coverage":
            st.error("Coverage checker: **not covered**. The request is closed and the address is added to the demand list for planning.")
        else:
            st.success("Coverage checker: **covered**.")
            sug = suggest_fats(req["lat"], req["lon"])
            if sug.empty:
                st.warning(f"No FATs within {SEARCH_RADIUS_M} m.")
            else:
                sug["Status"] = sug.Available.apply(lambda a: "Green" if a > 0 else "Orange")
                st.dataframe(styled(sug), width="stretch", hide_index=True)
            if req["suggestions"]:
                st.info(f"Sent to GIS with suggestions: {', '.join(req['suggestions'])}. Open **GIS approvals** to decide.")
            else:
                st.warning("Covered, but no FAT within reach has room. GIS can reject or raise a New FAT request.")


def page_approvals():
    header("GIS", "Approvals inbox", PERSONA["gis"])
    waiting = [r for r in st.session_state.requests if r["status"] == "With GIS"]
    if not waiting:
        st.info("Nothing waiting. Submit a request on the **New request** page first.")
    for req in waiting:
        with st.container(border=True):
            st.markdown(f"**{req['request_id']}** · {req['type']} · {req['customer']} · {req['street']} "
                        f"· submitted {req['submitted_at']} by {req['submitted_by']}")
            sug = suggest_fats(req["lat"], req["lon"])
            ok = sug[sug.Available > 0] if not sug.empty else sug
            if not sug.empty:
                sug["Status"] = sug.Available.apply(lambda a: "Green" if a > 0 else "Orange")
                st.dataframe(styled(sug), width="stretch", hide_index=True)
            c1, c2, c3 = st.columns([2, 1, 1])
            if ok.empty:
                c1.warning("No FAT within reach has room: covered, no capacity.")
            else:
                fat = c1.selectbox("Assign FAT", ok.FAT.tolist(), key=f"f{req['request_id']}")
                port = c2.selectbox("Port", free_ports(fat), key=f"p{req['request_id']}")
                if c3.button("Approve", key=f"a{req['request_id']}", type="primary", width="stretch"):
                    try:
                        approve(req["request_id"], fat, port)
                        st.rerun()
                    except ValueError as e:
                        st.error(str(e))
            r1, r2 = st.columns([2, 1])
            reason = r1.selectbox("Or reject with a reason", ["No capacity", "Needs new FAT", "Duplicate request", "Other"],
                                  key=f"r{req['request_id']}")
            if r2.button("Reject", key=f"x{req['request_id']}", width="stretch"):
                reject(req["request_id"], reason)
                st.rerun()
    done = [r for r in st.session_state.requests if r["status"] != "With GIS"]
    if done:
        st.markdown("#### All requests")
        st.dataframe(pd.DataFrame([{k: str(r[k]) for k in ["request_id", "type", "customer", "street", "coverage", "status",
                                                           "assigned_fat", "assigned_port", "hold_until", "reason"]} for r in done]),
                     width="stretch", hide_index=True)


def page_installer():
    header("Field", "Installer jobs", PERSONA["installer"])
    jobs = [r for r in st.session_state.requests if r["status"] == "Approved"]
    if not jobs:
        st.info("No approved jobs yet. Approve a request in **GIS approvals** first.")
    for req in jobs:
        with st.container(border=True):
            st.markdown(f"**{req['request_id']}** · {req['type']} · {req['customer']} · go to **{req['assigned_fat']} "
                        f"port {req['assigned_port']}** · held until {req['hold_until']}")
            st.caption("Try a wrong port, a far GPS distance or no photo to see the app block the save.")
            with st.form(f"inst{req['request_id']}"):
                c1, c2, c3 = st.columns(3)
                fats = D()["fats"].fat_id.tolist()
                scanned = c1.selectbox("Scanned FAT (QR)", fats, index=fats.index(req["assigned_fat"]))
                port = c2.selectbox("Port used", list(range(1, 9)), index=int(req["assigned_port"]) - 1)
                serial = c3.text_input("ONU serial (barcode)", f"ZTEGNEW{req['request_id'][-4:]}")
                gps = st.slider("Your distance from the FAT (GPS, metres)", 0, 500, 12)
                photo = st.checkbox("Photo of the FAT port attached")
                if st.form_submit_button("Confirm installation", type="primary"):
                    try:
                        install(req["request_id"], scanned, port, serial, gps, photo)
                        st.success("Saved. Utilization and colours updated.")
                        st.rerun()
                    except ValueError as e:
                        st.error(f"Blocked: {e}")


def page_sheets():
    header("The data standard", "Data sheets")
    st.markdown("Each tab is one sheet from the standard. Link columns (like `fed_from_id`, `fdt_id`, `upstream_fat_id`, "
                "`fat_id`) are the **\"who feeds me?\"** links. Utilization is calculated, never stored.")
    db = D()
    names = {"OLT": "olts", "ODF": "odfs", "Cabinet": "cabinets", "FDT": "fdts", "FAT": "fats", "ONU": "onus",
             "Cable master": "cables", "Cable cores": "cable_cores", "POP list": "pops", "Street list": "street_list",
             "Estate list": "estate_list"}
    tabs = st.tabs(list(names))
    for tab, (label, key) in zip(tabs, names.items()):
        with tab:
            st.dataframe(db[key], width="stretch", hide_index=True)
            st.download_button(f"Download {label} (CSV)", db[key].to_csv(index=False), f"{key}.csv", key=f"dl{key}")


# =============================================================================
# APP
# =============================================================================
init_state()
with st.sidebar:
    st.markdown("### Fiber Capacity")
    st.caption("Data standard v3 · demo")
    page = st.radio("Go to", ["Dashboard", "Search and trace", "New request", "GIS approvals", "Installer jobs", "Data sheets"],
                    label_visibility="collapsed")
    st.divider()
    st.markdown("**Colours**")
    st.markdown("Green below 80%  \nYellow 80–99%  \nOrange 100% (full)  \nRed over 100%")
    st.divider()
    st.markdown("**Try this demo flow**")
    st.markdown("1. New request → 18 Toyin Street  \n2. GIS approvals → Approve  \n3. Installer jobs → Confirm  \n"
                "4. Watch the log and the map")
    st.divider()
    if st.button("Reset demo", width="stretch"):
        init_state(force=True)
        st.rerun()

main, side = st.columns([3.1, 1.2], gap="large")
with main:
    {"Dashboard": page_dashboard, "Search and trace": page_search, "New request": page_request,
     "GIS approvals": page_approvals, "Installer jobs": page_installer, "Data sheets": page_sheets}[page]()
with side:
    render_log()
