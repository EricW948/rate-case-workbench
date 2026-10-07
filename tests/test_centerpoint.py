"""CenterPoint Energy Ohio: ownership transfer to National Fuel, rider authorities, cases."""
import seed


def test_centerpoint_landing_page(db):
    seed.seed()
    from fastapi.testclient import TestClient
    import main
    from main import is_docket
    from models import Utility, TariffRider, Case

    u = db.query(Utility).filter(Utility.name == "CenterPoint Energy Ohio").first()
    assert u is not None
    # ownership transferred 2026-10-01: National Fuel Gas Company
    assert u.ticker == "NYSE: NFG"
    assert u.parent_company == "National Fuel Gas Company"
    assert u.sector == "gas"
    assert "National Fuel" in (u.notes or "")
    assert "$2.62B" in (u.notes or "")

    riders = db.query(TariffRider).filter(TariffRider.utility_id == u.id).all()
    assert len(riders) == 15, len(riders)
    by_name = {r.name: r for r in riders}
    assert by_name["Capital Expenditure Program Rider"].authority_docket == "26-0620-GA-RDR"
    assert by_name["Uncollectible Expense Rider"].authority_docket == "26-0320-GA-UEX"
    assert by_name["Infrastructure Development Rider (IDR)"].authority_docket == "26-0520-GA-IDR"
    assert by_name["Gross Receipts Excise Tax Rider"].authority_docket == "24-0832-GA-AIR"
    # suspended riders carry no invented docket
    assert by_name["Migration Cost Rider"].status == "terminated"
    assert by_name["Migration Cost Rider"].authority_docket is None
    assert by_name["Gas Cost Recovery Rider"].status == "terminated"
    for r in riders:
        if r.authority_docket:
            assert is_docket(r.authority_docket)

    cases = {c.docket: c for c in db.query(Case).filter(Case.utility_id == u.id)}
    assert "24-0832-GA-AIR" in cases
    assert cases["24-0832-GA-AIR"].status == "decided"
    assert "18-0298-GA-AIR" in cases
    assert cases["18-0298-GA-AIR"].status == "decided"

    with TestClient(main.app) as client:
        r = client.get(f"/utilities/{u.id}")
        assert r.status_code == 200
        text = r.text
        assert "National Fuel Gas Company" in text
        assert "NYSE: NFG" in text
        for tab in ("Pending Cases", "Tariffs", "Riders", "Base Rate Case Build"):
            assert tab in text
        assert "CaseRecord.aspx?CaseNo=26-0620-GA-RDR" in text  # CEP rider
