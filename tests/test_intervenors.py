"""Phase 3: intervenor positions — sourced rows group by case; open Tier 1
cases with nothing on file sit in the extraction queue, never invented."""
import main
from models import Case, IntervenorPosition, Utility


def test_intervenor_rows_group_and_queue(db):
    u = Utility(name="Test Utility")
    db.add(u)
    db.flush()
    with_pos = Case(docket="26-0001-EL-AIR", utility_id=u.id,
                    status="pending", case_type="historical")
    queued = Case(docket="26-0002-EL-AIR", utility_id=u.id,
                  status="pending", case_type="historical")
    db.add_all([with_pos, queued])
    db.flush()
    db.add(IntervenorPosition(case_id=with_pos.id, intervenor="OCC",
                              issue="roe", summary="Proposes lower ROE",
                              value_text="9.0% ROE",
                              source_doc="OCC testimony", source_date="2026-10-01"))
    db.add(IntervenorPosition(case_id=with_pos.id, intervenor="OMA",
                              issue="rate_base",
                              summary="Excludes plant not in service",
                              source_doc="OMA brief", source_date="2026-10-15"))
    db.commit()

    rows = main.intervenor_rows(db)
    assert [g["case"].docket for g in rows["grouped"]] == ["26-0001-EL-AIR"]
    assert len(rows["grouped"][0]["positions"]) == 2
    assert [c.docket for c in rows["queue"]] == ["26-0002-EL-AIR"]


def test_intervenors_page_renders(db):
    import seed
    from fastapi.testclient import TestClient
    seed.seed()
    with TestClient(main.app) as client:
        r = client.get("/intervenors")
        assert r.status_code == 200
        assert "Intervenor positions" in r.text
        assert "Extraction queue" in r.text
        for docket in ("25-0958-EL-AIR", "26-0132-EL-AIR",
                       "26-0965-GA-AIR", "26-0347-EL-AIR"):
            assert docket in r.text


def test_seeded_intervenor_rows_and_queue(db):
    """2026-11-02 DIS extraction: 27 verified rows (AES 7, Duke 13,
    Enbridge 7); the queue holds only the three cases with nothing filed
    yet."""
    import seed
    from models import IntervenorPosition
    seed.seed()
    db.expire_all()
    assert db.query(IntervenorPosition).count() == 27
    rows = main.intervenor_rows(db)
    by_docket = {g["case"].docket: len(g["positions"]) for g in rows["grouped"]}
    assert by_docket == {"25-0958-EL-AIR": 7, "26-0132-EL-AIR": 13,
                         "25-1097-GA-AIR": 7}
    assert [c.docket for c in rows["queue"]] == [
        "26-0965-GA-AIR", "26-0635-GA-AIR", "26-0347-EL-AIR"]
    occ = [p for g in rows["grouped"] for p in g["positions"]
           if g["case"].docket == "26-0132-EL-AIR"
           and p.intervenor == "OCC" and p.issue == "roe"][0]
    assert occ.value_text == "9.30% ROE (9.05%–9.55%)"
    assert occ.source_date == "2026-10-21"
