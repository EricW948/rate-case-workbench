"""AEP Ohio (Ohio Power Company): landing page, rider authorities, base rate cases."""
import seed


def test_aep_landing_page(db):
    seed.seed()
    from fastapi.testclient import TestClient
    import main
    from main import is_docket
    from models import Utility, TariffRider, Case

    u = db.query(Utility).filter(Utility.name == "AEP Ohio").first()
    assert u is not None
    assert u.ticker == "Nasdaq: AEP"
    assert u.parent_company == "American Electric Power"
    assert u.sector == "electric"

    riders = db.query(TariffRider).filter(TariffRider.utility_id == u.id).all()
    assert len(riders) == 12, len(riders)
    by_name = {r.name: r for r in riders}
    assert by_name["Basic Transmission Cost Rider (BTCR)"].authority_docket == "26-0047-EL-RDR"
    assert by_name["Storm Damage Recovery Rider (SDRR)"].authority_docket == "26-0549-EL-RDR"
    assert by_name["Enhanced Service Reliability Rider (ESRR)"].authority_docket == "26-1027-EL-RDR"
    assert by_name["Tax Savings Credit Rider"].authority_docket == "24-0341-EL-RDR"
    for r in riders:
        assert r.authority_docket and is_docket(r.authority_docket)

    cases = {c.docket: c for c in db.query(Case).filter(Case.utility_id == u.id)}
    assert "25-0392-EL-AIR" in cases  # current case (pilot positions + 2026 updates)
    assert cases["25-0392-EL-AIR"].status == "decided"
    assert "PUCO No. 22" in cases["25-0392-EL-AIR"].notes
    assert "20-585-EL-AIR" in cases  # most recent completed
    assert cases["20-585-EL-AIR"].status == "decided"
    assert "2023-0464" in cases["20-585-EL-AIR"].notes

    with TestClient(main.app) as client:
        r = client.get(f"/utilities/{u.id}")
        assert r.status_code == 200
        text = r.text
        assert "Nasdaq: AEP" in text
        for tab in ("Pending Cases", "Tariffs", "Riders", "Base Rate Case Build"):
            assert tab in text
        assert "CaseRecord.aspx?CaseNo=26-1027-EL-RDR" in text  # ESRR rider
        # decided cases link to DIS from the case page, not the utility page
        case392 = cases["25-0392-EL-AIR"]
        assert "CaseRecord.aspx?CaseNo=25-0392-EL-AIR" in client.get(f"/cases/{case392.id}").text
