"""Seed idempotency tests."""
import database
import seed
from models import Utility, Case, ThreeWayPosition, TariffRider, Document, EarnedROE


def counts(db):
    return {
        "utilities": db.query(Utility).count(),
        "cases": db.query(Case).count(),
        "positions": db.query(ThreeWayPosition).count(),
        "riders": db.query(TariffRider).count(),
        "documents": db.query(Document).count(),
        "earned_roe": db.query(EarnedROE).count(),
    }


def test_seed_is_idempotent(db):
    seed.seed()
    first = counts(db)
    assert first["utilities"] == 8
    assert first["cases"] == 18
    assert first["positions"] == 39, first
    assert first["riders"] == 157, first
    assert first["documents"] == 10, first
    assert first["earned_roe"] == 6, first
    db.expire_all()
    seed.seed()
    db.expire_all()
    assert counts(db) == first


def test_seed_covers_expected_dockets(db):
    seed.seed()
    dockets = {c.docket for c in db.query(Case).all()}
    assert {"25-0392-EL-AIR", "20-585-EL-AIR", "21-0887-EL-AIR", "17-0032-EL-AIR",
            "24-1009-EL-AIR", "20-1651-EL-AIR", "25-0958-EL-AIR", "26-0347-EL-AIR",
            "24-0468-EL-AIR"} <= dockets


def test_seed_three_way_stages_present(db):
    seed.seed()
    c = db.query(Case).filter(Case.docket == "21-0887-EL-AIR").one()
    stages = {p.stage for p in c.positions}
    assert stages == {"as_filed", "staff", "final_or_stip"}
    final = [p for p in c.positions if p.stage == "final_or_stip"][0]
    assert final.roe == 9.5
    assert abs(final.revenue_change - 22.594) < 0.001
