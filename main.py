"""Distribution Rate Case workbench (v1). Plain-language UI, Excel-first data entry.
Deployed 2026-10-14: exec insights, gas compare, company logos.
"""
import os
import re
import uuid
from datetime import date, datetime, timedelta
from io import BytesIO

from fastapi import FastAPI, Request, Depends, UploadFile, File, Form
from fastapi.responses import HTMLResponse, StreamingResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

import hashlib

import database
from database import init_db, get_db
from models import (Utility, ServiceArea, Case, ThreeWayPosition, TariffRider, Document,
                    EarnedROE, DiscoveryRequest, ExpertWitness, Scenario, ScenarioAdjustment,
                    Milestone)
import seed as seed_module
import excel_templates
import excel_import
import charts

app = FastAPI(title="Rate Case Workbench")
templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "templates"))
app.mount("/static", StaticFiles(directory=os.path.join(os.path.dirname(__file__), "static")), name="static")

# Company logos for the Compare page, keyed by utility name.
UTILITY_LOGOS = {
    "AES Ohio": "aes.svg",
    "AEP Ohio": "aep.svg",
    "Duke Energy Ohio (Electric)": "duke.svg",
    "Duke Energy Ohio (Gas)": "duke.svg",
    "FirstEnergy": "firstenergy.svg",
    "Columbia Gas of Ohio": "columbia.svg",
    "CenterPoint Energy Ohio": "nationalfuel.svg",
    "Enbridge Gas Ohio": "enbridge.svg",
}

STAGE_LABELS = {"as_filed": "As filed", "staff": "Staff", "final_or_stip": "Final / stipulation"}
STATUS_LABELS = {"decided": "Decided", "pending": "In progress",
                 "stipulated": "Settlement filed - waiting on decision"}
TYPE_LABELS = {"historical": "Historical", "prospective": "Prospective",
               "tariff": "Tariff", "rider": "Rider", "other": "Other proceeding"}
DISP_LABELS = {"roll_into_base": "Rolls into base rates", "standalone": "Stays separate",
               "undecided": "Undecided"}
RIDER_STATUS_LABELS = {"effective": "In rates now", "proposed": "Proposed", "terminated": "Ended"}
DR_TYPE_LABELS = {"data_request": "DR", "interrogatory": "Interrogatory",
                  "production": "Request for production", "admission": "Request for admission",
                  "deposition": "Deposition", "motion": "Motion", "other": "Other"}
DR_STATUS_LABELS = {"open": "Open", "in_progress": "In progress", "in_review": "In review",
                    "complete": "Complete", "withdrawn": "Withdrawn"}
EXPERT_SIDE_LABELS = {"utility": "Ours", "staff": "Staff", "intervenor": "Intervenor"}
EXPERT_STATUS_LABELS = {"retained": "Retained", "drafting": "Drafting", "filed": "Filed",
                        "testified": "Testified", "withdrawn": "Withdrawn"}
KIND_LABELS = {"hearing": "Hearing", "testimony": "Testimony due", "comments": "Comments due",
               "filing": "Filing due", "decision": "Decision", "deadline": "Deadline"}
TEST_PERIOD_LABELS = {"historic": "Historic test year",
                      "historic_adjusted": "Historic + pro forma adjustments",
                      "future_test_year": "Future test year",
                      "multiyear_plan": "Multi-year rate plan",
                      "formula_rate": "Formula rate"}
RB_METHOD_LABELS = {"average_13mo": "13-month average", "year_end": "Year-end"}
ROE_METHOD_LABELS = {"dcf": "DCF", "capm": "CAPM", "risk_premium": "Risk premium",
                     "comparable_earnings": "Comparable earnings", "other": "Other"}
RISK_LABELS = {"low": "Low — likely flies", "medium": "Medium — a fight",
               "high": "High — dead on arrival", "unrated": "Not rated yet"}
ADJ_CAT_LABELS = {"annualization": "Annualization", "normalization": "Normalization",
                  "known_measurable": "Known & measurable", "other": "Other"}

# Utility featured as the model at the top of the dashboard.
MODEL_UTILITY = "AES Ohio"

_pending_imports = {}  # token -> (kind, rows)


@app.on_event("startup")
def startup():
    init_db()
    db = database.SessionLocal()
    try:
        if db.query(Utility).count() == 0:
            seed_module.seed()
        else:
            # One-time correction: ensure gas utilities carry sector="gas"
            # (older seeds left them as electric/default).
            for name in ("Duke Energy Ohio (Gas)", "CenterPoint Energy Ohio",
                         "Enbridge Gas Ohio", "Columbia Gas of Ohio"):
                u = db.query(Utility).filter(Utility.name == name).first()
                if u and u.sector != "gas":
                    u.sector = "gas"
            # One-time correction: populate FirstEnergy 24-0468-EL-AIR positions
            # (as-filed $190M / 10.8% ROE; final $34M / 9.63% ROE per PUCO order).
            from models import Case, ThreeWayPosition
            c46 = db.query(Case).filter(Case.docket == "24-0468-EL-AIR").first()
            if c46:
                for stage, rev, roe, notes in [
                    ("as_filed", 190.0, 10.8, "As-filed 5/31/2024. $4.3B rate base."),
                    ("final_or_stip", 34.0, 9.63, "PUCO order 11/19/2025. Net $34M increase."),
                ]:
                    p = db.query(ThreeWayPosition).filter(
                        ThreeWayPosition.case_id == c46.id,
                        ThreeWayPosition.stage == stage,
                        ThreeWayPosition.period.is_(None)).first()
                    if not p:
                        p = ThreeWayPosition(case_id=c46.id, stage=stage, period=None)
                        db.add(p)
                    p.revenue_change = rev
                    p.roe = roe
                    p.notes = notes
            # One-time correction: Columbia Gas formal filing 26-0965-GA-AIR
            # (filed 10/19/2026) replaces the pre-filing TBD placeholder.
            from models import Document
            tbd = db.query(Case).filter(Case.docket == "TBD (pre-filing 2026-09-18)").first()
            if tbd:
                db.query(ThreeWayPosition).filter(ThreeWayPosition.case_id == tbd.id).delete()
                db.query(Document).filter(Document.case_id == tbd.id).delete()
                db.delete(tbd)
                db.flush()
            col = db.query(Utility).filter(Utility.name == "Columbia Gas of Ohio").first()
            c965 = db.query(Case).filter(Case.docket == "26-0965-GA-AIR").first()
            if col and not c965:
                c965 = Case(docket="26-0965-GA-AIR", utility_id=col.id,
                            case_type="historical", status="pending",
                            date_filed="2026-10-19",
                            notes="Formal base rate case application filed 10/19/2026. "
                                  "Companion dockets 26-0966-GA-ATA, 26-0967-GA-UNC, "
                                  "26-0968-GA-AAM.")
                db.add(c965)
                db.flush()
            if c965:
                for period, rev, cod in (("TY1 2028", 158.8, 5.18),
                                         ("TY2 2029", 103.2, 5.28),
                                         ("TY3 2030", 89.3, 5.37)):
                    p = db.query(ThreeWayPosition).filter(
                        ThreeWayPosition.case_id == c965.id,
                        ThreeWayPosition.stage == "as_filed",
                        ThreeWayPosition.period == period).first()
                    if not p:
                        db.add(ThreeWayPosition(
                            case_id=c965.id, stage="as_filed", period=period,
                            revenue_change=rev, roe=10.25, equity_ratio=51.50,
                            cost_of_debt=cod,
                            capital_structure="51.50% common equity / 48.50% long-term debt"))
            # Gap-fill for 26-0965-GA-AIR (2026-10-26): the block above created
            # the case and its three as-filed positions but left test_year,
            # position notes, and the FTY1 gross revenue requirement blank.
            # Fill them from the filed application (same figures as seed.py);
            # rate base stays blank — the pleading narrative does not state it.
            if c965:
                c965.test_year = "FTY1 CY2028; FTY2 CY2029; FTY3 CY2030"
                for period, notes in (
                    ("TY1 2028",
                     "ROE 10.25% (low end of 10.25-11.25% Brattle range, witness Ann "
                     "Bulkley). WACC 7.79%. FTY1 increase inclusive of capital-rider "
                     "roll-in = $604.5M (58.40%); the 158.8 figure recognizes rider "
                     "termination. Capex $1,101.9M; new SGS-2 rate class (300-600 Mcf); "
                     "MGP environmental cost recovery (deferral capped at $24,997,442.98). "
                     "Source: application pp.7-11 (doc pp.5-9)."),
                    ("TY2 2029",
                     "WACC 7.84%. Capex $1,055.0M. FTY2 increase 5.53% (4.50% incl. rider "
                     "roll-in framing: 6.25%). Source: application pp.7-11 (doc pp.5-9)."),
                    ("TY3 2030",
                     "WACC 7.88%. Capex $934.4M. FTY3 increase 4.50% (incl. rider roll-in "
                     "framing: 5.05%). Source: application pp.7-11 (doc pp.5-9).")):
                    p = db.query(ThreeWayPosition).filter(
                        ThreeWayPosition.case_id == c965.id,
                        ThreeWayPosition.stage == "as_filed",
                        ThreeWayPosition.period == period).first()
                    if p:
                        p.notes = notes
                        if period == "TY1 2028":
                            p.revenue_requirement = 604.5
            # Tier 2 open-docket records (2026-10-29): non-rate-case proceedings
            # tracked as milestones only — no rate-case build, no positions.
            # Same records as seed.py; create-if-missing so existing production
            # DBs (which never re-run seed) pick them up on startup.
            for docket, util_name, notes in (
                ("26-0974-EL-SSO", "AES Ohio",
                 "Tier 2 docket record — milestones only, no rate-case build. "
                 "AES Ohio Market Rate Offer / Standard Service Offer case. "
                 "Companion dockets 26-0975-EL-RDR, 26-0976-EL-AAM. "
                 "Staff Report was due 10/16/2026; intervention deadline closed "
                 "10/23/2026; prehearing 10/28/2026 (10 AM, Room 11-C). "
                 "Next milestone: evidentiary hearing 11/12/2026 (10 AM, Room 11-A)."),
                ("26-0755-EL-ATA", "Duke Energy Ohio (Electric)",
                 "Tier 2 docket record — milestones only, no rate-case build. "
                 "Duke Energy Ohio data-center / large-load tariff proposal "
                 "(metering and cost-responsibility options; OCC backs 100% "
                 "data-center payment of dedicated line-extension/substation costs). "
                 "Comments filed 10/22/2026. "
                 "Next milestone: replies and interventions due 11/12/2026."),
                ("26-0505-EL-FOR", "AES Ohio",
                 "Tier 2 docket record — milestones only, no rate-case build. "
                 "AES Ohio long-term forecast docket. ALJ Entry 10/14/2026 "
                 "(Marcelletti) granted expedited continuance. "
                 "Next milestones: intervenor testimony 12/14/2026; discovery "
                 "cutoff 12/28/2026; Staff testimony 1/5/2027; hearing 1/12/2027.")):
                u = db.query(Utility).filter(Utility.name == util_name).first()
                if u and not db.query(Case).filter(Case.docket == docket).first():
                    db.add(Case(docket=docket, utility_id=u.id,
                                case_type="other", status="pending", notes=notes))
            # Phase 1 deadline machine (2026-10-29): structured milestones for
            # open cases, shared with seed.py so existing production DBs get
            # the same calendar. Create-if-missing, same as Tier 2 above.
            for docket, label, due, kind, notes in seed_module.PHASE1_MILESTONES:
                mc = db.query(Case).filter(Case.docket == docket).first()
                if mc and not db.query(Milestone).filter(
                        Milestone.case_id == mc.id, Milestone.label == label,
                        Milestone.due_date == due).first():
                    db.add(Milestone(case_id=mc.id, label=label, due_date=due,
                                     kind=kind, notes=notes))
            db.commit()
    finally:
        db.close()


# ---------------------------------------------------------------- auth gate
# Set APP_PASSWORD in the environment to lock the app behind a team sign-in
# (required before any public hosting). The cookie holds a hash of the
# password, not the password itself. Leave APP_PASSWORD unset for open
# local/dev access.
_AUTH_COOKIE = "rcw_auth"
_AUTH_FREE_PATHS = {"/login", "/logout", "/healthz"}


def _app_password():
    return os.environ.get("APP_PASSWORD", "")


def _auth_token():
    pw = _app_password()
    return hashlib.sha256(pw.encode()).hexdigest() if pw else ""


def _is_authed(request: Request):
    return bool(_app_password()) and request.cookies.get(_AUTH_COOKIE) == _auth_token()


@app.middleware("http")
async def auth_gate(request: Request, call_next):
    if _app_password() and request.url.path not in _AUTH_FREE_PATHS and not _is_authed(request):
        return RedirectResponse(url="/login", status_code=303)
    return await call_next(request)


@app.get("/healthz")
def healthz():
    return JSONResponse({"ok": True})


@app.get("/login", response_class=HTMLResponse)
def login_form(request: Request):
    if not _app_password():
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(request, "login.html", {"request": request, "error": ""})


@app.post("/login")
def login(request: Request, password: str = Form("")):
    if _app_password() and password == _app_password():
        resp = RedirectResponse("/", status_code=303)
        resp.set_cookie(_AUTH_COOKIE, _auth_token(), httponly=True, samesite="lax",
                        max_age=30 * 24 * 3600)
        return resp
    return templates.TemplateResponse(
        request, "login.html",
        {"request": request, "error": "Hmm, that's not it — try again."},
        status_code=401)


@app.get("/logout")
def logout():
    resp = RedirectResponse("/login", status_code=303)
    resp.delete_cookie(_AUTH_COOKIE)
    return resp


# ---------------------------------------------------------------- helpers

def _case_sort_key(c):
    return (c.date_order or "", c.date_filed or "")


def latest_case_for(db, utility):
    cases = db.query(Case).filter(Case.utility_id == utility.id).all()
    if not cases:
        return None
    return max(cases, key=_case_sort_key)


def final_position(db, case):
    if not case:
        return None
    return (db.query(ThreeWayPosition)
            .filter(ThreeWayPosition.case_id == case.id,
                    ThreeWayPosition.stage == "final_or_stip")
            .order_by(ThreeWayPosition.period).first())


def dashboard_cards(db):
    cards = []
    for u in db.query(Utility).order_by(Utility.name).all():
        lc = latest_case_for(db, u)
        auth_case = None
        for c in sorted(db.query(Case).filter(Case.utility_id == u.id).all(),
                        key=_case_sort_key, reverse=True):
            if c.status != "pending" and final_position(db, c):
                auth_case = c
                break
        fp = final_position(db, auth_case) if auth_case else None
        n_cases = db.query(Case).filter(Case.utility_id == u.id).count()
        n_riders = db.query(TariffRider).filter(TariffRider.utility_id == u.id).count()
        cards.append({"utility": u, "latest": lc, "auth_case": auth_case, "auth": fp,
                      "n_cases": n_cases, "n_riders": n_riders,
                      "is_model": u.name == MODEL_UTILITY,
                      "logo": UTILITY_LOGOS.get(u.name)})
    # Model utility leads the dashboard.
    cards.sort(key=lambda c: (not c["is_model"], c["utility"].name))
    return cards


def position_grid(db, case):
    """{period_label: {stage: position}} preserving a sensible stage order."""
    stages = ["as_filed", "staff", "final_or_stip"]
    by_period = {}
    for p in db.query(ThreeWayPosition).filter(
            ThreeWayPosition.case_id == case.id).all():
        key = p.period or "Single year"
        by_period.setdefault(key, {})[p.stage] = p
    ordered = {}
    for key in sorted(by_period.keys(), key=lambda k: (k != "Single year", k)):
        ordered[key] = [(s, by_period[key].get(s)) for s in stages]
    return ordered


def _ty1_positions(db, case):
    """TY1-or-single-year positions by stage, the comparison basis used by
    charts and benchmarks (multi-year plans compare on Test Year 1)."""
    pos = {}
    for p in db.query(ThreeWayPosition).filter(
            ThreeWayPosition.case_id == case.id).all():
        if not p.period or "TY1" in (p.period or ""):
            pos[p.stage] = p
    return pos


def benchmark_rows(db, sector="all"):
    """Phase 1: one row per case with an as-filed position — what was asked,
    what was granted, and the haircut. Pending cases show asked with granted
    blank. Returns (rows, landing-zone medians)."""
    import statistics
    rows = []
    for c in db.query(Case).all():
        if sector != "all" and (c.utility.sector or "electric") != sector:
            continue
        pos = _ty1_positions(db, c)
        af, fn = pos.get("as_filed"), pos.get("final_or_stip")
        if not af:
            continue
        haircut = haircut_pct = give_roe = None
        if fn and af.revenue_change is not None and fn.revenue_change is not None:
            haircut = fn.revenue_change - af.revenue_change
            if af.revenue_change != 0:
                haircut_pct = haircut / abs(af.revenue_change) * 100
        if fn and af.roe is not None and fn.roe is not None:
            give_roe = fn.roe - af.roe
        rows.append({
            "case": c, "utility": c.utility, "asked": af, "final": fn,
            "staff": pos.get("staff"),
            "haircut": haircut, "haircut_pct": haircut_pct, "give_roe": give_roe,
        })
    rows.sort(key=lambda r: (r["utility"].name, r["case"].docket))
    granted_roes = [r["final"].roe for r in rows
                    if r["final"] and r["final"].roe is not None
                    and r["case"].status in ("decided", "stipulated")]
    haircuts = [r["haircut_pct"] for r in rows if r["haircut_pct"] is not None]
    landing = {
        "median_roe": statistics.median(granted_roes) if granted_roes else None,
        "median_haircut": statistics.median(haircuts) if haircuts else None,
        "n_granted": len(granted_roes),
    }
    return rows, landing


def _fmt_money(v):
    if v is None:
        return None
    return ("+" if v >= 0 else "-") + f"${abs(v):.1f}M"


def _fmt_pct(v):
    return None if v is None else f"{v:.2f}%"


def settlement_bridge(db, case):
    """Phase 1: as-filed -> staff -> final walk, per period, for the case
    page. Only periods with an as-filed position and at least one later
    stage get a bridge; asked-only pending cases show nothing."""
    bridge = {}
    for period, cols in position_grid(db, case).items():
        pos = dict(cols)
        af, st, fn = pos.get("as_filed"), pos.get("staff"), pos.get("final_or_stip")
        if not af or (not st and not fn):
            continue
        rows = []
        for label, attr, fmt in (("Revenue change", "revenue_change", _fmt_money),
                                 ("ROE", "roe", _fmt_pct),
                                 ("Equity ratio", "equity_ratio", _fmt_pct),
                                 ("Rate base", "rate_base", _fmt_money)):
            a, s, f = (getattr(af, attr), getattr(st, attr) if st else None,
                       getattr(fn, attr) if fn else None)
            if a is None and s is None and f is None:
                continue
            give = (f - a) if (fn and a is not None and f is not None) else None
            give_str = None
            if give is not None:
                give_str = (f"{give:+.2f} pp" if attr in ("roe", "equity_ratio")
                            else _fmt_money(give))
            rows.append({"label": label, "asked": fmt(a), "staff": fmt(s),
                         "final": fmt(f), "give": give_str})
        if rows:
            bridge[period] = rows
    return bridge


def deadline_items(db):
    """Phase 1: one timeline — case milestones + open discovery items +
    pending expert testimony, sorted by date. Items without a date stay in
    their own pages."""
    items = []
    for m in db.query(Milestone).all():
        items.append({"date": m.due_date, "label": m.label, "kind": m.kind,
                      "docket": m.case.docket, "case_id": m.case_id,
                      "utility": m.case.utility.name, "source": "milestone",
                      "notes": m.notes})
    for r in db.query(DiscoveryRequest).filter(
            ~DiscoveryRequest.status.in_(excel_import.DR_DONE)).all():
        if not r.due_date:
            continue
        items.append({"date": r.due_date,
                      "label": (f"{DR_TYPE_LABELS.get(r.request_type, r.request_type)} "
                                f"{r.number or ''} from {r.requesting_party}").strip(),
                      "kind": "deadline", "docket": r.case.docket, "case_id": r.case_id,
                      "utility": r.case.utility.name, "source": "discovery",
                      "notes": r.assigned_to or None})
    for e in db.query(ExpertWitness).filter(
            ~ExpertWitness.status.in_(["testified", "withdrawn"])).all():
        if not e.testimony_due:
            continue
        items.append({"date": e.testimony_due,
                      "label": f"{e.name} testimony" + (f" — {e.topic}" if e.topic else ""),
                      "kind": "testimony", "docket": e.case.docket, "case_id": e.case_id,
                      "utility": e.case.utility.name, "source": "expert",
                      "notes": e.assigned_to or None})
    items.sort(key=lambda i: (i["date"] or "9999", i["docket"], i["label"]))
    return items


def upcoming_deadlines(db, n=5):
    today = date.today().isoformat()
    return [i for i in deadline_items(db) if (i["date"] or "9999") >= today][:n]


# ---------------------------------------------------------------- pages

# External navigation tools every utility team needs one tap away.
EXTERNAL_TOOLS = [
    {"name": "PJM", "url": "https://www.pjm.com/",
     "hint": "Wholesale markets & transmission"},
    {"name": "FERC", "url": "https://www.ferc.gov/",
     "hint": "Federal energy regulation"},
    {"name": "PUCO DIS", "url": "https://dis.puc.state.oh.us/",
     "hint": "Docket filings & documents"},
]

# Legal authorities counsel reaches for when building the case.
LEGAL_AUTHORITIES = [
    {"name": "ORC 4909.15", "url": "https://codes.ohio.gov/ohio-revised-code/section-4909.15",
     "hint": "Test periods & rate-case standards"},
    {"name": "ORC 4909.18", "url": "https://codes.ohio.gov/ohio-revised-code/section-4909.18",
     "hint": "Future / forecasted test periods"},
    {"name": "OAC 4901-7-01", "url": "https://codes.ohio.gov/oac/4901-7-01",
     "hint": "Filing requirements (SFR schedules)"},
    {"name": "ORC 4928.83", "url": "https://codes.ohio.gov/ohio-revised-code/section-4928.83",
     "hint": "Hosting capacity & reliability"},
]


def dis_url(docket):
    """Stable PUCO DIS case-record link for a docket like '25-0958-EL-AIR'."""
    from urllib.parse import quote
    return f"https://dis.puc.state.oh.us/CaseRecord.aspx?CaseNo={quote(docket)}"


_DOCKET_RE = re.compile(r"^\d{2}-\d{3,4}-[A-Z]{2,4}-[A-Z]{2,4}$")


def is_docket(value):
    """True when the string looks like a real PUCO docket (not a TBD placeholder)."""
    return bool(value) and bool(_DOCKET_RE.match(value.strip()))


def monogram(name):
    """Short logo tile text, e.g. 'AES Ohio' -> 'AES', 'Duke Energy Ohio' -> 'DE'."""
    parts = name.split()
    if parts and len(parts[0]) <= 4 and parts[0].isupper():
        return parts[0]
    return "".join(p[0] for p in parts[:2]).upper()


def _sdate(s):
    """Parse a YYYY-MM-DD string to a date, or None."""
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def _ror(equity_ratio, roe, cost_of_debt):
    """Overall rate of return (decimal) from capital structure."""
    eq = (equity_ratio or 0) / 100.0
    return eq * (roe or 0) / 100.0 + (1 - eq) * (cost_of_debt or 0) / 100.0


def rr_from_inputs(rate_base, equity_ratio, roe, cost_of_debt,
                   opex, depreciation, taxes, adjustments=0.0):
    """Revenue requirement ($M) from explicit inputs. Single source of
    truth for the executive math; scenario_math delegates to it."""
    ror = _ror(equity_ratio, roe, cost_of_debt)
    return_on_rb = (rate_base or 0) * ror
    return (return_on_rb + (opex or 0) + (depreciation or 0)
            + (taxes or 0) + (adjustments or 0))


def scenario_math(s):
    """Revenue requirement = rate base x overall return + O&M + depreciation
    + taxes + adjustments. Every methodology choice is a lever on this."""
    ror = _ror(s.equity_ratio, s.roe, s.cost_of_debt)
    adj_total = sum(a.amount or 0 for a in s.adjustments)
    rr = rr_from_inputs(s.rate_base, s.equity_ratio, s.roe, s.cost_of_debt,
                        s.opex, s.depreciation, s.taxes, adj_total)
    return {"ror_pct": ror * 100.0, "return_on_rb": (s.rate_base or 0) * ror,
            "adj_total": adj_total, "revenue_requirement": rr}


# ------------------------------------------------------------------ COSS /
# rate design / bill impacts
#
# The chain: (1) take a revenue requirement's components (from the
# as-filed position or any scenario); (2) allocate rate base, O&M,
# depreciation and taxes to customer classes by the COSS percentages;
# (3) compute each class's return from its allocated rate base at the
# source ROR; (4) design rates — the user sets customer and demand
# charges (policy choices) and the engine solves the energy charge as
# the plug that recovers the class RR; (5) bill impacts fall out of
# current vs proposed rates at representative usage.

COSS_COMPONENTS = ["rate_base", "opex", "depreciation", "taxes"]
COSS_LABELS = {"rate_base": "Rate base", "opex": "O&M",
               "depreciation": "Depreciation", "taxes": "Taxes"}


def rr_source_components(src):
    """Pull allocatable components ($M) and ROR (decimal) from a
    ThreeWayPosition or Scenario."""
    eq = (src.equity_ratio or 0) / 100.0
    ror = eq * (src.roe or 0) / 100.0 + (1 - eq) * (src.cost_of_debt or 0) / 100.0
    return {"rate_base": src.rate_base or 0, "opex": src.opex or 0,
            "depreciation": src.depreciation or 0, "taxes": src.taxes or 0,
            "ror": ror}


def class_revenue_requirements(classes, comp):
    """Allocate components to classes. Returns {class_id: dict} with
    allocated $M per component, the computed return, and class RR."""
    out = {}
    for c in classes:
        rb = comp["rate_base"] * (c.alloc_rate_base or 0) / 100.0
        ox = comp["opex"] * (c.alloc_opex or 0) / 100.0
        dp = comp["depreciation"] * (c.alloc_depreciation or 0) / 100.0
        tx = comp["taxes"] * (c.alloc_taxes or 0) / 100.0
        ret = rb * comp["ror"]
        out[c.id] = {"rate_base": rb, "return": ret, "opex": ox,
                     "depreciation": dp, "taxes": tx,
                     "total": ret + ox + dp + tx}
    return out


def design_rates(c, class_rr):
    """Solve the proposed energy charge ($/kWh) as the plug: class RR
    minus customer- and demand-charge recovery, divided by annual kWh.
    Returns the full proposed rate set plus check figures ($M)."""
    cust_rev = (c.prop_customer_charge or 0) * (c.customers or 0) * 12 / 1e6
    dem_rev = (c.prop_demand_charge or 0) * (c.kw_billing or 0) * 12 / 1e6
    kwh = c.kwh_annual or 0
    residual = class_rr - cust_rev - dem_rev
    energy = residual * 1e6 / kwh if kwh else None
    return {"customer_charge": c.prop_customer_charge or 0,
            "demand_charge": c.prop_demand_charge or 0,
            "energy_charge": energy,
            "customer_revenue": cust_rev, "demand_revenue": dem_rev,
            "energy_revenue": residual,
            "check_total": cust_rev + dem_rev + residual}


def monthly_bill(customer_charge, demand_charge, energy_charge, kwh, kw=0):
    """One monthly bill. Returns None when the energy charge is unknown."""
    if energy_charge is None:
        return None
    return ((customer_charge or 0) + (demand_charge or 0) * (kw or 0)
            + energy_charge * kwh)


def bill_impacts(c, class_rr):
    """Typical-bill impacts at low / typical / high usage (50% / 100% /
    200% of class-average monthly use). Returns a list of dicts."""
    rates = design_rates(c, class_rr)
    n = c.customers or 0
    avg_kwh = (c.kwh_annual or 0) / n / 12 if n else 0
    avg_kw = (c.kw_billing or 0) / n if n else 0
    out = []
    for label, mult in (("Low", 0.5), ("Typical", 1.0), ("High", 2.0)):
        kwh, kw = avg_kwh * mult, avg_kw * mult
        cur = monthly_bill(c.cur_customer_charge, c.cur_demand_charge,
                           c.cur_energy_charge, kwh, kw)
        prop = monthly_bill(rates["customer_charge"], rates["demand_charge"],
                            rates["energy_charge"], kwh, kw)
        if cur is None or prop is None or not cur:
            chg, pct = None, None
        else:
            chg, pct = prop - cur, (prop - cur) / cur * 100
        out.append({"level": label, "kwh": kwh, "kw": kw,
                    "current": cur, "proposed": prop,
                    "change": chg, "pct": pct})
    return out


def validate_coss_allocations(classes):
    """Allocation percentages must sum to 100 per component (within
    rounding tolerance). Returns a list of plain-language errors."""
    errors = []
    for comp in COSS_COMPONENTS:
        total = sum(getattr(c, "alloc_" + comp) or 0 for c in classes)
        if abs(total - 100.0) > 0.05:
            errors.append(
                "The %s allocation adds up to %.2f%% across classes — "
                "it needs to total 100%%. Check the Alloc %s %% column."
                % (COSS_LABELS[comp], total, COSS_LABELS[comp]))
    return errors


def parse_adjustments(text):
    """Parse pasted adjustment lines: 'name | amount' or
    'name | category | amount'. Amounts are $M, + or -. All-or-nothing."""
    adjs, errors = [], []
    for i, line in enumerate((text or "").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) == 2:
            name, cat, amt_s = parts[0], "other", parts[1]
        elif len(parts) == 3:
            name, cat, amt_s = parts
            if cat not in ADJ_CAT_LABELS:
                errors.append(f"Adjustment line {i}: category '{cat}' isn't one of "
                              f"{', '.join(ADJ_CAT_LABELS)} — leave it out to file under Other.")
                continue
        else:
            errors.append(f"Adjustment line {i}: write it as 'name | amount', "
                          f"e.g. 'Union contract | 12.5'. Amounts are millions of dollars, + or -.")
            continue
        try:
            amount = float(amt_s.replace(",", "").replace("$", ""))
        except ValueError:
            errors.append(f"Adjustment line {i}: '{amt_s}' isn't a number — "
                          f"amounts are millions of dollars, + or -.")
            continue
        if not name:
            errors.append(f"Adjustment line {i}: give the adjustment a name.")
            continue
        adjs.append({"name": name, "category": cat, "amount": amount})
    return adjs, errors


def _num(form, key, label, errors, lo=None, hi=None, required=True, default=None):
    raw = (form.get(key) or "").strip()
    if not raw:
        if required:
            errors.append(f"{label} is missing — enter a number.")
            return None
        return default
    try:
        v = float(raw.replace(",", "").replace("$", "").replace("%", ""))
    except ValueError:
        errors.append(f"{label} '{raw}' isn't a number I recognize.")
        return None
    if lo is not None and v < lo or hi is not None and v > hi:
        errors.append(f"{label} of {v} looks off — keep it between {lo} and {hi}.")
        return None
    return v


def regulatory_attention(db):
    """Where the bottlenecks are, for Regulatory Affairs.

    Returns open discovery items split into overdue / due within 7 days /
    unassigned, plus expert testimony due within 30 days (or already past).
    """
    today = date.today()
    week_out = today + timedelta(days=7)
    month_out = today + timedelta(days=30)
    open_dr = (db.query(DiscoveryRequest)
               .filter(~DiscoveryRequest.status.in_(excel_import.DR_DONE))
               .all())
    overdue, due_soon, unassigned = [], [], []
    for r in open_dr:
        d = _sdate(r.due_date)
        if d and d < today:
            overdue.append(r)
        elif d and d <= week_out:
            due_soon.append(r)
        if not (r.assigned_to or "").strip():
            unassigned.append(r)
    experts = (db.query(ExpertWitness)
               .filter(~ExpertWitness.status.in_(["testified", "withdrawn"]))
               .all())
    expert_due = []
    for e in experts:
        d = _sdate(e.testimony_due)
        if d and d <= month_out:
            expert_due.append(e)
    by_due = lambda r: (r.due_date or "9999")
    return {
        "today": today.isoformat(),
        "n_open": len(open_dr),
        "overdue": sorted(overdue, key=by_due),
        "due_soon": sorted(due_soon, key=by_due),
        "unassigned": sorted(unassigned, key=by_due),
        "expert_due": sorted(expert_due, key=lambda e: (e.testimony_due or "9999")),
        "n_experts": len(experts),
    }


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse(request, "dashboard.html", {
        "request": request, "cards": dashboard_cards(db),
        "status_labels": STATUS_LABELS, "type_labels": TYPE_LABELS,
        "attention": regulatory_attention(db),
        "deadlines": upcoming_deadlines(db, 5),
        "dr_status_labels": DR_STATUS_LABELS, "dr_type_labels": DR_TYPE_LABELS})


@app.get("/utilities/{utility_id}", response_class=HTMLResponse)
def utility_page(request: Request, utility_id: int, db: Session = Depends(get_db)):
    u = db.query(Utility).filter(Utility.id == utility_id).first()
    if not u:
        return HTMLResponse("Utility not found.", status_code=404)
    cases = db.query(Case).filter(Case.utility_id == u.id).all()
    pending = sorted(
        [c for c in cases if c.status in ("pending", "stipulated")],
        key=_case_sort_key, reverse=True)
    tariffs = sorted(
        [r for r in db.query(TariffRider).filter(
            TariffRider.utility_id == u.id, TariffRider.kind == "tariff").all()],
        key=lambda r: r.name)
    riders = sorted(
        [r for r in db.query(TariffRider).filter(
            TariffRider.utility_id == u.id, TariffRider.kind == "rider").all()],
        key=lambda r: r.name)
    n_positions = db.query(ThreeWayPosition).join(Case).filter(
        Case.utility_id == u.id).count()
    n_undecided = sum(1 for r in tariffs + riders if r.disposition == "undecided")
    # Returns at a glance: authorized ROE from the latest decided case's
    # final/stipulated position vs. actual earned ROE by year.
    auth_roe = auth_docket = auth_cap = auth_case_id = None
    decided = sorted([c for c in cases if c.status == "decided" and c.date_order],
                     key=lambda c: c.date_order, reverse=True)
    for c in decided:
        finals = [p for p in c.positions
                  if p.stage == "final_or_stip" and p.roe is not None]
        if finals:
            finals.sort(key=lambda p: 0 if not p.period else 1)
            p = finals[0]
            auth_roe, auth_docket, auth_cap = p.roe, c.docket, p.capital_structure
            auth_case_id = c.id
            break
    earned_rows = sorted(
        db.query(EarnedROE).filter(EarnedROE.utility_id == u.id).all(),
        key=lambda e: e.year, reverse=True)
    return templates.TemplateResponse(request, "utility.html", {
        "request": request, "utility": u, "is_model": u.name == MODEL_UTILITY,
        "monogram": monogram(u.name),
        "pending": pending, "tariffs": tariffs, "riders": riders,
        "external_tools": EXTERNAL_TOOLS, "legal": LEGAL_AUTHORITIES,
        "dis_url": dis_url, "is_docket": is_docket,
        "n_positions": n_positions, "n_undecided": n_undecided,
        "auth_roe": auth_roe, "auth_docket": auth_docket, "auth_cap": auth_cap,
        "auth_case_id": auth_case_id, "earned_rows": earned_rows,
        "status_labels": STATUS_LABELS, "type_labels": TYPE_LABELS,
        "disp_labels": DISP_LABELS, "rider_status_labels": RIDER_STATUS_LABELS})


@app.get("/cases", response_class=HTMLResponse)
def case_list(request: Request, db: Session = Depends(get_db)):
    cases = db.query(Case).all()
    cases.sort(key=_case_sort_key, reverse=True)
    return templates.TemplateResponse(request, "cases.html", {
        "request": request, "cases": cases,
        "status_labels": STATUS_LABELS, "type_labels": TYPE_LABELS})


@app.get("/cases/{case_id}", response_class=HTMLResponse)
def case_detail(request: Request, case_id: int, db: Session = Depends(get_db)):
    case = db.query(Case).filter(Case.id == case_id).first()
    if not case:
        return HTMLResponse("Case not found.", status_code=404)
    return templates.TemplateResponse(request, "case_detail.html", {
        "request": request, "case": case, "grid": position_grid(db, case),
        "stage_labels": STAGE_LABELS, "status_labels": STATUS_LABELS,
        "type_labels": TYPE_LABELS, "dis_url": dis_url, "is_docket": is_docket,
        "bridge": settlement_bridge(db, case), "kind_labels": KIND_LABELS,
        "dr_type_labels": DR_TYPE_LABELS, "dr_status_labels": DR_STATUS_LABELS,
        "expert_status_labels": EXPERT_STATUS_LABELS,
        "expert_side_labels": EXPERT_SIDE_LABELS})


@app.get("/discovery", response_class=HTMLResponse)
def discovery_center(request: Request, db: Session = Depends(get_db),
                     status: str = "", assignee: str = "", case_id: str = ""):
    """Regulatory Affairs command center: every DR and expert, who owns it,
    what's due, and where the bottlenecks are."""
    q = db.query(DiscoveryRequest)
    if status in excel_import.DR_STATUSES:
        q = q.filter(DiscoveryRequest.status == status)
    if assignee == "__unassigned__":
        q = q.filter((DiscoveryRequest.assigned_to == None) |  # noqa: E711
                      (DiscoveryRequest.assigned_to == ""))
    elif assignee:
        q = q.filter(DiscoveryRequest.assigned_to == assignee)
    if case_id.isdigit():
        q = q.filter(DiscoveryRequest.case_id == int(case_id))
    items = sorted(q.all(), key=lambda r: (r.due_date or "9999"))
    assignees = sorted({r.assigned_to for r in db.query(DiscoveryRequest).all()
                        if (r.assigned_to or "").strip()})
    cases = db.query(Case).order_by(Case.docket).all()
    experts = sorted(db.query(ExpertWitness).all(),
                     key=lambda e: (e.testimony_due or "9999"))
    return templates.TemplateResponse(request, "discovery.html", {
        "request": request, "items": items, "experts": experts,
        "attention": regulatory_attention(db),
        "dr_type_labels": DR_TYPE_LABELS, "dr_status_labels": DR_STATUS_LABELS,
        "dr_statuses": excel_import.DR_STATUSES,
        "expert_side_labels": EXPERT_SIDE_LABELS,
        "expert_status_labels": EXPERT_STATUS_LABELS,
        "assignees": assignees, "cases": cases,
        "f_status": status, "f_assignee": assignee, "f_case": case_id})


def _as_filed(db, case):
    return (db.query(ThreeWayPosition)
            .filter(ThreeWayPosition.case_id == case.id,
                    ThreeWayPosition.stage == "as_filed")
            .order_by(ThreeWayPosition.period).first())


def _scenario_ctx(db, case, errors=None, form=None):
    af = _as_filed(db, case)
    scenarios = (db.query(Scenario).filter(Scenario.case_id == case.id)
                 .order_by(Scenario.id).all())
    with_math = sorted(((s, scenario_math(s)) for s in scenarios),
                       key=lambda sm: sm[1]["revenue_requirement"], reverse=True)
    prefill = {"rate_base": af.rate_base if af and af.rate_base is not None else "",
               "roe": af.roe if af and af.roe is not None else "",
               "equity_ratio": af.equity_ratio if af and af.equity_ratio is not None else "",
               "cost_of_debt": af.cost_of_debt if af and af.cost_of_debt is not None else "",
               "opex": af.opex if af and af.opex is not None else "",
               "depreciation": af.depreciation if af and af.depreciation is not None else "",
               "taxes": af.taxes if af and af.taxes is not None else ""}
    prefilled = af is not None and any(v != "" for v in prefill.values())
    return {"case": case, "scenarios": with_math, "as_filed": af,
            "prefill": prefill, "prefilled": prefilled,
            "errors": errors or [], "form": form or {},
            "sens": None, "sens_errors": [],
            "sens_q": {"sens": "", "low": "", "high": "", "step": ""},
            "test_period_labels": TEST_PERIOD_LABELS, "rb_method_labels": RB_METHOD_LABELS,
            "roe_method_labels": ROE_METHOD_LABELS, "risk_labels": RISK_LABELS,
            "adj_cat_labels": ADJ_CAT_LABELS}


def roe_sensitivity(s, low, high, step_bps):
    """Revenue requirement at each ROE step, everything else held constant.
    Returns (rows, per_10bp) where rows = [(roe, rr, delta_vs_base)]."""
    eq = (s.equity_ratio or 0) / 100.0
    debt_c = (s.cost_of_debt or 0) / 100.0
    base_fixed = ((s.opex or 0) + (s.depreciation or 0) + (s.taxes or 0)
                  + sum(a.amount or 0 for a in s.adjustments))
    rb = s.rate_base or 0
    per_10bp = rb * eq * 0.001
    base_rr = scenario_math(s)["revenue_requirement"]
    rows = []
    r = low
    while r <= high + 1e-9 and len(rows) < 101:
        ror = eq * r / 100.0 + (1 - eq) * debt_c
        rr = rb * ror + base_fixed
        rows.append((round(r, 3), rr, rr - base_rr))
        r += step_bps / 100.0
    return rows, per_10bp


@app.get("/cases/{case_id}/scenarios", response_class=HTMLResponse)
def scenario_workbench(request: Request, case_id: int, db: Session = Depends(get_db)):
    case = db.query(Case).filter(Case.id == case_id).first()
    if not case:
        return HTMLResponse("Case not found.", status_code=404)
    ctx = _scenario_ctx(db, case)
    # ROE sensitivity toggles: ?sens=<scenario_id>&low=9.0&high=10.5&step=10
    sens, sens_errors = None, []
    q = request.query_params
    if "sens" in q:
        s = db.query(Scenario).filter(Scenario.id == q["sens"],
                                      Scenario.case_id == case.id).first()
        if not s:
            sens_errors.append("Pick one of this case's scenarios for the sensitivity run.")
        else:
            try:
                low = float(q.get("low", (s.roe or 9.5) - 1.0))
                high = float(q.get("high", (s.roe or 9.5) + 1.0))
                step = float(q.get("step", 10))
            except (TypeError, ValueError):
                low = high = step = None
                sens_errors.append("Low, high, and step need to be numbers.")
            if low is not None:
                if not (0 <= low < high <= 20):
                    sens_errors.append("Keep the ROE range between 0 and 20, low below high.")
                elif not (0 < step <= 200):
                    sens_errors.append("Keep the step between 1 and 200 basis points.")
                else:
                    rows, per_10bp = roe_sensitivity(s, low, high, step)
                    af = ctx["as_filed"]
                    af_rr = af.revenue_requirement if af else None
                    sens = {"scenario": s, "rows": rows, "per_10bp": per_10bp,
                            "low": low, "high": high, "step": step,
                            "base_rr": scenario_math(s)["revenue_requirement"],
                            "af_rr": af_rr}
    ctx["sens"] = sens
    ctx["sens_errors"] = sens_errors
    ctx["sens_q"] = {k: q.get(k, "") for k in ("sens", "low", "high", "step")}
    return templates.TemplateResponse(request, "scenarios.html",
                                      {"request": request, **ctx})


@app.post("/cases/{case_id}/scenarios")
async def scenario_create(request: Request, case_id: int, db: Session = Depends(get_db)):
    case = db.query(Case).filter(Case.id == case_id).first()
    if not case:
        return HTMLResponse("Case not found.", status_code=404)
    form = dict(await request.form())
    errors = []
    name = (form.get("name") or "").strip()
    if not name:
        errors.append("Give the scenario a name — e.g. 'Year-end RB, 10.1% ROE'.")
    tp = form.get("test_period_type") or "historic_adjusted"
    if tp not in TEST_PERIOD_LABELS:
        errors.append("Pick a test period type from the list.")
    rbm = form.get("rate_base_method") or "average_13mo"
    if rbm not in RB_METHOD_LABELS:
        errors.append("Pick a rate base measurement from the list.")
    roem = form.get("roe_method") or "dcf"
    if roem not in ROE_METHOD_LABELS:
        errors.append("Pick an ROE method from the list.")
    dc = (form.get("date_certain") or "").strip() or None
    if dc and not _sdate(dc):
        errors.append(f"Date certain '{dc}' isn't a real date — use YYYY-MM-DD or leave it blank.")
    roe = _num(form, "roe", "ROE", errors, lo=0, hi=20)
    eq = _num(form, "equity_ratio", "Equity ratio", errors, lo=0, hi=100)
    debt = _num(form, "cost_of_debt", "Cost of debt", errors, lo=0, hi=25)
    rb = _num(form, "rate_base", "Rate base", errors, lo=0, hi=1e6)
    opex = _num(form, "opex", "Operating expenses", errors, lo=-1e6, hi=1e6,
                required=False, default=0)
    depr = _num(form, "depreciation", "Depreciation", errors, lo=-1e6, hi=1e6,
                required=False, default=0)
    taxes = _num(form, "taxes", "Taxes", errors, lo=-1e6, hi=1e6,
                 required=False, default=0)
    risk = form.get("risk_level") or "unrated"
    if risk not in RISK_LABELS:
        errors.append("Pick a litigation-risk rating from the list.")
    adjs, aerrs = parse_adjustments(form.get("adjustments_text"))
    errors.extend(aerrs)
    if errors:
        return templates.TemplateResponse(request, "scenarios.html",
                                          {"request": request,
                                           **_scenario_ctx(db, case, errors, form)},
                                          status_code=400)
    s = Scenario(case_id=case.id, name=name, test_period_type=tp,
                 rate_base_method=rbm, date_certain=dc, roe_method=roem,
                 roe=roe, equity_ratio=eq, cost_of_debt=debt, rate_base=rb,
                 opex=opex, depreciation=depr, taxes=taxes, risk_level=risk,
                 risk_note=(form.get("risk_note") or "").strip() or None,
                 notes=(form.get("notes") or "").strip() or None)
    db.add(s)
    db.flush()
    for a in adjs:
        db.add(ScenarioAdjustment(scenario_id=s.id, **a))
    db.commit()
    return RedirectResponse(f"/cases/{case_id}/scenarios", status_code=303)


@app.post("/scenarios/{scenario_id}/risk")
async def scenario_set_risk(request: Request, scenario_id: int,
                            db: Session = Depends(get_db)):
    s = db.query(Scenario).filter(Scenario.id == scenario_id).first()
    if not s:
        return HTMLResponse("Scenario not found.", status_code=404)
    form = await request.form()
    risk = form.get("risk_level") or "unrated"
    if risk in RISK_LABELS:
        s.risk_level = risk
        s.risk_note = (form.get("risk_note") or "").strip() or None
        db.commit()
    return RedirectResponse(f"/cases/{s.case_id}/scenarios", status_code=303)


@app.post("/scenarios/{scenario_id}/delete")
def scenario_delete(scenario_id: int, db: Session = Depends(get_db)):
    s = db.query(Scenario).filter(Scenario.id == scenario_id).first()
    if not s:
        return HTMLResponse("Scenario not found.", status_code=404)
    case_id = s.case_id
    db.delete(s)
    db.commit()
    return RedirectResponse(f"/cases/{case_id}/scenarios", status_code=303)


def _coss_source(request, db, case):
    """Resolve the RR source for COSS pages: ?src=as_filed (default) or
    ?src=scenario:<id>. Returns (label, components dict, error)."""
    q = request.query_params.get("src", "as_filed")
    if q.startswith("scenario:"):
        try:
            sid = int(q.split(":", 1)[1])
        except ValueError:
            return None, None, "That scenario ID didn't parse - pick one from the list."
        s = db.query(Scenario).filter(Scenario.id == sid,
                                      Scenario.case_id == case.id).first()
        if not s:
            return None, None, "Pick one of this case's scenarios."
        return f"Scenario: {s.name}", rr_source_components(s), None
    pos = db.query(ThreeWayPosition).filter(
        ThreeWayPosition.case_id == case.id,
        ThreeWayPosition.stage == "as_filed").first()
    if not pos:
        return None, None, ("No as-filed position yet for this case - add one with the "
                            "positions template, or pick a scenario above.")
    return "As filed", rr_source_components(pos), None


def _coss_context(request, db, case):
    """Shared context for the COSS / rates / bills pages."""
    classes = sorted(case.customer_classes, key=lambda c: (c.sort_order or 0, c.name or ""))
    scenarios = db.query(Scenario).filter(Scenario.case_id == case.id).all()
    src_label, comp, src_error = _coss_source(request, db, case)
    alloc_errors = validate_coss_allocations(classes) if classes and not src_error else []
    class_rr = class_revenue_requirements(classes, comp) if comp and not alloc_errors else {}
    return {"request": request, "case": case, "classes": classes,
            "scenarios": scenarios, "src": request.query_params.get("src", "as_filed"),
            "src_label": src_label, "src_error": src_error,
            "alloc_errors": alloc_errors, "comp": comp, "class_rr": class_rr,
            "type_labels": TYPE_LABELS}


@app.get("/cases/{case_id}/coss", response_class=HTMLResponse)
def coss_page(request: Request, case_id: int, db: Session = Depends(get_db)):
    """Cost-of-service allocation: revenue requirement components by class."""
    case = db.query(Case).filter(Case.id == case_id).first()
    if not case:
        return HTMLResponse("Case not found.", status_code=404)
    ctx = _coss_context(request, db, case)
    ctx["coss_labels"] = COSS_LABELS
    return templates.TemplateResponse(request, "coss.html", ctx)


@app.get("/cases/{case_id}/rates", response_class=HTMLResponse)
def rates_page(request: Request, case_id: int, db: Session = Depends(get_db)):
    """Rate design: current vs proposed rates per class, with the proposed
    energy charge solved as the plug."""
    case = db.query(Case).filter(Case.id == case_id).first()
    if not case:
        return HTMLResponse("Case not found.", status_code=404)
    ctx = _coss_context(request, db, case)
    designed = {c.id: design_rates(c, ctx["class_rr"][c.id]["total"])
                for c in ctx["classes"] if c.id in ctx["class_rr"]}
    ctx["designed"] = designed
    return templates.TemplateResponse(request, "rates.html", ctx)


@app.get("/cases/{case_id}/bills", response_class=HTMLResponse)
def bills_page(request: Request, case_id: int, db: Session = Depends(get_db)):
    """Bill impacts: typical bills at low / typical / high usage per class."""
    case = db.query(Case).filter(Case.id == case_id).first()
    if not case:
        return HTMLResponse("Case not found.", status_code=404)
    ctx = _coss_context(request, db, case)
    impacts = {c.id: bill_impacts(c, ctx["class_rr"][c.id]["total"])
               for c in ctx["classes"] if c.id in ctx["class_rr"]}
    ctx["impacts"] = impacts
    return templates.TemplateResponse(request, "bills.html", ctx)


# ------------------------------------------------------------------ Executive
# insights: when to file, what to ask for.
#
# The C-suite asks two questions the workbench didn't answer. (1) What
# does delay cost? Every month without new rates forfeits 1/12 of the
# annual revenue increase — money that is gone forever, never recovered
# in a later case. (2) Which levers matter? Perturb each RR input by a
# standard increment and rank by dollar impact, so leadership aims
# testimony at the three biggest levers instead of tuning the model.

def _exec_inputs(src):
    """The seven RR inputs off a ThreeWayPosition or Scenario ($M / %)."""
    adj = sum(a.amount or 0 for a in getattr(src, "adjustments", None) or [])
    return {"rate_base": src.rate_base or 0, "equity_ratio": src.equity_ratio or 0,
            "roe": src.roe or 0, "cost_of_debt": src.cost_of_debt or 0,
            "opex": src.opex or 0, "depreciation": src.depreciation or 0,
            "taxes": src.taxes or 0, "adjustments": adj}


EXEC_LEVERS = [
    ("roe", "ROE", "+10 bps", lambda v: v + 0.10),
    ("equity_ratio", "Equity ratio", "+1 pt", lambda v: v + 1.0),
    ("rate_base", "Rate base", "+$100M", lambda v: v + 100.0),
    ("cost_of_debt", "Cost of debt", "+10 bps", lambda v: v + 0.10),
    ("opex", "O&M expense", "+$10M", lambda v: v + 10.0),
    ("depreciation", "Depreciation", "+$10M", lambda v: v + 10.0),
    ("taxes", "Taxes", "+$10M", lambda v: v + 10.0),
]


def lever_ranking(src):
    """Bump each lever by its standard increment, recompute RR through the
    shared engine, and rank by absolute dollar impact ($M)."""
    base = _exec_inputs(src)
    base_rr = rr_from_inputs(**base)
    rows = []
    for key, label, incr_label, bump in EXEC_LEVERS:
        bumped = dict(base)
        bumped[key] = bump(base[key])
        delta = rr_from_inputs(**bumped) - base_rr
        rows.append({"key": key, "label": label, "increment": incr_label,
                     "delta": delta})
    rows.sort(key=lambda r: abs(r["delta"]), reverse=True)
    return {"base_rr": base_rr, "inputs": base, "levers": rows}


def delay_analysis(src_rr, src_inputs, current_revenue, months):
    """Cost of waiting. If today's authorized revenue is known, each month
    of delay forfeits 1/12 of the annual increase. Always shows the
    foregone return on rate base as the profit lens."""
    ror = _ror(src_inputs["equity_ratio"], src_inputs["roe"],
               src_inputs["cost_of_debt"])
    foregone_monthly = (src_inputs["rate_base"] * ror) / 12.0
    out = {"src_rr": src_rr, "ror_pct": ror * 100.0,
           "foregone_return_monthly": foregone_monthly,
           "current_revenue": current_revenue, "months": months,
           "increase": None, "monthly": None, "rows": []}
    if current_revenue is not None:
        increase = src_rr - current_revenue
        monthly = increase / 12.0
        out["increase"] = increase
        out["monthly"] = monthly
        out["rows"] = [(m, m * monthly) for m in range(1, months + 1)]
    return out


@app.get("/cases/{case_id}/exec", response_class=HTMLResponse)
def exec_page(request: Request, case_id: int, db: Session = Depends(get_db)):
    """Executive insights: cost of regulatory delay + ranked RR levers."""
    case = db.query(Case).filter(Case.id == case_id).first()
    if not case:
        return HTMLResponse("Case not found.", status_code=404)
    af = _as_filed(db, case)
    scenarios = (db.query(Scenario).filter(Scenario.case_id == case.id)
                 .order_by(Scenario.id).all())
    q = request.query_params
    # Source: "as_filed" (default) or a scenario id.
    src_key = q.get("src", "as_filed")
    src, src_label, src_rr, src_inputs = None, "", None, None
    errors = []
    if src_key == "as_filed":
        src, src_label = af, "As filed"
    else:
        try:
            sid = int(src_key)
        except (TypeError, ValueError):
            sid = None
        src = next((s for s in scenarios if s.id == sid), None) if sid else None
        src_label = src.name if src else ""
        if not src:
            errors.append("Pick this case's as-filed position or one of its scenarios.")
    if src:
        src_inputs = _exec_inputs(src)
        if isinstance(src, Scenario):
            src_rr = scenario_math(src)["revenue_requirement"]
        else:
            src_rr = (af.revenue_requirement if af.revenue_requirement
                      else rr_from_inputs(**src_inputs))
    # Today's authorized revenue = as-filed RR minus the requested increase.
    current_revenue = None
    if (af and af.revenue_requirement not in (None, 0)
            and af.revenue_change not in (None, 0)):
        current_revenue = af.revenue_requirement - af.revenue_change
    try:
        months = int(q.get("months", 12))
    except (TypeError, ValueError):
        months = 12
    months = max(1, min(months, 60))
    delay = (delay_analysis(src_rr, src_inputs, current_revenue, months)
             if src else None)
    levers = lever_ranking(src) if src else None
    has_build = bool(src) and any(v for k, v in src_inputs.items()
                                  if k != "adjustments")
    return templates.TemplateResponse(request, "exec.html", {
        "request": request, "case": case, "as_filed": af,
        "scenarios": scenarios, "src_key": src_key, "src_label": src_label,
        "delay": delay, "levers": levers, "months": months,
        "has_build": has_build, "errors": errors,
        "q": {"src": src_key, "months": str(months)},
    })


@app.get("/riders", response_class=HTMLResponse)
def rider_list(request: Request, db: Session = Depends(get_db)):
    riders = (db.query(TariffRider).join(Utility)
              .order_by(Utility.name, TariffRider.name).all())
    return templates.TemplateResponse(request, "riders.html", {
        "request": request, "riders": riders, "disp_labels": DISP_LABELS,
        "rider_status_labels": RIDER_STATUS_LABELS})


@app.get("/charts", response_class=HTMLResponse)
def chart_page(request: Request, db: Session = Depends(get_db)):
    sector = request.query_params.get("sector", "all")
    if sector not in ("all", "electric", "gas"):
        sector = "all"
    cases = db.query(Case).all()
    if sector != "all":
        cases = [c for c in cases if (c.utility.sector or "electric") == sector]
    rev_groups, roe_groups = [], []
    for c in sorted(cases, key=lambda x: x.docket):
        pos = {p.stage: p for p in c.positions if not p.period or "TY1" in (p.period or "")}
        af, fn = pos.get("as_filed"), pos.get("final_or_stip")
        short = c.utility.name.replace(" Energy Ohio", "").replace(" Ohio", "")
        label = f"{short}"
        sub = c.docket.replace("-EL-AIR", "").replace("-GA-AIR", "")
        logo = UTILITY_LOGOS.get(c.utility.name)
        if af and af.revenue_change is not None and fn and fn.revenue_change is not None:
            rev_groups.append({"label": label, "sub": sub, "logo": logo,
                               "bars": [(af.revenue_change, charts.SLATE),
                                        (fn.revenue_change, charts.BLUE)]})
        if af and af.roe is not None and fn and fn.roe is not None:
            roe_groups.append({"label": label, "sub": sub, "logo": logo,
                               "bars": [(af.roe, charts.AMBER), (fn.roe, charts.GREEN)]})
    rev_svg = charts.grouped_bars(rev_groups, charts.money)
    roe_svg = charts.grouped_bars(roe_groups, charts.pct)
    return templates.TemplateResponse(request, "charts.html", {
        "request": request, "rev_svg": rev_svg, "roe_svg": roe_svg,
        "sector": sector,
        "rev_legend": charts.legend([(charts.SLATE, "As filed"), (charts.BLUE, "Final / stipulation")]),
        "roe_legend": charts.legend([(charts.AMBER, "Requested"), (charts.GREEN, "Authorized / settled")])})


@app.get("/benchmarks", response_class=HTMLResponse)
def benchmark_page(request: Request, db: Session = Depends(get_db)):
    """Phase 1: peer benchmarking — asked vs. granted, haircuts, and the
    Ohio landing zone, as a table the charts page can't show."""
    sector = request.query_params.get("sector", "all")
    if sector not in ("all", "electric", "gas"):
        sector = "all"
    rows, landing = benchmark_rows(db, sector)
    return templates.TemplateResponse(request, "benchmarks.html", {
        "request": request, "rows": rows, "landing": landing, "sector": sector})


@app.get("/deadlines", response_class=HTMLResponse)
def deadline_page(request: Request, db: Session = Depends(get_db)):
    """Phase 1: the deadline machine — every dated obligation across every
    case, overdue first, then upcoming."""
    today = date.today().isoformat()
    items = deadline_items(db)
    overdue = [i for i in items if (i["date"] or "9999") < today]
    upcoming = [i for i in items if (i["date"] or "9999") >= today]
    return templates.TemplateResponse(request, "deadlines.html", {
        "request": request, "overdue": overdue, "upcoming": upcoming,
        "today": today, "kind_labels": KIND_LABELS})


# ---------------------------------------------------------------- import

@app.get("/import", response_class=HTMLResponse)
def import_page(request: Request):
    return templates.TemplateResponse(request, "import.html", {
        "request": request, "templates": excel_templates.TEMPLATES})


@app.get("/templates/{kind}")
def download_template(kind: str):
    if kind not in excel_templates.TEMPLATES:
        return HTMLResponse("Unknown template.", status_code=404)
    filename, builder, _label = excel_templates.TEMPLATES[kind]
    buf = builder()
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@app.post("/import/{kind}", response_class=HTMLResponse)
async def upload_import(request: Request, kind: str, file: UploadFile = File(...),
                        db: Session = Depends(get_db)):
    if kind not in excel_import.VALIDATORS:
        return HTMLResponse("Unknown import type.", status_code=404)
    label = excel_templates.TEMPLATES[kind][2]
    try:
        raw = await file.read()
    except Exception:
        raw = b""
    if not raw:
        return templates.TemplateResponse(request, "import_result.html", {
            "request": request, "kind": kind, "label": label,
            "errors": ["That upload came through empty. Please choose an .xlsx file and try again."],
            "rows": [], "token": None})
    rows, errors = excel_import.VALIDATORS[kind](BytesIO(raw), db)
    if errors:
        return templates.TemplateResponse(request, "import_result.html", {
            "request": request, "kind": kind, "label": label,
            "errors": errors, "rows": [], "token": None})
    if not rows:
        return templates.TemplateResponse(request, "import_result.html", {
            "request": request, "kind": kind, "label": label,
            "errors": ["I didn't find any data rows to import. Fill in at least one row on the "
                       "'Data - fill this in' sheet (the example row doesn't count) and try again."],
            "rows": [], "token": None})
    token = uuid.uuid4().hex
    _pending_imports[token] = (kind, rows)
    return templates.TemplateResponse(request, "import_result.html", {
        "request": request, "kind": kind, "label": label,
        "errors": [], "rows": rows, "token": token})


@app.post("/import/{kind}/confirm", response_class=HTMLResponse)
def confirm_import(request: Request, kind: str, token: str = Form(...),
                   db: Session = Depends(get_db)):
    label = excel_templates.TEMPLATES.get(kind, ("", None, kind))[2]
    pending = _pending_imports.pop(token, None)
    if not pending or pending[0] != kind:
        return templates.TemplateResponse(request, "import_result.html", {
            "request": request, "kind": kind, "label": label,
            "errors": ["That import preview expired. Please upload the file again."],
            "rows": [], "token": None})
    _kind, rows = pending
    try:
        n = excel_import.LOADERS[_kind](db, rows)
    except Exception as e:  # never show a traceback to the user
        return templates.TemplateResponse(request, "import_result.html", {
            "request": request, "kind": kind, "label": label,
            "errors": [f"Something went wrong saving the data ({e}). Nothing was loaded. "
                       f"Please try again or check the file."],
            "rows": [], "token": None})
    return templates.TemplateResponse(request, "import_done.html", {
        "request": request, "label": label, "count": n})


@app.post("/seed")
def reseed(db: Session = Depends(get_db)):
    seed_module.seed()
    return RedirectResponse("/", status_code=303)
