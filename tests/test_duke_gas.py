"""Duke Energy Ohio (Gas): landing page, rider authorities, gas base rate cases."""
import seed


def test_duke_gas_landing_page(db):
    seed.seed()
    from fastapi.testclient import TestClient
    import main
    from main import is_docket
    from models import Utility, TariffRider, Case

    u = db.query(Utility).filter(Utility.name == "Duke Energy Ohio (Gas)").first()
    assert u is not None
    assert u.ticker == "NYSE: DUK"
    assert u.parent_company == "Duke Energy"
    assert u.sector == "gas"

    riders = db.query(TariffRider).filter(TariffRider.utility_id == u.id).all()
    assert len(riders) == 26  # 20 effective + 6 withdrawn/cancelled
    by_name = {r.name: r for r in riders}
    assert by_name["Rider CEP - Capital Expenditure Program Rider"].authority_docket == "25-0618-GA-RDR"
    assert by_name["Rider PIPP - Percentage of Income Payment Plan"].authority_docket == "26-0418-GA-PIP"
    assert by_name["Infrastructure Development Rider - IDR"].authority_docket == "26-0518-GA-IDR"
    assert by_name["Rider UE-G - Uncollectible Expense Rider"].authority_docket == "26-0318-GA-UEX"
    assert by_name["Rider GCR - Gas Cost Recovery"].status == "terminated"
    for r in riders:
        assert r.authority_docket and is_docket(r.authority_docket)

    cases = {c.docket: c for c in db.query(Case).filter(Case.utility_id == u.id)}
    assert "26-0635-GA-AIR" in cases  # pending
    assert cases["26-0635-GA-AIR"].status == "pending"
    assert "22-0507-GA-AIR" in cases  # most recent completed
    assert cases["22-0507-GA-AIR"].status == "decided"

    with TestClient(main.app) as client:
        r = client.get(f"/utilities/{u.id}")
        assert r.status_code == 200
        text = r.text
        assert "NYSE: DUK" in text
        for tab in ("Pending Cases", "Tariffs", "Riders", "Base Rate Case Build"):
            assert tab in text
        assert "CaseRecord.aspx?CaseNo=26-0635-GA-AIR" in text
        assert "CaseRecord.aspx?CaseNo=25-0618-GA-RDR" in text  # CEP rider
