"""Data model for the Distribution Rate Case workbench (v1)."""
from sqlalchemy import Column, Integer, String, Float, Text, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship
from database import Base


class Utility(Base):
    __tablename__ = "utilities"
    id = Column(Integer, primary_key=True)
    name = Column(String(200), unique=True, nullable=False)
    sector = Column(String(20), default="electric")  # electric | gas | water
    ticker = Column(String(30))  # e.g. "NYSE: AES"
    parent_company = Column(String(200))  # e.g. "NiSource"
    shares_outstanding_m = Column(Float)  # parent shares, millions — hand-entered from the 10-K, never guessed
    shares_source = Column(String(200))  # e.g. "AES Corp 10-K 2025"
    notes = Column(Text)  # e.g. ownership changes, former names

    service_areas = relationship("ServiceArea", back_populates="utility", cascade="all, delete-orphan")
    cases = relationship("Case", back_populates="utility")
    riders = relationship("TariffRider", back_populates="utility")
    earned_returns = relationship("EarnedROE", back_populates="utility", cascade="all, delete-orphan")


class EarnedROE(Base):
    """Actual earned ROE per calendar year, from annual earnings filings
    (PUCO earnings reports, 10-Ks, SEET filings) - not from the rate case."""
    __tablename__ = "earned_roe"
    id = Column(Integer, primary_key=True)
    utility_id = Column(Integer, ForeignKey("utilities.id"), nullable=False)
    year = Column(Integer, nullable=False)
    earned_roe = Column(Float)  # percent, e.g. 10.42
    source = Column(String(200))  # e.g. "2024 PUCO earnings report"
    notes = Column(Text)

    utility = relationship("Utility", back_populates="earned_returns")

    __table_args__ = (UniqueConstraint("utility_id", "year", name="uq_earned_roe_utility_year"),)


class ServiceArea(Base):
    __tablename__ = "service_areas"
    id = Column(Integer, primary_key=True)
    utility_id = Column(Integer, ForeignKey("utilities.id"), nullable=False)
    name = Column(String(200), nullable=False)

    utility = relationship("Utility", back_populates="service_areas")


class Case(Base):
    __tablename__ = "cases"
    id = Column(Integer, primary_key=True)
    docket = Column(String(60), unique=True, nullable=False)
    utility_id = Column(Integer, ForeignKey("utilities.id"), nullable=False)
    operating_company = Column(String(200))  # e.g. "Ohio Edison" (FirstEnergy)
    case_type = Column(String(20), default="historical")  # historical | prospective | tariff | rider | other
    status = Column(String(20), default="pending")  # decided | pending | stipulated
    date_filed = Column(String(10))        # YYYY-MM-DD
    date_staff_report = Column(String(10))  # YYYY-MM-DD
    date_order = Column(String(10))        # YYYY-MM-DD
    test_year = Column(String(80))
    date_certain = Column(String(10))
    notes = Column(Text)

    utility = relationship("Utility", back_populates="cases")
    positions = relationship("ThreeWayPosition", back_populates="case", cascade="all, delete-orphan")
    documents = relationship("Document", back_populates="case", cascade="all, delete-orphan")
    discovery = relationship("DiscoveryRequest", back_populates="case", cascade="all, delete-orphan")
    experts = relationship("ExpertWitness", back_populates="case", cascade="all, delete-orphan")
    scenarios = relationship("Scenario", back_populates="case", cascade="all, delete-orphan")
    milestones = relationship("Milestone", back_populates="case", cascade="all, delete-orphan")
    customer_classes = relationship("CustomerClass", back_populates="case",
                                    cascade="all, delete-orphan")


class ThreeWayPosition(Base):
    """One stage of the as-filed -> staff -> final comparison for a case."""
    __tablename__ = "three_way_positions"
    id = Column(Integer, primary_key=True)
    case_id = Column(Integer, ForeignKey("cases.id"), nullable=False)
    stage = Column(String(20), nullable=False)  # as_filed | staff | final_or_stip
    period = Column(String(40))  # optional, e.g. "TY1 2027" for multi-year plans
    revenue_requirement = Column(Float)  # $M
    revenue_change = Column(Float)        # $M annual change vs. current rates
    roe = Column(Float)                   # percent, e.g. 9.84
    capital_structure = Column(String(120))  # free text, e.g. "49.12% debt / 50.88% equity"
    equity_ratio = Column(Float)          # percent equity, e.g. 50.88 — powers scenario math
    cost_of_debt = Column(Float)          # percent, pre-tax — powers scenario math
    rate_base = Column(Float)              # $M
    opex = Column(Float)                   # $M operating expenses — powers scenario math
    depreciation = Column(Float)           # $M depreciation expense — powers scenario math
    taxes = Column(Float)                  # $M income + other taxes — powers scenario math
    notes = Column(Text)

    case = relationship("Case", back_populates="positions")

    __table_args__ = (UniqueConstraint("case_id", "stage", "period", name="uq_case_stage_period"),)


class TariffRider(Base):
    __tablename__ = "tariffs_riders"
    id = Column(Integer, primary_key=True)
    utility_id = Column(Integer, ForeignKey("utilities.id"), nullable=False)
    name = Column(String(200), nullable=False)
    kind = Column(String(20), default="rider")  # tariff | rider
    operating_company = Column(String(200))  # e.g. "Ohio Edison" (FirstEnergy)
    status = Column(String(20), default="effective")  # effective | proposed | terminated
    annual_revenue = Column(Float)  # $M, optional
    disposition = Column(String(20), default="undecided")  # roll_into_base | standalone | undecided
    authority_docket = Column(String(60))  # PUCO case that established it, e.g. "23-0279-EL-RDR"
    notes = Column(Text)

    utility = relationship("Utility", back_populates="riders")


class Milestone(Base):
    """Phase 1 deadline machine: a dated obligation on a case — hearing,
    testimony, comments, filing, decision. Merged with open discovery and
    pending expert testimony on the /deadlines page."""
    __tablename__ = "milestones"
    id = Column(Integer, primary_key=True)
    case_id = Column(Integer, ForeignKey("cases.id"), nullable=False)
    label = Column(String(300), nullable=False)
    due_date = Column(String(10), nullable=False)  # YYYY-MM-DD
    kind = Column(String(20), default="deadline")
    notes = Column(Text)
    case = relationship("Case", back_populates="milestones")


class Document(Base):
    __tablename__ = "documents"
    id = Column(Integer, primary_key=True)
    case_id = Column(Integer, ForeignKey("cases.id"))
    docket = Column(String(60))
    doc_type = Column(String(60))  # application | staff_report | stipulation | order | other
    file_path = Column(String(500))
    page_count = Column(Integer)

    case = relationship("Case", back_populates="documents")


class DiscoveryRequest(Base):
    """One DR / discovery item in a case, owned by someone, due on a date.

    Regulatory Affairs is the quarterback: every item is assigned out, tracked,
    and its response assembled inside the prescribed time frame.
    """
    __tablename__ = "discovery_requests"
    id = Column(Integer, primary_key=True)
    case_id = Column(Integer, ForeignKey("cases.id"), nullable=False)
    request_type = Column(String(40), default="data_request")
    # data_request | interrogatory | production | admission | deposition | motion | other
    requesting_party = Column(String(120))  # e.g. "Staff", "OCC", "OEG"
    set_number = Column(String(40))  # e.g. "Set 3"
    number = Column(String(40))  # e.g. "3-12"
    served_date = Column(String(10))  # YYYY-MM-DD
    due_date = Column(String(10))     # YYYY-MM-DD
    assigned_to = Column(String(120))  # person owning the response
    status = Column(String(20), default="open")
    # open | in_progress | in_review | complete | withdrawn
    response_summary = Column(Text)
    notes = Column(Text)

    case = relationship("Case", back_populates="discovery")


class ExpertWitness(Base):
    """Expert witness roster per case, with testimony deadlines."""
    __tablename__ = "expert_witnesses"
    id = Column(Integer, primary_key=True)
    case_id = Column(Integer, ForeignKey("cases.id"), nullable=False)
    name = Column(String(200), nullable=False)
    firm = Column(String(200))
    topic = Column(String(200))  # e.g. "Cost of capital"
    side = Column(String(20), default="utility")  # utility | staff | intervenor
    testimony_due = Column(String(10))  # YYYY-MM-DD
    status = Column(String(20), default="retained")
    # retained | drafting | filed | testified | withdrawn
    assigned_to = Column(String(120))  # internal owner shepherding the testimony
    notes = Column(Text)

    case = relationship("Case", back_populates="experts")


class Scenario(Base):
    """One rate-making scenario for a case: a methodology bundle plus the
    numbers behind it. The team toggles levers (test period, rate base
    measurement, ROE method, capital structure, adjustments) and the app
    computes the revenue requirement, so scenarios can be compared side by
    side for the maximum defensible return."""
    __tablename__ = "scenarios"
    id = Column(Integer, primary_key=True)
    case_id = Column(Integer, ForeignKey("cases.id"), nullable=False)
    name = Column(String(200), nullable=False)
    test_period_type = Column(String(30), default="historic_adjusted")
    # historic | historic_adjusted | future_test_year | multiyear_plan | formula_rate
    rate_base_method = Column(String(20), default="average_13mo")
    # average_13mo | year_end
    date_certain = Column(String(10))  # YYYY-MM-DD, optional
    roe_method = Column(String(30), default="dcf")
    # dcf | capm | risk_premium | comparable_earnings | other
    roe = Column(Float)          # authorized ROE under this scenario, %
    equity_ratio = Column(Float)  # % of capital structure that is equity
    cost_of_debt = Column(Float)  # %, pre-tax
    rate_base = Column(Float)     # $M
    opex = Column(Float, default=0)         # $M operating expenses
    depreciation = Column(Float, default=0)  # $M depreciation expense
    taxes = Column(Float, default=0)         # $M income + other taxes
    risk_level = Column(String(10), default="unrated")
    # low | medium | high | unrated — litigation risk, calibrated by Eric
    risk_note = Column(Text)
    notes = Column(Text)

    case = relationship("Case", back_populates="scenarios")
    adjustments = relationship("ScenarioAdjustment", back_populates="scenario",
                               cascade="all, delete-orphan")


class ScenarioAdjustment(Base):
    """One pro forma adjustment inside a scenario: annualization,
    normalization, or a known-and-measurable change, with its $M impact
    on the revenue requirement (+ or -)."""
    __tablename__ = "scenario_adjustments"
    id = Column(Integer, primary_key=True)
    scenario_id = Column(Integer, ForeignKey("scenarios.id"), nullable=False)
    name = Column(String(200))
    category = Column(String(30), default="other")
    # annualization | normalization | known_measurable | other
    amount = Column(Float, default=0)  # $M

    scenario = relationship("Scenario", back_populates="adjustments")


class CustomerClass(Base):
    """One customer class in a case's cost-of-service study.

    Holds test-year billing determinants, COSS allocation percentages
    (which must sum to 100 per component across the case's classes),
    and current + proposed rate elements. The proposed energy charge is
    always computed by the engine (it is the plug that recovers the
    class revenue requirement after customer and demand charges).
    """
    __tablename__ = "customer_classes"
    id = Column(Integer, primary_key=True)
    case_id = Column(Integer, ForeignKey("cases.id"), nullable=False)
    name = Column(String(200), nullable=False)  # e.g. "Residential"
    sort_order = Column(Integer, default=0)
    # Billing determinants (test year, weather-normalized)
    customers = Column(Float)      # average customer count
    kwh_annual = Column(Float)     # total annual kWh
    kw_billing = Column(Float)     # billing demand kW (demand-metered classes)
    # COSS allocation percentages — sum to 100 per component across classes
    alloc_rate_base = Column(Float)    # %
    alloc_opex = Column(Float)         # %
    alloc_depreciation = Column(Float) # %
    alloc_taxes = Column(Float)        # %
    # Current rate elements
    cur_customer_charge = Column(Float)  # $/customer/month
    cur_demand_charge = Column(Float)    # $/kW
    cur_energy_charge = Column(Float)    # $/kWh
    # Proposed rate elements (policy inputs; energy charge is computed)
    prop_customer_charge = Column(Float)  # $/customer/month
    prop_demand_charge = Column(Float)     # $/kW
    notes = Column(Text)

    case = relationship("Case", back_populates="customer_classes")

    __table_args__ = (UniqueConstraint("case_id", "name",
                                      name="uq_customer_class_case_name"),)
