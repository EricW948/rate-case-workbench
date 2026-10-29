"""Tier 2 open-docket records: milestones-only cases with no rate-case build."""
import seed


TIER2 = {
    "26-0974-EL-SSO": "AES Ohio",
    "26-0755-EL-ATA": "Duke Energy Ohio (Electric)",
    "26-0505-EL-FOR": "AES Ohio",
}


def test_seed_creates_tier2(db):
    seed.seed()
    from models import Case, ThreeWayPosition
    for docket, util_name in TIER2.items():
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
    for name in ("AES Ohio", "Duke Energy Ohio (Electric)"):
        db.add(Utility(name=name, sector="electric"))
    db.commit()
    main.startup()
    main.startup()
    db.expire_all()
    for docket in TIER2:
        c = db.query(Case).filter(Case.docket == docket).first()
        assert c is not None
        assert c.status == "pending" and c.case_type == "other"
        assert db.query(ThreeWayPosition).filter(
            ThreeWayPosition.case_id == c.id).count() == 0
    assert db.query(Case).filter(Case.docket.in_(list(TIER2))).count() == 3


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
