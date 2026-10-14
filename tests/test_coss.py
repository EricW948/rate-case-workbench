"""Cost-of-service allocation, rate design, and bill impacts."""
import seed
from models import Case, CustomerClass, ThreeWayPosition
import main


def _case(db, docket="26-0347-EL-AIR"):
    return db.query(Case).filter(Case.docket == docket).one()


def _classes(db, case):
    res = CustomerClass(case_id=case.id, name="Residential", sort_order=1,
                        customers=450000, kwh_annual=5_400_000_000, kw_billing=None,
                        alloc_rate_base=55.0, alloc_opex=60.0,
                        alloc_depreciation=58.0, alloc_taxes=52.0,
                        cur_customer_charge=8.50, cur_demand_charge=0,
                        cur_energy_charge=0.07521,
                        prop_customer_charge=10.00, prop_demand_charge=0)
    com = CustomerClass(case_id=case.id, name="General Service", sort_order=2,
                        customers=50000, kwh_annual=3_600_000_000, kw_billing=900000,
                        alloc_rate_base=45.0, alloc_opex=40.0,
                        alloc_depreciation=42.0, alloc_taxes=48.0,
                        cur_customer_charge=25.00, cur_demand_charge=8.00,
                        cur_energy_charge=0.06200,
                        prop_customer_charge=30.00, prop_demand_charge=9.00)
    db.add(res)
    db.add(com)
    db.commit()
    return res, com


def _position(db, case):
    p = ThreeWayPosition(case_id=case.id, stage="as_filed",
                         revenue_requirement=169.8, roe=10.0, equity_ratio=50.0,
                         cost_of_debt=5.0, rate_base=1000.0, opex=200.0,
                         depreciation=100.0, taxes=50.0)
    db.add(p)
    db.commit()
    return p


def test_allocation_sums_to_source(db):
    seed.seed()
    case = _case(db)
    res, com = _classes(db, case)
    pos = _position(db, case)
    comp = main.rr_source_components(pos)
    # ROR = 50% x 10% + 50% x 5% = 7.5%
    assert abs(comp["ror"] - 0.075) < 1e-9
    rrs = main.class_revenue_requirements([res, com], comp)
    # Allocated dollars must sum back to the source components.
    assert abs(sum(v["rate_base"] for v in rrs.values()) - 1000.0) < 1e-6
    assert abs(sum(v["opex"] for v in rrs.values()) - 200.0) < 1e-6
    assert abs(sum(v["depreciation"] for v in rrs.values()) - 100.0) < 1e-6
    assert abs(sum(v["taxes"] for v in rrs.values()) - 50.0) < 1e-6
    # Residential: 55% of 1000 = 550 RB; return = 550 x 7.5% = 41.25
    r = rrs[res.id]
    assert abs(r["rate_base"] - 550.0) < 1e-6
    assert abs(r["return"] - 41.25) < 1e-6
    assert abs(r["total"] - (41.25 + 120.0 + 58.0 + 26.0)) < 1e-6


def test_allocation_validation(db):
    seed.seed()
    case = _case(db)
    res, com = _classes(db, case)
    assert main.validate_coss_allocations([res, com]) == []
    com.alloc_opex = 30.0  # now sums to 90
    assert len(main.validate_coss_allocations([res, com])) == 1
    assert "O&M" in main.validate_coss_allocations([res, com])[0]


def test_rate_design_plug(db):
    seed.seed()
    case = _case(db)
    res, com = _classes(db, case)
    pos = _position(db, case)
    comp = main.rr_source_components(pos)
    rrs = main.class_revenue_requirements([res, com], comp)
    d = main.design_rates(res, rrs[res.id]["total"])
    # Customer recovery: $10 x 450,000 x 12 / 1M = $54M
    assert abs(d["customer_revenue"] - 54.0) < 1e-6
    assert abs(d["demand_revenue"] - 0.0) < 1e-6
    # Check figure must tie back to the class RR.
    assert abs(d["check_total"] - rrs[res.id]["total"]) < 1e-6
    assert d["energy_charge"] is not None and d["energy_charge"] > 0
    # Demand class: customer + demand recovery both nonzero.
    dc = main.design_rates(com, rrs[com.id]["total"])
    assert abs(dc["customer_revenue"] - 30.0 * 50000 * 12 / 1e6) < 1e-6
    assert abs(dc["demand_revenue"] - 9.0 * 900000 * 12 / 1e6) < 1e-6
    assert abs(dc["check_total"] - rrs[com.id]["total"]) < 1e-6


def test_bill_impacts(db):
    seed.seed()
    case = _case(db)
    res, com = _classes(db, case)
    pos = _position(db, case)
    comp = main.rr_source_components(pos)
    rrs = main.class_revenue_requirements([res, com], comp)
    rows = main.bill_impacts(res, rrs[res.id]["total"])
    assert len(rows) == 3
    assert [r["level"] for r in rows] == ["Low", "Typical", "High"]
    # Typical = average monthly kWh = 5.4B / 450k / 12 = 1000 kWh.
    typ = rows[1]
    assert abs(typ["kwh"] - 1000.0) < 1e-6
    assert typ["current"] is not None and typ["proposed"] is not None
    # Current typical bill: 8.50 + 0.07521 x 1000 = 83.71
    assert abs(typ["current"] - 83.71) < 0.01
    assert typ["change"] is not None and typ["pct"] is not None


def test_coss_import_roundtrip(db, tmp_path):
    """Build a COSS workbook in-memory, validate, load, verify."""
    import io
    from openpyxl import Workbook
    import excel_import
    seed.seed()
    case = _case(db)
    wb = Workbook()
    ws = wb.active
    ws.title = excel_import.DATA_SHEET
    ws.append(["Docket", "Class name", "Customers", "Annual kWh", "Billing kW",
               "Alloc RB%", "Alloc Opex%", "Alloc Depr%", "Alloc Taxes%",
               "Cur cust $", "Cur dem $", "Cur en $", "Prop cust $", "Prop dem $",
               "Notes"])
    ws.append([case.docket, "Residential", 450000, 5400000000, "",
               55.0, 60.0, 58.0, 52.0, 8.50, 0, 0.07521, 10.00, 0, ""])
    ws.append([case.docket, "General Service", 50000, 3600000000, 900000,
               45.0, 40.0, 42.0, 48.0, 25.00, 8.00, 0.062, 30.00, 9.00, ""])
    buf = io.BytesIO()
    wb.save(buf)
    rows, errors = excel_import.validate_coss(buf.getvalue(), db)
    assert errors == [], errors
    assert len(rows) == 2
    n = excel_import.load_coss(db, rows)
    assert n == 2
    got = db.query(CustomerClass).filter(CustomerClass.case_id == case.id).all()
    assert len(got) == 2
    # Bad allocation (sums to 90) must fail validation, all-or-nothing.
    wb2 = Workbook()
    ws2 = wb2.active
    ws2.title = excel_import.DATA_SHEET
    ws2.append(["Docket", "Class name", "Customers", "Annual kWh", "Billing kW",
                "Alloc RB%", "Alloc Opex%", "Alloc Depr%", "Alloc Taxes%",
                "Cur cust $", "Cur dem $", "Cur en $", "Prop cust $", "Prop dem $",
                "Notes"])
    ws2.append([case.docket, "Residential", 450000, 5400000000, "",
                55.0, 50.0, 58.0, 52.0, 8.50, 0, 0.07521, 10.00, 0, ""])
    buf2 = io.BytesIO()
    wb2.save(buf2)
    rows2, errors2 = excel_import.validate_coss(buf2.getvalue(), db)
    assert errors2, "allocation must total 100"
    assert any("O&M" in e for e in errors2)
