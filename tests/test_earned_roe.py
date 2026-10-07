"""Earned ROE tracking: model, Excel import, and the main-page returns section."""
import seed
from seed import upsert_earned_roe
from models import Utility, EarnedROE


def _aep(db):
    return db.query(Utility).filter(Utility.name == "AEP Ohio").first()


def test_returns_at_a_glance_on_main_page(db):
    seed.seed()
    # synthetic earned-ROE fixture (test data only, not real earnings)
    aep = _aep(db)
    upsert_earned_roe(db, aep, 2024, 10.42, "test fixture earnings report")
    upsert_earned_roe(db, aep, 2023, 9.10, "test fixture earnings report")
    db.commit()

    from fastapi.testclient import TestClient
    import main
    with TestClient(main.app) as client:
        text = client.get(f"/utilities/{aep.id}").text
        assert "Returns at a glance" in text
        # authorized: 25-0392 final/stipulated ROE 9.84
        assert "9.84%" in text
        assert "25-0392-EL-AIR" in text
        # earned latest year + variance (+0.58 pts over-earning)
        assert "10.42%" in text
        assert "+0.58 pts" in text
        assert "over-earning" in text
        # debt / equity from the authorized position's capital structure
        assert "Debt / equity (authorized)" in text
        assert "49.12% debt / 50.88% equity" in text
        # history table
        assert "9.10%" in text


def test_returns_empty_state(db):
    seed.seed()
    col = db.query(Utility).filter(Utility.name == "Columbia Gas of Ohio").first()
    from fastapi.testclient import TestClient
    import main
    with TestClient(main.app) as client:
        text = client.get(f"/utilities/{col.id}").text
        assert "Returns at a glance" in text
        assert "Earned ROE template" in text  # import hint, no earned rows


def test_earned_roe_is_idempotent(db):
    seed.seed()
    aep = _aep(db)
    upsert_earned_roe(db, aep, 2024, 10.42, "src one")
    upsert_earned_roe(db, aep, 2024, 10.55, "src two")
    db.commit()
    rows = db.query(EarnedROE).filter(EarnedROE.utility_id == aep.id,
                                     EarnedROE.year == 2024).all()
    assert len(rows) == 1
    assert rows[0].earned_roe == 10.55
    assert rows[0].source == "src two"


def _make_wb(rows):
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.title = "Data - fill this in"
    ws.append(["Utility", "Year", "Earned ROE (%)", "Source", "Notes (optional)"])
    for r in rows:
        ws.append(r)
    from io import BytesIO
    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


def test_earned_roe_import_validation(db):
    seed.seed()
    import excel_import
    good = _make_wb([["AEP Ohio", 2024, 10.42, "2024 PUCO earnings report", ""]])
    rows, errors = excel_import.validate_earned_roe(good, db)
    assert not errors, errors
    assert rows[0]["earned_roe"] == 10.42 and rows[0]["year"] == 2024

    bad = _make_wb([
        ["AEP Ohio", "not-a-year", 10.42, "src", ""],   # bad year
        ["AEP Ohio", 2024, "", "src", ""],              # missing ROE
        ["AEP Ohio", 2024, 10.42, "", ""],              # missing source
        ["No Such Utility", 2024, 10.42, "src", ""],   # unknown utility
    ])
    rows, errors = excel_import.validate_earned_roe(bad, db)
    assert not rows
    assert len(errors) == 4


def test_earned_roe_import_loads(db):
    seed.seed()
    import excel_import
    good = _make_wb([["AEP Ohio", 2024, 10.42, "2024 PUCO earnings report", "note"]])
    rows, errors = excel_import.validate_earned_roe(good, db)
    assert not errors
    n = excel_import.load_earned_roe(db, rows)
    assert n == 1
    rec = db.query(EarnedROE).filter(EarnedROE.utility_id == _aep(db).id,
                                         EarnedROE.year == 2024).one()
    assert rec.earned_roe == 10.42 and rec.notes == "note"


def test_seeded_earned_roe_figures(db):
    seed.seed()
    aep = db.query(Utility).filter(Utility.name == "AEP Ohio").first()
    rows = {e.year: e for e in
            db.query(EarnedROE).filter(EarnedROE.utility_id == aep.id).all()}
    assert rows[2024].earned_roe == 9.41
    assert rows[2022].earned_roe == 9.70
    assert "SECONDARY SOURCE" in rows[2024].source
    assert "S&P Global/RRA" in rows[2024].source
    fe = db.query(Utility).filter(Utility.name == "FirstEnergy").first()
    fe_rows = {e.year: e for e in
               db.query(EarnedROE).filter(EarnedROE.utility_id == fe.id).all()}
    assert fe_rows[2023].earned_roe == 15.40
    assert "Ohio Edison Co. only" in fe_rows[2023].notes


def test_earned_roe_template_registered():
    import excel_templates
    assert "earned_roe" in excel_templates.TEMPLATES
    buf = excel_templates.TEMPLATES["earned_roe"][1]()
    assert buf.getvalue()[:2] == b"PK"  # xlsx bytes
