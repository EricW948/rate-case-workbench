"""AES Ohio riders carry verified DIS authority dockets."""
import seed


def test_aes_rider_authority_dockets(db):
    seed.seed()
    from fastapi.testclient import TestClient
    import main
    from main import is_docket
    from models import Utility, TariffRider

    aes = db.query(Utility).filter(Utility.name == "AES Ohio").first()
    expected = {
        "Customer Programs Rider": "22-0900-EL-SSO",
        "Economic Development Rider": "23-0279-EL-RDR",
        "Energy Efficiency Rider": "17-1398-EL-POR",
        "Rider DIR": "22-0900-EL-SSO",
        "Rider IIR": "21-1110-EL-RDR",
        "Rider PRO": "22-0900-EL-SSO",
        "Rider RCR": "22-0900-EL-SSO",
        "Rider SCRR": "22-0900-EL-SSO",
        "Tax Savings Credit Rider": "24-1009-EL-AIR",
        "True-Up Rider": "25-0961-EL-RDR",
    }
    for name, docket in expected.items():
        r = db.query(TariffRider).filter(
            TariffRider.utility_id == aes.id, TariffRider.name == name).first()
        assert r is not None, f"missing rider {name}"
        assert r.authority_docket == docket, f"{name}: {r.authority_docket}"
        assert is_docket(r.authority_docket)

    # every AES rider row links out to its DIS case record on the landing page
    with TestClient(main.app) as client:
        text = client.get(f"/utilities/{aes.id}").text
        for docket in set(expected.values()):
            assert f"CaseRecord.aspx?CaseNo={docket}" in text, docket
