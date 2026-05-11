"""Layer 3 — Model engine.

Single public function: run_model(deal, product, params) → ModelOutputs

Rules:
  - No Streamlit imports, ever.
  - No file I/O. Receives pre-loaded objects; callers own YAML loading.
  - No global state. Pure function: same inputs → same outputs.
  - All monetary values must already be in the deal's declared currency before calling.

Savings are computed for Year 1 and held flat across the contract term (conservative).
The service fee escalates; costs do not. This slightly understates NPV — intentional.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, List, Optional

try:
    import numpy_financial as nf
    _HAS_NPF = True
except ImportError:
    _HAS_NPF = False

from layer3.models import (
    BaselineCosts,
    CapexBreakdown,
    DealInputs,
    ModelOutputs,
    SavingsAttribution,
    ScenarioParams,
    YearlyCashflow,
)

if TYPE_CHECKING:
    from layer2.models import ProductConfig

# Fraction of B3 (annual capex budget) attributable to fixture replacement.
# The rest (pole structural, electrical, other) does not scale with failure rate.
# Becomes a slider in v2 of the engine.
_B3_FIXTURE_SHARE = 0.70

# LED replacement baseline: assume a standard LED retrofit reduces electricity by
# this fraction vs the existing fixture (HPS → LED without AI).
_LED_WATTAGE_REDUCTION_PCT = 0.50   # 50% wattage drop, a conservative LED-only baseline

# LED replacement capex premium over product capex_per_light (standard LED, no AI).
# Used to model the "like-for-like LED replacement" baseline.
_LED_CAPEX_PER_LIGHT_FRACTION = 0.55  # standard LED ≈ 55% of HPWinner AI lamp cost


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _compute_capex(
    deal: DealInputs,
    params: ScenarioParams,
    product,  # ProductConfig
) -> CapexBreakdown:
    fixtures = deal.n_lights * params.capex_per_light

    trenching = 0.0
    if (
        product.trenching_required
        and deal.trenching_required in ("Yes", "Partial")
        and deal.trenching_length_m
        and deal.trenching_cost_per_km
    ):
        trenching = (deal.trenching_length_m / 1000.0) * deal.trenching_cost_per_km

    contingency = (fixtures + trenching) * (params.contingency_pct / 100.0)
    return CapexBreakdown(fixtures=fixtures, trenching=trenching, contingency=contingency)


def _compute_savings(
    deal: DealInputs,
    params: ScenarioParams,
    product,  # ProductConfig
) -> SavingsAttribution:
    hours = deal.effective_annual_hours

    # 1. Wattage reduction — deterministic, no slider
    kw_existing = deal.existing_wattage_W / 1000.0
    kw_proposed = deal.proposed_wattage_W / 1000.0
    kwh_baseline = kw_existing * hours * deal.n_lights
    kwh_post_wattage = kw_proposed * hours * deal.n_lights
    saving_wattage = (kwh_baseline - kwh_post_wattage) * deal.tariff_avg_per_kwh

    # 2. Adaptive dimming — applied to post-wattage energy
    kwh_dimming_saved = kwh_post_wattage * (params.adaptive_dimming_pct / 100.0)
    saving_dimming = kwh_dimming_saved * deal.tariff_avg_per_kwh

    # 3. Solar grid offset — solar product only, applied after wattage + dimming
    if product.solar_capable:
        kwh_post_dimming = kwh_post_wattage - kwh_dimming_saved
        saving_solar = kwh_post_dimming * (params.solar_grid_offset_pct / 100.0) * deal.tariff_avg_per_kwh
    else:
        saving_solar = 0.0

    # 4. Inspection round reduction
    p_days = deal.person_days_per_round or params.person_days_per_round_default
    v_days = deal.vehicle_days_per_round or params.vehicle_days_per_round_default
    cost_per_round = (
        p_days * params.om_cost_per_person_day
        + v_days * params.om_cost_per_vehicle_day
    )
    rounds_saved = deal.inspection_rounds_yr * (params.inspection_reduction_pct / 100.0)
    saving_inspections = rounds_saved * cost_per_round

    # 5. Fault ticket reduction
    tickets_saved = deal.annual_fault_tickets * (params.ticket_reduction_pct / 100.0)
    saving_tickets = tickets_saved * params.repair_cost_per_ticket

    # 6. Failure rate reduction → fixture replacement capex avoided
    #    Actual reduction capped to what the product specs actually deliver
    baseline_failure_rate = (
        deal.existing_failure_rate_pct
        if deal.existing_failure_rate_pct is not None
        else product.conventional_failure_rate_pct
    )
    if baseline_failure_rate > 0:
        spec_reduction_pct = max(
            0.0,
            (baseline_failure_rate - product.our_failure_rate_pct) / baseline_failure_rate * 100.0,
        )
        effective_reduction_pct = min(params.failure_reduction_pct, spec_reduction_pct)
    else:
        effective_reduction_pct = 0.0

    b3 = deal.annual_capex_budget or 0.0
    saving_failure = b3 * _B3_FIXTURE_SHARE * (effective_reduction_pct / 100.0)

    return SavingsAttribution(
        wattage_reduction=saving_wattage,
        adaptive_dimming=saving_dimming,
        inspection_reduction=saving_inspections,
        ticket_reduction=saving_tickets,
        failure_rate_reduction=saving_failure,
        solar_grid_offset=saving_solar,
    )


def _compute_cashflows(
    capex_total: float,
    annual_service_fee_y1: float,
    annual_platform_costs: float,
    params: ScenarioParams,
) -> List[YearlyCashflow]:
    rows: List[YearlyCashflow] = []
    cumulative = 0.0

    # Year 0 — capital outlay
    net_y0 = -capex_total
    cumulative += net_y0
    rows.append(YearlyCashflow(
        year=0,
        service_fee_revenue=0.0,
        platform_costs=0.0,
        net_cashflow=net_y0,
        cumulative_cashflow=cumulative,
    ))

    # Years 1..N — operating
    for yr in range(1, params.contract_yrs + 1):
        escalation = (1.0 + params.annual_fee_escalator_pct / 100.0) ** (yr - 1)
        fee_yr = annual_service_fee_y1 * escalation
        net_yr = fee_yr - annual_platform_costs
        # Terminal year: add residual asset value
        if yr == params.contract_yrs:
            net_yr += capex_total * (params.residual_value_pct / 100.0)
        cumulative += net_yr
        rows.append(YearlyCashflow(
            year=yr,
            service_fee_revenue=fee_yr,
            platform_costs=annual_platform_costs,
            net_cashflow=net_yr,
            cumulative_cashflow=cumulative,
        ))

    return rows


def _compute_npv(cashflows: List[float], wacc: float) -> float:
    return sum(cf / (1.0 + wacc) ** t for t, cf in enumerate(cashflows))


def _compute_irr(cashflows: List[float]) -> Optional[float]:
    if not _HAS_NPF:
        return None
    try:
        r = nf.irr(cashflows)
        if r is None or r != r:  # NaN check
            return None
        return float(r)
    except (ValueError, TypeError):
        return None


def _compute_payback(rows: List[YearlyCashflow]) -> Optional[float]:
    """Interpolated payback year (when cumulative cashflow first crosses zero)."""
    for i in range(1, len(rows)):
        prev, curr = rows[i - 1], rows[i]
        if prev.cumulative_cashflow < 0 and curr.cumulative_cashflow >= 0:
            # Linear interpolation
            span = curr.cumulative_cashflow - prev.cumulative_cashflow
            frac = -prev.cumulative_cashflow / span
            return (curr.year - 1) + frac
    return None  # never recovers within contract


def _compute_baselines(
    deal: DealInputs,
    params: ScenarioParams,
    annual_service_fee_y1: float,
) -> BaselineCosts:
    N = params.contract_yrs
    baseline_annual = deal.baseline_total_annual_cost

    # Baseline A: status quo — keep paying same costs forever
    status_quo_total = baseline_annual * N

    # Baseline B: like-for-like LED replacement
    led_capex = deal.n_lights * params.capex_per_light * _LED_CAPEX_PER_LIGHT_FRACTION
    led_elec_reduction = deal.annual_electricity_cost * _LED_WATTAGE_REDUCTION_PCT
    led_annual_opex = (
        (deal.annual_electricity_cost - led_elec_reduction)
        + deal.annual_om_cost
        + (deal.annual_capex_budget or 0.0) * (1 - _B3_FIXTURE_SHARE * 0.30)  # LED has lower failure rate
    )
    led_replacement_total = led_capex + led_annual_opex * N

    # LaaS customer total (escalating fee, no upfront capex)
    laas_fee_total = sum(
        annual_service_fee_y1 * (1.0 + params.annual_fee_escalator_pct / 100.0) ** (yr - 1)
        for yr in range(1, N + 1)
    )

    return BaselineCosts(
        status_quo_total=status_quo_total,
        led_replacement_total=led_replacement_total,
        laas_customer_total=laas_fee_total,
        laas_customer_saving_vs_status_quo=status_quo_total - laas_fee_total,
        laas_customer_saving_vs_led=led_replacement_total - laas_fee_total,
    )


def _go_nogo(
    npv: float,
    irr: Optional[float],
    payback: Optional[float],
    params: ScenarioParams,
    deal: DealInputs,
    customer_net_saving_y1: float,
) -> tuple:
    reasons: List[str] = []
    flags: List[str] = []

    wacc = params.hpwinner_wacc_pct / 100.0

    if npv < 0:
        flags.append("no-go")
        reasons.append(f"NPV is negative ({npv:,.0f} {deal.currency}) — deal destroys value at WACC {params.hpwinner_wacc_pct}%")

    if irr is not None and irr < wacc:
        flags.append("no-go")
        reasons.append(f"IRR ({irr * 100:.1f}%) is below WACC ({params.hpwinner_wacc_pct}%)")
    elif irr is None:
        flags.append("borderline")
        reasons.append("IRR could not be computed — check that cash flows change sign")

    if payback is None:
        flags.append("no-go")
        reasons.append("CAPEX not recovered within contract term")
    elif payback > params.contract_yrs * 0.75:
        flags.append("borderline")
        reasons.append(
            f"Payback ({payback:.1f} yr) is late in the contract ({params.contract_yrs} yr) — "
            "little cushion if revenues disappoint"
        )

    if customer_net_saving_y1 <= 0:
        flags.append("borderline")
        reasons.append(
            "Customer does not benefit in Year 1 — service fee exceeds baseline cost; "
            "reconsider HPWinner savings share or capex"
        )

    if deal.customer_fiscal_stress == "Yes":
        flags.append("borderline")
        reasons.append("Customer flagged as fiscally stressed (G1) — payment risk elevated")

    if deal.data_confidence == "Low":
        flags.append("borderline")
        reasons.append("Data confidence is Low (K3) — outputs should be treated as directional only")

    if "no-go" in flags:
        verdict = "no-go"
    elif "borderline" in flags:
        verdict = "borderline"
    else:
        verdict = "go"
        if not reasons:
            reasons.append("NPV positive, IRR above WACC, payback within 75% of contract, customer benefits")

    return verdict, reasons


def _collect_warnings(deal: DealInputs, params: ScenarioParams) -> List[str]:
    warnings: List[str] = []
    if deal.person_days_per_round is None:
        warnings.append(
            f"D3 (person-days/round) not provided — using default {params.person_days_per_round_default}"
        )
    if deal.vehicle_days_per_round is None:
        warnings.append(
            f"D4 (vehicle-days/round) not provided — using default {params.vehicle_days_per_round_default}"
        )
    if deal.annual_capex_budget is None:
        warnings.append(
            "B3 (annual capex budget) not provided — failure-rate-reduction saving set to zero"
        )
    if deal.existing_failure_rate_pct is None:
        warnings.append(
            "A9 (existing failure rate) not provided — using product conventional_failure_rate_pct"
        )
    if deal.trenching_required in ("Unknown", "Partial") and params.capex_per_light > 0:
        warnings.append(
            "E1 (trenching) is Unknown/Partial — trenching cost excluded from CAPEX; "
            "add E2×E3 manually if applicable"
        )
    return warnings


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def run_model(
    deal: DealInputs,
    product,            # ProductConfig from layer2.models
    params: ScenarioParams,
    config_versions: Optional[dict] = None,
) -> ModelOutputs:
    """Compute the full LaaS deal economics.

    Args:
        deal:            Fixed facts from the questionnaire (Layer 1).
        product:         Product configuration chosen for this deal (Layer 2).
        params:          All adjustable assumptions for this run (sliders + commercial lever).
        config_versions: Dict from layer2.loader.config_versions() — stamped on output for audit.

    Returns:
        ModelOutputs containing NPV, IRR, payback, savings attribution, cashflows,
        customer perspective, baseline comparisons, and go/no-go verdict.
    """
    warnings = _collect_warnings(deal, params)

    # 1. CAPEX
    capex = _compute_capex(deal, params, product)

    # 2. Savings attribution (Year 1, pre-escalation)
    savings = _compute_savings(deal, params, product)

    # 3. Service fee and HPWinner annual opex
    annual_service_fee_y1 = savings.total * (params.hpwinner_savings_share_pct / 100.0)
    annual_platform_costs = deal.n_lights * params.platform_fee_per_light_yr

    # Sanity check: fee must not exceed customer's total baseline spend
    if annual_service_fee_y1 > deal.baseline_total_annual_cost:
        annual_service_fee_y1 = deal.baseline_total_annual_cost
        warnings.append(
            "Service fee exceeded customer baseline — capped at baseline total cost. "
            "Reduce HPWinner savings share or re-check savings assumptions."
        )

    # 4. Cashflows and financial metrics
    rows = _compute_cashflows(capex.total, annual_service_fee_y1, annual_platform_costs, params)
    raw_cfs = [r.net_cashflow for r in rows]

    npv = _compute_npv(raw_cfs, params.hpwinner_wacc_pct / 100.0)
    irr = _compute_irr(raw_cfs)
    payback = _compute_payback(rows)

    # 5. Customer perspective
    customer_net_saving_y1 = deal.baseline_total_annual_cost - annual_service_fee_y1
    customer_net_saving_total = sum(
        deal.baseline_total_annual_cost
        - annual_service_fee_y1 * (1.0 + params.annual_fee_escalator_pct / 100.0) ** (yr - 1)
        for yr in range(1, params.contract_yrs + 1)
    )

    # 6. Baseline comparisons
    baselines = _compute_baselines(deal, params, annual_service_fee_y1)

    # 7. Go/no-go
    verdict, reasons = _go_nogo(npv, irr, payback, params, deal, customer_net_saving_y1)

    return ModelOutputs(
        deal_id=deal.deal_id,
        product_key=params.product_key,
        config_versions=config_versions or {},
        npv=npv,
        irr=irr,
        payback_years=payback,
        capex=capex,
        annual_savings=savings,
        annual_service_fee_y1=annual_service_fee_y1,
        annual_platform_costs=annual_platform_costs,
        yearly_cashflows=rows,
        customer_net_saving_y1=customer_net_saving_y1,
        customer_net_saving_total=customer_net_saving_total,
        baselines=baselines,
        go_nogo=verdict,
        go_nogo_reasons=reasons,
        warnings=warnings,
    )
