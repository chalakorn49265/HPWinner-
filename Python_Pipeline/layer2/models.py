"""Pydantic models for the Layer 2 assumptions store.

Three config families, each loaded from a versioned YAML:
  ProductsConfig  — product_key → ProductConfig (capex, lifetime, failure rates, etc.)
  SavingsConfig   — mechanism_key → SavingsMechanism (sliders with min/default/max + source)
  FinancialConfig — named financial params, each a RangedParam (WACC, escalator, cost benchmarks)

These models are the contract between the YAML files and Layer 3 (model engine).
If a field is added to a YAML it must be added here; Pydantic will reject unknown fields
so YAML drift is caught at load time, not buried in a runtime KeyError.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, field_validator, model_validator

Confidence = Literal["high", "medium", "speculative"]
Driver = Literal["slider", "questionnaire"]
GridDependency = Literal["full", "partial", "none"]


# ---------------------------------------------------------------------------
# Products
# ---------------------------------------------------------------------------

class ProductConfig(BaseModel):
    display_name: str
    hardware_cost_per_light_cny: float
    installation_cost_per_light_cny: float
    expected_lifetime_yrs: int

    @property
    def capex_per_light_cny(self) -> float:
        return self.hardware_cost_per_light_cny + self.installation_cost_per_light_cny
    rated_wattage_W: float
    connectivity_options: list[str]
    trenching_required: bool
    our_failure_rate_pct: float
    conventional_failure_rate_pct: float
    platform_fee_per_light_yr_cny: float
    warranty_yrs: int
    dimming_capable: bool
    solar_capable: bool
    battery_backup_hrs: float
    poles_reusable: bool
    grid_dependent: GridDependency

    @field_validator("grid_dependent", mode="before")
    @classmethod
    def _coerce_grid_dependent(cls, v: object) -> str:
        # YAML parses bare `true`/`false` as Python bools
        if v is True:
            return "full"
        if v is False:
            return "none"
        return str(v)


class ProductsConfig(BaseModel):
    config_version: str
    products: dict[str, ProductConfig]

    def get(self, key: str) -> ProductConfig:
        """Raise KeyError with a helpful message if product key is unknown."""
        if key not in self.products:
            raise KeyError(
                f"Unknown product {key!r}. Valid keys: {list(self.products)}"
            )
        return self.products[key]


# ---------------------------------------------------------------------------
# Savings mechanisms
# ---------------------------------------------------------------------------

class SavingsMechanism(BaseModel):
    display_name: str
    description: str
    driver: Driver
    applies_to: list[str]
    unit: Optional[str] = None
    min_pct: Optional[float] = None
    default_pct: Optional[float] = None
    max_pct: Optional[float] = None
    confidence: Confidence
    source: str

    @model_validator(mode="after")
    def _slider_has_bounds(self) -> "SavingsMechanism":
        if self.driver == "slider":
            missing = [
                f for f in ("min_pct", "default_pct", "max_pct", "unit")
                if getattr(self, f) is None
            ]
            if missing:
                raise ValueError(
                    f"Slider mechanism {self.display_name!r} missing fields: {missing}"
                )
            assert self.min_pct <= self.default_pct <= self.max_pct, (  # type: ignore[operator]
                f"min_pct ≤ default_pct ≤ max_pct violated for {self.display_name!r}"
            )
        return self

    def applies_to_product(self, product_key: str) -> bool:
        return "all" in self.applies_to or product_key in self.applies_to


class SavingsConfig(BaseModel):
    config_version: str
    mechanisms: dict[str, SavingsMechanism]

    def sliders(self) -> dict[str, SavingsMechanism]:
        """Return only the slider mechanisms (excludes questionnaire-driven ones)."""
        return {k: v for k, v in self.mechanisms.items() if v.driver == "slider"}

    def sliders_for_product(self, product_key: str) -> dict[str, SavingsMechanism]:
        return {
            k: v for k, v in self.sliders().items()
            if v.applies_to_product(product_key)
        }


# ---------------------------------------------------------------------------
# Financial assumptions
# ---------------------------------------------------------------------------

class RangedParam(BaseModel):
    display_name: str
    default: float
    min: float
    max: float
    unit: str
    source: str
    confidence: Confidence

    @model_validator(mode="after")
    def _bounds_order(self) -> "RangedParam":
        if not (self.min <= self.default <= self.max):
            raise ValueError(
                f"min ≤ default ≤ max violated for {self.display_name!r}: "
                f"{self.min} / {self.default} / {self.max}"
            )
        return self


class FinancialConfig(BaseModel):
    config_version: str
    hpwinner_wacc: RangedParam
    annual_fee_escalator: RangedParam
    corporate_tax_rate: RangedParam
    depreciation_yrs: RangedParam
    contingency_on_capex: RangedParam
    default_contract_yrs: RangedParam
    om_cost_per_person_day: RangedParam
    om_cost_per_vehicle_day: RangedParam
    repair_cost_per_ticket: RangedParam
    residual_value_pct: RangedParam

    def as_defaults(self) -> dict[str, float]:
        """Return {field_name: default} for all params — convenient for the engine."""
        return {
            field: getattr(self, field).default
            for field in self.model_fields
            if field != "config_version"
        }
