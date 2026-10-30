"""Columbia Gas of Ohio: gas landing page, ticker, rider authorities, formal case 26-0965-GA-AIR."""
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
        # formal application announcement is present (filed 10/19/2026)
        assert "2026-10-19" in text
        # rider authority dockets link out to DIS
        assert "CaseRecord.aspx?CaseNo=25-1058-GA-RDR" in text  # IRP rider
        assert "CaseRecord.aspx?CaseNo=25-0621-GA-RDR" in text  # CEP rider

        # the pre-filing placeholder is retired; the filed case links out to DIS
        cases = {c.docket: c for c in db.query(Case).filter(Case.utility_id == col.id)}
        assert "TBD (pre-filing 2026-09-18)" not in cases
        new = cases["26-0965-GA-AIR"]
        assert is_docket(new.docket)
        r2 = client.get(f"/cases/{new.id}")
        assert r2.status_code == 200
        assert "CaseRecord.aspx?CaseNo=26-0965-GA-AIR" in r2.text
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


def test_columbia_startup_gapfill(db):
    """Production path: the 4cb31ce2 migration created 26-0965-GA-AIR and its
    three as-filed positions but left test_year, position notes, and the FTY1
    gross revenue requirement blank. The 2026-10-26 gap-fill in main.startup()
    must populate them, idempotently, without inventing a rate base."""
    import main
    from models import Utility, Case, ThreeWayPosition

    col = Utility(name="Columbia Gas of Ohio", sector="gas")
    db.add(col)
    db.flush()
    c = Case(docket="26-0965-GA-AIR", utility_id=col.id,
             case_type="historical", status="pending", date_filed="2026-10-19",
             notes="Formal base rate case application filed 10/19/2026. "
                   "Companion dockets 26-0966-GA-ATA, 26-0967-GA-UNC, "
                   "26-0968-GA-AAM.")
    db.add(c)
    db.flush()
    for period, rev, cod in (("TY1 2028", 158.8, 5.18),
                             ("TY2 2029", 103.2, 5.28),
                             ("TY3 2030", 89.3, 5.37)):
        db.add(ThreeWayPosition(
            case_id=c.id, stage="as_filed", period=period,
            revenue_change=rev, roe=10.25, equity_ratio=51.50,
            cost_of_debt=cod,
            capital_structure="51.50% common equity / 48.50% long-term debt"))
    db.commit()

    main.startup()
    main.startup()  # second run must not duplicate or clobber anything
    db.expire_all()

    c = db.query(Case).filter(Case.docket == "26-0965-GA-AIR").first()
    assert c.test_year == "FTY1 CY2028; FTY2 CY2029; FTY3 CY2030"
    pos = {p.period: p for p in
           db.query(ThreeWayPosition).filter(ThreeWayPosition.case_id == c.id).all()}
    assert sorted(pos) == ["TY1 2028", "TY2 2029", "TY3 2030"]
    assert "7.79" in pos["TY1 2028"].notes and "SGS-2" in pos["TY1 2028"].notes
    assert "24,997,442.98" in pos["TY1 2028"].notes
    assert pos["TY1 2028"].revenue_requirement == 604.5
    assert "7.84" in pos["TY2 2029"].notes
    assert "7.88" in pos["TY3 2030"].notes
    assert all(p.rate_base is None for p in pos.values())  # never invented
