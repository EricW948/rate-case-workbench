"""Phase 2: executive lens — toggle, EPS translation, sliders, board brief."""
import pytest

import seed
from models import Case, ThreeWayPosition, Utility


def _full_build_case(db, shares=None):
    u = Utility(name="Test Utility", sector="electric",
                shares_outstanding_m=shares)
    db.add(u)
    db.flush()
    c = Case(docket="99-0000-EL-AIR", utility_id=u.id, status="pending")
    db.add(c)
    db.flush()
    # rate base 2000, equity 50%, ROE 10% -> equity earnings 100.0
    db.add(ThreeWayPosition(case_id=c.id, stage="as_filed", period=None,
                            revenue_requirement=500.0, revenue_change=120.0,
                            roe=10.0, equity_ratio=50.0, cost_of_debt=5.0,
                            rate_base=2000.0, opex=200.0, depreciation=100.0,
                            taxes=50.0))
    # staff: rate base 1900, equity 50%, ROE 9.5% -> 90.25
    db.add(ThreeWayPosition(case_id=c.id, stage="staff", period=None,
                            revenue_requirement=470.0, revenue_change=90.0,
                            roe=9.5, equity_ratio=50.0, cost_of_debt=5.0,
                            rate_base=1900.0))
    # final: rate base 1950, equity 50%, ROE 9.75% -> 95.0625
    db.add(ThreeWayPosition(case_id=c.id, stage="final_or_stip",
                            period=None, revenue_requirement=480.0,
                            revenue_change=100.0, roe=9.75,
                            equity_ratio=50.0, cost_of_debt=5.0,
                            rate_base=1950.0))
    db.commit()
    return u, c


def test_eps_translation_math(db):
    import main
    u, c = _full_build_case(db, shares=1000.0)
    db.expire_all()
    c = db.query(Case).filter(Case.id == c.id).first()
    eps = main.eps_translation(db, c)
    assert eps["shares"] == 1000.0
    assert eps["rows"][0]["earnings"] == pytest.approx(100.0)
    assert eps["rows"][0]["eps"] == pytest.approx(0.10)
    assert eps["rows"][1]["earnings"] == pytest.approx(90.25)
    assert eps["rows"][2]["earnings"] == pytest.approx(95.0625)
    assert eps["give_earnings"] == pytest.approx(-4.9375)
    assert eps["give_eps"] == pytest.approx(-0.0049375)


def test_eps_without_shares_shows_earnings_not_eps(db):
    import main
    _u, c = _full_build_case(db, shares=None)
    db.expire_all()
    c = db.query(Case).filter(Case.id == c.id).first()
    eps = main.eps_translation(db, c)
    assert eps["rows"][0]["earnings"] == pytest.approx(100.0)
    assert eps["rows"][0]["eps"] is None
    assert eps["give_eps"] is None


def test_eps_missing_inputs_show_dashes(db):
    import main
    u = Utility(name="No Build Utility", sector="electric")
    db.add(u)
    db.flush()
    c = Case(docket="99-0001-EL-AIR", utility_id=u.id, status="pending")
    db.add(c)
    db.flush()
    db.add(ThreeWayPosition(case_id=c.id, stage="as_filed", period=None,
                            revenue_change=50.0))  # no rate base / equity / ROE
    db.commit()
    db.expire_all()
    c = db.query(Case).filter(Case.id == c.id).first()
    eps = main.eps_translation(db, c)
    assert all(r["earnings"] is None for r in eps["rows"])
    assert main.slider_state(db, c, {}) is None


def test_slider_without_cost_of_debt_still_slides_earnings(db):
    """Cost of debt gates only the RR/ROR rows; earnings and EPS slide
    on rate base, ROE, and equity alone."""
    import main
    u = Utility(name="No Cod Utility", sector="electric",
                shares_outstanding_m=1000.0)
    db.add(u)
    db.flush()
    c = Case(docket="99-0002-EL-AIR", utility_id=u.id, status="pending")
    db.add(c)
    db.flush()
    db.add(ThreeWayPosition(case_id=c.id, stage="as_filed", period=None,
                            revenue_requirement=500.0, roe=10.0,
                            equity_ratio=50.0, rate_base=2000.0))
    db.commit()
    db.expire_all()
    c = db.query(Case).filter(Case.id == c.id).first()
    s = main.slider_state(db, c, {"roe": "11.0"})
    assert s["rr"] is None and s["cod"] is None
    assert s["earnings"] == pytest.approx(110.0)
    assert s["eps"] == pytest.approx(0.11)
    assert s["delta_earnings"] == pytest.approx(10.0)


def test_slider_recompute_uses_engine(db):
    import main
    _u, c = _full_build_case(db, shares=1000.0)
    db.expire_all()
    c = db.query(Case).filter(Case.id == c.id).first()
    base = main.slider_state(db, c, {})
    assert base["roe"] == 10.0
    assert base["rr"] == pytest.approx(500.0)  # 2000*.075 + 200 + 100 + 50
    bumped = main.slider_state(db, c, {"roe": "11.0"})
    # ROR moves 50% x 1pp = 0.5pp on 2000 = +10.0
    assert bumped["rr"] == pytest.approx(510.0)
    assert bumped["delta_rr"] == pytest.approx(10.0)
    assert bumped["earnings"] == pytest.approx(110.0)
    assert bumped["eps"] == pytest.approx(0.11)
    # Out-of-range inputs clamp instead of exploding.
    clamped = main.slider_state(db, c, {"roe": "99"})
    assert clamped["roe"] == 15.0


def test_aes_equity_transcription(db):
    """Staff 50% and the stipulation glide come from the seed's own
    capital-structure strings; as-filed stays blank (implied, not stated)."""
    seed.seed()
    db.expire_all()
    import main
    c = db.query(Case).filter(Case.docket == "25-0958-EL-AIR").first()
    pos = main._ty1_positions(db, c)
    assert pos["staff"].equity_ratio == 50.0
    assert pos["final_or_stip"].equity_ratio == 53.37
    assert pos["as_filed"].equity_ratio is None


def test_lens_pages(db):
    seed.seed()
    db.expire_all()
    import main
    from fastapi.testclient import TestClient
    c = db.query(Case).filter(Case.docket == "25-0958-EL-AIR").first()
    with TestClient(main.app) as client:
        reg = client.get(f"/cases/{c.id}")
        assert reg.status_code == 200
        assert "As-filed vs. Staff vs. final" in reg.text
        assert "Scenario sliders" not in reg.text
        ex = client.get(f"/cases/{c.id}?lens=executive")
        assert ex.status_code == 200
        assert "The bottom line" in ex.text
        assert "EPS translation" in ex.text
        assert "Scenario sliders" in ex.text
        assert "Download board brief (PDF)" in ex.text
        assert "Discovery &amp; experts" not in ex.text
        # AES as-filed build is incomplete, so sliders explain, not invent.
        assert "isn't on file for this case" in ex.text
        # FirstEnergy's as-filed build HAS rate base, ROE, and equity, so
        # its sliders render live (RR rows wait on cost of debt).
        fe = db.query(Case).filter(Case.docket == "26-0347-EL-AIR").first()
        fe_ex = client.get(f"/cases/{fe.id}?lens=executive")
        assert fe_ex.status_code == 200
        assert "Equity earnings" in fe_ex.text
        assert "isn't on file for this case" not in fe_ex.text
        dash_ex = client.get("/?lens=executive")
        assert dash_ex.status_code == 200
        assert "Portfolio" in dash_ex.text
        assert "Total asked" in dash_ex.text
        dash_reg = client.get("/")
        assert "At a glance" in dash_reg.text
        assert "Portfolio" not in dash_reg.text


def test_shares_post_and_pdf(db):
    seed.seed()
    db.expire_all()
    import main
    from fastapi.testclient import TestClient
    aes = db.query(Utility).filter(Utility.name == "AES Ohio").first()
    c = db.query(Case).filter(Case.docket == "25-0958-EL-AIR").first()
    with TestClient(main.app) as client:
        r = client.post(f"/utilities/{aes.id}/shares",
                        data={"shares_outstanding_m": "500",
                              "shares_source": "AES Corp 10-K 2025"},
                        follow_redirects=False)
        assert r.status_code == 303
        db.expire_all()
        aes = db.query(Utility).filter(Utility.id == aes.id).first()
        assert aes.shares_outstanding_m == 500.0
        assert aes.shares_source == "AES Corp 10-K 2025"
        ex = client.get(f"/cases/{c.id}?lens=executive")
        # Stipulated TY1: 1801.83 x 53.37% x 9.50% = ~91.37 -> $0.18/share
        assert "Parent shares: 500.0M" in ex.text
        pdf = client.get(f"/cases/{c.id}/brief.pdf")
        assert pdf.status_code == 200
        assert pdf.headers["content-type"] == "application/pdf"
        assert pdf.content[:4] == b"%PDF"


def test_portfolio_totals(db):
    seed.seed()
    db.expire_all()
    import main
    totals = main.portfolio_totals(db)
    assert totals["n"] == 18  # same coverage rule as benchmarks
    assert totals["asked"] > 0
    assert totals["granted"] > 0
