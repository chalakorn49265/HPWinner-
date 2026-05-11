"""Illustrative client economics from questionnaire answers + scenario sliders.

MVED-aligned: simplified formulas only; all outputs labeled illustrative in the UI.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from chongqing.routing import extract_numbers

try:
    import numpy_financial as nf
except ImportError:
    nf = None  # type: ignore[misc, assignment]


def _f(x: Any) -> float | None:
    if x is None:
        return None
    if isinstance(x, bool):
        return None
    if isinstance(x, (int, float)):
        return float(x)
    nums = extract_numbers(x)
    return float(nums[0]) if nums else None


@dataclass(frozen=True)
class EconomicsSummary:
    currency: str
    client_investment: float
    annual_electricity_baseline: float
    annual_electricity_after: float
    annual_elec_savings: float
    annual_client_cash_in: float
    simple_payback_years: float | None
    horizon_years: int
    cumulative_net: float
    annual_irr: float | None
    rows: list[dict[str, Any]]


def build_economics(
    answers: dict[str, Any],
    *,
    horizon_years: float,
    fee_split_client_pct: int,
    savings_pct: int,
) -> EconomicsSummary:
    """Construct year-0..H cashflows: −CAPEX then annual client share of energy savings."""
    cur = str(answers.get("INT4") or "CNY").strip() or "CNY"
    lamps = _f(answers.get("A3")) or 0.0
    unit_capex = _f(answers.get("E3")) or 0.0
    # Primary CAPEX proxy: fixture × per-lamp all-in (E3×A3). Civil trench (E2) is CNY/km — excluded here without route km; surfaced in cost tables.
    client_investment = max(0.0, lamps * unit_capex)

    b2 = _f(answers.get("B2")) or 0.0
    annual_elec_savings = max(0.0, b2 * (savings_pct / 100.0))
    annual_client_cash_in = annual_elec_savings * (fee_split_client_pct / 100.0)
    annual_electricity_after = max(0.0, b2 - annual_elec_savings)

    h = max(1, int(round(horizon_years)))
    cfs: list[float] = [-client_investment]
    for _ in range(h):
        cfs.append(annual_client_cash_in)

    cumulative = 0.0
    rows: list[dict[str, Any]] = []
    for i, cf in enumerate(cfs):
        cumulative += cf
        rows.append(
            {
                "year_index": i,
                "net_cashflow": cf,
                "cumulative_net": cumulative,
            }
        )

    simple_pb: float | None = None
    if annual_client_cash_in > 1e-6 and client_investment > 0:
        simple_pb = client_investment / annual_client_cash_in

    irr_annual: float | None = None
    if nf is not None and len(cfs) > 1:
        try:
            r = nf.irr(cfs)
            if r is not None:
                irr_annual = float(r)
                if irr_annual != irr_annual:  # NaN
                    irr_annual = None
        except (ValueError, TypeError):
            pass

    cum_horizon = float(rows[-1]["cumulative_net"]) if rows else 0.0

    return EconomicsSummary(
        currency=cur,
        client_investment=client_investment,
        annual_electricity_baseline=b2,
        annual_electricity_after=annual_electricity_after,
        annual_elec_savings=annual_elec_savings,
        annual_client_cash_in=annual_client_cash_in,
        simple_payback_years=simple_pb,
        horizon_years=h,
        cumulative_net=cum_horizon,
        annual_irr=irr_annual,
        rows=rows,
    )


def baseline_annual_spend_parts(answers: dict[str, Any]) -> dict[str, float | None]:
    """Rough operating baseline split for CAPEX vs OPEX tables (illustrative)."""
    return {
        "annual_electricity": _f(answers.get("B2")),
        "annual_om_style": _f(answers.get("B3")),
        "annual_outsourced_om": _f(answers.get("D2")),
    }
