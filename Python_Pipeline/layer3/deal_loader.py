"""Convert a Layer 1 answers dict into a DealInputs object.

The answers dict is the flat {id: answer} output from read_questionnaire_input.py,
keyed by v2 questionnaire IDs (INT1, A5, B1, C1, C6, ...).

This module is the only place in Layer 3 that knows about questionnaire ID strings.
The engine itself (engine.py) only sees DealInputs — it is ID-agnostic.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional


def _to_float(v: Any) -> Optional[float]:
    if v is None:
        return None
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace(",", "")
    nums = re.findall(r"\d+(?:\.\d+)?", s)
    return float(nums[0]) if nums else None


def _to_int(v: Any) -> Optional[int]:
    f = _to_float(v)
    return int(round(f)) if f is not None else None


def _to_str(v: Any, default: str = "Unknown") -> str:
    if v is None:
        return default
    return str(v).strip() or default


def from_answers(answers: Dict[str, Any]) -> "DealInputs":
    """Build DealInputs from a v2 questionnaire answers dict.

    Raises ValueError if required fields are missing or invalid (proposed ≥ existing wattage).
    Collects all missing-required-field errors before raising so the caller gets them all at once.
    """
    from layer3.models import DealInputs  # local import avoids circular dependency

    errors: List[str] = []

    def require(key: str, label: str) -> Any:
        v = answers.get(key)
        if v is None or (isinstance(v, str) and not v.strip()):
            errors.append(f"{key} ({label}) is required but missing")
        return v

    def require_float(key: str, label: str) -> Optional[float]:
        v = require(key, label)
        if v is None:
            return None
        f = _to_float(v)
        if f is None:
            errors.append(f"{key} ({label}) could not be parsed as a number: {v!r}")
        return f

    def require_positive_float(key: str, label: str) -> Optional[float]:
        f = require_float(key, label)
        if f is not None and f <= 0:
            errors.append(f"{key} ({label}) must be positive, got {f}")
        return f

    # Required fields
    deal_id = _to_str(answers.get("INT1"), default="UNKNOWN")
    currency = _to_str(answers.get("INT6"), default="CNY")

    n_lights = require_float("A5", "number of lights in scope")
    annual_electricity_cost = require_positive_float("B1", "annual electricity cost")
    annual_om_cost = require_float("B2", "annual O&M cost")
    existing_wattage_W = require_positive_float("C1", "existing wattage (W)")
    proposed_wattage_W = require_positive_float("C2", "proposed wattage (W)")
    hours_per_night = require_positive_float("C3", "hours per night")
    tariff_avg_per_kwh = require_positive_float("C6", "average electricity tariff")
    inspection_rounds_yr = require_float("D2", "inspection rounds per year")
    annual_fault_tickets = require_float("D5", "annual fault tickets")

    if errors:
        raise ValueError("Missing or invalid required fields:\n" + "\n".join(f"  • {e}" for e in errors))

    # Wattage ordering check — DealInputs validator will also catch this,
    # but give a clearer message here with the actual values.
    if proposed_wattage_W is not None and existing_wattage_W is not None:
        if proposed_wattage_W >= existing_wattage_W:
            raise ValueError(
                f"C2 proposed wattage ({proposed_wattage_W}W) must be less than "
                f"C1 existing wattage ({existing_wattage_W}W). "
                "Check that the questionnaire filled the right columns."
            )

    return DealInputs(
        # Metadata
        deal_id=deal_id,
        currency=currency,
        # Scope
        n_lights=int(round(n_lights)),
        existing_failure_rate_pct=_to_float(answers.get("A9")),
        # Cost baseline
        annual_electricity_cost=annual_electricity_cost,
        annual_om_cost=annual_om_cost or 0.0,
        annual_capex_budget=_to_float(answers.get("B3")),
        project_investment_cny=_to_float(answers.get("B6")),
        annual_electricity_y_minus_3=_to_float(answers.get("B1c")),
        annual_electricity_y_minus_1=_to_float(answers.get("B1a")),
        annual_electricity_y_minus_2=_to_float(answers.get("B1b")),
        annual_om_y_minus_3=_to_float(answers.get("B2c")),
        annual_om_y_minus_1=_to_float(answers.get("B2a")),
        annual_om_y_minus_2=_to_float(answers.get("B2b")),
        pole_count=_to_int(answers.get("A5b")),
        expected_annual_savings=_to_float(answers.get("G6")),
        contract_total_value=_to_float(answers.get("H5")),
        # Operating profile
        existing_wattage_W=existing_wattage_W,
        proposed_wattage_W=proposed_wattage_W,
        hours_per_night=hours_per_night,
        annual_hours=_to_float(answers.get("C4")),
        tariff_avg_per_kwh=tariff_avg_per_kwh,
        # O&M
        inspection_rounds_yr=inspection_rounds_yr or 0.0,
        person_days_per_round=_to_float(answers.get("D3")),
        vehicle_days_per_round=_to_float(answers.get("D4")),
        annual_fault_tickets=annual_fault_tickets or 0.0,
        # Civil
        trenching_required=_to_str(answers.get("E1"), default="Unknown"),
        trenching_length_m=_to_float(answers.get("E2")),
        trenching_cost_per_km=_to_float(answers.get("E3")),
        # Contract
        contract_length_yrs=_to_float(answers.get("H1")),
        # Financial context
        customer_fiscal_stress=_to_str(answers.get("G1"), default="Unknown"),
        subsidy_available=_to_str(answers.get("G3"), default="Unknown"),
        data_confidence=_to_str(answers.get("K3"), default="Medium"),
    )
