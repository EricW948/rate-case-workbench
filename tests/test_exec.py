"""Executive insights: delay cost and lever ranking."""
import pytest
import seed
from models import Case, Scenario, ThreeWayPosition
import main
from main import (rr_from_inputs, scenario_math, lever_ranking,
                  delay_analysis, _exec_inputs)


def _case(db, docket="26-0347-EL-AIR"):
    seed.seed()
    return db.query(Case).filter(Case.docket == docket).one()


def _position(db, case):
    p = ThreeWayPosition(case_id=case.id, stage="as_filed",
                         revenue_requirement=500.0, revenue_change=169.8,
                         roe=10.0, equity_ratio=50.0, cost_of_debt=5.0,
                         rate_base=4000.0, opex=200.0,
                         depreciation=100.0, taxes=50.0)
    db.add(p)
    db.commit()
    return p


def test_rr_from_inputs_matches_scenario_math(db):
    case = _case(db)
    s = Scenario(case_id=case.id, name="t", rate_base=4000.0, roe=10.0,
                 equity_ratio=50.0, cost_of_debt=5.0, opex=200.0,
                 depreciation=100.0, taxes=50.0)
    db.add(s)
    db.commit()
    adj = sum(a.amount or 0 for a in s.adjustments)
    assert rr_from_inputs(4000.0, 50.0, 10.0, 5.0, 200.0, 100.0, 50.0, adj) == \
        pytest.approx(scenario_math(s)["revenue_requirement"])


def test_lever_ranking_order_and_values(db):
    case = _case(db)
    p = _position(db, case)
    res = lever_ranking(p)
    # rate base 4000, eq 50%, roe 10, debt 5 -> ror 7.5%
    # ROE +10bps: 4000 * 0.5 * 0.001 = 2.0
    roe_row = next(r for r in res["levers"] if r["key"] == "roe")
    assert roe_row["delta"] == pytest.approx(2.0)
    # O&M +10M is 1:1
    opex_row = next(r for r in res["levers"] if r["key"] == "opex")
    assert opex_row["delta"] == pytest.approx(10.0)
    # ranked by |delta| descending
    deltas = [abs(r["delta"]) for r in res["levers"]]
    assert deltas == sorted(deltas, reverse=True)
    assert len(res["levers"]) == 7


def test_lever_ranking_equity_ratio_math(db):
    case = _case(db)
    p = _position(db, case)
    res = lever_ranking(p)
    eq_row = next(r for r in res["levers"] if r["key"] == "equity_ratio")
    # +1pt equity: 4000 * (10 - 5)/100 * 0.01 = 2.0
    assert eq_row["delta"] == pytest.approx(2.0)


def test_delay_analysis_monthly_and_cumulative(db):
    case = _case(db)
    p = _position(db, case)
    src_inputs = _exec_inputs(p)
    current = p.revenue_requirement - p.revenue_change  # 330.2
    out = delay_analysis(500.0, src_inputs, current, 12)
    assert out["increase"] == pytest.approx(169.8)
    assert out["monthly"] == pytest.approx(169.8 / 12.0)
    assert out["rows"][-1] == (12, pytest.approx(169.8))
    # foregone return: 4000 * 7.5% / 12 = 25.0
    assert out["foregone_return_monthly"] == pytest.approx(25.0)


def test_delay_analysis_without_current_revenue(db):
    case = _case(db)
    p = _position(db, case)
    src_inputs = _exec_inputs(p)
    out = delay_analysis(500.0, src_inputs, None, 6)
    assert out["monthly"] is None
    assert out["rows"] == []
    assert out["foregone_return_monthly"] == pytest.approx(25.0)


def test_exec_page_renders(db):
    from fastapi.testclient import TestClient
    case = _case(db)
    _position(db, case)
    with TestClient(main.app) as client:
        r = client.get(f"/cases/{case.id}/exec")
    assert r.status_code == 200
    assert "Executive insights" in r.text
    assert "Cost of delay" in r.text
    assert "Lever ranking" in r.text


def test_exec_page_needs_build(db):
    from fastapi.testclient import TestClient
    from models import Utility
    seed.seed()
    u = db.query(Utility).first()
    case = Case(utility_id=u.id, docket="99-9999-XX-AIR", case_type="historical",
                status="pending")
    db.add(case)
    db.commit()
    with TestClient(main.app) as client:
        r = client.get(f"/cases/{case.id}/exec")
    assert r.status_code == 200
    assert "No revenue-requirement build yet" in r.text


def test_exec_page_bad_source(db):
    from fastapi.testclient import TestClient
    case = _case(db)
    _position(db, case)
    with TestClient(main.app) as client:
        r = client.get(f"/cases/{case.id}/exec?src=99999")
    assert r.status_code == 200
    assert "Pick this case" in r.text
