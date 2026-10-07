"""Distribution Rate Case workbench (v1). Plain-language UI, Excel-first data entry."""
import os
import re
import uuid
from datetime import date, datetime, timedelta
from io import BytesIO

from fastapi import FastAPI, Request, Depends, UploadFile, File, Form
from fastapi.responses import HTMLResponse, StreamingResponse, RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

import hashlib

import database
from database import init_db, get_db
from models import (Utility, ServiceArea, Case, ThreeWayPosition, TariffRider, Document,
                    EarnedROE, DiscoveryRequest, ExpertWitness, Scenario, ScenarioAdjustment)
import seed as seed_module
import excel_templates
import excel_import
import charts

app = FastAPI(title="Rate Case Workbench")
templates = Jinja2Templates(directory=os.path.join(os.path.dirname(__file__), "templates"))

STAGE_LABELS = {"as_filed": "As filed", "staff": "Staff", "final_or_stip": "Final / stipulation"}
STATUS_LABELS = {"decided": "Decided", "pending": "In progress",
                 "stipulated": "Settlement filed - waiting on decision"}
TYPE_LABELS = {"historical": "Historical", "prospective": "Prospective"}
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
                      "is_model": u.name == MODEL_UTILITY})
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


def scenario_math(s):
    """Revenue requirement = rate base x overall return + O&M + depreciation
    + taxes + adjustments. Every methodology choice is a lever on this."""
    eq = (s.equity_ratio or 0) / 100.0
    ror = eq * (s.roe or 0) / 100.0 + (1 - eq) * (s.cost_of_debt or 0) / 100.0
    return_on_rb = (s.rate_base or 0) * ror
    adj_total = sum(a.amount or 0 for a in s.adjustments)
    rr = (return_on_rb + (s.opex or 0) + (s.depreciation or 0)
          + (s.taxes or 0) + adj_total)
    return {"ror_pct": ror * 100.0, "return_on_rb": return_on_rb,
            "adj_total": adj_total, "revenue_requirement": rr}


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


@app.get("/riders", response_class=HTMLResponse)
def rider_list(request: Request, db: Session = Depends(get_db)):
    riders = (db.query(TariffRider).join(Utility)
              .order_by(Utility.name, TariffRider.name).all())
    return templates.TemplateResponse(request, "riders.html", {
        "request": request, "riders": riders, "disp_labels": DISP_LABELS,
        "rider_status_labels": RIDER_STATUS_LABELS})


@app.get("/charts", response_class=HTMLResponse)
def chart_page(request: Request, db: Session = Depends(get_db)):
    cases = db.query(Case).all()
    rev_groups, roe_groups = [], []
    for c in sorted(cases, key=lambda x: x.docket):
        pos = {p.stage: p for p in c.positions if not p.period or "TY1" in (p.period or "")}
        af, fn = pos.get("as_filed"), pos.get("final_or_stip")
        short = c.utility.name.replace(" Energy Ohio", "").replace(" Ohio", "")
        label = f"{short}"
        sub = c.docket.replace("-EL-AIR", "")
        if af and af.revenue_change is not None and fn and fn.revenue_change is not None:
            rev_groups.append({"label": label, "sub": sub,
                               "bars": [(af.revenue_change, charts.SLATE),
                                        (fn.revenue_change, charts.BLUE)]})
        if af and af.roe is not None and fn and fn.roe is not None:
            roe_groups.append({"label": label, "sub": sub,
                               "bars": [(af.roe, charts.AMBER), (fn.roe, charts.GREEN)]})
    rev_svg = charts.grouped_bars(rev_groups, charts.money)
    roe_svg = charts.grouped_bars(roe_groups, charts.pct)
    return templates.TemplateResponse(request, "charts.html", {
        "request": request, "rev_svg": rev_svg, "roe_svg": roe_svg,
        "rev_legend": charts.legend([(charts.SLATE, "As filed"), (charts.BLUE, "Final / stipulation")]),
        "roe_legend": charts.legend([(charts.AMBER, "Requested"), (charts.GREEN, "Authorized / settled")])})


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
