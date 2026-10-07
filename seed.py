"""Seed the database from the v1 research files. Idempotent: safe to re-run.

Sources (no invented data; gaps left null and noted):
- dis-docs/extraction/electric-outcomes.md   (six decided electric cases)
- dis-docs/25-0958-EL-AIR/comparison.md     (AES prospective three-way + riders)
- dis-docs/26-0347-EL-AIR/as-filed-snapshot.md (FirstEnergy prospective as-filed)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import database
from database import init_db
from models import Utility, ServiceArea, Case, ThreeWayPosition, TariffRider, Document, EarnedROE, DiscoveryRequest, ExpertWitness


# Stock tickers for the dashboard/landing pages (display only).
TICKERS = {
    "AES Ohio": "NYSE: AES",
    "AEP Ohio": "Nasdaq: AEP",
    "Duke Energy Ohio (Electric)": "NYSE: DUK",
    "Duke Energy Ohio (Gas)": "NYSE: DUK",
    "FirstEnergy": "NYSE: FE",
    "Columbia Gas of Ohio": "NYSE: NI",
    "CenterPoint Energy Ohio": "NYSE: NFG",
    "Enbridge Gas Ohio": "NYSE: ENB",
}
PARENTS = {
    "AES Ohio": "AES Corporation",
    "AEP Ohio": "American Electric Power",
    "Duke Energy Ohio (Electric)": "Duke Energy",
    "Duke Energy Ohio (Gas)": "Duke Energy",
    "FirstEnergy": "FirstEnergy Corp.",
    "Columbia Gas of Ohio": "NiSource",
    "CenterPoint Energy Ohio": "National Fuel Gas Company",
    "Enbridge Gas Ohio": "Enbridge Inc.",
}


def get_or_create_utility(db, name, sector="electric"):
    u = db.query(Utility).filter(Utility.name == name).first()
    if not u:
        u = Utility(name=name, sector=sector)
        db.add(u)
        db.flush()
    ticker = TICKERS.get(name)
    if ticker and u.ticker != ticker:
        u.ticker = ticker
    parent = PARENTS.get(name)
    if parent and u.parent_company != parent:
        u.parent_company = parent
    return u


def get_or_create_case(db, docket, utility, **kw):
    c = db.query(Case).filter(Case.docket == docket).first()
    if not c:
        c = Case(docket=docket, utility_id=utility.id, **kw)
        db.add(c)
        db.flush()
    return c


def upsert_position(db, case, stage, period=None, **kw):
    q = db.query(ThreeWayPosition).filter(
        ThreeWayPosition.case_id == case.id,
        ThreeWayPosition.stage == stage,
        ThreeWayPosition.period == period,
    )
    p = q.first()
    if not p:
        p = ThreeWayPosition(case_id=case.id, stage=stage, period=period)
        db.add(p)
    for k, v in kw.items():
        setattr(p, k, v)
    return p


def upsert_rider(db, utility, name, **kw):
    r = db.query(TariffRider).filter(
        TariffRider.utility_id == utility.id, TariffRider.name == name
    ).first()
    if not r:
        r = TariffRider(utility_id=utility.id, name=name)
        db.add(r)
    for k, v in kw.items():
        setattr(r, k, v)
    return r


def upsert_earned_roe(db, utility, year, earned_roe, source, notes=None):
    rec = db.query(EarnedROE).filter(
        EarnedROE.utility_id == utility.id, EarnedROE.year == year).first()
    if not rec:
        rec = EarnedROE(utility_id=utility.id, year=year)
        db.add(rec)
        db.flush()  # make the pending row visible to the next upsert's query
    rec.earned_roe = earned_roe
    rec.source = source
    rec.notes = notes
    return rec


def upsert_document(db, case, doc_type, **kw):
    d = db.query(Document).filter(
        Document.case_id == case.id, Document.doc_type == doc_type
    ).first()
    if not d:
        d = Document(case_id=case.id, docket=case.docket, doc_type=doc_type)
        db.add(d)
    for k, v in kw.items():
        setattr(d, k, v)
    return d


def upsert_discovery(db, case, request_type, requesting_party, set_number, number, **kw):
    """Natural key: case + type + party + set + number."""
    r = db.query(DiscoveryRequest).filter(
        DiscoveryRequest.case_id == case.id,
        DiscoveryRequest.request_type == request_type,
        DiscoveryRequest.requesting_party == (requesting_party or None),
        DiscoveryRequest.set_number == (set_number or None),
        DiscoveryRequest.number == (number or None),
    ).first()
    if not r:
        r = DiscoveryRequest(case_id=case.id, request_type=request_type,
                             requesting_party=requesting_party, set_number=set_number,
                             number=number)
        db.add(r)
        db.flush()  # make the pending row visible to the next upsert's query
    for k, v in kw.items():
        setattr(r, k, v)
    return r


def upsert_expert(db, case, name, **kw):
    e = db.query(ExpertWitness).filter(
        ExpertWitness.case_id == case.id, ExpertWitness.name == name
    ).first()
    if not e:
        e = ExpertWitness(case_id=case.id, name=name)
        db.add(e)
        db.flush()  # make the pending row visible to the next upsert's query
    for k, v in kw.items():
        setattr(e, k, v)
    return e


def seed():
    init_db()
    db = database.SessionLocal()

    # ---- Utilities & service areas ----
    aep = get_or_create_utility(db, "AEP Ohio")
    # Duke Energy Ohio is split into separate gas and electric utilities.
    # The pre-split "Duke Energy Ohio" row (electric cases) is renamed in place.
    old_duke = db.query(Utility).filter(Utility.name == "Duke Energy Ohio").first()
    if old_duke:
        old_duke.name = "Duke Energy Ohio (Electric)"
        db.flush()
    duke_elec = get_or_create_utility(db, "Duke Energy Ohio (Electric)")
    duke_gas = get_or_create_utility(db, "Duke Energy Ohio (Gas)", sector="gas")
    aes = get_or_create_utility(db, "AES Ohio")
    fe = get_or_create_utility(db, "FirstEnergy")
    centerpoint = get_or_create_utility(db, "CenterPoint Energy Ohio", sector="gas")
    # Ownership changed 2026-10-01: CenterPoint Energy sold its Ohio gas business to
    # National Fuel Gas Company (NYSE: NFG) for $2.62B - $1.42B cash plus a $1.20B
    # promissory note at 6.5%. All approvals are complete, including PUCO review.
    # Legal entity is now National Fuel Gas Distribution of Ohio, LLC (formerly
    # Vectren Energy Delivery of Ohio, LLC d/b/a CenterPoint Energy Ohio, tariff
    # P.U.C.O. No. 5). Footprint: ~335k customers, ~5,900 miles of pipeline,
    # 16 counties (Dayton/Miami Valley). Source: PR Newswire via Morningstar,
    # 10/01/2026.
    centerpoint.notes = ("Closed 10/01/2026: CenterPoint Energy sold its Ohio gas "
                         "business to National Fuel Gas Company (NYSE: NFG) for "
                         "$2.62B ($1.42B cash + $1.20B promissory note at 6.5%). "
                         "Legal entity: National Fuel Gas Distribution of Ohio, LLC "
                         "(formerly Vectren Energy Delivery of Ohio, LLC d/b/a "
                         "CenterPoint Energy Ohio; tariff P.U.C.O. No. 5). Footprint: "
                         "~335k customers, ~5,900 miles of pipeline, 16 counties "
                         "(Dayton/Miami Valley). All approvals complete, including "
                         "PUCO review. Source: PR Newswire via Morningstar, "
                         "10/01/2026.")
    # "Dominion Energy Ohio" no longer exists: the utility is The East Ohio Gas
    # Company d/b/a Enbridge Gas Ohio (parent Enbridge Inc.). Rename in place.
    old_dom = db.query(Utility).filter(Utility.name == "Dominion Energy Ohio").first()
    if old_dom:
        old_dom.name = "Enbridge Gas Ohio"
        db.flush()
    enbridge = get_or_create_utility(db, "Enbridge Gas Ohio", sector="gas")
    for sa_name in ["Ohio Edison", "The Cleveland Electric Illuminating Company",
                    "The Toledo Edison Company"]:
        if not db.query(ServiceArea).filter(
            ServiceArea.utility_id == fe.id, ServiceArea.name == sa_name
        ).first():
            db.add(ServiceArea(utility_id=fe.id, name=sa_name))

    # ---- 25-0392-EL-AIR : AEP Ohio (historical, decided 4/1/2026) ----
    c = get_or_create_case(db, "25-0392-EL-AIR", aep, case_type="historical",
                           status="decided", date_order="2026-04-01",
                           notes="Settlement adopted.")
    upsert_position(db, c, "as_filed", revenue_change=405.2, roe=10.9,
                    notes="As recited in O&O: +$405,215,077 (~41%); overall return 7.64%; "
                          "net $97.4M base-rate increase after rider roll-ins.")
    upsert_position(db, c, "staff", revenue_change=288.0, roe=9.59,
                    notes="Midpoint of Staff recommendation; Staff ROE range 9.33-9.84%.")
    upsert_position(db, c, "final_or_stip", revenue_requirement=1300.0, revenue_change=320.1,
                    roe=9.84, capital_structure="49.12% debt / 50.88% equity",
                    notes="Gross +$320.1M is mostly rider roll-ins; NET new base-rate revenue "
                          "is +$11.1M. With $105M excess-ADIT credit over 18 months the net "
                          "customer effect is a decrease during the refund period. LT debt cost 4.27%.")
    upsert_document(db, c, "order", page_count=76)

    # ---- 20-585-EL-AIR : AEP Ohio (historical, decided 11/17/2021) ----
    c = get_or_create_case(db, "20-585-EL-AIR", aep, case_type="historical",
                           status="decided", date_order="2021-11-17",
                           notes="Settlement adopted.")
    upsert_position(db, c, "as_filed", revenue_change=42.281, roe=10.15,
                    notes="As recited in O&O: +$42.281M (+3.5% avg annual total revenue); ROR 7.90%.")
    upsert_position(db, c, "staff", revenue_change=247.45, roe=9.27,
                    notes="Midpoints of Staff ranges (increase $237.2M-$257.7M; ROE 8.76-9.78%). "
                          "Note basis mismatch: net of rider roll-ins, Staff's recommendation "
                          "is a net DECREASE of $122.6M-$102.1M.")
    upsert_position(db, c, "final_or_stip", revenue_requirement=955.101, revenue_change=294.729,
                    roe=9.7, capital_structure="45.57% debt / 54.43% equity",
                    rate_base=3088.389,
                    notes="Overall ROR 7.28%; LT debt cost 4.4%. Residential customer charge "
                          "$14/mo as-filed -> $10/mo stipulated.")
    upsert_document(db, c, "order", page_count=95)

    # ---- 21-0887-EL-AIR : Duke Energy Ohio (historical, decided 12/14/2022) ----
    c = get_or_create_case(db, "21-0887-EL-AIR", duke_elec, case_type="historical",
                           status="decided", date_order="2022-12-14",
                           notes="Joint stipulation adopted.")
    upsert_position(db, c, "as_filed", revenue_change=54.7, roe=10.3,
                    notes="As recited in O&O: +$54.7M (+10% avg annual total revenue; ~3.3% "
                          "total-bill increase); ROR 7.26%.")
    upsert_position(db, c, "staff", revenue_change=8.57, roe=9.345,
                    notes="Midpoints of Staff ranges (increase $1.86M-$15.28M; ROE 8.84-9.85%).")
    upsert_position(db, c, "final_or_stip", revenue_requirement=578.116, revenue_change=22.594,
                    roe=9.5, capital_structure="50.50% equity / 49.50% LT debt",
                    rate_base=2037.893,
                    notes="Overall ROR 6.86%; below Duke's then-current authorized ROE of 9.84%.")
    upsert_document(db, c, "order", page_count=103)

    # ---- 17-0032-EL-AIR : Duke Energy Ohio (historical, decided 12/19/2018) ----
    c = get_or_create_case(db, "17-0032-EL-AIR", duke_elec, case_type="historical",
                           status="decided", date_order="2018-12-19",
                           notes="Global settlement of 10 cases incl. ESP; outcome was a net decrease.")
    upsert_position(db, c, "as_filed", revenue_change=15.4,
                    notes="As recited in O&O: +$15.4M (+3.18% over current revenues); "
                          "proposed ROR 7.82%. As-filed ROE not stated in O&O.")
    upsert_position(db, c, "staff", revenue_change=-23.65, roe=9.73,
                    notes="Midpoints of Staff ranges (decrease $18.36M-$28.93M; ROE 9.22-10.24%).")
    upsert_position(db, c, "final_or_stip", revenue_change=-19.0, roe=9.84,
                    notes="Reduction in base distribution revenue of OVER $19M. Stipulated ROE "
                          "9.84%; capital structure not stated in O&O. Secondary reports cite "
                          "a 7.54% overall rate of return and a ~$1.57/mo typical-residential "
                          "(1,000 kWh) bill increase - not shown on the docket card.")
    upsert_document(db, c, "order", page_count=119)
    c.date_filed = "2017-01-31"

    # Research refinements for 21-0887 (verified 2026-10-01 via tariff Sheet 85 footer).
    c21887 = db.query(Case).filter(Case.docket == "21-0887-EL-AIR").first()
    if c21887:
        c21887.date_filed = "2021-09-01"
        if "Sheet 85" not in (c21887.notes or ""):
            c21887.notes = ((c21887.notes or "") +
                            " Order date confirmed by tariff Sheet 85 footer: 'Filed pursuant "
                            "to an Order dated December 14, 2022 in Case No. 21-0887-EL-AIR'.")

    # ---- 26-0132-EL-AIR : Duke Energy Ohio (Electric) (pending base rate case) ----
    # Verified on DIS 2026-10-01. Revenue figure is secondary-source only.
    c = get_or_create_case(db, "26-0132-EL-AIR", duke_elec, case_type="historical",
                           status="pending", date_filed="2026-02-27",
                           date_staff_report="2026-09-21",
                           notes="Staff Report filed 9/21/2026. Local public hearings scheduled "
                                 "12/1/2026 and 12/10/2026 (Middletown, Cincinnati, Hamilton).")
    upsert_position(db, c, "as_filed", revenue_change=90.0,
                    notes="UNVERIFIED revenue figure: ~$90M annual per openratebase summary; "
                          "OCC factsheet reports Duke seeks ~38% increase in distribution "
                          "charges (~$8.32/month for a typical residential customer). Neither "
                          "figure appears on the DIS docket card.")
    upsert_position(db, c, "staff",
                    notes="Staff Report filed 9/21/2026; figures not extracted yet.")

    # ---- Duke Energy Ohio (Electric) rider inventory ----
    # From the electric tariff's "Sheet No. 85 - Applicable Riders" (Rev. 85.2);
    # every authority docket verified on its DIS case-record card 2026-10-01.
    for name, auth, extra in [
        ("Rider ETCJA - Electric Tax Cuts and Jobs Act Rider", "18-1186-EL-ATA",
         "F&O 2/20/2019 approving TCJA tariff."),
        ("Rider ESRR - Electric Service Reliability Rider", "25-0014-EL-RDR",
         "Entry 5/28/2025 (vegetation management cost recovery)."),
        ("Rider PF - Power Future Initiatives Rider", "25-0154-EL-RDR",
         "F&O 3/18/2026 (Phase IV)."),
        ("Rider USR - Universal Service Fund Rider", "25-0607-EL-USF",
         "Statewide USF case (Ohio Dept. of Development); O&O 12/17/2025; Duke USR "
         "tariff pages eff. 1/2026 filed in it. Duke's own 23-0454-EL-USF was voided."),
        ("Rider UE-GEN - Uncollectible Expense, Electric Generation", "26-0699-EL-UEX",
         "Opened 6/30/2026 to adjust the UE-GEN rate."),
        ("Rider BTR - Base Transmission Rider", "26-0719-EL-RDR",
         "F&O 9/17/2026."),
        ("Rider SGF - Solar Generation Fund Rider", "25-0547-EL-RDR",
         "Rate set to $0 effective 8/14/2025 per 8/6/2025 Entry (subject to final "
         "reconciliation); still listed as an applicable rider."),
        ("Rider DSR - Distribution Storm Rider", "24-0072-EL-RDR",
         "F&O 10/2/2024 (major storm expense recovery)."),
        ("Rider DCI - Distribution Capital Investment Rider", "24-0637-EL-RDR",
         "Annual review case (audit of 7/1/2023-6/30/2024 costs)."),
        ("Rider DR-ECF - Economic Competitiveness Fund Rider", "17-1263-EL-SSO",
         "Duke's 2017 ESP/SSO case; OMA 2024 summary cites it for the DR-ECF charge "
         "effective 7/1/2020."),
        ("Rider UE-ED - Uncollectible Expense, Electric Distribution", "26-0698-EL-UEX",
         "Opened 6/30/2026 to set the UE-ED rate."),
        ("Rider AER-R - Alternative Energy Recovery Rider", "22-1063-EL-RDR",
         "Opened 12/1/2022."),
        ("Rider RC - Retail Capacity Rider", "24-0278-EL-SSO",
         "Current SSO case, status OPEN (RC/RE/SCR tariff updates filed here)."),
        ("Rider RE - Retail Energy Rider", "24-0278-EL-SSO",
         "Same SSO case as RC."),
        ("Rider SCR - Supplier Cost Reconciliation Rider", "24-0278-EL-SSO",
         "Same SSO case as RC."),
        ("Rider EE-PDRR - Energy Efficiency and Peak Demand Response Recovery Rate",
         "16-0576-EL-POR",
         "EE/PDR portfolio case; later applications 19-0678-EL-POR (voided), "
         "20-1013-EL-POR and 24-0045-EL-POR (withdrawn) did not supersede it."),
        ("Rider DDR - Distribution Decoupling Rider", "24-0141-EL-RDR",
         "F&O 10/15/2024."),
        ("Rider PSR - Price Stabilization Rider", "17-0032-EL-AIR",
         "Non-bypassable OVEC rider; continued by the 12/19/2018 order in the "
         "electric base rate case."),
        ("Rider LGR - Legacy Generation Rider", "25-0547-EL-RDR",
         "Rate set to $0 effective 8/14/2025 per 8/6/2025 Entry (subject to final "
         "reconciliation); still listed as an applicable rider."),
    ]:
        upsert_rider(db, duke_elec, name, kind="rider", status="effective",
                     disposition="undecided", authority_docket=auth, notes=extra)
    # OET: statutory pass-through; original authority docket could not be verified.
    upsert_rider(db, duke_elec, "Rider OET - Ohio Excise Tax Rider", kind="rider",
                 status="effective", disposition="undecided", authority_docket=None,
                 notes="Statutory kWh-tax pass-through (R.C. 5727.81) in effect since the "
                       "early 2000s. Original authority docket could not be verified - not "
                       "invented.")

    # ---- 24-1009-EL-AIR : AES Ohio (historical, decided 11/5/2025) ----
    c = get_or_create_case(db, "24-1009-EL-AIR", aes, case_type="historical",
                           status="decided", date_order="2025-11-05",
                           notes="Settlement adopted. Date certain 9/30/2024; test year 6/1/2024-5/31/2025.")
    upsert_position(db, c, "as_filed", revenue_requirement=547.115, revenue_change=235.2,
                    notes="Implied increase ~$235.2M; ROR 7.97%. As-filed ROE not stated in O&O. "
                          "As-filed residential customer charge $22.12/mo.")
    upsert_position(db, c, "staff",
                    notes="No explicit Staff revenue or ROE figure in O&O; only that the "
                          "stipulation is 'only slightly higher' than Staff's proposed range.")
    upsert_position(db, c, "final_or_stip", revenue_requirement=483.123, revenue_change=167.966,
                    roe=9.999, capital_structure="46.13% LT debt / 53.87% common equity",
                    rate_base=1252.369,
                    notes="Overall ROR 7.46%; LT debt cost 4.49%. Residential customer charge "
                          "held at $9.75/mo; $25 reconnection fee eliminated. $36M prepaid "
                          "pension excluded from rate base per Staff.")
    upsert_document(db, c, "order", page_count=23)

    # ---- 20-1651-EL-AIR : AES Ohio (historical, decided 12/14/2022) ----
    c = get_or_create_case(db, "20-1651-EL-AIR", aes, case_type="historical",
                           status="decided", date_order="2022-12-14",
                           notes="Contested case (no stipulation).")
    upsert_position(db, c, "as_filed", revenue_change=120.8, roe=10.5,
                    notes="As recited in O&O: +$120.8M (+49.4% over test-year operating "
                          "revenues); ROR 7.71%.")
    upsert_position(db, c, "staff", revenue_change=67.05,
                    notes="Midpoint of amended Staff range ($64.27M-$69.82M). Staff recommended "
                          "against 10.5% ROE; no Staff ROE figure stated.")
    upsert_position(db, c, "final_or_stip", revenue_requirement=320.560, revenue_change=75.617,
                    roe=9.999, capital_structure="53.87% equity / 46.13% debt",
                    rate_base=783.478,
                    notes="Overall ROR 7.43%; LT debt cost 4.4%. PROVISIONAL ONLY - ESP I rate "
                          "freeze barred implementation; no new tariffs effective under this order.")
    upsert_document(db, c, "order", page_count=92)

    # ---- 25-0958-EL-AIR : AES Ohio (PROSPECTIVE, stipulated - no final order) ----
    c = get_or_create_case(
        db, "25-0958-EL-AIR", aes, case_type="prospective", status="stipulated",
        date_filed="2025-11-10", date_staff_report="2026-05-19",
        test_year="TY1 CY2027; TY2 CY2028; TY3 CY2029",
        notes="First HB 15 forecasted-test-period TYRP (R.C. 4909.15(C)(1)(a) + 4909.18). "
              "Stipulation filed 7/21/2026; Commission decision outstanding. "
              "13-month average rate bases. Companions: 25-0959-EL-AAM, 25-0960-EL-ATA, 25-0961-EL-RDR.")
    ty = [("TY1 2027", 657.47, 169.82, 612.43, 113.85, 643.86 - 0, 0, 622.53, 123.95,
           1773.20, 1775.95, 1801.83),
          ("TY2 2028", 700.51, 41.38, 643.86, 28.39, 0, 0, 656.15, 30.52,
           1953.13, 1934.03, 1960.86),
          ("TY3 2029", 727.56, 26.25, 667.91, 22.27, 0, 0, 679.31, 21.34,
           2092.41, 2055.64, 2083.30)]
    for (per, f_rr, f_ch, s_rr, s_ch, _s2, _s3, t_rr, t_ch, f_rb, s_rb, t_rb) in ty:
        upsert_position(db, c, "as_filed", period=per, revenue_requirement=f_rr,
                        revenue_change=f_ch, roe=10.10, capital_structure="~52% equity (implied)",
                        rate_base=f_rb,
                        notes="~$94.5M of the 2027 deficiency is ESP rider roll-in, not new money.")
        upsert_position(db, c, "staff", period=per, revenue_requirement=s_rr,
                        revenue_change=s_ch, roe=9.40, capital_structure="50% equity / 50% debt",
                        rate_base=s_rb, notes="Staff ROE range 9.15-9.66.")
        upsert_position(db, c, "final_or_stip", period=per, revenue_requirement=t_rr,
                        revenue_change=t_ch, roe=9.50,
                        capital_structure="Equity cap glide: 53.37 / 52.00 / 50.50",
                        rate_base=t_rb,
                        notes="Stipulation (7/21/2026): ROE 9.50% reset annually before PIMs; "
                              "pension asset partially restored (+$25M/$26M/$27M savings-generating "
                              "portion). No final order yet.")
    base = os.path.expanduser("~/workspace/rate-case-app/dis-docs/25-0958-EL-AIR")
    upsert_document(db, c, "application", page_count=20,
                    file_path=os.path.join(base, "application.pdf"))
    upsert_document(db, c, "staff_report", page_count=384,
                    file_path=os.path.join(base, "staff-report.pdf"))
    upsert_document(db, c, "stipulation", page_count=66,
                    file_path=os.path.join(base, "stipulation.pdf"))
    # Verified 2026-10-01 from current aes-ohio.com tariff sheets' "Filed pursuant
    # to" lines; every docket confirmed on PUCO DIS. Caveats: Tax Savings Credit
    # cites 24-1009-EL-AIR as the most recent authorizing docket, not the rider's
    # original 2018 federal-tax-reform establishment; True-Up's docket is
    # open/pending with no tariff sheet yet.
    aes_rider_authority = {
        "Rider DIR": ("22-0900-EL-SSO", "D36, 5th rev, eff. 7-1-2026; ESP IV O&O 8/9/2023"),
        "Rider IIR": ("21-1110-EL-RDR", "D29, 6th rev, eff. 7-1-2026; F&O 2/23/2022"),
        "Rider PRO": ("22-0900-EL-SSO", "D32, 5th rev, eff. 4-1-2026; ESP IV O&O 8/9/2023"),
        "Customer Programs Rider": ("22-0900-EL-SSO", "D37, 4th rev, eff. 6-1-2026; ESP IV O&O 8/9/2023"),
        "Rider SCRR": ("22-0900-EL-SSO", "D30, 4th rev, eff. 6-1-2026; ESP IV O&O 8/9/2023"),
        "Rider RCR": ("22-0900-EL-SSO", "D31, 2nd rev, eff. 9-1-2023; ESP IV O&O 8/9/2023"),
        "Energy Efficiency Rider": ("17-1398-EL-POR", "D38; EE/PDR portfolio plan F&O 12/30/2020"),
    }
    for rider in ["Rider DIR", "Rider IIR", "Rider PRO", "Customer Programs Rider",
                  "Rider SCRR", "Rider RCR", "Energy Efficiency Rider"]:
        auth, src = aes_rider_authority[rider]
        upsert_rider(db, aes, rider, kind="rider", status="terminated",
                     disposition="roll_into_base", authority_docket=auth,
                     notes="Rolled into base rates 1/1/2027 upon ESP termination (R.C. 4928.1410); "
                           "rates set to zero. Part of ~$94.5M roll-in. "
                           f"Authority {auth} per current tariff sheet ({src}).")
    upsert_rider(db, aes, "Tax Savings Credit Rider", kind="rider", status="effective",
                 disposition="standalone", authority_docket="24-1009-EL-AIR",
                 notes="Continues under stipulation. Most recent authorizing docket "
                       "per D41 (8th rev, eff. 11-6-2025; O&O 11/5/2025), not the rider's "
                       "original establishment.")
    upsert_rider(db, aes, "Economic Development Rider", kind="rider", status="effective",
                 disposition="standalone", authority_docket="23-0279-EL-RDR",
                 notes="Continues under stipulation. Authority 23-0279-EL-RDR per D39 "
                       "(2nd rev, eff. 9-1-2023; F&O 5/17/2023).")
    upsert_rider(db, aes, "True-Up Rider", kind="rider", status="proposed",
                 disposition="undecided", authority_docket="25-0961-EL-RDR",
                 notes="Stipulated true-up vehicle; first true-up proceeding no later than "
                       "5/1/2028. Docket 25-0961-EL-RDR is open/pending (joint application "
                       "11/10/2025 with 25-0958-EL-AIR, -0959, -0960); no tariff sheet yet.")

    # ---- 26-0347-EL-AIR : FirstEnergy OE/CEI/TE (PROSPECTIVE, as-filed only) ----
    c = get_or_create_case(
        db, "26-0347-EL-AIR", fe, case_type="prospective", status="pending",
        date_filed="2026-05-22",
        test_year="TY1 7/1/2027-6/30/2028; TY2 7/1/2028-6/30/2029; TY3 7/1/2029-6/30/2030",
        notes="Three-year rate plan (TYRP) under R.C. 4909.18. DIS Date Opened 4/22/2026 "
              "reflects the pre-filing notice; application filed 5/22/2026 and deemed "
              "complete 7/1/2026. NO Staff Report yet. 13-month average rate bases "
              "(June-June). Companions: 26-0348-EL-ATA, 26-0349-EL-AAM, 26-0350-EL-UNC. "
              "Joint filing for Ohio Edison, CEI, and Toledo Edison. Recent activity: "
              "third-party intervention motions (Sept 2026).")
    # Rate bases per FirstEnergy's own as-filed materials (IR summary
    # Ohio-2026-TYRP.pdf, 5/30/2026 for TY1; RateBase citing FE's spring 2026
    # investor update for OE TY2/TY3). ROE 10.20%, 53% equity, all companies.
    fe_filed = [
        ("Ohio Edison", "TY1", 848.4, 99.8, 5100), ("Ohio Edison", "TY2", None, 27.8, 5500),
        ("Ohio Edison", "TY3", None, 36.2, 5900),
        ("CEI", "TY1", 769.8, 121.4, 4500), ("CEI", "TY2", None, 17.0, None),
        ("CEI", "TY3", None, 26.1, None),
        ("Toledo Edison", "TY1", 236.9, 32.8, 1500), ("Toledo Edison", "TY2", None, 14.0, None),
        ("Toledo Edison", "TY3", None, 17.1, None),
    ]
    for co, per, rr, ch, rb in fe_filed:
        rb_note = (f" Rate base ${rb/1000:.1f}B ({per}) per FE IR summary Ohio-2026-TYRP.pdf "
                   "(5/30/2026)." if rb and per == "TY1" else
                   (f" Rate base ${rb/1000:.1f}B ({per}) per RateBase citing FE spring 2026 "
                    "investor update." if rb else
                    " Rate base not yet published for this rate year."))
        upsert_position(db, c, "as_filed", period=f"{co} {per}",
                        revenue_requirement=rr, revenue_change=ch, roe=10.20,
                        equity_ratio=53.0, rate_base=rb,
                        capital_structure="53% equity / 47% debt",
                        notes=f"As-filed {co}. ROE 10.20% on 53% equity. "
                              f"No Staff Report yet.{rb_note}")
    upsert_document(db, c, "application", page_count=21,
                    file_path=os.path.expanduser(
                        "~/workspace/rate-case-app/dis-docs/26-0347-EL-AIR/application.pdf"))
    # One-time rename of the short rider names seeded before 2026-10-01.
    for short, full in [("Rider AMI", "Advanced Metering Infrastructure / Modern Grid"),
                        ("Rider DCR", "Delivery Capital Recovery"),
                        ("Rider DUN", "Distribution Uncollectible"),
                        ("Rider PUR", "PIPP Uncollectible")]:
        rr = db.query(TariffRider).filter(TariffRider.utility_id == fe.id,
                                          TariffRider.name == short).first()
        if rr:
            rr.name = full
            db.flush()
    for rider, auth in [("Advanced Metering Infrastructure / Modern Grid", "25-1105-EL-RDR"),
                        ("Delivery Capital Recovery", "25-0929-EL-RDR"),
                        ("Distribution Uncollectible", "25-1104-EL-RDR"),
                        ("PIPP Uncollectible", "25-1104-EL-RDR")]:
        upsert_rider(db, fe, rider, kind="rider", status="proposed",
                     disposition="roll_into_base", authority_docket=auth,
                     notes="ESP IV rider proposed to roll into base rates and reset to zero "
                           f"in 26-0347-EL-AIR. Authority: {auth}.")

    # ---- 24-0468-EL-AIR : FirstEnergy (prior base case; positions not yet extracted) ----
    c46 = get_or_create_case(db, "24-0468-EL-AIR", fe, case_type="historical", status="decided",
                             date_filed="2024-05-31", date_order="2025-11-19",
                             notes="Prior joint base rate case (OE/CEI/TE). Positions not yet "
                                   "extracted into the app.")
    # DIS status nuance: after the 4th Entry on Rehearing (06/10/2026) the case was
    # appealed to the Supreme Court of Ohio (No. 2026-1056, notice filed 08/10/2026),
    # so DIS shows it OPEN-OPEN on appeal; Commission orders are issued.
    c46.notes = ("Prior joint base rate case (OE/CEI/TE). Positions not yet extracted into "
                 "the app. DIS shows OPEN-OPEN: appealed to the Supreme Court of Ohio "
                 "(No. 2026-1056, notice 08/10/2026) after the 4th Entry on Rehearing "
                 "(06/10/2026); Commission orders are issued.")

    # ---- FirstEnergy Ohio: current tariff rider inventory ----
    # From the 2026 tariff books (OE P.U.C.O. No. 11, CEI No. 13, TE No. 8), riders
    # table of contents; authority dockets verified on DIS 2026-10-01. Riders whose
    # most recent authorizing docket could not be identified carry no authority
    # docket (never invented). operating_company is set only where a rider is
    # company-specific; blank = all three Ohio operating companies.
    _ROLLIN = {"Advanced Metering Infrastructure / Modern Grid",
               "Delivery Capital Recovery", "Distribution Uncollectible",
               "PIPP Uncollectible"}  # already seeded above as proposed/roll_into_base
    for name, opco, auth, extra in [
        ("Partial Service", "Ohio Edison", None, "Sheet 24."),
        ("Summary", None, None, "Sheet 80."),
        ("Residential Distribution Credit", None, None, "Sheet 81."),
        ("Transmission and Ancillary Services", None, None, "Sheet 83."),
        ("Alternative Energy Resource", None, "25-1136-EL-RDR",
         "Rider AER tariff update filed 12/02/2025."),
        ("School Distribution Credit", None, None, "Sheet 85."),
        ("Business Distribution Credit", None, None, "Sheet 86."),
        ("Hospital Net Energy Metering", None, None, "Sheet 87."),
        ("Economic Development (4a)", "The Toledo Edison Company", None, "Sheet 88."),
        ("Peak Time Rebate Program", "The Illuminating Company", None, "Sheet 88."),
        ("Residential Critical Peak Pricing", "The Illuminating Company", None, "Sheet 89."),
        ("Percentage of Income Payment Plan Rider", None, None, "Sheet 90."),
        ("Tax Savings Adjustment", None, "25-1107-EL-RDR",
         "Rider TSA update filed 11/26/2025."),
        ("State kWh Tax", None, None, "Sheet 92."),
        ("Net Energy Metering", None, None, "Sheet 93/94."),
        ("Grandfathered Contract", "The Illuminating Company", None, "Sheet 94."),
        ("Delta Revenue Recovery", None, "25-1109-EL-RDR",
         "Update to Riders DRR et al. filed 11/26/2025."),
        ("Demand Side Management", None, None, "Sheet 97."),
        ("Reasonable Arrangement", None, None, "Sheet 98."),
        ("Economic Load Response Program", None, None, "Sheet 101."),
        ("Generation Cost Reconciliation", None, "25-1104-EL-RDR",
         "Rider GCR update filed 12/02/2025."),
        ("Fuel", None, None, "Sheet 105."),
        ("Line Extension Cost Recovery", None, None, "Sheet 107."),
        ("Delivery Service Improvement", None, None, "Sheet 108."),
        ("Non-Distribution Uncollectible", None, "25-1104-EL-RDR",
         "Rider NDU update filed 12/02/2025."),
        ("Experimental Real Time Pricing", None, "25-1109-EL-RDR", "Rider RTP."),
        ("CEI Delta Revenue Recovery", "The Illuminating Company", None, "Sheet 112."),
        ("Experimental Critical Peak Pricing", None, "25-1109-EL-RDR", "Rider CPP."),
        ("Generation Service", None, "26-0543-EL-RDR",
         "Rider GEN update; F&O 05/27/2026."),
        ("Demand Side Management and Energy Efficiency", None, "25-1106-EL-RDR",
         "Rider DSE tariff update filed 11/26/2025."),
        ("Economic Development", None, "25-1104-EL-RDR",
         "Rider EDR update filed 12/02/2025."),
        ("Deferred Generation Cost Recovery", None, None, "Sheet 117."),
        ("Deferred Fuel Cost Recovery", None, None, "Sheet 118."),
        ("Non-Market-Based Services", None, "26-0035-EL-RDR",
         "Rider NMB update; F&O 03/18/2026, rehearing entry 05/13/2026."),
        ("Residential Deferred Distribution Cost Recovery", None, None, "Sheet 120."),
        ("Non-Residential Deferred Distribution Cost Recovery", None, None, "Sheet 121."),
        ("Customer Credit Recovery", None, None, "Sheet 122."),
        ("Residential Generation Credit", None, None, "Sheet 123."),
        ("Phase-In Recovery", None, None, "Sheet 125."),
        ("Government Directives Recovery", None, None, "Sheet 126."),
        ("Automated Meter Opt Out", None, None, "Sheet 128."),
        ("Ohio Renewable Resources", None, None, "Sheet 129."),
        ("Commercial High Load Factor Experimental TOU", None, "25-1109-EL-RDR",
         "Rider HLF."),
        ("Conservation Support Rider", None, None, "Sheet 133."),
        ("County Fairs and Agricultural Societies", None, "25-1111-EL-RDR",
         "Rider CFA tariff update filed 11/26/2025."),
        ("Legacy Generation Resource", None, "24-1062-EL-RDR",
         "Rider LGR update filed 12/02/2024; compliance tariffs approved 08/06/2025."),
        ("Solar Generation Fund", None, None, "Sheet 136."),
        ("Consumer Rate Credit", None, "25-1137-EL-RDR",
         "Rider CRC tariff update filed 12/01/2025."),
        ("Electric Vehicle Charging", None, "26-0163-EL-RDR",
         "Rider EVC update filed 02/25/2026."),
    ]:
        if name in _ROLLIN:
            continue  # kept as proposed / roll_into_base from the 26-0347 block above
        upsert_rider(db, fe, name, kind="rider", status="effective",
                     disposition="standalone", operating_company=opco,
                     authority_docket=auth,
                     notes=(f"Authority: {auth}. {extra}" if auth
                            else f"Most recent authorizing docket not identified. {extra}"))

    # ---- Columbia Gas of Ohio (NiSource) ----
    # Tariff/rider inventory sourced from the company's current tariff
    # (P.U.C.O. No. 2, Sixty-Sixth Revised Sheet No. 1c, issued Jun. 29, 2026);
    # each sheet names its authority docket.
    col = get_or_create_utility(db, "Columbia Gas of Ohio", sector="gas")
    get_or_create_case(db, "21-0637-GA-AIR", col, case_type="historical", status="decided",
                       date_filed="2021-06-30", date_order="2023-01-26",
                       notes="2021 base rate case (et al.): requested $220M+; approved $68M. "
                             "Residential fixed charge stepping to $58/mo by 2027. Affirmed by "
                             "the Ohio Supreme Court 6/25/2026 (2026-Ohio-2381). Positions not "
                             "yet extracted into the app.")
    get_or_create_case(db, "TBD (pre-filing 2026-09-18)", col, case_type="historical",
                       status="pending", date_filed="2026-09-18",
                       notes="Preliminary proposal for a base rate increase filed 9/18/2026 "
                             "(Columbus Dispatch, 9/25/2026). Residential base rate would rise "
                             "to $68.05/mo in 2028, $72.92 in 2029, $77.12 in 2030; typical "
                             "10 mcf bill estimated at $137.56 vs $122.77 today. ~1.5M customers "
                             "in 61 counties. OCC intervening. Formal application not yet "
                             "filed; PUCO decision expected summer 2027. Docket TBD.")
    for name, kind, auth, extra in [
        ("Monthly Delivery Charge (base tariff)", "tariff", "21-0637-GA-AIR",
         "Base delivery charge, $36.36/mo (SGS)."),
        ("Non-Temperature Balancing Service Fee", "tariff", "21-0637-GA-AIR",
         "$0.2700/Mcf."),
        ("Standard Choice Offer Rider", "rider", "26-0121-GA-UNC", "$0.5481/Ccf."),
        ("PIP Plan Tariff Schedule Rider", "rider", "26-0421-GA-PIP", "$0.2612/Mcf."),
        ("Uncollectible Expense Rider", "rider", "26-0321-GA-UEX", "$0.1509/Mcf. "
         "Tariff sheet prints 26-321-GA-UEX; normalized to DIS 4-digit form."),
        ("CHOICE/SCO Reconciliation Rider", "rider", "26-0121-GA-UNC", "$0.3310/Mcf."),
        ("Infrastructure Replacement Program Rider", "rider", "25-1058-GA-RDR",
         "$6.37/mo."),
        ("Capital Expenditure Program (CEP) Rider", "rider", "25-0621-GA-RDR",
         "$6.14/mo."),
        ("PHMSA Rider", "rider", "25-0981-GA-RDR", "$1.05/mo."),
        ("Demand Side Management Rider", "rider", "25-1059-GA-RDR", "$0.0633/Mcf."),
        ("Infrastructure Development Rider", "rider", "25-0521-GA-AIR", "$0.87/mo."),
    ]:
        upsert_rider(db, col, name, kind=kind, status="effective",
                     disposition="standalone", authority_docket=auth,
                     notes=f"Authority: {auth}. {extra}")

    # ---- Enbridge Gas Ohio (The East Ohio Gas Company d/b/a Enbridge Gas Ohio) ----
    # Formerly Dominion Energy Ohio; parent is now Enbridge Inc. (NYSE: ENB).
    # Rider inventory from enbridgegas.com/ohio/rates-and-tariffs; every docket
    # verified on its DIS case-record card 2026-10-01.
    for name, auth, extra in [
        ("Interim Emergency and Temporary PIP Plan Rider", "26-0419-GA-PIP",
         "PIP rider; tariff sheet F-PIP 1 filed 07/14/2026."),
        ("Uncollectible Expense Rider", "26-0319-GA-UEX",
         "Approved by Finding & Order 07/08/2026; tariff sheets filed 07/15/2026."),
        ("Operational Balancing Rider (OBR)", "26-0219-GA-EXR",
         "Annual OBR + Transportation Migration Rider Part B audit case; revised "
         "sheet OBR 1 filed 08/06/2026."),
        ("Transportation Surcredit Rider", "23-0894-GA-AIR",
         "Current sheet filed under 23-0894 authority; effective 11/01/2025."),
        ("Gross Receipts Tax and Excise Tax Riders", "23-0894-GA-AIR",
         "Current sheet filed under 23-0894 authority; effective 11/01/2025."),
        ("Demand Side Management Rider", "25-1091-GA-RDR",
         "Adjustment approved by Finding & Order 04/29/2026."),
        ("Pipeline Infrastructure Replacement (PIR) Cost Recovery Charge",
         "25-1090-GA-RDR",
         "Adjustment approved by Finding & Order 04/29/2026."),
        ("Infrastructure Development Rider (IDR)", "26-0519-GA-IDR",
         "Annual IDR rate adjustment case filed 01/02/2026."),
        ("Tax Savings Credit Rider", "23-0894-GA-AIR",
         "Originally established in 18-1098-GA-UNC (O&O 08/08/2018); current "
         "sheet references the 23-0894 Finding and Order."),
        ("Capital Expenditure Program (CEP) Rider", "26-0619-GA-RDR",
         "Annual CEP rider case filed 01/02/2026."),
    ]:
        upsert_rider(db, enbridge, name, kind="rider", status="effective",
                     disposition="standalone", authority_docket=auth,
                     notes=f"Authority: {auth}. {extra}")

    # ---- 25-1097-GA-AIR : Enbridge Gas Ohio (pending base rate case) ----
    c = get_or_create_case(db, "25-1097-GA-AIR", enbridge, case_type="historical",
                           status="pending", date_filed="2025-12-31",
                           date_staff_report="2026-07-06",
                           notes="Notice of intent 11/26/2025; application filed 12/31/2025 "
                                 "(accepted for filing Feb 2026). Staff Report 07/06/2026. Joint "
                                 "Stipulation filed 09/11/2026 is CONTESTED (OCC and NOPEC "
                                 "testimony opposing, 09/16-09/25/2026). No final order. "
                                 "Requested vs. approved revenue not shown on docket card.")
    # ---- 23-0894-GA-AIR : Enbridge Gas Ohio (most recent completed base case) ----
    c = get_or_create_case(db, "23-0894-GA-AIR", enbridge, case_type="historical",
                           status="decided", date_filed="2023-10-31", date_order="2025-06-26",
                           notes="O&O 06/26/2025 approving rate increase and alternative rate "
                                 "plan; rehearing entries 08/20/2025 and 10/15/2025; tariffs "
                                 "effective 11/01/2025. DIS shows case OPEN solely because of "
                                 "pending Supreme Court of Ohio appeal (No. 2025-1622, filed "
                                 "12/12/2025); Commission orders are final. Requested vs. "
                                 "approved revenue not shown on docket card.")

    # ---- Duke Energy Ohio (Gas) ----
    # Rider inventory from duke-energy.com gas tariff sheets (47-89); every docket
    # verified on its DIS case-record card 2026-10-01. Dockets use DIS 4-digit form.
    for name, auth, extra in [
        ("Rate NGV - Natural Gas Vehicle Fueling Rider", "22-0507-GA-AIR",
         "Tariff sheet 47."),
        ("Rider EFBS - Enhanced Firm Balancing Service", "21-0903-GA-EXM",
         "Tariff sheet 50."),
        ("Rider DRR - Default Recovery Rider", "22-0507-GA-AIR",
         "Tariff sheet 60."),
        ("Rider GTCJA - Gas Tax Cuts and Jobs Act Rider", "18-1830-GA-UNC",
         "Tariff sheet 61."),
        ("Rider X - Main Extension Policy", "22-0507-GA-AIR",
         "Tariff sheet 62."),
        ("Rider PIPP - Percentage of Income Payment Plan", "26-0418-GA-PIP",
         "Annual PIPP rider application filed 05/28/2026; tariff sheet 63."),
        ("Rider ETR - Ohio Excise Tax Liability Rider", "22-0507-GA-AIR",
         "Tariff sheet 64."),
        ("Rider GSR - Gas Surcredit Rider", "22-0507-GA-AIR",
         "Tariff sheet 66."),
        ("Rider UE-G - Uncollectible Expense Rider", "26-0318-GA-UEX",
         "Adjustment approved by Finding & Order 07/08/2026; tariff sheet 67."),
        ("Rider STR - State Tax Rider", "22-0507-GA-AIR",
         "Tariff sheet 68."),
        ("Rider SSO - Standard Service Offer", "26-0052-GA-ATA",
         "F&O 03/18/2026 approving gas tariff amendments; tariff sheet 72."),
        ("Rider SSOR - Standard Service Offer Rate", "21-0903-GA-EXM",
         "Tariff sheet 73."),
        ("Rider SSOCR - Standard Service Offer Cost Reconciliation Rider",
         "21-0903-GA-EXM", "Tariff sheet 74."),
        ("Rider CCCR - Contract Commitment Cost Recovery Rider", "22-0507-GA-AIR",
         "Tariff sheet 76."),
        ("Rider ATC - Auction Transition Cost Rider", "21-0903-GA-EXM",
         "Tariff sheet 77."),
        ("Rider SBC - Storage Balancing Charge", "26-0052-GA-ATA",
         "Tariff sheet 78."),
        ("Rider SBS - Optional Summary Billing Service Pilot", "22-0507-GA-AIR",
         "Tariff sheet 83."),
        ("Rider CEP - Capital Expenditure Program Rider", "25-0618-GA-RDR",
         "Active infrastructure-replacement rider; adjustment approved by F&O "
         "10/15/2025; tariff sheet 84."),
        ("Rider FTDC - Firm Transportation Development Cost Rider", "22-0507-GA-AIR",
         "Tariff sheet 87."),
        ("Infrastructure Development Rider - IDR", "26-0518-GA-IDR",
         "Annual IDR case; updated tariff sheets 04/20/2026; tariff sheet 89."),
    ]:
        upsert_rider(db, duke_gas, name, kind="rider", status="effective",
                     disposition="standalone", authority_docket=auth,
                     notes=f"Authority: {auth}. {extra}")
    # Withdrawn / cancelled riders, kept for a complete disposition picture.
    for name, auth, extra in [
        ("Rider AMRP - Accelerated Main Replacement Program", "22-0507-GA-AIR",
         "Withdrawn by Order 11/01/2023; tariff sheet 65 cancelled."),
        ("Rider MGP - Manufactured Gas Plant Rider", "18-1830-GA-UNC",
         "Withdrawn by Order 04/20/2022; tariff sheet 69 cancelled."),
        ("Rider GCR - Gas Cost Recovery", "21-0903-GA-EXM",
         "Cancelled/withdrawn starting April 2026 billing cycle; tariff sheet 70."),
        ("Rider GCRR - Gas Cost Recovery Rate", "21-0903-GA-EXM",
         "Cancelled/withdrawn starting April 2026 billing cycle; tariff sheet 71."),
        ("Rider FBS - Firm Balancing Service", "21-0903-GA-EXM",
         "Cancelled/withdrawn after 05/31/2025; tariff sheet 75."),
        ("Rider AU - Advanced Utility Rider", "19-0664-GA-RDR",
         "Withdrawn by Order 02/10/2021; tariff sheet 88 cancelled."),
    ]:
        upsert_rider(db, duke_gas, name, kind="rider", status="terminated",
                     disposition="standalone", authority_docket=auth,
                     notes=f"Authority: {auth}. {extra}")

    # ---- 26-0635-GA-AIR : Duke Energy Ohio (Gas) (pending base rate case) ----
    c = get_or_create_case(db, "26-0635-GA-AIR", duke_gas, case_type="historical",
                           status="pending", date_filed="2026-05-29",
                           notes="Application deemed complete 08/12/2026 (ALJ entry). Staff "
                                 "Report due 01/11/2027; evidentiary hearing scheduled "
                                 "03/30/2027. Direct testimony filed 06/29-06/30/2026; OCC and "
                                 "Ohio Energy Group intervened. Companion cases: 26-0636-GA-ALT, "
                                 "26-0637-GA-ATA, 26-0638-GA-AAM. No final order.")
    # ---- 22-0507-GA-AIR : Duke Energy Ohio (Gas) (most recent completed) ----
    c = get_or_create_case(db, "22-0507-GA-AIR", duke_gas, case_type="historical",
                           status="decided", date_filed="2022-05-31", date_order="2023-11-01",
                           notes="O&O 11/01/2023 adopting the 04/28/2023 joint stipulation "
                                 "resolving all issues. Companion cases 22-0508-GA-ALT, "
                                 "22-0509-GA-ATA, 22-0510-GA-AAM. DIS still shows OPEN because "
                                 "OCC appealed (notice 10/25/2024); Supreme Court Judgment Entry "
                                 "06/23/2026 concluded the appeal. Requested vs. approved "
                                 "revenue not shown on docket card.")

    # ---- AEP Ohio (Ohio Power Company; aepohio.com has rebranded to Ohio Power ----
    # ---- Company, still an AEP subsidiary) ----
    # Rider inventory with most recent verified authority docket per rider (DIS,
    # 2026-10-01). AEP Ohio operates Columbus Southern Power and Ohio Power rate
    # zones under a single Ohio Power Company tariff (PUCO No. 21/22); zone-level
    # differences could not be verified (current tariff book PDFs are broken on
    # aepohio.com), so operating_company is left blank. No EL-UEX/EL-USF/EL-IDR/
    # EL-EFC/EL-FAC dockets exist for Ohio Power Company.
    for name, auth, extra in [
        ("Basic Transmission Cost Rider (BTCR)", "26-0047-EL-RDR",
         "Update approved by F&O 03/18/2026; interim update approved 09/17/2026."),
        ("Economic Development Cost Recovery Rider (EDCRR/EDR)", "26-0815-EL-RDR",
         "Rate adjustment approved by F&O 09/30/2026."),
        ("Storm Damage Recovery Rider (SDRR)", "26-0549-EL-RDR",
         "PUCO Staff review filed 09/16/2026; open."),
        ("Generation Energy Rider & Generation Capacity Rider", "26-0548-EL-RDR",
         "Updated tariffs approved by F&O 05/27/2026."),
        ("gridSMART Rider", "26-0547-EL-RDR",
         "Quarterly updates; open."),
        ("Distribution Investment Rider (DIR)", "26-0143-EL-RDR",
         "Annual audit/review case; related 25-1180-EL-RDR (2026 DIR work plan)."),
        ("Energy Efficiency Rider", "26-0086-EL-RDR",
         "Smart City Rider folded in per 24-0691-EL-RDR F&O 04/02/2025."),
        ("Enhanced Service Reliability Rider (ESRR)", "26-1027-EL-RDR",
         "Filed 09/30/2026; open."),
        ("Tax Savings Credit Rider", "24-0341-EL-RDR",
         "O&O 04/01/2026 adopting joint stipulation; rehearing denied 05/27/2026; "
         "PUCO Tariff No. 22 effective 04/10/2026."),
        ("Alternative Energy Rider (AER)", "23-0251-EL-RDR",
         "Management/performance & financial audit case for 2018-2022 activity; open."),
        ("Solar Generation Fund Rider (SGFR)", "22-1052-EL-RDR",
         "Updated tariffs approved by F&O 12/14/2022 effective 01/01/2023."),
        ("Pilot Throughput Balancing Adjustment Rider", "22-0159-EL-RDR",
         "Most recent verified docket; current effectiveness not re-confirmed."),
    ]:
        upsert_rider(db, aep, name, kind="rider", status="effective",
                     disposition="standalone", authority_docket=auth,
                     notes=f"Authority: {auth}. {extra}")

    # ---- 20-0585-EL-AIR : AEP Ohio (most recent completed base case) ----
    # Already seeded above as 20-585-EL-AIR with pilot-extracted positions; the new
    # research (2026-10-01) adds: DIS shows OPEN-OPEN due to post-order activity
    # (Supreme Court of Ohio Case No. 2023-0464 appeal referenced in filings).
    c585 = db.query(Case).filter(Case.docket == "20-585-EL-AIR").first()
    if c585:
        c585.notes = ("O&O 11/17/2021 adopting stipulation. DIS shows OPEN-OPEN due to "
                      "post-order activity (Supreme Court of Ohio Case No. 2023-0464 "
                      "appeal referenced in filings); Commission orders are issued. "
                      "Requested vs. approved revenue not shown on docket card.")
    # New research on 25-0392-EL-AIR (2026-10-01): Entry on Rehearing 05/27/2026
    # denied rehearing (OCC, Ohio Environmental Council); compliance tariffs
    # (PUCO No. 22) filed 04/08/2026. DIS still shows it OPEN; it is the only
    # active EL-AIR case for Ohio Power Company.
    c392 = db.query(Case).filter(Case.docket == "25-0392-EL-AIR").first()
    if c392:
        c392.date_filed = "2025-04-10"
        c392.notes = ("O&O 04/01/2026 adopting the joint stipulation and recommendation. "
                      "Entry on Rehearing 05/27/2026 denying rehearing (OCC, Ohio "
                      "Environmental Council); compliance tariffs (PUCO No. 22) filed "
                      "04/08/2026. DIS shows the case OPEN; it is the only active "
                      "EL-AIR case for Ohio Power Company.")

    # ---- CenterPoint Energy Ohio (National Fuel Gas Distribution of Ohio, LLC) ----
    # Rider inventory from tariff P.U.C.O. No. 5 Table of Contents (Sheets 30-48);
    # dockets verified on DIS 2026-10-01. The utility uses standing annual docket
    # series (0120-UNC, 0220-EXR, 0320-UEX, 0420-PIP, 0520-IDR, 0620-RDR, 0720-RDR,
    # 0820-RDR, 1020-RDR). Entire tariff book reissued 01/09/2026 under 24-0832.
    for name, kind, status, auth, extra in [
        ("Capital Expenditure Program Rider", "rider", "effective", "26-0620-GA-RDR",
         "Finding & Order 08/19/2026."),
        ("Tax Adjustment Rider", "rider", "effective", "26-1020-GA-RDR",
         "Filed 09/28/2026; open."),
        ("Uncollectible Expense Rider", "rider", "effective", "26-0320-GA-UEX",
         "Filed 01/02/2026; open."),
        ("PIPP Rider", "rider", "effective", "26-0420-GA-PIP",
         "Filed 01/02/2026; open."),
        ("Exit Transition Cost (ETC) Rider", "rider", "effective", "26-0220-GA-EXR",
         "Annual ETC filing, filed 12/31/2025; open."),
        ("Standard Choice Offer (SCO) Rider", "rider", "effective", "26-0120-GA-UNC",
         "Monthly SCO/ECF tariff sheets; F&O 01/22/2026."),
        ("Distribution Replacement Rider (DRR)", "rider", "effective", "26-0720-GA-RDR",
         "Filed 05/01/2026; open."),
        ("Energy Efficiency Funding Rider (EEFR)", "rider", "effective",
         "26-0820-GA-RDR", "Filed 07/01/2026; open."),
        ("Energy Conversion Factor (ECF)", "tariff", "effective", "26-0120-GA-UNC",
         "Filed together with SCO Rider monthly; F&O 01/22/2026."),
        ("Infrastructure Development Rider (IDR)", "rider", "effective",
         "26-0520-GA-IDR", "Filed 01/02/2026; open."),
        ("Gross Receipts Excise Tax Rider", "rider", "effective", "24-0832-GA-AIR",
         "Current sheet cites the 24-0832 O&O of 01/07/2026; no separate rider "
         "proceeding found in DIS."),
        ("S.B. 287 Excise Tax Rider", "rider", "effective", "24-0832-GA-AIR",
         "Current sheet cites the 24-0832 O&O of 01/07/2026; no separate rider "
         "proceeding found in DIS."),
        ("Gas Cost Recovery Rider", "rider", "terminated", "08-0220-GA-GCR",
         "SUSPENDED per tariff; last docket filed 12/31/2007."),
        ("Migration Cost Rider", "rider", "terminated", None,
         "SUSPENDED per tariff; no active docket."),
        ("Balancing Cost Rider", "rider", "terminated", None,
         "SUSPENDED per tariff; no active docket."),
    ]:
        upsert_rider(db, centerpoint, name, kind=kind, status=status,
                     disposition="standalone", authority_docket=auth,
                     notes=((f"Authority: {auth}. {extra}") if auth else extra))

    # ---- 24-0832-GA-AIR : CenterPoint Energy Ohio (recent; O&O 01/07/2026) ----
    c = get_or_create_case(db, "24-0832-GA-AIR", centerpoint, case_type="historical",
                           status="decided", date_filed="2024-10-29",
                           date_order="2026-01-07",
                           notes="Notices of intent 08/27/2024; application 10/29/2024. "
                                 "O&O 01/07/2026 (50 pp.) modified and adopted the "
                                 "stipulation resolving all issues. DIS shows OPEN "
                                 "(compliance/tariff phase; revised tariff pages filed "
                                 "01/09/2026). Companions: 24-0833-GA-ALT, 24-0834-GA-AAM, "
                                 "24-0835-GA-ATA. Requested revenue ~$100M per secondary "
                                 "sources (NOT verified from the application).")
    upsert_position(db, c, "final_or_stip", revenue_requirement=371.442,
                    revenue_change=59.740, rate_base=1437.626,
                    notes="Per O&O: revenue requirement $371,441,948; deficiency "
                          "(increase) $59,740,346; rate base $1,437,626,151 "
                          "(12/31/2024); test-period operating income $102,103,628.")
    # ---- 18-0298-GA-AIR : CenterPoint Energy Ohio (most recent completed) ----
    c = get_or_create_case(db, "18-0298-GA-AIR", centerpoint, case_type="historical",
                           status="decided", date_filed="2018-02-21",
                           date_order="2019-08-28",
                           notes="O&O 08/28/2019 (85 pp.) adopted the stipulation; Second "
                                 "Entry on Rehearing 12/04/2019 denied rehearing. Case "
                                 "closed 09/01/2023. Requested vs. approved revenue not "
                                 "extracted.")

    # ---- Earned ROE (actual, not authorized) ----
    # Only 6 figures could be verified (2026-10-01 research): all from the secondary
    # source below, citing S&P Global/RRA. Everything else was NOT FOUND - the primary
    # source (PUCO SEET application PDFs on DIS) has no extractable text layer.
    # Source is recorded on every row; nothing here is estimated.
    GABELLI_SRC = ("Gabelli Funds, 'U.S. Utilities - Powering the Future' (6/30/2025), "
                   "Table 6 'Highest Earning Electric Utilities Based on ROE's', citing "
                   "S&P Global/RRA - SECONDARY SOURCE, not PUCO SEET methodology")
    aep = db.query(Utility).filter(Utility.name == "AEP Ohio").first()
    fe = db.query(Utility).filter(Utility.name == "FirstEnergy").first()
    for year, val in [(2022, 9.70), (2023, 9.86), (2024, 9.41)]:
        upsert_earned_roe(db, aep, year, val, GABELLI_SRC)
    for year, val in [(2022, 15.14), (2023, 15.40), (2024, 8.48)]:
        upsert_earned_roe(db, fe, year, val, GABELLI_SRC,
                          notes="Ohio Edison Co. only - not CEI or Toledo Edison.")

    db.commit()
    db.close()
    print("Seed complete.")


if __name__ == "__main__":
    seed()
