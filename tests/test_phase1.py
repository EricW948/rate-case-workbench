"""Phase 1 foundation: peer benchmarks, settlement bridge, deadline machine."""
import seed


def _aes_2598_row(db):
    import main
    from models import Case
    c = db.query(Case).filter(Case.docket == "25-0958-EL-AIR").first()
    rows, _landing = main.benchmark_rows(db, "all")
    return [r for r in rows if r["case"].id == c.id][0]


def test_benchmark_row_math(db):
    """AES 25-0958 TY1 2027: asked 169.82 / 10.10%, stipulated 123.95 / 9.50%."""
    seed.seed()
    db.expire_all()
    row = _aes_2598_row(db)
    assert row["asked"].revenue_change == 169.82
    assert row["final"].revenue_change == 123.95
    assert abs(row["haircut"] - (-45.87)) < 0.01
    assert abs(row["haircut_pct"] - (-27.01)) < 0.05
    assert abs(row["give_roe"] - (-0.60)) < 0.01


def test_benchmark_page_and_sector_filter(db):
    seed.seed()
    from fastapi.testclient import TestClient
    import main
    with TestClient(main.app) as client:
        r = client.get("/benchmarks")
        assert r.status_code == 200
        assert "Peer benchmarks" in r.text
        assert "Ohio landing zone" in r.text
        assert "25-0958-EL-AIR" in r.text
        g = client.get("/benchmarks?sector=gas")
        assert g.status_code == 200
        assert "26-0965-GA-AIR" in g.text
        assert "25-0958-EL-AIR" not in g.text


def test_settlement_bridge_values(db):
    seed.seed()
    db.expire_all()
    import main
    from models import Case
    c = db.query(Case).filter(Case.docket == "25-0958-EL-AIR").first()
    bridge = main.settlement_bridge(db, c)
    assert "TY1 2027" in bridge
    rows = {r["label"]: r for r in bridge["TY1 2027"]}
    assert rows["Revenue change"]["asked"] == "+$169.8M"
    assert rows["Revenue change"]["staff"] == "+$113.8M"  # stored 113.85 formats down
    assert rows["Revenue change"]["final"] == "+$124.0M"
    assert rows["Revenue change"]["give"] == "-$45.9M"
    assert rows["ROE"]["asked"] == "10.10%"
    assert rows["ROE"]["final"] == "9.50%"
    assert rows["ROE"]["give"] == "-0.60 pp"


def test_bridge_absent_for_asked_only_case(db):
    """Columbia 26-0965 has as-filed positions only: no bridge card."""
    seed.seed()
    db.expire_all()
    import main
    from models import Case
    c = db.query(Case).filter(Case.docket == "26-0965-GA-AIR").first()
    assert main.settlement_bridge(db, c) == {}
    from fastapi.testclient import TestClient
    with TestClient(main.app) as client:
        r = client.get(f"/cases/{c.id}")
        assert r.status_code == 200
        assert "Settlement bridge" not in r.text


def test_milestones_seed_and_startup_idempotent(db):
    """Seed path and production path (startup migration, run twice) each
    yield exactly the nine Phase 1 milestones, no duplicates."""
    import main
    from models import Milestone
    seed.seed()
    db.expire_all()
    assert db.query(Milestone).count() == 9
    main.startup()
    main.startup()
    db.expire_all()
    assert db.query(Milestone).count() == 9
    m = db.query(Milestone).filter(
        Milestone.due_date == "2026-11-12",
        Milestone.label.like("%Room 11-A%")).first()
    assert m is not None
    assert m.case.docket == "26-0974-EL-SSO"


def test_deadlines_page_and_dashboard(db):
    seed.seed()
    from fastapi.testclient import TestClient
    import main
    with TestClient(main.app) as client:
        r = client.get("/deadlines")
        assert r.status_code == 200
        assert "Deadline calendar" in r.text
        assert "26-0974-EL-SSO" in r.text
        assert "2026-11-12" in r.text
        d = client.get("/")
        assert d.status_code == 200
        assert "Upcoming deadlines" in d.text
        assert "2026-11-12" in d.text


def test_upcoming_deadlines_sorted(db):
    seed.seed()
    db.expire_all()
    import main
    ups = main.upcoming_deadlines(db, 5)
    assert len(ups) == 5
    dates = [u["date"] for u in ups]
    assert dates == sorted(dates)
    assert dates[0] == "2026-11-12"


def test_benchmark_coverage_names_the_gap(db):
    """Gas used to show one utility because only one gas case had an
    as-filed position on file. After the 2026-10-29 extraction all eight
    do; the dropped list still works for any future position-less case."""
    seed.seed()
    db.expire_all()
    import main
    gas = main.benchmark_coverage(db, "gas")
    assert gas["total"] == 8
    assert gas["shown"] == 8
    assert gas["dropped"] == []
    everything = main.benchmark_coverage(db, "all")
    assert everything["total"] == 18
    assert everything["shown"] == 18
    # A synthetic position-less rate case reappears in the dropped list.
    from models import Utility, Case
    u = Utility(name="Ghost Gas", sector="gas")
    db.add(u)
    db.flush()
    db.add(Case(docket="99-9999-GA-AIR", utility_id=u.id,
                case_type="historical", status="decided"))
    db.commit()
    db.expire_all()
    gas = main.benchmark_coverage(db, "gas")
    assert gas["total"] == 9 and gas["shown"] == 8
    assert [c.docket for c in gas["dropped"]] == ["99-9999-GA-AIR"]
    from fastapi.testclient import TestClient
    with TestClient(main.app) as client:
        g = client.get("/benchmarks?sector=gas")
        assert g.status_code == 200
        assert "Coverage: 8 of 9" in g.text
        assert "99-9999-GA-AIR" in g.text
