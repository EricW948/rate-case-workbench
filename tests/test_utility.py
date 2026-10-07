"""Utility landing page: ticker, tab boxes, external tools."""
import seed


def test_utility_landing_page(db):
    seed.seed()
    from fastapi.testclient import TestClient
    import main
    from models import Utility
    with TestClient(main.app) as client:
        aes = db.query(Utility).filter(Utility.name == "AES Ohio").first()
        assert aes is not None
        assert aes.ticker == "NYSE: AES"

        r = client.get(f"/utilities/{aes.id}")
        assert r.status_code == 200
        text = r.text
        assert "NYSE: AES" in text
        assert "Model utility" in text
        for tab in ("Pending Cases", "Tariffs", "Riders", "Base Rate Case Build"):
            assert tab in text
        for tool in ("pjm.com", "ferc.gov", "dis.puc.state.oh.us"):
            assert tool in text
        # verified DIS case-record link for the pending AES docket
        assert "CaseRecord.aspx?CaseNo=25-0958-EL-AIR" in text
        # legal authorities for counsel in the build section
        assert "section-4909.15" in text and "section-4909.18" in text

        dash = client.get("/").text
        assert f"/utilities/{aes.id}" in dash
        # AES leads the dashboard as the model utility
        assert dash.index("AES Ohio") < dash.index("AEP Ohio")

        assert client.get("/utilities/99999").status_code == 404
