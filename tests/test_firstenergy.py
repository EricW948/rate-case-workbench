"""FirstEnergy Ohio: rider inventory by operating company, verified authorities, case notes."""
import seed


def test_firstenergy_inventory(db):
    seed.seed()
    from fastapi.testclient import TestClient
    import main
    from main import is_docket
    from models import Utility, TariffRider, Case

    fe = db.query(Utility).filter(Utility.name == "FirstEnergy").first()
    assert fe is not None
    assert fe.ticker == "NYSE: FE"
    assert fe.parent_company == "FirstEnergy Corp."

    riders = db.query(TariffRider).filter(TariffRider.utility_id == fe.id).all()
    # 49 current-tariff riders + 4 proposed roll-into-base = 53 rows
    assert len(riders) == 53, len(riders)
    by_name = {r.name: r for r in riders}

    # spot-check verified authorities
    assert by_name["Alternative Energy Resource"].authority_docket == "25-1136-EL-RDR"
    assert by_name["Tax Savings Adjustment"].authority_docket == "25-1107-EL-RDR"
    assert by_name["Generation Service"].authority_docket == "26-0543-EL-RDR"
    assert by_name["Electric Vehicle Charging"].authority_docket == "26-0163-EL-RDR"
    assert by_name["Legacy Generation Resource"].authority_docket == "24-1062-EL-RDR"
    # unverified riders carry no invented docket
    assert by_name["Residential Distribution Credit"].authority_docket is None
    assert by_name["Fuel"].authority_docket is None

    # operating-company splits
    assert by_name["Partial Service"].operating_company == "Ohio Edison"
    assert by_name["Peak Time Rebate Program"].operating_company == "The Illuminating Company"
    assert by_name["Economic Development (4a)"].operating_company == "The Toledo Edison Company"
    assert by_name["CEI Delta Revenue Recovery"].operating_company == "The Illuminating Company"
    assert by_name["Alternative Energy Resource"].operating_company is None  # all three

    # the four ESP IV riders are proposed to roll into base, not effective
    for n in ("Advanced Metering Infrastructure / Modern Grid", "Delivery Capital Recovery",
              "Distribution Uncollectible", "PIPP Uncollectible"):
        r = by_name[n]
        assert r.status == "proposed", n
        assert r.disposition == "roll_into_base", n
        assert r.authority_docket and is_docket(r.authority_docket), n
    # no leftover short names
    for n in ("Rider AMI", "Rider DCR", "Rider DUN", "Rider PUR"):
        assert n not in by_name

    cases = {c.docket: c for c in db.query(Case).filter(Case.utility_id == fe.id)}
    assert "26-0347-EL-AIR" in cases
    assert cases["26-0347-EL-AIR"].status == "pending"
    assert "2026-1056" in cases["24-0468-EL-AIR"].notes  # appeal noted

    with TestClient(main.app) as client:
        r = client.get(f"/utilities/{fe.id}")
        assert r.status_code == 200
        text = r.text
        assert "NYSE: FE" in text
        assert "FirstEnergy Corp." in text
        assert "Ohio Edison" in text  # operating company column populated
        for tab in ("Pending Cases", "Tariffs", "Riders", "Base Rate Case Build"):
            assert tab in text
        assert "CaseRecord.aspx?CaseNo=26-0543-EL-RDR" in text
