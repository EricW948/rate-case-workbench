"""Enbridge Gas Ohio (fka Dominion Energy Ohio): landing page, rider authorities, cases."""
import seed


def test_enbridge_landing_page(db):
    seed.seed()
    from fastapi.testclient import TestClient
    import main
    from main import is_docket
    from models import Utility, TariffRider, Case

    u = db.query(Utility).filter(Utility.name == "Enbridge Gas Ohio").first()
    assert u is not None
    assert u.ticker == "NYSE: ENB"
    assert u.parent_company == "Enbridge Inc."
    assert u.sector == "gas"
    # old name is gone (renamed in place)
    assert db.query(Utility).filter(Utility.name == "Dominion Energy Ohio").first() is None

    riders = db.query(TariffRider).filter(TariffRider.utility_id == u.id).all()
    assert len(riders) == 10
    by_name = {r.name: r for r in riders}
    assert by_name["Uncollectible Expense Rider"].authority_docket == "26-0319-GA-UEX"
    assert by_name["Pipeline Infrastructure Replacement (PIR) Cost Recovery Charge"].authority_docket == "25-1090-GA-RDR"
    assert by_name["Capital Expenditure Program (CEP) Rider"].authority_docket == "26-0619-GA-RDR"
    assert by_name["Tax Savings Credit Rider"].authority_docket == "23-0894-GA-AIR"
    for r in riders:
        assert r.authority_docket and is_docket(r.authority_docket)

    cases = {c.docket: c for c in db.query(Case).filter(Case.utility_id == u.id)}
    assert "25-1097-GA-AIR" in cases  # pending
    assert cases["25-1097-GA-AIR"].status == "pending"
    assert "23-0894-GA-AIR" in cases  # most recent completed
    assert cases["23-0894-GA-AIR"].status == "decided"

    with TestClient(main.app) as client:
        r = client.get(f"/utilities/{u.id}")
        assert r.status_code == 200
        text = r.text
        assert "Enbridge Inc." in text
        assert "NYSE: ENB" in text
        for tab in ("Pending Cases", "Tariffs", "Riders", "Base Rate Case Build"):
            assert tab in text
        assert "CaseRecord.aspx?CaseNo=25-1097-GA-AIR" in text
        assert "CaseRecord.aspx?CaseNo=26-0619-GA-RDR" in text  # CEP rider
