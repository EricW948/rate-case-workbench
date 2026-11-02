"""Phase 3: next-filing countdown — each utility's next dated step, in days.

Pinned to a fixed `today` so the tests never depend on the real calendar
(the Phase 1 deadline tests lean on live dates and will age out)."""
from datetime import date

import main
from models import Case, Milestone, Utility


def _mk(db, utility_name, docket, milestones):
    u = Utility(name=utility_name)
    db.add(u)
    db.flush()
    c = Case(docket=docket, utility_id=u.id)
    db.add(c)
    db.flush()
    for label, due, kind in milestones:
        db.add(Milestone(case_id=c.id, label=label, due_date=due, kind=kind))
    db.commit()
    return u


def test_countdown_days_and_order(db):
    today = date(2026, 11, 2)
    _mk(db, "B Utility", "26-0001-EL-UNC",
         [("Evidentiary hearing", "2026-11-12", "hearing")])
    _mk(db, "A Utility", "26-0002-EL-UNC",
         [("Intervenor testimony", "2026-11-05", "testimony"),
          ("Comments due", "2026-10-20", "comments")])
    _mk(db, "C Utility", "26-0003-EL-UNC", [])
    rows = main.countdown_rows(db, today=today)
    assert [r["utility"] for r in rows] == ["A Utility", "B Utility", "C Utility"]
    a, b, c = rows
    assert (a["days"], a["days_label"]) == (3, "In 3 days")
    assert a["next"]["docket"] == "26-0002-EL-UNC"
    assert a["overdue_count"] == 1 and a["upcoming_count"] == 1
    assert (b["days"], b["days_label"]) == (10, "In 10 days")
    assert c["days"] is None and c["next"] is None
    assert c["days_label"] == "No dated next step on file"


def test_countdown_today_and_tomorrow_labels(db):
    today = date(2026, 11, 2)
    _mk(db, "Today Utility", "26-0010-EL-UNC",
         [("Hearing", "2026-11-02", "hearing")])
    _mk(db, "Tomorrow Utility", "26-0011-EL-UNC",
         [("Testimony due", "2026-11-03", "testimony")])
    rows = main.countdown_rows(db, today=today)
    by_name = {r["utility"]: r for r in rows}
    assert (by_name["Today Utility"]["days"],
            by_name["Today Utility"]["days_label"]) == (0, "Today")
    assert (by_name["Tomorrow Utility"]["days"],
            by_name["Tomorrow Utility"]["days_label"]) == (1, "Tomorrow")


def test_countdown_page_renders(db):
    import seed
    from fastapi.testclient import TestClient
    seed.seed()
    with TestClient(main.app) as client:
        r = client.get("/countdown")
        assert r.status_code == 200
        assert "Next-filing countdown" in r.text
        assert "26-0974-EL-SSO" in r.text
        assert "2026-11-12" in r.text
