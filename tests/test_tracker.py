"""Phase 3: rider/deferral tracker — exact docket joins only, no guessed
links between riders and review proceedings."""
import main
from models import Case, Milestone, TariffRider, Utility


def _mk_case(db, u, docket, case_type="other", status="pending", notes=None):
    c = Case(docket=docket, utility_id=u.id, case_type=case_type,
             status=status, notes=notes)
    db.add(c)
    db.flush()
    return c


def test_tracker_exact_joins_only(db):
    u = Utility(name="Test Utility")
    db.add(u)
    db.flush()
    rdr = _mk_case(db, u, "25-0110-EL-RDR")
    db.add(Milestone(case_id=rdr.id, label="Hearing", due_date="2026-12-01",
                     kind="hearing"))
    _mk_case(db, u, "26-0579-GA-UNC", notes="Annual report of pipeline "
             "safety program deferred expenses.")
    _mk_case(db, u, "26-0999-GA-UNC", notes="Procurement plan review.")
    decided = _mk_case(db, u, "24-1009-EL-AIR", case_type="historical",
                       status="decided")
    db.add(TariffRider(utility_id=u.id, name="Rider DIR", status="effective",
                       disposition="undecided",
                       authority_docket="25-0110-EL-RDR"))
    db.add(TariffRider(utility_id=u.id, name="Rider XYZ", status="effective",
                       disposition="standalone",
                       authority_docket="24-1009-EL-AIR"))
    db.add(TariffRider(utility_id=u.id, name="Rider ABC", status="effective",
                       disposition="undecided", authority_docket=None))
    db.commit()

    t = main.tracker_rows(db)
    assert [x["case"].docket for x in t["review_cases"]] == ["25-0110-EL-RDR"]
    assert t["review_cases"][0]["next_date"] == "2026-12-01"
    assert [x["case"].docket for x in t["deferral_cases"]] == ["26-0579-GA-UNC"]
    assert [x["rider"].name for x in t["undecided_riders"]] == [
        "Rider ABC", "Rider DIR"]
    dir_row = [x for x in t["undecided_riders"]
               if x["rider"].name == "Rider DIR"][0]
    assert dir_row["authority_case"].docket == "25-0110-EL-RDR"
    abc_row = [x for x in t["undecided_riders"]
               if x["rider"].name == "Rider ABC"][0]
    assert abc_row["authority_case"] is None
    # Only the rider whose authority docket is a pending case qualifies;
    # the decided-case authority does not.
    assert [x["rider"].name for x in t["open_authority"]] == ["Rider DIR"]


def test_tracker_page_renders(db):
    import seed
    from fastapi.testclient import TestClient
    seed.seed()
    with TestClient(main.app) as client:
        r = client.get("/tracker")
        assert r.status_code == 200
        assert "Rider &amp; deferral tracker" in r.text
        assert "25-0110-EL-RDR" in r.text
        assert "26-0579-GA-UNC" in r.text
