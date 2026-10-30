"""Gas position extraction (2026-10-29): the seven gas cases that had
case rows but no positions now benchmark."""
import seed
from models import Case, ThreeWayPosition, Utility


def _pos(db, docket, stage):
    c = db.query(Case).filter(Case.docket == docket).first()
    assert c is not None, docket
    return db.query(ThreeWayPosition).filter(
        ThreeWayPosition.case_id == c.id,
        ThreeWayPosition.stage == stage,
        ThreeWayPosition.period.is_(None)).first()


def test_gas_coverage_now_complete(db):
    seed.seed()
    db.expire_all()
    import main
    gas = main.benchmark_coverage(db, "gas")
    assert gas["total"] == 8
    assert gas["shown"] == 8
    assert gas["dropped"] == []
    everything = main.benchmark_coverage(db, "all")
    assert everything["total"] == 18
    assert everything["shown"] == 18
    from fastapi.testclient import TestClient
    with TestClient(main.app) as client:
        g = client.get("/benchmarks?sector=gas")
        assert g.status_code == 200
        assert "Coverage: 8 of 8" in g.text
        for docket in ("18-0298-GA-AIR", "21-0637-GA-AIR", "22-0507-GA-AIR",
                       "23-0894-GA-AIR", "24-0832-GA-AIR", "25-1097-GA-AIR",
                       "26-0635-GA-AIR", "26-0965-GA-AIR"):
            assert docket in g.text


def test_extracted_figures(db):
    seed.seed()
    db.expire_all()
    # Columbia 21-0637: asked 221.429, staff range in notes, final ~68.
    af = _pos(db, "21-0637-GA-AIR", "as_filed")
    assert af.revenue_change == 221.429 and af.roe == 10.95
    st = _pos(db, "21-0637-GA-AIR", "staff")
    assert st.revenue_change is None and "35,197,000" in st.notes
    fn = _pos(db, "21-0637-GA-AIR", "final_or_stip")
    assert fn.revenue_change == 68.0 and fn.roe == 9.60
    assert fn.equity_ratio == 50.6 and fn.rate_base == 3510.0
    # Duke Gas 22-0507: the full three-way from SEC filings.
    af = _pos(db, "22-0507-GA-AIR", "as_filed")
    assert af.revenue_change == 49.0 and af.roe == 10.3
    st = _pos(db, "22-0507-GA-AIR", "staff")
    assert st.equity_ratio == 52.32 and "24–36M" in st.notes
    fn = _pos(db, "22-0507-GA-AIR", "final_or_stip")
    assert fn.revenue_change == 32.0 and fn.roe == 9.6
    assert fn.equity_ratio == 52.32
    # Enbridge 23-0894: asked 212, final a decrease.
    assert _pos(db, "23-0894-GA-AIR", "as_filed").revenue_change == 212.0
    fn = _pos(db, "23-0894-GA-AIR", "final_or_stip")
    assert fn.revenue_change == -26.3 and fn.roe == 9.79
    # Vectren 18-0298: asked 34, final ~22.7.
    assert _pos(db, "18-0298-GA-AIR", "as_filed").revenue_change == 34.0
    assert _pos(db, "18-0298-GA-AIR", "final_or_stip").revenue_change == 22.7
    # CenterPoint 24-0832: asked now 99.5; the O&O final is untouched.
    assert _pos(db, "24-0832-GA-AIR", "as_filed").revenue_change == 99.5
    fn = _pos(db, "24-0832-GA-AIR", "final_or_stip")
    assert fn.revenue_change == 59.740 and fn.revenue_requirement == 371.442
    assert fn.rate_base == 1437.626
    # Pending cases: as-filed only, no invented final.
    af = _pos(db, "25-1097-GA-AIR", "as_filed")
    assert af.revenue_change == 163.1
    assert _pos(db, "25-1097-GA-AIR", "final_or_stip") is None
    af = _pos(db, "26-0635-GA-AIR", "as_filed")
    assert af.revenue_change == 102.0 and af.roe == 10.5
    assert af.equity_ratio == 53.14


def test_startup_migration_backfills_and_is_idempotent(db):
    """Production DBs never re-run seed: the startup else-branch must
    create the same positions, and re-running must not duplicate them."""
    import main
    utils = {"CenterPoint Energy Ohio": "gas", "Columbia Gas of Ohio": "gas",
             "Duke Energy Ohio (Gas)": "gas", "Enbridge Gas Ohio": "gas"}
    for name, sector in utils.items():
        u = Utility(name=name, sector=sector)
        db.add(u)
    db.flush()
    for docket, uname in (
            ("18-0298-GA-AIR", "CenterPoint Energy Ohio"),
            ("21-0637-GA-AIR", "Columbia Gas of Ohio"),
            ("22-0507-GA-AIR", "Duke Energy Ohio (Gas)"),
            ("23-0894-GA-AIR", "Enbridge Gas Ohio"),
            ("24-0832-GA-AIR", "CenterPoint Energy Ohio"),
            ("25-1097-GA-AIR", "Enbridge Gas Ohio"),
            ("26-0635-GA-AIR", "Duke Energy Ohio (Gas)")):
        u = db.query(Utility).filter(Utility.name == uname).first()
        db.add(Case(docket=docket, utility_id=u.id,
                    case_type="historical", status="decided",
                    notes="Requested revenue ~$100M per secondary sources "
                          "(NOT verified from the application)."
                    if docket == "24-0832-GA-AIR" else
                    "Requested vs. approved revenue not shown on docket card."
                    if docket == "25-1097-GA-AIR" else ""))
    db.commit()
    main.startup()
    db.expire_all()
    assert _pos(db, "21-0637-GA-AIR", "as_filed").revenue_change == 221.429
    assert _pos(db, "26-0635-GA-AIR", "as_filed").revenue_change == 102.0
    c83 = db.query(Case).filter(Case.docket == "24-0832-GA-AIR").first()
    assert "NOT verified" not in c83.notes and "99.5M" in c83.notes
    c1097 = db.query(Case).filter(Case.docket == "25-1097-GA-AIR").first()
    assert "144.6M" in c1097.notes
    n_before = db.query(ThreeWayPosition).count()
    main.startup()
    db.expire_all()
    assert db.query(ThreeWayPosition).count() == n_before
