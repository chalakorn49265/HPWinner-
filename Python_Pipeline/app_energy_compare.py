"""能源托管 (Energy Management) Comparison Dashboard.

Client-facing view: how much the customer saves with HPWinner's solution
versus their current status quo. Reuses the same engine and configs as the
LaaS analyzer, but frames everything from the client's perspective.

Run from repo root:
    streamlit run Python_Pipeline/app_energy_compare.py
"""

from __future__ import annotations

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

import i18n as _i18n
from i18n import t
from layer2.loader import config_versions, load_financial, load_products, load_savings
from layer3.deal_loader import from_answers
from layer3.engine import run_model
from layer3.models import DealInputs, ScenarioParams


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


def _savings_waterfall(s, currency: str) -> go.Figure:
    labels = t("chart_wf_labels")  # reuses LaaS labels — same mechanisms
    raw_values = [
        s.wattage_reduction, s.adaptive_dimming, s.inspection_reduction,
        s.ticket_reduction, s.failure_rate_reduction,
    ]
    if s.solar_grid_offset > 0:
        display_labels = labels[:6] + [labels[-1]]
        raw_values.append(s.solar_grid_offset)
    else:
        display_labels = labels[:5] + [labels[-1]]
    raw_values.append(s.total)

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


def _history_trend_chart(deal: DealInputs, after_total: float) -> Optional[go.Figure]:
    """3-yr historical electricity + O&M, plus projected 'After HPWinner' bar."""
    elec_y = [deal.annual_electricity_y_minus_2,
              deal.annual_electricity_y_minus_1,
              deal.annual_electricity_cost]
    om_y   = [deal.annual_om_y_minus_2,
              deal.annual_om_y_minus_1,
              deal.annual_om_cost]
    # Need at least one prior-year datapoint to be worth showing
    if not any(v for v in elec_y[:2]) and not any(v for v in om_y[:2]):
        return None

    labels = [t("em_history_y_minus_2"), t("em_history_y_minus_1"),
              t("em_history_y_0"), t("em_history_after")]
    elec_vals = [(v or 0) for v in elec_y] + [after_total["elec"]]
    om_vals   = [(v or 0) for v in om_y]   + [after_total["om"]]

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
    # Vertical divider between history and projection
    fig.add_vline(x=2.5, line_dash="dot", line_color="white", line_width=1)
    fig.update_layout(
        title=t("em_history_title"),
        barmode="stack",
        yaxis_title=f"{deal.currency}/yr",
        height=400,
        legend=dict(orientation="h", y=1.1),
    )
    return fig


def _trend_message(deal: DealInputs) -> Optional[str]:
    """Detect rising/falling/flat trend in combined electricity + O&M."""
    totals = []
    for elec, om in [
        (deal.annual_electricity_y_minus_2, deal.annual_om_y_minus_2),
        (deal.annual_electricity_y_minus_1, deal.annual_om_y_minus_1),
        (deal.annual_electricity_cost,      deal.annual_om_cost),
    ]:
        totals.append((elec or 0) + (om or 0))
    if all(v > 0 for v in totals):
        change = (totals[-1] - totals[0]) / totals[0]
        if change > 0.05:
            return "em_history_trend_up"
        if change < -0.05:
            return "em_history_trend_dn"
        return "em_history_trend_flat"
    return None


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
    energy = _energy_metrics(deal, params, product)
    co2_t_yr = energy["kwh_saved"] * emission_factor / 1000.0
    savings_rate = (s.total / deal.baseline_total_annual_cost) if deal.baseline_total_annual_cost > 0 else 0.0
    fee_yr = s.total * fee_rate_pct / 100.0
    net_yr = s.total - fee_yr
    net_total = net_yr * contract_yrs
    fee_total = fee_yr * contract_yrs

    # ----------------------------------------------------------------
    # Hero strip
    # ----------------------------------------------------------------
    st.header(t("em_hero_title", deal_id=deal.deal_id))

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric(t("em_hero_kwh_saved"), f"{energy['kwh_saved']/1000:,.0f} MWh")
    c2.metric(t("em_hero_gross"),     _fmt(s.total, deal.currency))
    c3.metric(t("em_hero_rate"),      f"{savings_rate*100:.1f}%")
    c4.metric(t("em_hero_net_total", yrs=contract_yrs), _fmt(net_total, deal.currency))
    c5.metric(t("em_hero_co2"),       f"{co2_t_yr:,.0f} tCO₂e")

    # ----------------------------------------------------------------
    # Tabs
    # ----------------------------------------------------------------
    tab_cmp, tab_detail, tab_multi, tab_tech = st.tabs([
        t("em_tab_compare"), t("em_tab_detail"),
        t("em_tab_multi"),   t("em_tab_tech"),
    ])

    # Build before/after cost dicts
    elec_saving = s.wattage_reduction + s.adaptive_dimming + s.solar_grid_offset
    om_saving   = s.inspection_reduction + s.ticket_reduction
    capex_saving = s.failure_rate_reduction
    before = {
        "elec":         deal.annual_electricity_cost,
        "om":           deal.annual_om_cost,
        "capex_budget": deal.annual_capex_budget or 0.0,
    }
    after = {
        "elec":         max(deal.annual_electricity_cost - elec_saving, 0),
        "om":           max(deal.annual_om_cost - om_saving, 0),
        "capex_budget": max((deal.annual_capex_budget or 0.0) - capex_saving, 0),
    }

    with tab_cmp:
        # 3-year historical trend (only if questionnaire has B1a/B1b/B2a/B2b)
        hist_fig = _history_trend_chart(deal, after)
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
| **{t('em_cat_total')}** | **{total_before:,.0f}** | **{total_after:,.0f}** | **{s.total:,.0f}** |
        """)

    with tab_detail:
        st.plotly_chart(_savings_waterfall(s, deal.currency), use_container_width=True)

        st.subheader(t("em_energy_table_title"))
        kw_before = deal.existing_wattage_W * deal.n_lights / 1000.0
        kw_after  = deal.proposed_wattage_W * deal.n_lights / 1000.0
        cost_before = deal.annual_electricity_cost
        cost_after  = max(cost_before - elec_saving, 0)
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
            annual_gross=s.total,
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


if __name__ == "__main__":
    main()
