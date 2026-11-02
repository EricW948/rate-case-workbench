"""Tier 2 open-docket records: milestones-only cases with no rate-case build."""
import seed


TIER2 = {
    "26-0974-EL-SSO": "AES Ohio",
    "26-0755-EL-ATA": "Duke Energy Ohio (Electric)",
    "26-0505-EL-FOR": "AES Ohio",
}

# Full 8-utility sweep (2026-11-02 DIS inventory). Pinned independently of
# seed.SWEEP_TIER2 so the test guards the expected set, not just the code.
SWEEP = {
    "26-0501-EL-FOR": "AEP Ohio",
    "25-1039-EL-ATR": "AEP Ohio",
    "25-0110-EL-RDR": "AEP Ohio",
    "23-1017-EL-UNC": "AEP Ohio",
    "26-0612-EL-UNC": "AEP Ohio",
    "25-0550-EL-UNC": "AEP Ohio",
    "24-0364-EL-UNC": "AEP Ohio",
    "26-1024-EL-RDR": "AES Ohio",
    "25-0900-EL-RDR": "AES Ohio",
    "26-0541-EL-RDR": "AES Ohio",
    "26-0961-EL-UNC": "AES Ohio",
    "26-0033-GA-UNC": "CenterPoint Energy Ohio",
    "23-1020-GA-RDR": "CenterPoint Energy Ohio",
    "24-0820-GA-RDR": "CenterPoint Energy Ohio",
    "26-0121-GA-UNC": "Columbia Gas of Ohio",
    "23-0503-EL-FOR": "Duke Energy Ohio (Electric)",
    "25-0154-EL-RDR": "Duke Energy Ohio (Electric)",
    "24-0637-EL-RDR": "Duke Energy Ohio (Electric)",
    "26-0118-GA-UNC": "Duke Energy Ohio (Gas)",
    "26-0029-GA-UNC": "Duke Energy Ohio (Gas)",
    "25-0139-GA-UNC": "Duke Energy Ohio (Gas)",
    "26-0119-GA-UNC": "Enbridge Gas Ohio",
    "26-0504-EL-FOR": "FirstEnergy",
    "26-0798-EL-UNC": "FirstEnergy",
    "25-0240-EL-UNC": "FirstEnergy",
    "23-0893-EL-RDR": "FirstEnergy",
    "22-0892-EL-RDR": "FirstEnergy",
    "26-0706-EL-AEC": "AEP Ohio",
    "25-1096-EL-AEC": "AEP Ohio",
    "25-0134-EL-AEC": "AEP Ohio",
    "25-0133-EL-AEC": "AEP Ohio",
    "24-0734-EL-AEC": "AEP Ohio",
    "24-0383-EL-AEC": "AEP Ohio",
    "24-0025-EL-AEC": "AEP Ohio",
    "23-0948-EL-AEC": "AEP Ohio",
    "23-0891-EL-AEC": "AEP Ohio",
    "23-0866-EL-AEC": "AEP Ohio",
    "23-0858-EL-AEC": "AEP Ohio",
    "26-0748-EL-AEC": "Duke Energy Ohio (Electric)",
    "26-0680-EL-AEC": "Duke Energy Ohio (Electric)",
    "24-0146-EL-AEC": "FirstEnergy",
    "24-0278-EL-SSO": "Duke Energy Ohio (Electric)",
    "26-1014-GA-UNC": "Columbia Gas of Ohio",
    "26-0579-GA-UNC": "Columbia Gas of Ohio",
}

ALL_TIER2 = {**TIER2, **SWEEP}


def test_seed_creates_tier2(db):
    seed.seed()
    from models import Case, ThreeWayPosition
    for docket, util_name in ALL_TIER2.items():
        c = db.query(Case).filter(Case.docket == docket).first()
        assert c is not None
        assert c.status == "pending"
        assert c.case_type == "other"
        assert c.utility.name == util_name
        assert db.query(ThreeWayPosition).filter(
            ThreeWayPosition.case_id == c.id).count() == 0
        assert "Tier 2" in c.notes


def test_startup_migration_creates_tier2(db):
    """Production path: existing DBs never re-run seed, so the startup
    migration must create the Tier 2 records itself, idempotently."""
    import main
    from models import Utility, Case, ThreeWayPosition
    for name, sector in (
            ("AEP Ohio", "electric"),
            ("AES Ohio", "electric"),
            ("CenterPoint Energy Ohio", "gas"),
            ("Columbia Gas of Ohio", "gas"),
            ("Duke Energy Ohio (Electric)", "electric"),
            ("Duke Energy Ohio (Gas)", "gas"),
            ("Enbridge Gas Ohio", "gas"),
            ("FirstEnergy", "electric")):
        db.add(Utility(name=name, sector=sector))
    db.commit()
    main.startup()
    main.startup()
    db.expire_all()
    for docket in ALL_TIER2:
        c = db.query(Case).filter(Case.docket == docket).first()
        assert c is not None
        assert c.status == "pending" and c.case_type == "other"
        assert db.query(ThreeWayPosition).filter(
            ThreeWayPosition.case_id == c.id).count() == 0
    assert db.query(Case).filter(Case.docket.in_(list(ALL_TIER2))).count() == 47


def test_tier2_case_page_renders(db):
    """A Tier 2 case has no positions; its page must still render 200."""
    seed.seed()
    from fastapi.testclient import TestClient
    import main
    from models import Case
    c = db.query(Case).filter(Case.docket == "26-0974-EL-SSO").first()
    with TestClient(main.app) as client:
        r = client.get(f"/cases/{c.id}")
        assert r.status_code == 200
        assert "26-0974-EL-SSO" in r.text
        assert "Tier 2" in r.text


def test_sweep_case_page_renders(db):
    """A sweep record (no milestones at all) must still render 200."""
    seed.seed()
    from fastapi.testclient import TestClient
    import main
    from models import Case
    c = db.query(Case).filter(Case.docket == "26-0501-EL-FOR").first()
    with TestClient(main.app) as client:
        r = client.get(f"/cases/{c.id}")
        assert r.status_code == 200
        assert "26-0501-EL-FOR" in r.text
        assert "Tier 2" in r.text
