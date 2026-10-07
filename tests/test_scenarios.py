"""Scenario workbench: revenue-requirement math, builder, comparison, risk stamps."""
import seed
from models import Case, Scenario, ScenarioAdjustment
import main
import excel_import


def _case(db, docket="26-0347-EL-AIR"):
    return db.query(Case).filter(Case.docket == docket).one()


def _form(**kw):
    base = {"name": "Year-end RB, 10.1% ROE", "test_period_type": "historic_adjusted",
            "rate_base_method": "year_end", "date_certain": "2026-09-30",
            "roe_method": "dcf", "roe": "10.10", "equity_ratio": "52",
            "cost_of_debt": "5.25", "rate_base": "1000", "opex": "200",
            "depreciation": "100", "taxes": "50",
            "adjustments_text": "Union contract | known_measurable | 12.5\nStorm reserve | -3.0",
            "risk_level": "medium", "risk_note": "Staff fought this in 21-0887",
            "notes": ""}
    base.update(kw)
    return base


def test_scenario_math_is_right(db):
    seed.seed()
    c = _case(db)
    s = Scenario(case_id=c.id, name="math check", roe=10.0, equity_ratio=50.0,
                 cost_of_debt=5.0, rate_base=1000.0, opex=200.0,
                 depreciation=100.0, taxes=50.0)
    db.add(s)
    db.flush()
    db.add(ScenarioAdjustment(scenario_id=s.id, name="plus", amount=25.0))
    db.add(ScenarioAdjustment(scenario_id=s.id, name="minus", amount=-10.0))
    db.commit()
    m = main.scenario_math(s)
    # overall return = 50% x 10% + 50% x 5% = 7.5%
    assert abs(m["ror_pct"] - 7.5) < 1e-9
    assert abs(m["return_on_rb"] - 75.0) < 1e-9
    assert abs(m["adj_total"] - 15.0) < 1e-9
    # 75 + 200 + 100 + 50 + 15 = 440
    assert abs(m["revenue_requirement"] - 440.0) < 1e-9


def test_parse_adjustments(db):
    adjs, errors = main.parse_adjustments(
        "Union contract | known_measurable | 12.5\nStorm reserve | -3.0\n\n")
    assert errors == []
    assert adjs == [{"name": "Union contract", "category": "known_measurable", "amount": 12.5},
                    {"name": "Storm reserve", "category": "other", "amount": -3.0}]
    adjs, errors = main.parse_adjustments("Bad line\n")
    assert adjs == [] and len(errors) == 1
    adjs, errors = main.parse_adjustments("X | bogus_cat | 5\n")
    assert adjs == [] and len(errors) == 1
    assert "category" in errors[0]


def test_create_scenario_round_trip(db):
    seed.seed()
    c = _case(db)
    from fastapi.testclient import TestClient
    with TestClient(main.app) as client:
        r = client.post(f"/cases/{c.id}/scenarios", data=_form(),
                        follow_redirects=False)
        assert r.status_code == 303, r.text
        page = client.get(f"/cases/{c.id}/scenarios").text
        assert "Year-end RB, 10.1% ROE" in page
        assert "Union contract" in page
        assert "Known &amp; measurable" in page or "Known & measurable" in page
    s = db.query(Scenario).filter(Scenario.case_id == c.id).one()
    assert s.roe == 10.10 and s.equity_ratio == 52.0
    assert len(s.adjustments) == 2
    assert s.risk_level == "medium"


def test_create_scenario_bad_input_saves_nothing(db):
    seed.seed()
    c = _case(db)
    from fastapi.testclient import TestClient
    with TestClient(main.app) as client:
        r = client.post(f"/cases/{c.id}/scenarios",
                        data=_form(name="", roe="lots",
                                   adjustments_text="No pipes here"))
        assert r.status_code == 400
        assert "didn&#x27;t save" in r.text or "didn't save" in r.text
    assert db.query(Scenario).filter(Scenario.case_id == c.id).count() == 0


def test_comparison_sorts_highest_rr_first(db):
    seed.seed()
    c = _case(db)
    from fastapi.testclient import TestClient
    with TestClient(main.app) as client:
        client.post(f"/cases/{c.id}/scenarios", data=_form(name="Low"))
        client.post(f"/cases/{c.id}/scenarios",
                    data=_form(name="High", roe="12.00", rate_base="2000"))
        page = client.get(f"/cases/{c.id}/scenarios").text
    assert page.index(">High<") < page.index(">Low<")
    assert "Top RR" in page


def test_risk_stamp_and_delete(db):
    seed.seed()
    c = _case(db)
    from fastapi.testclient import TestClient
    with TestClient(main.app) as client:
        client.post(f"/cases/{c.id}/scenarios", data=_form(name="Stamp me"))
        s = db.query(Scenario).filter(Scenario.name == "Stamp me").one()
        r = client.post(f"/scenarios/{s.id}/risk",
                        data={"risk_level": "low", "risk_note": "Eric: flies"},
                        follow_redirects=False)
        assert r.status_code == 303
        db.refresh(s)
        assert s.risk_level == "low" and s.risk_note == "Eric: flies"
        page = client.get(f"/cases/{c.id}/scenarios").text
        assert "Low — likely flies" in page
        r = client.post(f"/scenarios/{s.id}/delete", follow_redirects=False)
        assert r.status_code == 303
    assert db.query(Scenario).count() == 0


def test_case_page_links_workbench(db):
    seed.seed()
    c = _case(db)
    from fastapi.testclient import TestClient
    with TestClient(main.app) as client:
        page = client.get(f"/cases/{c.id}").text
        assert "Scenario workbench" in page
        assert f"/cases/{c.id}/scenarios" in page


def test_positions_import_new_build_columns(db):
    seed.seed()
    from tests.test_import import make_wb
    wb = make_wb([["Docket", "Stage", "Period", "RR", "Change", "ROE", "Cap", "RB",
                   "Notes", "Eq%", "Debt%", "Opex", "Depr", "Taxes"],
                  ["20-585-EL-AIR", "as_filed", "", "955.1", "42.3", "10.15",
                   "54.43% equity / 45.57% debt", "3088.4", "", "54.43", "5.25",
                   "410.2", "165.0", "88.4"]])
    rows, errors = excel_import.validate_positions(wb, db)
    assert errors == [], errors
    assert rows[0]["equity_ratio"] == 54.43
    assert rows[0]["cost_of_debt"] == 5.25
    assert rows[0]["opex"] == 410.2
    n = excel_import.load_positions(db, rows)
    assert n == 1
    from models import ThreeWayPosition
    p = db.query(ThreeWayPosition).filter(
        ThreeWayPosition.case.has(docket="20-585-EL-AIR"),
        ThreeWayPosition.stage == "as_filed").one()
    assert p.equity_ratio == 54.43 and p.taxes == 88.4


def test_positions_import_old_format_still_works(db):
    seed.seed()
    from tests.test_import import make_wb
    wb = make_wb([["Docket", "Stage", "Period", "RR", "Change", "ROE", "Cap", "RB", "Notes"],
                  ["20-585-EL-AIR", "staff", "", "900", "240", "9.5", "", "", "old file"]])
    rows, errors = excel_import.validate_positions(wb, db)
    assert errors == [], errors
    assert rows[0]["equity_ratio"] is None
    n = excel_import.load_positions(db, rows)
    assert n == 1


def test_positions_import_bad_build_numbers_get_friendly_errors(db):
    seed.seed()
    from tests.test_import import make_wb
    wb = make_wb([["Docket", "Stage", "Period", "RR", "Change", "ROE", "Cap", "RB",
                   "Notes", "Eq%", "Debt%", "Opex", "Depr", "Taxes"],
                  ["20-585-EL-AIR", "as_filed", "", "", "", "", "", "", "", "lots", "", "", "", ""]])
    rows, errors = excel_import.validate_positions(wb, db)
    assert rows == []
    assert len(errors) == 1 and "Equity ratio" in errors[0]


def test_workbench_prefills_from_as_filed_build(db):
    seed.seed()
    c = _case(db)
    from seed import upsert_position
    upsert_position(db, c, "as_filed", revenue_requirement=769.8, roe=10.2,
                    rate_base=2037.9, equity_ratio=53.0, cost_of_debt=5.10,
                    opex=410.0, depreciation=165.0, taxes=88.0)
    db.commit()
    from fastapi.testclient import TestClient
    with TestClient(main.app) as client:
        page = client.get(f"/cases/{c.id}/scenarios").text
    assert "prefilled from the as-filed numbers" in page
    assert 'value="2037.9"' in page
    assert 'value="53.0"' in page
    assert 'value="88.0"' in page


def test_init_db_migration_is_idempotent(db):
    import database
    database.init_db()  # second run must not error
    cols = [r[1] for r in
            db.execute(__import__("sqlalchemy").text("PRAGMA table_info(three_way_positions)")).fetchall()]
    for col in ("equity_ratio", "cost_of_debt", "opex", "depreciation", "taxes"):
        assert col in cols


def test_roe_sensitivity_math(db):
    seed.seed()
    c = _case(db)
    s = Scenario(case_id=c.id, name="sens", roe=10.0, equity_ratio=50.0,
                 cost_of_debt=5.0, rate_base=1000.0, opex=200.0,
                 depreciation=100.0, taxes=50.0)
    db.add(s)
    db.commit()
    rows, per_10bp = main.roe_sensitivity(s, 9.5, 10.5, 25)
    # 10bp = 1000 x 50% x 0.001 = $0.5M
    assert abs(per_10bp - 0.5) < 1e-9
    # 9.50, 9.75, 10.00, 10.25, 10.50
    assert [r[0] for r in rows] == [9.5, 9.75, 10.0, 10.25, 10.5]
    base = [r for r in rows if r[0] == 10.0][0]
    assert abs(base[1] - 425.0) < 1e-9  # 75 + 200 + 100 + 50
    assert abs(base[2]) < 1e-9
    lo = rows[0]
    assert abs(lo[2] - (-2.5)) < 1e-9  # 50bp down x $0.5M/10bp


def test_sensitivity_page_round_trip(db):
    seed.seed()
    c = _case(db)
    from fastapi.testclient import TestClient
    with TestClient(main.app) as client:
        client.post(f"/cases/{c.id}/scenarios", data=_form(name="Sens base"))
        s = db.query(Scenario).filter(Scenario.name == "Sens base").one()
        page = client.get(f"/cases/{c.id}/scenarios? sens={s.id}&low=9.4&high=9.7&step=10".replace(" ", "")).text
        assert "basis-point toggles" in page or "ROE sensitivity" in page
        assert "9.40%" in page and "9.70%" in page
        assert "Every 10 basis points" in page


def test_sensitivity_bad_range_shows_error(db):
    seed.seed()
    c = _case(db)
    from fastapi.testclient import TestClient
    with TestClient(main.app) as client:
        client.post(f"/cases/{c.id}/scenarios", data=_form(name="Sens bad"))
        s = db.query(Scenario).filter(Scenario.name == "Sens bad").one()
        page = client.get(f"/cases/{c.id}/scenarios?sens={s.id}&low=10.5&high=9.0&step=10").text
        assert "low below high" in page
