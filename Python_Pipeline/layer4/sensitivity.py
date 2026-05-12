"""One-at-a-time sensitivity analysis — builds tornado chart data.

For each parameter in the spec list:
  1. Hold everything else at base value
  2. Run engine at param=low, param=high
  3. Record NPV at each end
  4. Sort all rows by NPV swing descending

The spec list is built from Layer 2 YAML bounds so ranges stay in sync
with the slider definitions — no hardcoded magic numbers here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, List

from layer3.engine import run_model
from layer4.models import SensitivityRow, TornadoResult

if TYPE_CHECKING:
    from layer2.models import FinancialConfig, SavingsConfig
    from layer3.models import DealInputs, ScenarioParams


# Maps savings.yaml mechanism keys → ScenarioParams field names
_SAVINGS_FIELD_MAP = {
    "adaptive_dimming":                    "adaptive_dimming_pct",
    "predictive_maintenance_inspections":  "inspection_reduction_pct",
    "predictive_maintenance_tickets":      "ticket_reduction_pct",
    "failure_rate_reduction":              "failure_reduction_pct",
    "solar_grid_offset":                   "solar_grid_offset_pct",
}

# Maps financial.yaml param keys → ScenarioParams field names
_FINANCIAL_FIELD_MAP = {
    "hpwinner_wacc":        "hpwinner_wacc_pct",
    "annual_fee_escalator": "annual_fee_escalator_pct",
    "contingency_on_capex": "contingency_pct",
    "residual_value_pct":   "residual_value_pct",
}

# Cost benchmarks — vary ±30% around base (site conditions vary more than product specs)
_COST_VARIANCE = 0.30


@dataclass
class SensitivitySpec:
    field: str
    display_name: str
    low: float
    high: float
    confidence: str


def build_specs(
    params: "ScenarioParams",
    savings_cfg: "SavingsConfig",
    financial_cfg: "FinancialConfig",
) -> List[SensitivitySpec]:
    """Build the full list of parameters to vary, pulling ranges from Layer 2 YAMLs."""
    specs: List[SensitivitySpec] = []

    # --- Savings sliders (from savings.yaml) ---
    for key, mech in savings_cfg.sliders().items():
        field_name = _SAVINGS_FIELD_MAP.get(key)
        if not field_name or not hasattr(params, field_name):
            continue
        # Skip solar offset for non-solar products
        if key == "solar_grid_offset" and not _product_is_solar(params):
            continue
        specs.append(SensitivitySpec(
            field=field_name,
            display_name=mech.display_name,
            low=mech.min_pct,
            high=mech.max_pct,
            confidence=mech.confidence,
        ))

    # --- Financial assumptions (from financial.yaml) ---
    for yaml_key, field_name in _FINANCIAL_FIELD_MAP.items():
        param = getattr(financial_cfg, yaml_key, None)
        if param is None or not hasattr(params, field_name):
            continue
        specs.append(SensitivitySpec(
            field=field_name,
            display_name=param.display_name,
            low=param.min,
            high=param.max,
            confidence=param.confidence,
        ))

    # --- Hardware and installation cost (deal-specific ±30%) ---
    hw = params.hardware_cost_per_light
    specs.append(SensitivitySpec(
        field="hardware_cost_per_light",
        display_name="Hardware cost per light (±30%)",
        low=round(hw * (1 - _COST_VARIANCE)),
        high=round(hw * (1 + _COST_VARIANCE)),
        confidence="medium",
    ))

    inst = params.installation_cost_per_light
    specs.append(SensitivitySpec(
        field="installation_cost_per_light",
        display_name="Installation cost per light (±30%)",
        low=round(inst * (1 - _COST_VARIANCE)),
        high=round(inst * (1 + _COST_VARIANCE)),
        confidence="medium",
    ))

    # --- Service fee (±25% around team's chosen value) ---
    fee = params.annual_service_fee_per_light
    if fee > 0:
        specs.append(SensitivitySpec(
            field="annual_service_fee_per_light",
            display_name="Annual service fee per light (±25%)",
            low=round(fee * 0.75),
            high=round(fee * 1.25),
            confidence="high",
        ))

    return specs


def run_tornado(
    deal: "DealInputs",
    product,
    params: "ScenarioParams",
    specs: List[SensitivitySpec],
    config_versions: dict,
) -> TornadoResult:
    """Run engine 2×N times (low + high for each spec), return sorted tornado."""

    base_result = run_model(deal, product, params, config_versions)
    base_npv = base_result.npv

    rows: List[SensitivityRow] = []

    for spec in specs:
        base_val = getattr(params, spec.field)

        p_low  = params.model_copy(update={spec.field: spec.low})
        p_high = params.model_copy(update={spec.field: spec.high})

        npv_low  = run_model(deal, product, p_low,  config_versions).npv
        npv_high = run_model(deal, product, p_high, config_versions).npv

        rows.append(SensitivityRow(
            parameter=spec.field,
            display_name=spec.display_name,
            confidence=spec.confidence,
            base_value=base_val,
            low_value=spec.low,
            high_value=spec.high,
            npv_at_low=npv_low,
            npv_at_high=npv_high,
            base_npv=base_npv,
        ))

    rows.sort(key=lambda r: r.npv_swing, reverse=True)
    return TornadoResult(base_npv=base_npv, rows=rows)


def _product_is_solar(params: "ScenarioParams") -> bool:
    return params.product_key == "ai_solar_lamp"
