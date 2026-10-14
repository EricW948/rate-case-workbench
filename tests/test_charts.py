"""Compare page: sector filtering and company logos."""
import seed
from models import Case, ThreeWayPosition, Utility
import main
from main import UTILITY_LOGOS
import charts


def _seeded(db):
    seed.seed()
    return db


def _position(db, case, rev_change=100.0, roe=10.0):
    p = ThreeWayPosition(case_id=case.id, stage="as_filed",
                         revenue_requirement=500.0, revenue_change=rev_change,
                         roe=roe, equity_ratio=50.0, cost_of_debt=5.0,
                         rate_base=4000.0, opex=200.0,
                         depreciation=100.0, taxes=50.0)
    p2 = ThreeWayPosition(case_id=case.id, stage="final_or_stip",
                          revenue_requirement=450.0, revenue_change=rev_change - 20.0,
                          roe=roe - 0.5, equity_ratio=50.0, cost_of_debt=5.0,
                          rate_base=4000.0, opex=200.0,
                          depreciation=100.0, taxes=50.0)
    db.add(p)
    db.add(p2)
    db.commit()


def _client_get(db, url):
    from fastapi.testclient import TestClient
    with TestClient(main.app) as client:
        return client.get(url)


def test_sector_gas_only_shows_gas(db):
    _seeded(db)
    gas_utils = db.query(Utility).filter(Utility.sector == "gas").all()
    assert gas_utils, "seed should include gas utilities"
    case = db.query(Case).filter(Case.utility_id == gas_utils[0].id).first()
    _position(db, case)
    r = _client_get(db, "/charts?sector=gas")
    assert r.status_code == 200
    assert "Gas" in r.text
    # gas utility short name should appear; electric-only names should not
    assert "Columbia" in r.text or "Enbridge" in r.text or "Duke" in r.text


def test_sector_electric_excludes_gas(db):
    _seeded(db)
    r = _client_get(db, "/charts?sector=electric")
    assert r.status_code == 200
    assert 'sector=gas' in r.text  # tab link present


def test_sector_defaults_to_all(db):
    _seeded(db)
    r = _client_get(db, "/charts")
    assert r.status_code == 200
    assert "/charts?sector=gas" in r.text
    assert "/charts?sector=electric" in r.text


def test_bad_sector_falls_back_to_all(db):
    _seeded(db)
    r = _client_get(db, "/charts?sector=nuclear")
    assert r.status_code == 200


def test_every_utility_has_logo_mapping(db):
    _seeded(db)
    names = [u.name for u in db.query(Utility).all()]
    assert names
    for n in names:
        assert n in UTILITY_LOGOS, f"no logo mapping for {n}"


def test_grouped_bars_renders_logo_image():
    groups = [{"label": "AEP", "sub": "25-0392", "logo": "aep.svg",
               "bars": [(100.0, charts.SLATE), (80.0, charts.BLUE)]}]
    svg = charts.grouped_bars(groups, charts.money)
    assert '<image href="/static/logos/aep.svg"' in svg
    assert "AEP" not in svg.replace("<title>AEP</title>", "")


def test_grouped_bars_falls_back_to_text_without_logo():
    groups = [{"label": "AEP", "sub": "25-0392",
               "bars": [(100.0, charts.SLATE), (80.0, charts.BLUE)]}]
    svg = charts.grouped_bars(groups, charts.money)
    assert "<image" not in svg
    assert ">AEP</text>" in svg
