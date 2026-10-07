"""Per-test isolated SQLite database."""
import os
import pytest

import database


@pytest.fixture()
def db(tmp_path):
    os.environ["RATECASE_DB"] = str(tmp_path / "test.db")
    database.rebind_db()
    database.init_db()
    session = database.SessionLocal()
    yield session
    session.close()
    os.environ.pop("RATECASE_DB", None)
