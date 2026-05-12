"""Data models for Layer 3 — the model engine.

Three families:
  DealInputs    — fixed facts from the questionnaire (Layer 1). Maps 1:1 to v2 IDs.
  ScenarioParams — the adjustable assumptions for a given run (sliders + commercial lever).
  ModelOutputs  — everything the engine produces; consumed by Layers 4 and 5.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from pydantic import BaseModel, field_validator, model_validator


# ---------------------------------------------------------------------------
# Deal inputs (from Layer 1 questionnaire, v2 IDs)
# ---------------------------------------------------------------------------

class DealInputs(BaseModel):
    """Fixed facts submitted via the intake questionnaire (v2 schema).

    Field names match the questionnaire's variable names from the ID_Mapping sheet.
    Every field that is optional in the questionnaire is Optional here too.
    """

    # Metadata
    deal_id: str                           # INT1
    currency: str = "CNY"                  # INT6

    # Scope
    n_lights: int                          # A5
    existing_failure_rate_pct: Optional[float] = None  # A9 — % per year; None → use product default

    # Cost baseline (annualized, in deal currency)
    annual_electricity_cost: float         # B1
    annual_om_cost: float                  # B2
    annual_capex_budget: Optional[float] = None  # B3 — equipment / replacement budget

    # Deal-level negotiated CAPEX (one-time, all-in incl. trenching + contingency).
    # Used by the 能源托管 dashboard; when present the engine treats it as the
    # authoritative project investment and ignores per-light cost sliders and
    # trenching/contingency calculations.
    project_investment_cny: Optional[float] = None  # B6

    # Multi-year history for trend analysis (能源托管 dashboard contrast view)
    annual_electricity_y_minus_1: Optional[float] = None  # B1a
    annual_electricity_y_minus_2: Optional[float] = None  # B1b
    annual_om_y_minus_1: Optional[float] = None           # B2a
    annual_om_y_minus_2: Optional[float] = None           # B2b

    # Scope detail
    pole_count: Optional[int] = None                      # A5b — distinct from fixture count (A5)

    # Customer expectations & contract economics (informational)
    expected_annual_savings: Optional[float] = None       # G6
    contract_total_value: Optional[float] = None          # H5

    # Operating profile
    existing_wattage_W: float              # C1
    proposed_wattage_W: float              # C2
    hours_per_night: float                 # C3
    annual_hours: Optional[float] = None   # C4 — computed as C3×365 when absent
    tariff_avg_per_kwh: float              # C6

    # O&M detail
    inspection_rounds_yr: float            # D2
    person_days_per_round: Optional[float] = None   # D3
    vehicle_days_per_round: Optional[float] = None  # D4
    annual_fault_tickets: float            # D5

    # Civil works (drive CAPEX, not savings)
    trenching_required: str = "Unknown"    # E1: "Yes" | "No" | "Partial" | "Unknown"
    trenching_length_m: Optional[float] = None    # E2
    trenching_cost_per_km: Optional[float] = None # E3

    # Contract preferences (inform defaults; sliders override)
    contract_length_yrs: Optional[float] = None   # H1

    # Financial context (used in go/no-go logic)
    customer_fiscal_stress: str = "Unknown"  # G1
    subsidy_available: str = "Unknown"       # G3
    data_confidence: str = "Medium"          # K3

    @field_validator("existing_wattage_W")
    @classmethod
    def _wattage_positive(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("existing_wattage_W must be positive")
        return v

    @model_validator(mode="after")
    def _proposed_less_than_existing(self) -> "DealInputs":
        if self.proposed_wattage_W >= self.existing_wattage_W:
            raise ValueError(
                f"proposed_wattage_W ({self.proposed_wattage_W}W) must be less than "
                f"existing_wattage_W ({self.existing_wattage_W}W)"
            )
        return self

    @property
    def effective_annual_hours(self) -> float:
        return self.annual_hours if self.annual_hours else self.hours_per_night * 365

    @property
    def baseline_total_annual_cost(self) -> float:
        """Customer's total annual spend under status quo (B1 + B2 + B3)."""
        return (
            self.annual_electricity_cost
            + self.annual_om_cost
            + (self.annual_capex_budget or 0.0)
        )


# ---------------------------------------------------------------------------
# Scenario parameters (all sliders + commercial lever)
# ---------------------------------------------------------------------------

class ScenarioParams(BaseModel):
    """Everything the user can adjust in the UI for a given run.

    Populated from Layer 2 defaults via from_defaults(); overridden by sliders.
    All monetary values must be in the deal's declared currency (DealInputs.currency).
    """

    # --- Tab 1: Product configuration ---
    product_key: str                              # selects ProductConfig from Layer 2
    hardware_cost_per_light: float                # LC/light, fixture + controller (editable)
    installation_cost_per_light: float            # LC/light, on-site labor per light (editable)
    platform_fee_per_light_yr: float              # LC/light/yr (IoT platform + connectivity)

    @property
    def capex_per_light(self) -> float:
        return self.hardware_cost_per_light + self.installation_cost_per_light

    # --- Tab 2: Savings assumptions (sliders) ---
    adaptive_dimming_pct: float = 12.0        # % further reduction on post-wattage energy
    inspection_reduction_pct: float = 30.0    # % fewer D2 inspection rounds
    ticket_reduction_pct: float = 25.0        # % fewer D5 fault tickets
    failure_reduction_pct: float = 60.0       # % lower failure rate → % of B3 avoided
    solar_grid_offset_pct: float = 75.0       # solar product only: % kWh met by solar

    # Fallback labor/vehicle/repair rates when D3/D4 are not in questionnaire
    person_days_per_round_default: float = 2.0   # used when D3 is absent
    vehicle_days_per_round_default: float = 1.0  # used when D4 is absent
    om_cost_per_person_day: float = 350.0
    om_cost_per_vehicle_day: float = 800.0
    repair_cost_per_ticket: float = 600.0

    # --- Tab 3: Contract & financial structure ---
    contract_yrs: int = 8
    annual_service_fee_per_light: float = 0.0  # LC/light/yr — the fee HPWinner charges
                                                # the customer. Set directly by the internal
                                                # team. Must be > 0 for the engine to run.
    annual_fee_escalator_pct: float = 2.0
    hpwinner_wacc_pct: float = 8.0
    contingency_pct: float = 5.0
    residual_value_pct: float = 10.0

    @classmethod
    def from_defaults(
        cls,
        product_key: str,
        product,           # ProductConfig from Layer 2
        financial,         # FinancialConfig from Layer 2
        deal: Optional[DealInputs] = None,
    ) -> "ScenarioParams":
        """Build a ScenarioParams seeded with Layer 2 defaults.

        annual_service_fee_per_light is initialised to 0 — the team must set it.
        A suggested starting point is available via suggest_fee_per_light().
        """
        contract_yrs = int(deal.contract_length_yrs) if (deal and deal.contract_length_yrs) else int(financial.default_contract_yrs.default)
        return cls(
            product_key=product_key,
            hardware_cost_per_light=product.hardware_cost_per_light_cny,
            installation_cost_per_light=product.installation_cost_per_light_cny,
            platform_fee_per_light_yr=product.platform_fee_per_light_yr_cny,
            contract_yrs=contract_yrs,
            annual_service_fee_per_light=0.0,
            hpwinner_wacc_pct=financial.hpwinner_wacc.default,
            annual_fee_escalator_pct=financial.annual_fee_escalator.default,
            contingency_pct=financial.contingency_on_capex.default,
            residual_value_pct=financial.residual_value_pct.default,
            om_cost_per_person_day=financial.om_cost_per_person_day.default,
            om_cost_per_vehicle_day=financial.om_cost_per_vehicle_day.default,
            repair_cost_per_ticket=financial.repair_cost_per_ticket.default,
        )

    def suggest_fee_per_light(self, deal: DealInputs) -> float:
        """Return a starting-point fee per light for the team to adjust.

        Logic: recover CAPEX over contract + cover platform costs + 30% margin.
        This is a floor estimate — the team should raise it until NPV is acceptable.
        """
        capex_recovery = self.capex_per_light / self.contract_yrs
        platform = self.platform_fee_per_light_yr
        return round((capex_recovery + platform) * 1.30)


# ---------------------------------------------------------------------------
# Output sub-models
# ---------------------------------------------------------------------------

@dataclass
class SavingsAttribution:
    """Annual savings broken down by mechanism — feeds the attribution waterfall."""
    wattage_reduction: float        # deterministic from C1/C2
    adaptive_dimming: float
    inspection_reduction: float
    ticket_reduction: float
    failure_rate_reduction: float
    solar_grid_offset: float        # 0.0 unless solar product

    @property
    def total(self) -> float:
        return (
            self.wattage_reduction
            + self.adaptive_dimming
            + self.inspection_reduction
            + self.ticket_reduction
            + self.failure_rate_reduction
            + self.solar_grid_offset
        )

    def as_dict(self) -> Dict[str, float]:
        return {
            "wattage_reduction": self.wattage_reduction,
            "adaptive_dimming": self.adaptive_dimming,
            "inspection_reduction": self.inspection_reduction,
            "ticket_reduction": self.ticket_reduction,
            "failure_rate_reduction": self.failure_rate_reduction,
            "solar_grid_offset": self.solar_grid_offset,
            "total": self.total,
        }


@dataclass
class CapexBreakdown:
    hardware: float        # n_lights × hardware_cost_per_light
    installation: float    # n_lights × installation_cost_per_light
    trenching: float       # from E2×E3 when applicable
    contingency: float     # % on (hardware + installation + trenching)

    @property
    def total(self) -> float:
        return self.hardware + self.installation + self.trenching + self.contingency


@dataclass
class YearlyCashflow:
    year: int                    # 0 = capex year, 1..N = operating years
    service_fee_revenue: float   # HPWinner receives from customer (0 in year 0)
    platform_costs: float        # IoT fees HPWinner pays (0 in year 0)
    net_cashflow: float          # revenue - costs; year 0 = -capex_total
    cumulative_cashflow: float


@dataclass
class BaselineCosts:
    """Total-cost-of-ownership for both baseline scenarios over contract period."""
    status_quo_total: float       # N × (B1 + B2 + B3), no change
    led_replacement_total: float  # upfront LED capex + N × reduced opex
    laas_customer_total: float    # N × service_fee (what customer pays HPWinner)
    laas_customer_saving_vs_status_quo: float
    laas_customer_saving_vs_led: float


@dataclass
class ModelOutputs:
    """Complete engine output — consumed by Layers 4 (orchestration) and 5 (UI)."""

    deal_id: str
    product_key: str
    config_versions: Dict[str, str]     # stamp from layer2.loader.config_versions()

    # Hero numbers (HPWinner perspective)
    npv: float
    irr: Optional[float]               # None if not computable
    payback_years: Optional[float]      # None if HPWinner never recovers CAPEX in contract

    # Detail
    capex: CapexBreakdown
    annual_savings: SavingsAttribution  # year-1 values (pre-escalation)
    annual_service_fee_y1: float        # what customer pays HPWinner in year 1
    annual_platform_costs: float        # HPWinner's annual IoT opex
    hpwinner_implied_savings_share_pct: Optional[float]  # fee / total_savings — informational

    yearly_cashflows: List[YearlyCashflow]

    # Customer view
    customer_net_saving_y1: float       # (B1+B2+B3) - service_fee, year 1
    customer_net_saving_total: float    # sum over contract period
    baselines: BaselineCosts

    # Risk
    go_nogo: str                        # "go" | "borderline" | "no-go"
    go_nogo_reasons: List[str]
    warnings: List[str]                 # data quality flags (missing D3, B3, etc.)
