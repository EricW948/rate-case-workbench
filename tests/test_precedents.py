"""Phase 3: precedent library — decided cases reorganized by issue."""
import main
from models import Case, TariffRider, ThreeWayPosition, Utility


def _mk_case(db, u, docket, status="decided", case_type="historical",
             test_year=None, date_order=None):
    c = Case(docket=docket, utility_id=u.id, status=status,
             case_type=case_type, test_year=test_year, date_order=date_order)
    db.add(c)
    db.flush()
    return c


def _pos(db, c, stage, roe=None, equity=None, rb=None, cod=None):
    db.add(ThreeWayPosition(case_id=c.id, stage=stage, roe=roe,
                            equity_ratio=equity, rate_base=rb,
                            cost_of_debt=cod))
    db.flush()


def test_precedent_rows_only_decided(db):
    u = Utility(name="Test Utility")
    db.add(u)
    db.flush()
    decided = _mk_case(db, u, "21-0001-GA-AIR", test_year="2023",
                       date_order="2024-01-15")
    _pos(db, decided, "as_filed", roe=10.5, equity=52.0, rb=1000.0, cod=5.0)
    _pos(db, decided, "final_or_stip", roe=9.6, equity=50.5, rb=900.0, cod=4.8)
    pending = _mk_case(db, u, "26-0002-GA-AIR", status="pending",
                       case_type="historical")
    _pos(db, pending, "as_filed", roe=11.0)
    db.add(TariffRider(utility_id=u.id, name="Rider TEST",
                       status="effective", disposition="roll_into_base",
                       authority_docket="21-0001-GA-AIR"))
    db.commit()

    sections = {s["key"]: s for s in main.precedent_rows(db)}
    assert [s for s in main.precedent_rows(db)][0]["key"] == "roe"
    roe = sections["roe"]["rows"]
    assert len(roe) == 1
    assert roe[0]["case"].docket == "21-0001-GA-AIR"
    assert (roe[0]["asked"], roe[0]["final"], roe[0]["give"]) == (
        "10.50%", "9.60%", "-0.90 pp")
    rb = sections["rate_base"]["rows"][0]
    assert (rb["asked"], rb["final"], rb["give"]) == (
        "+$1000.0M", "+$900.0M", "-$100.0M")
    assert [x["rider"].name for x in
            sections["rider_disposition"]["rows"]] == ["Rider TEST"]
    tp = sections["test_period"]["rows"][0]
    assert (tp["test_year"], tp["date_order"]) == ("2023", "2024-01-15")
    assert sections["cost_allocation"]["rows"] == []


def test_precedents_page_renders(db):
    import seed
    from fastapi.testclient import TestClient
    seed.seed()
    with TestClient(main.app) as client:
        r = client.get("/precedents")
        assert r.status_code == 200
        assert "Precedent library" in r.text
        assert "24-1009-EL-AIR" in r.text
