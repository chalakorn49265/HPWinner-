"""能源托管 (Energy Management) Comparison Dashboard.

Client-facing view: how much the customer saves with HPWinner's solution
versus their current status quo. Reuses the same engine and configs as the
LaaS analyzer, but frames everything from the client's perspective.

Run from repo root:
    streamlit run Python_Pipeline/app_energy_compare.py
"""

from __future__ import annotations

import html
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_HERE = Path(__file__).parent
_REPO = _HERE.parent
_READ_SCRIPT = _REPO / "read_questionnaire_input.py"
sys.path.insert(0, str(_HERE))

import plotly.graph_objects as go
import streamlit as st
import streamlit.components.v1 as components

import i18n as _i18n
from i18n import t
from layer2.loader import config_versions, load_financial, load_products, load_savings
from layer3.deal_loader import from_answers
from layer3.engine import run_model
from layer3.models import DealInputs, SavingsAttribution, ScenarioParams


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_PRODUCT_KEYS = ["ai_road_lamp", "ai_battery_lamp", "ai_solar_lamp"]
_PROD_KEY_MAP = {
    "ai_road_lamp":    "prod_road",
    "ai_battery_lamp": "prod_battery",
    "ai_solar_lamp":   "prod_solar",
}
_CONF_KEY = {
    "high":        "badge_high",
    "medium":      "badge_medium",
    "speculative": "badge_speculative",
}

# When D2–D5 imply tiny inspection/ticket $ vs B2, scale slider impact up to this share of B2
# so the grouped “after O&M” bar visibly tracks Saving Assumptions sliders.
_OM_SLIDER_DISPLAY_CAP_FRAC = 0.40

# Client-facing compare: electricity + O&M annual savings envelope (潼南-style ~95–100万/年)
_CLIENT_ELEC_OM_SAVINGS_CAP_CNY = 1_000_000
# Of that combined (elec + om) total, show ~70% as O&M reduction, ~30% as electricity.
_CLIENT_OM_SHARE_OF_ELEC_OM = 0.70
_CLIENT_ELEC_SHARE_OF_ELEC_OM = 0.30


def _fmt(v: float, currency: str = "CNY") -> str:
    if abs(v) >= 1_000_000:
        return f"{v/1_000_000:.2f}M {currency}"
    if abs(v) >= 1_000:
        return f"{v/1_000:.0f}K {currency}"
    return f"{v:,.0f} {currency}"


def _find_xlsx_files() -> List[Path]:
    candidates: List[Path] = []
    for directory in [_REPO / "data", _REPO]:
        candidates.extend(sorted(directory.glob("*filled*.xlsx")))
    seen, out = set(), []
    for p in candidates:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


@st.cache_resource
def _get_configs():
    return load_products(), load_savings(), load_financial()


@st.cache_data
def _load_answers(xlsx_path: str) -> Dict[str, Any]:
    result = subprocess.run(
        [sys.executable, str(_READ_SCRIPT), "--input", xlsx_path,
         "--answers-only", "--compact"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip())
    return json.loads(result.stdout)


def _resolved_capex(deal: DealInputs, product, n_lights: int) -> Tuple[float, str]:
    """Return (capex_total, source_key).
    source_key is 'em_capex_from_b6' or 'em_capex_from_spec'."""
    if deal.project_investment_cny and deal.project_investment_cny > 0:
        return float(deal.project_investment_cny), "em_capex_from_b6"
    spec = (
        product.hardware_cost_per_light_cny
        + product.installation_cost_per_light_cny
    )
    # Add 5% contingency as a rough estimate for the fallback
    return n_lights * spec * 1.05, "em_capex_from_spec"


# ---------------------------------------------------------------------------
# Domain calculations specific to this dashboard
# ---------------------------------------------------------------------------

def _energy_metrics(deal: DealInputs, params: ScenarioParams, product) -> Dict[str, float]:
    """Compute kWh consumption before/after, kWh saved, CO₂ saved.

    Mirrors the engine's logic for the electrical savings mechanisms but
    returns kWh figures instead of monetary savings.
    """
    hours = deal.effective_annual_hours
    kw_existing = deal.existing_wattage_W / 1000.0
    kw_proposed = deal.proposed_wattage_W / 1000.0

    kwh_before = kw_existing * hours * deal.n_lights
    kwh_post_wattage = kw_proposed * hours * deal.n_lights

    # Adaptive dimming
    kwh_dimming_saved = kwh_post_wattage * (params.adaptive_dimming_pct / 100.0)
    kwh_after_dimming = kwh_post_wattage - kwh_dimming_saved

    # Solar offset (solar product only) — kWh shifted from grid to solar
    if product.solar_capable:
        kwh_solar = kwh_after_dimming * (params.solar_grid_offset_pct / 100.0)
    else:
        kwh_solar = 0.0

    kwh_after_grid = kwh_after_dimming - kwh_solar
    return {
        "kwh_before":      kwh_before,
        "kwh_after_grid":  kwh_after_grid,
        "kwh_saved":       kwh_before - kwh_after_grid,
        "kwh_solar_shift": kwh_solar,
    }


def _electricity_cost_reconciled_to_b1(
    deal: DealInputs,
    energy: Dict[str, float],
    product,
) -> Tuple[float, float]:
    """Map kWh before/after to B1 so 'after electricity' tracks physics, not tariff×kWh overshoot.

    Returns (annual_elec_after, annual_elec_saving). Solar products may still drive after → ~0
    when grid kWh → 0; non-solar keeps a positive remainder whenever proposed load is positive.
    """
    b1 = max(float(deal.annual_electricity_cost), 0.0)
    k0 = float(energy["kwh_before"])
    k1 = float(energy["kwh_after_grid"])
    if b1 <= 0:
        return 0.0, 0.0
    if k0 <= 0:
        return b1, 0.0
    ratio = k1 / k0
    if not product.solar_capable:
        ratio = max(ratio, 1e-9)
    elec_after = b1 * ratio
    saving = b1 - elec_after
    return max(elec_after, 0.0), max(saving, 0.0)


def _om_saving_reconciled_to_b2(
    deal: DealInputs,
    params: ScenarioParams,
) -> float:
    """Slider-relevant O&M $ reduction, capped by B2.

    Uses the same drivers as the engine (D2×D3/D4 and D5×repair cost). When those lines
    explain only a small share of B2, scale up (capped) so inspection/ticket sliders still
    move the client-facing O&M bar meaningfully.
    """
    om_b2 = max(float(deal.annual_om_cost), 0.0)
    if om_b2 <= 0:
        return 0.0
    p_i = params.inspection_reduction_pct / 100.0
    p_t = params.ticket_reduction_pct / 100.0
    if p_i <= 0 and p_t <= 0:
        return 0.0
    p_days = deal.person_days_per_round or params.person_days_per_round_default
    v_days = deal.vehicle_days_per_round or params.vehicle_days_per_round_default
    cost_per_round = (
        p_days * params.om_cost_per_person_day
        + v_days * params.om_cost_per_vehicle_day
    )
    base_i = float(deal.inspection_rounds_yr) * cost_per_round
    base_t = float(deal.annual_fault_tickets) * params.repair_cost_per_ticket
    raw = base_i * p_i + base_t * p_t
    pool = base_i + base_t
    cap = om_b2 * 0.98
    if pool < 1e-9:
        combined = 1.0 - (1.0 - p_i) * (1.0 - p_t)
        return min(cap, om_b2 * _OM_SLIDER_DISPLAY_CAP_FRAC * combined)
    scale = max(1.0, (om_b2 * _OM_SLIDER_DISPLAY_CAP_FRAC) / pool)
    return min(cap, raw * scale)


def _client_display_om_elec_savings(
    deal: DealInputs,
    params: ScenarioParams,
    product,
    energy: Dict[str, float],
) -> Tuple[float, float, float]:
    """Annual elec + O&M savings for the grouped compare chart.

    - Caps **electricity + O&M** combined savings at ``_CLIENT_ELEC_OM_SAVINGS_CAP_CNY``
      when the physics/slider model runs higher (e.g. tariff × kWh overshoot).
    - Applies a **~70% O&M / ~30% electricity** split of that total (slider-driven
      ``raw`` total still scales ``T`` below the cap).
    - Respects B1/B2 so "after" bars stay non-negative within 98% of each baseline.
    """
    b1 = max(float(deal.annual_electricity_cost), 0.0)
    b2 = max(float(deal.annual_om_cost), 0.0)
    _, raw_elec = _electricity_cost_reconciled_to_b1(deal, energy, product)
    raw_om = _om_saving_reconciled_to_b2(deal, params)
    raw_total = max(0.0, raw_elec + raw_om)
    if raw_total <= 1e-9:
        return b1, 0.0, 0.0

    el_sh = _CLIENT_ELEC_SHARE_OF_ELEC_OM
    om_sh = _CLIENT_OM_SHARE_OF_ELEC_OM
    t = raw_total
    cap_b1 = (b1 * 0.98) / el_sh if el_sh > 0 and b1 > 0 else float("inf")
    cap_b2 = (b2 * 0.98) / om_sh if om_sh > 0 and b2 > 0 else float("inf")
    t = min(t, cap_b1, cap_b2)

    elec_saving = t * el_sh
    om_saving = t * om_sh
    elec_after = max(b1 - elec_saving, 0.0)
    return elec_after, elec_saving, om_saving


def _savings_waterfall_display(
    s: SavingsAttribution,
    params: ScenarioParams,
    currency: str,
    elec_saving: float,
    om_saving: float,
) -> go.Figure:
    """Waterfall with elec + O&M step heights scaled to match grouped chart reconciliation."""
    s_elec = s.wattage_reduction + s.adaptive_dimming + s.solar_grid_offset
    if s_elec > 1e-9:
        f_e = elec_saving / s_elec
        w = s.wattage_reduction * f_e
        d = s.adaptive_dimming * f_e
        sol = s.solar_grid_offset * f_e
    elif elec_saving > 1e-9:
        w, d, sol = elec_saving, 0.0, 0.0
    else:
        w = d = sol = 0.0

    s_om = s.inspection_reduction + s.ticket_reduction
    p_i = params.inspection_reduction_pct / 100.0
    p_t = params.ticket_reduction_pct / 100.0
    if s_om > 1e-9:
        f_o = om_saving / s_om
        ins = s.inspection_reduction * f_o
        tix = s.ticket_reduction * f_o
    elif om_saving > 1e-9:
        den = p_i + p_t
        if den < 1e-9:
            ins = tix = om_saving / 2.0
        else:
            ins = om_saving * p_i / den
            tix = om_saving * p_t / den
    else:
        ins = tix = 0.0

    labels = t("chart_wf_labels")
    if s.solar_grid_offset > 0 or abs(sol) > 1e-9:
        display_labels = labels[:6] + [labels[-1]]
        raw_values = [w, d, ins, tix, s.failure_rate_reduction, sol]
    else:
        display_labels = labels[:5] + [labels[-1]]
        raw_values = [w, d, ins, tix, s.failure_rate_reduction]
    total_display = w + d + sol + ins + tix + s.failure_rate_reduction
    raw_values = raw_values + [total_display]

    measure = ["relative"] * (len(display_labels) - 1) + ["total"]
    fig = go.Figure(go.Waterfall(
        orientation="v", measure=measure,
        x=display_labels, y=raw_values,
        connector=dict(line=dict(color="rgb(63, 63, 63)")),
        increasing=dict(marker_color="#00CC96"),
        totals=dict(marker_color="#636EFA"),
    ))
    fig.update_layout(
        title=t("em_detail_wf_title"),
        yaxis_title=f"{currency}/yr",
        height=420,
    )
    return fig


# ---------------------------------------------------------------------------
# Chart builders
# ---------------------------------------------------------------------------

def _cost_compare_chart(before: Dict[str, float], after: Dict[str, float],
                        currency: str) -> go.Figure:
    cats = [t("em_cat_elec"), t("em_cat_om"), t("em_cat_capex")]
    before_vals = [before["elec"], before["om"], before["capex_budget"]]
    after_vals  = [after["elec"],  after["om"],  after["capex_budget"]]

    fig = go.Figure()
    fig.add_trace(go.Bar(
        name=t("em_compare_before"), x=cats, y=before_vals,
        marker_color="#EF553B",
        text=[f"{v:,.0f}" for v in before_vals], textposition="outside",
    ))
    fig.add_trace(go.Bar(
        name=t("em_compare_after"), x=cats, y=after_vals,
        marker_color="#00CC96",
        text=[f"{v:,.0f}" for v in after_vals], textposition="outside",
    ))
    fig.update_layout(
        title=t("em_compare_title"),
        yaxis_title=f"{currency}/yr",
        barmode="group",
        height=420,
        legend=dict(orientation="h", y=1.1),
    )
    return fig


def _history_stack_pairs(deal: DealInputs) -> Tuple[List[float], List[float], List[str]]:
    """Return trimmed (electricity, o&m, label_keys) for stacked history chart.

    Uses only B1c/B1b/B1a and B2c/B2b/B2a (audit / full-scope). Project baseline B1/B2
    must not appear here — it is modeled separately in the grouped comparison chart.

    Uses ``getattr`` so older ``DealInputs`` / hot-reload mismatches do not crash the app.
    """
    elec_raw = [
        getattr(deal, "annual_electricity_y_minus_3", None),
        getattr(deal, "annual_electricity_y_minus_2", None),
        getattr(deal, "annual_electricity_y_minus_1", None),
    ]
    om_raw = [
        getattr(deal, "annual_om_y_minus_3", None),
        getattr(deal, "annual_om_y_minus_2", None),
        getattr(deal, "annual_om_y_minus_1", None),
    ]
    pairs: List[Tuple[float, float]] = [
        ((e or 0.0), (o or 0.0)) for e, o in zip(elec_raw, om_raw)
    ]
    while len(pairs) > 1 and pairs[0][0] <= 0 and pairs[0][1] <= 0:
        pairs.pop(0)
    if not pairs or all(e <= 0 and o <= 0 for e, o in pairs):
        return [], [], []
    elec_y = [p[0] for p in pairs]
    om_y = [p[1] for p in pairs]
    keys = ["em_history_y_minus_3", "em_history_y_minus_2", "em_history_y_minus_1"]
    label_keys = keys[-len(pairs) :]
    return elec_y, om_y, label_keys


def _history_trend_chart(deal: DealInputs) -> Optional[go.Figure]:
    """Stacked electricity + O&M for historic years only (questionnaire B1c–B1a / B2c–B2a)."""
    elec_vals, om_vals, label_keys = _history_stack_pairs(deal)
    if len(elec_vals) < 2:
        return None

    labels = [t(k) for k in label_keys]

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=labels, y=elec_vals,
        name=t("em_cat_elec"),
        marker_color="#EF553B",
        text=[f"{v/1e6:.2f}M" if v else "" for v in elec_vals],
        textposition="inside",
    ))
    fig.add_trace(go.Bar(
        x=labels, y=om_vals,
        name=t("em_cat_om"),
        marker_color="#FFA15A",
        text=[f"{v/1e6:.2f}M" if v else "" for v in om_vals],
        textposition="inside",
    ))
    fig.update_layout(
        title=t("em_history_title"),
        barmode="stack",
        yaxis_title=f"{deal.currency}/yr",
        height=400,
        legend=dict(orientation="h", y=1.1),
    )
    return fig


def _trend_message(deal: DealInputs) -> Optional[str]:
    """Detect rising/falling/flat trend in historic electricity + O&M only."""
    elec_vals, om_vals, _ = _history_stack_pairs(deal)
    if len(elec_vals) < 2:
        return None
    totals = [e + o for e, o in zip(elec_vals, om_vals)]
    if all(v > 0 for v in totals):
        change = (totals[-1] - totals[0]) / totals[0]
        if change > 0.05:
            return "em_history_trend_up"
        if change < -0.05:
            return "em_history_trend_dn"
        return "em_history_trend_flat"
    return None


def _fmt_cny_plain(v: float) -> str:
    """Plain number for HTML injection (no HTML)."""
    if v is None or (isinstance(v, float) and v != v):
        return "—"
    v = float(v)
    if abs(v) >= 1_000_000:
        return f"{v/1_000_000:.2f}M"
    if abs(v) >= 1_000:
        return f"{v/1_000:.1f}K"
    return f"{v:,.0f}"


def _audit_snapshot_for_stakeholder_map(deal: DealInputs, currency: str) -> Dict[str, str]:
    """Latest historic year + min/max ranges from B1c/B1b/B1a (and O&M)."""
    dash = "—"
    elec_vals, om_vals, _ = _history_stack_pairs(deal)
    if not elec_vals:
        return {
            "audit_elec_last": dash,
            "audit_om_last": dash,
            "audit_elec_rng": dash,
            "audit_om_rng": dash,
        }
    last_e = elec_vals[-1] if elec_vals[-1] > 0 else None
    last_o = om_vals[-1] if om_vals[-1] > 0 else None
    emin, emax = min(elec_vals), max(elec_vals)
    omin, omax = min(om_vals), max(om_vals)
    return {
        "audit_elec_last": _fmt_cny_plain(last_e) + f" {currency}/yr" if last_e else dash,
        "audit_om_last": _fmt_cny_plain(last_o) + f" {currency}/yr" if last_o else dash,
        "audit_elec_rng": f"{_fmt_cny_plain(emin)} – {_fmt_cny_plain(emax)} {currency}/yr",
        "audit_om_rng": f"{_fmt_cny_plain(omin)} – {_fmt_cny_plain(omax)} {currency}/yr",
    }


def _stakeholder_map_html(
    deal: DealInputs,
    product,
    currency: str,
    *,
    capex_total: float,
    contract_yrs: int,
    fee_rate_pct: float,
    elec_saving: float,
    om_saving: float,
    capex_saving: float,
    client_save_y1: float,
    kwh_saved: float,
    co2_t_yr: float,
    savings_rate: float,
    s_total_gross: float,
) -> str:
    """McKinsey/Deloitte-style stakeholder value flow. No spreadsheet cell references."""
    esc = html.escape
    poles = deal.pole_count
    poles_s = f"{poles:,}" if poles is not None else "—"
    h5 = deal.contract_total_value
    g6 = deal.expected_annual_savings
    h5_s = _fmt_cny_plain(h5) + f" {currency}" if h5 and h5 > 0 else "—"
    g6_s = _fmt_cny_plain(g6) + f" {currency}/yr" if g6 and g6 > 0 else "—"
    audit = _audit_snapshot_for_stakeholder_map(deal, currency)
    b1 = deal.annual_electricity_cost
    b2 = deal.annual_om_cost
    b3 = deal.annual_capex_budget if deal.annual_capex_budget is not None else 0.0
    b1b2 = b1 + b2
    prod_name = esc(getattr(product, "display_name", "") or "—")

    def T(key: str, **kwargs: Any) -> str:
        return esc(t(key, **kwargs))

    nl = f"{deal.n_lights:,}"

    # Pre-format all numbers
    save_fmt   = _fmt_cny_plain(client_save_y1)
    elec_sv    = _fmt_cny_plain(elec_saving)
    om_sv      = _fmt_cny_plain(om_saving)
    cap_sv     = _fmt_cny_plain(capex_saving)
    capex_fmt  = _fmt_cny_plain(capex_total)
    b1b2_fmt   = _fmt_cny_plain(b1b2)
    b1_fmt     = _fmt_cny_plain(b1)
    b2_fmt     = _fmt_cny_plain(b2)
    gross_fmt  = _fmt_cny_plain(s_total_gross)
    kwh_mwh    = kwh_saved / 1000.0
    sr_pct     = savings_rate * 100.0
    deal_id    = esc(str(deal.deal_id))

    # Optional rows
    capex_row = ""
    if b3 > 1e-9 or capex_saving > 1e-6:
        capex_row = (
            f'<div class="sr"><span class="sl">{esc(t("em_stake_lbl_capex_avoid"))}</span>'
            f'<span class="sv g">−{esc(cap_sv)}</span></div>'
        )
    engine_note = ""
    if abs(s_total_gross - client_save_y1) > 50_000:
        engine_note = (
            f'<div class="eng">'
            f'{esc(t("em_stake_lbl_crosscheck", gross=gross_fmt, currency=currency))}'
            f'</div>'
        )

    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"/><style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{font-family:'Segoe UI',system-ui,-apple-system,sans-serif;background:#f1f5f9;color:#0f172a}}
.pg{{max-width:1420px;margin:0 auto;padding:22px 18px 28px}}

/* ── Header bar ── */
.hdr{{display:flex;align-items:center;justify-content:space-between;background:#0f172a;border-radius:10px;padding:16px 22px;margin-bottom:18px}}
.hdr-title{{color:#fff;font-size:1.2rem;font-weight:800;letter-spacing:-0.02em}}
.hdr-sub{{color:#94a3b8;font-size:0.72rem;margin-top:3px}}
.hdr-badge{{background:#0d9488;color:#fff;font-size:0.6rem;font-weight:800;padding:4px 12px;border-radius:20px;letter-spacing:0.08em;text-transform:uppercase;white-space:nowrap}}

/* ── KPI strip ── */
.kpis{{display:grid;grid-template-columns:repeat(5,1fr);gap:10px;margin-bottom:18px}}
.kpi{{border-radius:8px;padding:14px 15px}}
.kpi-a{{background:#0d9488;color:#fff}}
.kpi-b{{background:#0f172a;color:#fff}}
.kpi-c{{background:#fff;border:1px solid #e2e8f0;box-shadow:0 1px 3px rgba(0,0,0,0.06)}}
.kpi .ql{{font-size:0.59rem;font-weight:800;text-transform:uppercase;letter-spacing:0.1em;margin-bottom:7px}}
.kpi-a .ql,.kpi-b .ql{{color:#99f6e4}}
.kpi-c .ql{{color:#64748b}}
.kpi .qv{{font-size:1.5rem;font-weight:800;line-height:1;letter-spacing:-0.02em}}
.kpi-a .qv,.kpi-b .qv{{color:#fff}}
.kpi-c .qv{{color:#0f172a}}
.kpi .qu{{font-size:0.62rem;margin-top:5px}}
.kpi-a .qu,.kpi-b .qu{{color:#94a3b8}}
.kpi-c .qu{{color:#64748b}}

/* ── Flow grid ── */
.flow{{display:flex;align-items:flex-start;gap:0}}
.col{{flex:1 1 0;min-width:0;padding:0 7px}}
.col:first-child{{padding-left:0}}
.col:last-child{{padding-right:0}}
.col-wide{{flex:1.65 1 0}}
.col-hdr{{font-size:0.57rem;font-weight:800;text-transform:uppercase;letter-spacing:0.1em;color:#94a3b8;padding-bottom:7px;border-bottom:2px solid #cbd5e1;margin-bottom:9px}}

/* ── Arrow connectors ── */
.arrow{{flex:0 0 24px;display:flex;flex-direction:column;align-items:center;padding-top:48px;color:#0d9488}}
.arrow svg{{width:16px;height:16px;flex-shrink:0}}
.arrow-lbl{{font-size:0.5rem;font-weight:700;text-align:center;color:#94a3b8;max-width:40px;margin-top:4px;line-height:1.3;text-transform:uppercase;letter-spacing:0.05em}}

/* ── Entity cards ── */
.card{{background:#fff;border:1px solid #e2e8f0;border-radius:8px;padding:11px 12px;margin-bottom:8px;box-shadow:0 1px 3px rgba(0,0,0,0.05)}}
.card-t{{font-size:0.77rem;font-weight:700;color:#0f172a;margin-bottom:3px}}
.card-b{{font-size:0.66rem;color:#475569;line-height:1.5}}
.tag{{display:inline-block;background:#f0fdfa;color:#0d9488;font-size:0.58rem;font-weight:700;padding:2px 7px;border-radius:3px;border:1px solid #99f6e4;margin-top:4px}}

/* ── Data rows inside cards ── */
.sr{{display:flex;justify-content:space-between;align-items:baseline;padding:2.5px 0}}
.sl{{font-size:0.63rem;color:#64748b}}
.sv{{font-size:0.71rem;font-weight:600;color:#0f172a}}
.sv.g{{color:#0d9488}}

/* ── Value pool (baseline column) ── */
.pool{{background:#f0fdfa;border:1px solid #99f6e4;border-left:4px solid #0d9488;border-radius:8px;overflow:hidden;box-shadow:0 1px 4px rgba(13,148,136,0.08)}}
.psec{{padding:10px 14px;border-bottom:1px solid #ccfbf1}}
.psec:last-child{{border-bottom:none}}
.psec-t{{font-size:0.57rem;font-weight:800;text-transform:uppercase;letter-spacing:0.09em;color:#0d9488;margin-bottom:5px}}
.pval{{font-size:0.88rem;font-weight:700;color:#0f172a;line-height:1.3}}
.psub{{font-size:0.62rem;color:#64748b;margin-top:2px;line-height:1.4}}
.total-row{{display:flex;justify-content:space-between;align-items:baseline;margin-top:7px;padding-top:7px;border-top:1px solid #99f6e4}}
.total-lbl{{font-size:0.7rem;font-weight:700;color:#0f172a}}
.total-val{{font-size:1.0rem;font-weight:800;color:#0d9488}}
.eng{{font-size:0.59rem;color:#94a3b8;margin-top:5px;font-style:italic}}

/* ── Outcome cards ── */
.oc{{background:#fff;border:1px solid #e2e8f0;border-radius:8px;padding:10px 12px;margin-bottom:7px;box-shadow:0 1px 2px rgba(0,0,0,0.04)}}
.oc-l{{font-size:0.57rem;font-weight:800;text-transform:uppercase;letter-spacing:0.09em;color:#94a3b8;margin-bottom:4px}}
.oc-v{{font-size:1.05rem;font-weight:800;color:#0f172a;line-height:1.2}}
.oc-v.t{{color:#0d9488}}

/* ── Footer ── */
.foot{{margin-top:16px;font-size:0.6rem;color:#94a3b8;border-top:1px solid #e2e8f0;padding-top:10px;line-height:1.6}}
</style></head><body><div class="pg">

<div class="hdr">
  <div>
    <div class="hdr-title">{T("em_stake_framework_title")}</div>
    <div class="hdr-sub">{deal_id} &nbsp;·&nbsp; {prod_name} &nbsp;·&nbsp; {T("em_stake_programme_sub", contract_yrs=contract_yrs)}</div>
  </div>
  <div class="hdr-badge">{T("em_stake_confidential")}</div>
</div>

<div class="kpis">
  <div class="kpi kpi-a">
    <div class="ql">{T("em_stake_kpi_savings_lbl")}</div>
    <div class="qv">{esc(save_fmt)}</div>
    <div class="qu">{T("em_stake_kpi_savings_unit", currency=currency)}</div>
  </div>
  <div class="kpi kpi-b">
    <div class="ql">{T("em_hero_rate")}</div>
    <div class="qv">{sr_pct:.1f}%</div>
    <div class="qu">{T("em_stake_kpi_rate_unit")}</div>
  </div>
  <div class="kpi kpi-b">
    <div class="ql">{T("em_stake_kpi_energy_lbl")}</div>
    <div class="qv">{kwh_mwh:,.0f}</div>
    <div class="qu">{T("em_stake_kpi_energy_unit")}</div>
  </div>
  <div class="kpi kpi-b">
    <div class="ql">{T("em_stake_kpi_carbon_lbl")}</div>
    <div class="qv">{co2_t_yr:,.0f}</div>
    <div class="qu">{T("em_stake_kpi_carbon_unit")}</div>
  </div>
  <div class="kpi kpi-c">
    <div class="ql">{T("em_stake_kpi_invest_lbl")}</div>
    <div class="qv">{esc(capex_fmt)}</div>
    <div class="qu">{T("em_stake_kpi_invest_unit", currency=currency)}</div>
  </div>
</div>

<div class="flow">

  <div class="col">
    <div class="col-hdr">{T("em_stake_col_gov")}</div>
    <div class="card">
      <div class="card-t">{T("em_stake_node_district")}</div>
      <div class="card-b">{T("em_stake_node_district_sub")}</div>
    </div>
    <div class="card">
      <div class="card-t">{T("em_stake_node_urban_mgmt")}</div>
      <div class="card-b">{T("em_stake_node_urban_mgmt_sub")}</div>
    </div>
    <div class="card">
      <div class="card-t">{T("em_stake_node_dev_group")}</div>
      <div class="card-b">{T("em_stake_node_dev_group_sub")}</div>
    </div>
  </div>

  <div class="arrow">
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M5 12h14M13 6l6 6-6 6"/></svg>
    <div class="arrow-lbl">{T("em_stake_edge_to_middle")}</div>
  </div>

  <div class="col">
    <div class="col-hdr">{T("em_stake_col_market")}</div>
    <div class="card">
      <div class="card-t">{T("em_stake_node_tender")}</div>
      <div class="card-b">{T("em_stake_node_tender_sub")}</div>
    </div>
    <div class="card">
      <div class="card-t">{T("em_stake_node_hpwinner")}</div>
      <div class="card-b">{T("em_stake_node_hpwinner_sub")}<br/><span class="tag">{prod_name}</span></div>
    </div>
  </div>

  <div class="arrow">
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M5 12h14M13 6l6 6-6 6"/></svg>
    <div class="arrow-lbl">{T("em_stake_arrow_install")}</div>
  </div>

  <div class="col">
    <div class="col-hdr">{T("em_stake_col_middle")}</div>
    <div class="card">
      <div class="card-t">{T("em_stake_node_hosting")}</div>
      <div class="card-b">
        <div class="sr"><span class="sl">{T("em_stake_lbl_lights")}</span><span class="sv">{nl}</span></div>
        <div class="sr"><span class="sl">{T("em_stake_lbl_poles")}</span><span class="sv">{esc(poles_s)}</span></div>
        <div class="sr"><span class="sl">{T("em_stake_out_contract")}</span><span class="sv">{contract_yrs} yr</span></div>
        <div class="sr"><span class="sl">{T("tbl_total_capex")}</span><span class="sv">{esc(capex_fmt)} {esc(currency)}</span></div>
      </div>
    </div>
    <div class="card">
      <div class="card-t">{T("em_stake_node_ai_platform")}</div>
      <div class="card-b">{T("em_stake_edge_feedback")}</div>
    </div>
  </div>

  <div class="arrow">
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M5 12h14M13 6l6 6-6 6"/></svg>
    <div class="arrow-lbl">{T("em_stake_edge_data_in")}</div>
  </div>

  <div class="col col-wide">
    <div class="col-hdr">{T("em_stake_col_pool")}</div>
    <div class="pool">

      <div class="psec">
        <div class="psec-t">{T("em_stake_pool_audit")}</div>
        <div class="pval">{esc(audit["audit_elec_last"])} &nbsp;·&nbsp; {esc(audit["audit_om_last"])}</div>
        <div class="psub">{T("em_stake_lbl_elec_om_sub")}</div>
      </div>

      <div class="psec">
        <div class="psec-t">{T("em_stake_pool_audit_range")}</div>
        <div class="pval">{esc(audit["audit_elec_rng"])}</div>
      </div>

      <div class="psec">
        <div class="psec-t">{T("em_stake_pool_audit_om_range")}</div>
        <div class="pval">{esc(audit["audit_om_rng"])}</div>
      </div>

      <div class="psec">
        <div class="psec-t">{T("em_stake_lbl_baseline")}</div>
        <div class="pval">{esc(b1b2_fmt)} {esc(currency)}/yr</div>
        <div class="psub">{T("em_stake_lbl_bline_detail", b1=b1_fmt, b2=b2_fmt)}</div>
      </div>

      <div class="psec">
        <div class="psec-t">{T("em_stake_pool_savings")}</div>
        <div class="sr"><span class="sl">{T("em_stake_lbl_elec_reduc")}</span><span class="sv g">−{esc(elec_sv)}</span></div>
        <div class="sr"><span class="sl">{T("em_stake_lbl_om_reduc")}</span><span class="sv g">−{esc(om_sv)}</span></div>
        {capex_row}
        <div class="total-row">
          <span class="total-lbl">{T("em_stake_lbl_total_save")}</span>
          <span class="total-val">{esc(save_fmt)} {esc(currency)}/yr</span>
        </div>
        {engine_note}
      </div>

      <div class="psec">
        <div class="psec-t">{T("em_stake_lbl_cont_targets")}</div>
        <div class="sr"><span class="sl">{T("em_stake_lbl_cont_total")}</span><span class="sv">{esc(h5_s)}</span></div>
        <div class="sr"><span class="sl">{T("em_stake_lbl_tgt_savings")}</span><span class="sv">{esc(g6_s)}</span></div>
        <div class="sr"><span class="sl">{T("em_stake_lbl_mgmt_fee")}</span><span class="sv">{T("em_stake_lbl_fee_pct", fee=fee_rate_pct)}</span></div>
      </div>

    </div>
  </div>

  <div class="arrow">
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M5 12h14M13 6l6 6-6 6"/></svg>
    <div class="arrow-lbl">{T("em_stake_edge_to_out")}</div>
  </div>

  <div class="col">
    <div class="col-hdr">{T("em_stake_col_out")}</div>
    <div class="oc"><div class="oc-l">{T("em_stake_out_contract")}</div><div class="oc-v">{contract_yrs} yr</div></div>
    <div class="oc"><div class="oc-l">{T("em_stake_out_energy")}</div><div class="oc-v t">{kwh_mwh:,.0f} MWh</div></div>
    <div class="oc"><div class="oc-l">{T("em_stake_out_carbon")}</div><div class="oc-v t">{co2_t_yr:,.1f} tCO₂e</div></div>
    <div class="oc"><div class="oc-l">{T("em_stake_out_savings_rate")}</div><div class="oc-v">{sr_pct:.1f}%</div></div>
    <div class="oc"><div class="oc-l">{T("em_stake_out_fee")}</div><div class="oc-v">{fee_rate_pct:.0f}%</div></div>
  </div>

</div>

<div class="foot">
  {T("em_stake_footer_text", currency=currency)}
</div>

</div></body></html>"""


def _payback_chart(
    capex: float, annual_gross: float, fee_rate_pct: float,
    contract_yrs: int, currency: str,
) -> Tuple[go.Figure, Optional[float], float]:
    """Client cumulative cashflow with payback marker.

    Returns (figure, payback_year_or_none, final_cumulative_at_term).
    """
    fee_yr = annual_gross * fee_rate_pct / 100.0
    net_yr = annual_gross - fee_yr

    years = list(range(0, contract_yrs + 1))
    bar_y: List[float] = [-capex] + [net_yr] * contract_yrs
    cum: List[float] = []
    running = 0.0
    for v in bar_y:
        running += v
        cum.append(running)

    # Linear-interpolated payback year (when cumulative first crosses zero)
    payback: Optional[float] = None
    for i in range(1, len(cum)):
        if cum[i-1] < 0 and cum[i] >= 0:
            frac = -cum[i-1] / (cum[i] - cum[i-1])
            payback = (i - 1) + frac
            break

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=years, y=bar_y,
        name=t("em_payback_annual_net"),
        marker_color=["#EF553B" if v < 0 else "#00CC96" for v in bar_y],
        text=[f"{v/1e6:+.2f}M" for v in bar_y],
        textposition="outside",
    ))
    fig.add_trace(go.Scatter(
        x=years, y=cum,
        name=t("em_payback_cum"),
        mode="lines+markers",
        line=dict(color="#FECB52", width=3),
    ))
    fig.add_hline(y=0, line_dash="dash", line_color="gray", line_width=1)
    if payback is not None:
        fig.add_vline(
            x=payback, line_dash="dash", line_color="#00CC96", line_width=2,
            annotation_text=t("em_payback_marker", yrs=payback),
            annotation_position="top",
        )
    fig.update_layout(
        title=t("em_payback_title"),
        xaxis_title=t("em_payback_axis"),
        yaxis_title=t("em_payback_y", currency=currency),
        height=460,
        hovermode="x unified",
        legend=dict(orientation="h", y=1.12),
    )
    return fig, payback, cum[-1]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    st.set_page_config(
        page_title="能源托管 Compare",
        page_icon="💧",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    st.markdown("""
    <style>
    [data-testid="metric-container"] { background: #1e2130; border-radius: 8px; padding: 12px; }
    </style>
    """, unsafe_allow_html=True)

    products_cfg, savings_cfg, financial_cfg = _get_configs()

    # ----------------------------------------------------------------
    # Sidebar
    # ----------------------------------------------------------------
    with st.sidebar:
        lang = st.radio("Language / 语言", options=["EN", "中文"], horizontal=True)
        _i18n.set_lang("en" if lang == "EN" else "zh")

        st.title(t("em_sidebar_title"))
        st.caption(t("em_sidebar_caption"))
        st.divider()

        # --- Deal file ---
        st.subheader(t("deal_file_header"))
        files = _find_xlsx_files()
        if not files:
            st.error(t("no_files_error"))
            st.stop()

        file_labels = {f.name: f for f in files}
        chosen_name = st.selectbox(t("select_questionnaire"), list(file_labels))
        chosen_xlsx = file_labels[chosen_name]

        try:
            answers = _load_answers(str(chosen_xlsx))
            deal = from_answers(answers)
        except Exception as e:
            st.error(t("load_error", error=e))
            st.stop()

        st.caption(t("deal_caption",
                     deal_id=deal.deal_id,
                     n_lights=deal.n_lights,
                     currency=deal.currency))

        # --- Product ---
        st.subheader(t("product_header"))
        product_key = st.radio(
            t("select_product"), _PRODUCT_KEYS,
            format_func=lambda k: t(_PROD_KEY_MAP[k]),
        )
        product = products_cfg.get(product_key)

        # --- Project CAPEX (single number, no per-light sliders) ---
        st.subheader(t("em_capex_header"))
        default_capex, source_key = _resolved_capex(deal, product, deal.n_lights)
        capex_total = st.number_input(
            t("em_capex_label", currency=deal.currency),
            min_value=0.0,
            value=float(default_capex),
            step=100_000.0,
            help=t("em_capex_help"),
        )
        st.caption(t("em_capex_source", source=t(source_key)))

        # --- Contract length ---
        fin = financial_cfg
        contract_yrs = st.slider(
            t("contract_yrs_label"),
            min_value=int(fin.default_contract_yrs.min),
            max_value=int(fin.default_contract_yrs.max),
            value=int(deal.contract_length_yrs or fin.default_contract_yrs.default),
        )

        # --- Savings sliders ---
        st.subheader(t("savings_header"))
        slider_mechanisms = savings_cfg.sliders_for_product(product_key)
        _field_map = {
            "adaptive_dimming":                   "adaptive_dimming_pct",
            "predictive_maintenance_inspections":  "inspection_reduction_pct",
            "predictive_maintenance_tickets":      "ticket_reduction_pct",
            "failure_rate_reduction":              "failure_reduction_pct",
            "solar_grid_offset":                   "solar_grid_offset_pct",
        }
        _slider_vals: Dict[str, float] = {}
        for key, mech in slider_mechanisms.items():
            if key not in _field_map:
                continue
            badge = t(_CONF_KEY.get(mech.confidence, "badge_medium"))
            display = t("savings_names").get(key, mech.display_name)
            val = st.slider(
                f"{display} — {badge}",
                min_value=float(mech.min_pct),
                max_value=float(mech.max_pct),
                value=float(mech.default_pct),
                step=1.0, format="%g%%",
            )
            _slider_vals[_field_map[key]] = val

        adaptive_dimming_pct     = _slider_vals.get("adaptive_dimming_pct", 12.0)
        inspection_reduction_pct = _slider_vals.get("inspection_reduction_pct", 30.0)
        ticket_reduction_pct     = _slider_vals.get("ticket_reduction_pct", 25.0)
        failure_reduction_pct    = _slider_vals.get("failure_reduction_pct", 60.0)
        solar_grid_offset_pct    = _slider_vals.get("solar_grid_offset_pct", 75.0)

        # --- Carbon emission factor ---
        st.subheader(t("em_emission_header"))
        emission_factor = st.slider(
            t("em_emission_label"),
            min_value=0.3, max_value=0.9,
            value=0.581, step=0.01,
            help=t("em_emission_help"),
        )

        # --- 托管费率 ---
        st.subheader(t("em_fee_header"))
        fee_rate_pct = st.slider(
            t("em_fee_label"),
            min_value=0.0, max_value=80.0,
            value=30.0, step=5.0,
            help=t("em_fee_help"),
        )

    # ----------------------------------------------------------------
    # Build params (force project_investment_cny via deal override)
    # ----------------------------------------------------------------
    # If the user edited the capex number in the sidebar, override deal.B6.
    deal_for_engine = deal.model_copy(update={"project_investment_cny": capex_total})

    params = ScenarioParams(
        product_key=product_key,
        # These per-light values are irrelevant when B6 is set, but the model
        # still requires them — use product spec as a placeholder.
        hardware_cost_per_light=product.hardware_cost_per_light_cny,
        installation_cost_per_light=product.installation_cost_per_light_cny,
        platform_fee_per_light_yr=product.platform_fee_per_light_yr_cny,
        annual_service_fee_per_light=1.0,   # dummy, not surfaced in this UI
        contract_yrs=contract_yrs,
        adaptive_dimming_pct=adaptive_dimming_pct,
        inspection_reduction_pct=inspection_reduction_pct,
        ticket_reduction_pct=ticket_reduction_pct,
        failure_reduction_pct=failure_reduction_pct,
        solar_grid_offset_pct=solar_grid_offset_pct,
        annual_fee_escalator_pct=financial_cfg.annual_fee_escalator.default,
        hpwinner_wacc_pct=financial_cfg.hpwinner_wacc.default,
        contingency_pct=0.0,
        residual_value_pct=financial_cfg.residual_value_pct.default,
        om_cost_per_person_day=financial_cfg.om_cost_per_person_day.default,
        om_cost_per_vehicle_day=financial_cfg.om_cost_per_vehicle_day.default,
        repair_cost_per_ticket=financial_cfg.repair_cost_per_ticket.default,
    )

    with st.spinner(t("spinner_model")):
        r = run_model(deal_for_engine, product, params, config_versions())

    s = r.annual_savings
    energy = _energy_metrics(deal_for_engine, params, product)
    elec_after, elec_saving, om_saving = _client_display_om_elec_savings(
        deal_for_engine, params, product, energy
    )
    capex_saving = s.failure_rate_reduction
    client_save_y1 = elec_saving + om_saving + capex_saving

    co2_t_yr = energy["kwh_saved"] * emission_factor / 1000.0
    savings_rate = (
        (client_save_y1 / deal_for_engine.baseline_total_annual_cost)
        if deal_for_engine.baseline_total_annual_cost > 0
        else 0.0
    )
    fee_yr = client_save_y1 * fee_rate_pct / 100.0
    net_yr = client_save_y1 - fee_yr
    net_total = net_yr * contract_yrs
    fee_total = fee_yr * contract_yrs

    # ----------------------------------------------------------------
    # Hero strip
    # ----------------------------------------------------------------
    st.header(t("em_hero_title", deal_id=deal.deal_id))

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric(t("em_hero_kwh_saved"), f"{energy['kwh_saved']/1000:,.0f} MWh")
    c2.metric(t("em_hero_gross"),     _fmt(client_save_y1, deal.currency))
    if abs(s.total - client_save_y1) > 50_000:
        c2.caption(t("em_hero_gross_engine_note", engine=_fmt(s.total, deal.currency)))
    c3.metric(t("em_hero_rate"),      f"{savings_rate*100:.1f}%")
    c4.metric(t("em_hero_net_total", yrs=contract_yrs), _fmt(net_total, deal.currency))
    c5.metric(t("em_hero_co2"),       f"{co2_t_yr:,.0f} tCO₂e")

    # ----------------------------------------------------------------
    # Tabs
    # ----------------------------------------------------------------
    tab_cmp, tab_detail, tab_multi, tab_tech, tab_stake = st.tabs([
        t("em_tab_compare"), t("em_tab_detail"),
        t("em_tab_multi"),   t("em_tab_tech"),
        t("em_tab_stakeholders"),
    ])

    # Build before/after cost dicts — reconciled to B1/B2 so bars match questionnaire baselines
    before = {
        "elec":         deal_for_engine.annual_electricity_cost,
        "om":           deal_for_engine.annual_om_cost,
        "capex_budget": deal_for_engine.annual_capex_budget or 0.0,
    }
    after = {
        "elec":         elec_after,
        "om":           max(deal_for_engine.annual_om_cost - om_saving, 0),
        "capex_budget": max((deal_for_engine.annual_capex_budget or 0.0) - capex_saving, 0),
    }

    with tab_cmp:
        st.subheader(t("em_history_section"))
        hist_fig = _history_trend_chart(deal)
        if hist_fig is not None:
            st.plotly_chart(hist_fig, use_container_width=True)
            trend_key = _trend_message(deal)
            if trend_key == "em_history_trend_up":
                st.warning(t(trend_key))
            elif trend_key:
                st.info(t(trend_key))
            st.caption(t("em_history_help"))
        else:
            st.caption(t("em_history_no_data"))

        st.divider()
        st.subheader(t("em_project_compare_section"))
        st.plotly_chart(_cost_compare_chart(before, after, deal.currency),
                        use_container_width=True)
        # Summary table
        total_before = sum(before.values())
        total_after  = sum(after.values())
        st.markdown(f"""
| {t('em_energy_metric')} | {t('em_compare_before')} | {t('em_compare_after')} | {t('em_compare_saving')} |
|---|---:|---:|---:|
| {t('em_cat_elec')}   | {before['elec']:,.0f} | {after['elec']:,.0f} | {elec_saving:,.0f} |
| {t('em_cat_om')}     | {before['om']:,.0f}   | {after['om']:,.0f}   | {om_saving:,.0f} |
| {t('em_cat_capex')}  | {before['capex_budget']:,.0f} | {after['capex_budget']:,.0f} | {capex_saving:,.0f} |
| **{t('em_cat_total')}** | **{total_before:,.0f}** | **{total_after:,.0f}** | **{client_save_y1:,.0f}** |
        """)

    with tab_detail:
        st.plotly_chart(
            _savings_waterfall_display(s, params, deal.currency, elec_saving, om_saving),
            use_container_width=True,
        )

        st.subheader(t("em_energy_table_title"))
        kw_before = deal_for_engine.existing_wattage_W * deal_for_engine.n_lights / 1000.0
        kw_after  = deal_for_engine.proposed_wattage_W * deal_for_engine.n_lights / 1000.0
        cost_before = deal_for_engine.annual_electricity_cost
        cost_after  = elec_after
        co2_before  = energy["kwh_before"] * emission_factor / 1000.0
        co2_after   = energy["kwh_after_grid"] * emission_factor / 1000.0
        st.markdown(f"""
| {t('em_energy_metric')} | {t('em_energy_before')} | {t('em_energy_after')} | {t('em_energy_saved')} |
|---|---:|---:|---:|
| {t('em_row_fixture_w')} | {deal.existing_wattage_W:,.0f} | {deal.proposed_wattage_W:,.0f} | {deal.existing_wattage_W - deal.proposed_wattage_W:,.0f} |
| {t('em_row_fleet_kw')} | {kw_before:,.1f} | {kw_after:,.1f} | {kw_before - kw_after:,.1f} |
| {t('em_row_annual_kwh')} | {energy['kwh_before']:,.0f} | {energy['kwh_after_grid']:,.0f} | {energy['kwh_saved']:,.0f} |
| {t('em_row_annual_cost', currency=deal.currency)} | {cost_before:,.0f} | {cost_after:,.0f} | {elec_saving:,.0f} |
| {t('em_row_co2')} | {co2_before:,.1f} | {co2_after:,.1f} | {co2_t_yr:,.1f} |
        """)

    with tab_multi:
        # New: CAPEX-inclusive client cashflow with payback marker
        fig, payback, final_cum = _payback_chart(
            capex=capex_total,
            annual_gross=client_save_y1,
            fee_rate_pct=fee_rate_pct,
            contract_yrs=contract_yrs,
            currency=deal.currency,
        )
        st.plotly_chart(fig, use_container_width=True)
        st.caption(t("em_payback_help"))

        if payback is not None:
            st.success(t("em_payback_summary_ok",
                         capex=_fmt(capex_total, deal.currency),
                         payback=payback,
                         yrs=contract_yrs,
                         profit=_fmt(final_cum, deal.currency)))
        else:
            st.warning(t("em_payback_summary_long",
                         capex=_fmt(capex_total, deal.currency),
                         net=_fmt(net_yr, deal.currency),
                         yrs=contract_yrs,
                         shortfall=_fmt(abs(final_cum), deal.currency)))

    with tab_tech:
        st.subheader(t("em_tech_specs_title"))
        yes = t("em_spec_yes"); no = t("em_spec_no")
        st.markdown(f"""
| {t('em_energy_metric')} | {t('em_compare_before')} | {t('em_compare_after')} |
|---|---|---|
| {t('em_row_fixture_w')} | {deal.existing_wattage_W:,.0f} W ({deal.n_lights:,} 盏) | {deal.proposed_wattage_W:,.0f} W ({deal.n_lights:,} 盏) |
| {t('em_spec_lifetime')} | — | {product.expected_lifetime_yrs} |
| {t('em_spec_warranty')} | — | {product.warranty_yrs} |
| {t('em_spec_failure')} | {(deal.existing_failure_rate_pct or product.conventional_failure_rate_pct):.1f}% | {product.our_failure_rate_pct:.1f}% |
| {t('em_spec_dimming')} | {no} | {yes if product.dimming_capable else no} |
| {t('em_spec_solar')}   | {no} | {yes if product.solar_capable else no} |
        """)

    with tab_stake:
        stake_html = _stakeholder_map_html(
            deal_for_engine,
            product,
            deal_for_engine.currency,
            capex_total=capex_total,
            contract_yrs=contract_yrs,
            fee_rate_pct=fee_rate_pct,
            elec_saving=elec_saving,
            om_saving=om_saving,
            capex_saving=capex_saving,
            client_save_y1=client_save_y1,
            kwh_saved=energy["kwh_saved"],
            co2_t_yr=co2_t_yr,
            savings_rate=savings_rate,
            s_total_gross=s.total,
        )
        components.html(stake_html, height=1200, scrolling=True)


if __name__ == "__main__":
    main()
