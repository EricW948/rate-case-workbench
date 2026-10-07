"""Columbia Gas of Ohio: gas landing page, ticker, rider authorities, new pre-filing case."""
import seed


def test_columbia_landing_page(db):
    seed.seed()
    from fastapi.testclient import TestClient
    import main
    from main import is_docket, dis_url
    from models import Utility, TariffRider, Case

    col = db.query(Utility).filter(Utility.name == "Columbia Gas of Ohio").first()
    assert col is not None
    assert col.ticker == "NYSE: NI"
    assert col.sector == "gas"

    with TestClient(main.app) as client:
        r = client.get(f"/utilities/{col.id}")
        assert r.status_code == 200
        text = r.text
        assert "NYSE: NI" in text
        for tab in ("Pending Cases", "Tariffs", "Riders", "Base Rate Case Build"):
            assert tab in text
        # new base rate case announcement is present
        assert "2026-09-18" in text
        # rider authority dockets link out to DIS
        assert "CaseRecord.aspx?CaseNo=25-1058-GA-RDR" in text  # IRP rider
        assert "CaseRecord.aspx?CaseNo=25-0621-GA-RDR" in text  # CEP rider

        # pre-filing case has no bogus DIS link; decided case links fine
        cases = {c.docket: c for c in db.query(Case).filter(Case.utility_id == col.id)}
        pre = cases["TBD (pre-filing 2026-09-18)"]
        assert not is_docket(pre.docket)
        r2 = client.get(f"/cases/{pre.id}")
        assert r2.status_code == 200
        assert "dis.puc.state.oh.us" not in r2.text  # no DIS button for TBD docket
        assert "68.05" in r2.text  # proposed 2028 residential base rate in notes
        old = cases["21-0637-GA-AIR"]
        assert is_docket(old.docket)
        assert "CaseRecord.aspx?CaseNo=21-0637-GA-AIR" in client.get(f"/cases/{old.id}").text

    # rider inventory fully populated from the tariff sheet
    riders = db.query(TariffRider).filter(TariffRider.utility_id == col.id).all()
    assert len(riders) == 11
    by_name = {r.name: r for r in riders}
    assert by_name["Infrastructure Replacement Program Rider"].authority_docket == "25-1058-GA-RDR"
    assert by_name["Infrastructure Development Rider"].authority_docket == "25-0521-GA-AIR"
    assert by_name["Uncollectible Expense Rider"].authority_docket == "26-0321-GA-UEX"
    assert all(is_docket(r.authority_docket) for r in riders)
    assert all(r.status == "effective" for r in riders)

    # seed is idempotent — re-running keeps one copy of everything
    seed.seed()
    assert db.query(Utility).filter(Utility.name == "Columbia Gas of Ohio").count() == 1
    assert db.query(TariffRider).filter(TariffRider.utility_id == col.id).count() == 11


def test_is_docket():
    from main import is_docket
    assert is_docket("25-0958-EL-AIR")
    assert is_docket("26-0121-GA-UNC")
    assert is_docket("21-0637-GA-AIR")
    assert not is_docket("TBD (pre-filing 2026-09-18)")
    assert not is_docket("")
    assert not is_docket(None)
