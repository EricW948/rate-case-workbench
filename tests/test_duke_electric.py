"""Duke Energy Ohio (Electric) buildout: 20-strong rider inventory, pending case."""
import seed
from models import Utility, Case, TariffRider


def _elec(db):
    return db.query(Utility).filter(Utility.name == "Duke Energy Ohio (Electric)").first()


def test_duke_electric_rider_inventory(db):
    seed.seed()
    elec = _elec(db)
    riders = db.query(TariffRider).filter(TariffRider.utility_id == elec.id).all()
    assert len(riders) == 20, [r.name for r in riders]
    by_name = {r.name: r for r in riders}
    assert by_name["Rider BTR - Base Transmission Rider"].authority_docket == "26-0719-EL-RDR"
    assert by_name["Rider PSR - Price Stabilization Rider"].authority_docket == "17-0032-EL-AIR"
    assert by_name["Rider EE-PDRR - Energy Efficiency and Peak Demand Response Recovery Rate"].authority_docket == "16-0576-EL-POR"
    # SSO trio shares one authority docket
    for n in ("Rider RC - Retail Capacity Rider", "Rider RE - Retail Energy Rider",
              "Rider SCR - Supplier Cost Reconciliation Rider"):
        assert by_name[n].authority_docket == "24-0278-EL-SSO"
    # OET: statutory pass-through, authority docket honestly left blank
    oet = by_name["Rider OET - Ohio Excise Tax Rider"]
    assert oet.authority_docket is None
    assert "could not be verified" in oet.notes
    # zero-rated but still applicable riders
    assert "Rate set to $0" in by_name["Rider SGF - Solar Generation Fund Rider"].notes
    assert "Rate set to $0" in by_name["Rider LGR - Legacy Generation Rider"].notes
    assert all(r.status == "effective" for r in riders)


def test_duke_electric_pending_case(db):
    seed.seed()
    c = db.query(Case).filter(Case.docket == "26-0132-EL-AIR").one()
    assert c.status == "pending"
    assert c.date_filed == "2026-02-27"
    assert c.date_staff_report == "2026-09-21"
    assert "12/10/2026" in c.notes
    af = [p for p in c.positions if p.stage == "as_filed"][0]
    assert af.revenue_change == 90.0
    assert "UNVERIFIED" in af.notes


def test_duke_electric_history_enriched(db):
    seed.seed()
    c = db.query(Case).filter(Case.docket == "21-0887-EL-AIR").one()
    assert c.date_filed == "2021-09-01"
    assert "Sheet 85" in c.notes
    c17 = db.query(Case).filter(Case.docket == "17-0032-EL-AIR").one()
    assert c17.date_filed == "2017-01-31"


def test_duke_electric_identity(db):
    seed.seed()
    elec = _elec(db)
    assert elec.parent_company == "Duke Energy"
    assert elec.ticker == "NYSE: DUK"
