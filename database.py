"""Database setup: SQLite + SQLAlchemy."""
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

APP_DIR = os.path.dirname(os.path.abspath(__file__))

def _db_path():
    return os.environ.get("RATECASE_DB", os.path.join(APP_DIR, "ratecase.db"))


def _make_engine():
    return create_engine(f"sqlite:///{_db_path()}", connect_args={"check_same_thread": False})


engine = _make_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
Base = declarative_base()


def rebind_db():
    """Re-read RATECASE_DB and rebuild the engine (used by tests)."""
    global engine, SessionLocal
    engine = _make_engine()
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def init_db():
    from models import (  # noqa: F401  (import registers models)
        Utility, ServiceArea, Case, ThreeWayPosition, TariffRider, Document, EarnedROE,
        DiscoveryRequest, ExpertWitness, Scenario, ScenarioAdjustment,
    )
    Base.metadata.create_all(bind=engine)
    # Lightweight migrations for DBs created before these columns existed.
    with engine.begin() as conn:
        cols = [r[1] for r in conn.exec_driver_sql("PRAGMA table_info(utilities)").fetchall()]
        if "ticker" not in cols:
            conn.exec_driver_sql("ALTER TABLE utilities ADD COLUMN ticker VARCHAR(30)")
        if "parent_company" not in cols:
            conn.exec_driver_sql("ALTER TABLE utilities ADD COLUMN parent_company VARCHAR(200)")
        if "notes" not in cols:
            conn.exec_driver_sql("ALTER TABLE utilities ADD COLUMN notes TEXT")
        ccols = [r[1] for r in conn.exec_driver_sql("PRAGMA table_info(cases)").fetchall()]
        if "operating_company" not in ccols:
            conn.exec_driver_sql("ALTER TABLE cases ADD COLUMN operating_company VARCHAR(200)")
        rcols = [r[1] for r in conn.exec_driver_sql("PRAGMA table_info(tariffs_riders)").fetchall()]
        if "authority_docket" not in rcols:
            conn.exec_driver_sql("ALTER TABLE tariffs_riders ADD COLUMN authority_docket VARCHAR(60)")
        if "operating_company" not in rcols:
            conn.exec_driver_sql("ALTER TABLE tariffs_riders ADD COLUMN operating_company VARCHAR(200)")
        pcols = [r[1] for r in conn.exec_driver_sql("PRAGMA table_info(three_way_positions)").fetchall()]
        for col in ("equity_ratio", "cost_of_debt", "opex", "depreciation", "taxes"):
            if col not in pcols:
                conn.exec_driver_sql(f"ALTER TABLE three_way_positions ADD COLUMN {col} FLOAT")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
