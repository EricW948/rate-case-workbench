"""Discovery command center: DR tracking, expert roster, bottleneck views."""
from datetime import date, timedelta
from io import BytesIO

from openpyxl import Workbook

import seed
from seed import upsert_discovery, upsert_expert
from models import Case, DiscoveryRequest, ExpertWitness
import excel_import
import excel_templates


def make_wb(data_rows):
    wb = Workbook()
    ws = wb.active
    ws.title = "Data - fill this in"
    for r in data_rows:
        ws.append(r)
    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf


def _case(db, docket="26-0347-EL-AIR"):
    return db.query(Case).filter(Case.docket == docket).one()


def test_upsert_discovery_is_idempotent(db):
    seed.seed()
    c = _case(db)
    upsert_discovery(db, c, "data_request", "Staff", "Set 1", "1-04",
                     due_date="2026-10-06", assigned_to="Jane Smith", status="open")
    upsert_discovery(db, c, "data_request", "Staff", "Set 1", "1-04",
                     due_date="2026-10-06", assigned_to="Jane Smith", status="in_progress")
    db.commit()
    rows = db.query(DiscoveryRequest).filter(DiscoveryRequest.case_id == c.id).all()
    assert len(rows) == 1
    assert rows[0].status == "in_progress"


def test_upsert_expert_is_idempotent(db):
    seed.seed()
    c = _case(db)
    upsert_expert(db, c, "Dr. Jane Smith", topic="Cost of capital",
                  testimony_due="2026-11-20", status="drafting")
    upsert_expert(db, c, "Dr. Jane Smith", status="filed")
    db.commit()
    rows = db.query(ExpertWitness).filter(ExpertWitness.case_id == c.id).all()
    assert len(rows) == 1
    assert rows[0].status == "filed"
    assert rows[0].topic == "Cost of capital"


DR_HEADER = ["Docket", "Type", "Requesting party", "Set", "Number", "Served", "Due",
             "Assigned to", "Status", "Response summary", "Notes"]


def test_discovery_import_good_row_loads(db):
    seed.seed()
    wb = make_wb([DR_HEADER,
                  ["26-0347-EL-AIR", "data_request", "Staff", "Set 1", "1-04",
                   "2026-09-15", "2026-10-06", "Jane Smith", "in_progress",
                   "Draft with Regulatory", ""]])
    rows, errors = excel_import.validate_discovery(wb, db)
    assert errors == [], errors
    assert len(rows) == 1
    assert rows[0]["due_date"] == "2026-10-06"
    n = excel_import.load_discovery(db, rows)
    assert n == 1
    n = excel_import.load_discovery(db, rows)  # re-upload updates, not duplicates
    assert n == 1
    assert db.query(DiscoveryRequest).count() == 1


def test_discovery_import_bad_rows_get_friendly_errors(db):
    seed.seed()
    wb = make_wb([DR_HEADER,
                  ["26-0347-EL-AIR", "data_request", "Staff", "Set 1", "1-04",
                   "", "", "Jane", "open", "", ""],                    # row 2: no due date
                  ["99-9999-XX-XXX", "data_request", "Staff", "", "",
                   "", "2026-10-06", "", "open", "", ""],             # row 3: unknown docket
                  ["26-0347-EL-AIR", "data_request", "", "", "",
                   "", "2026-10-06", "", "open", "", ""],             # row 4: no party
                  ["26-0347-EL-AIR", "data_request", "Staff", "", "",
                   "", "October 6th", "", "open", "", ""]])           # row 5: bad date
    rows, errors = excel_import.validate_discovery(wb, db)
    assert rows == []
    assert len(errors) == 4, errors
    text = " | ".join(errors)
    assert "Due date" in text and "99-9999-XX-XXX" in text


EX_HEADER = ["Docket", "Name", "Firm", "Topic", "Side", "Testimony due", "Status",
             "Assigned to", "Notes"]


def test_experts_import_good_row_loads(db):
    seed.seed()
    wb = make_wb([EX_HEADER,
                  ["26-0347-EL-AIR", "Dr. Jane Smith", "Acme Consulting",
                   "Cost of capital", "utility", "2026-11-20", "drafting", "John Doe", ""]])
    rows, errors = excel_import.validate_experts(wb, db)
    assert errors == [], errors
    assert rows[0]["testimony_due"] == "2026-11-20"
    n = excel_import.load_experts(db, rows)
    assert n == 1
    assert db.query(ExpertWitness).count() == 1


def test_experts_import_bad_rows_get_friendly_errors(db):
    seed.seed()
    wb = make_wb([EX_HEADER,
                  ["26-0347-EL-AIR", "", "", "", "", "2026-11-20", "", "", ""],   # no name
                  ["26-0347-EL-AIR", "Dr. X", "", "", "", "", "", "", ""]])       # no due date
    rows, errors = excel_import.validate_experts(wb, db)
    assert rows == []
    assert len(errors) == 2, errors


def test_templates_registered():
    assert "discovery" in excel_templates.TEMPLATES
    assert "experts" in excel_templates.TEMPLATES
    assert "discovery" in excel_import.VALIDATORS
    assert "experts" in excel_import.LOADERS
    # templates actually build
    assert len(excel_templates.TEMPLATES["discovery"][1]().getvalue()) > 1000
    assert len(excel_templates.TEMPLATES["experts"][1]().getvalue()) > 1000


def _seed_attention_fixtures(db):
    """Synthetic discovery data (test only) painting every bottleneck."""
    seed.seed()
    c = _case(db)
    today = date.today()
    past = (today - timedelta(days=3)).isoformat()
    soon = (today + timedelta(days=3)).isoformat()
    later = (today + timedelta(days=60)).isoformat()
    upsert_discovery(db, c, "data_request", "Staff", "Set 1", "1-01",
                     due_date=past, assigned_to="Jane Smith", status="open")
    upsert_discovery(db, c, "interrogatory", "OCC", "Set 2", "2-05",
                     due_date=soon, assigned_to="John Doe", status="in_progress")
    upsert_discovery(db, c, "production", "OEG", None, None,
                     due_date=later, assigned_to=None, status="open")
    upsert_discovery(db, c, "data_request", "Staff", "Set 1", "1-09",
                     due_date=past, assigned_to="Jane Smith", status="complete")
    upsert_expert(db, c, "Dr. Jane Smith", topic="Cost of capital",
                  testimony_due=soon, status="drafting", assigned_to="John Doe")
    upsert_expert(db, c, "Dr. Old News", testimony_due=past, status="testified")
    db.commit()
    return c


def test_regulatory_attention_flags_bottlenecks(db):
    _seed_attention_fixtures(db)
    import main
    att = main.regulatory_attention(db)
    assert att["n_open"] == 3
    assert len(att["overdue"]) == 1
    assert att["overdue"][0].number == "1-01"
    assert len(att["due_soon"]) == 1
    assert att["due_soon"][0].number == "2-05"
    assert len(att["unassigned"]) == 1
    assert att["unassigned"][0].requesting_party == "OEG"
    # completed item is not counted; testified expert is not flagged
    assert len(att["expert_due"]) == 1
    assert att["expert_due"][0].name == "Dr. Jane Smith"


def test_discovery_page_and_dashboard_panel(db):
    c = _seed_attention_fixtures(db)
    from fastapi.testclient import TestClient
    import main
    with TestClient(main.app) as client:
        text = client.get("/discovery").text
        assert "Discovery command center" in text
        assert "Where the bottlenecks are" in text
        assert "1-01" in text and "Dr. Jane Smith" in text
        # filters work
        only_open = client.get("/discovery?status=open").text
        assert "1-01" in only_open
        dash = client.get("/").text
        assert "Regulatory attention" in dash
        assert "Overdue" in dash
        # case page shows the discovery section
        case_text = client.get(f"/cases/{c.id}").text
        assert "Discovery &amp; experts" in case_text
        assert "2-05" in case_text


def test_dashboard_hides_panel_when_empty(db):
    seed.seed()
    from fastapi.testclient import TestClient
    import main
    with TestClient(main.app) as client:
        dash = client.get("/").text
        assert "Regulatory attention" not in dash
