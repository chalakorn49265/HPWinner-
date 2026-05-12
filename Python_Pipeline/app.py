"""Layer 5 — Streamlit dashboard for HPWinner LaaS deal analysis.

Run from repo root:
    streamlit run Python_Pipeline/app.py
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

_HERE = Path(__file__).parent          # Python_Pipeline/
_REPO = _HERE.parent                   # repo root
_READ_SCRIPT = _REPO / "read_questionnaire_input.py"

# Make layer2/layer3/layer4 importable without a package prefix
sys.path.insert(0, str(_HERE))

import plotly.graph_objects as go
import streamlit as st

import i18n as _i18n
from i18n import t
from layer2.loader import config_versions, load_financial, load_products, load_savings
from layer3.deal_loader import from_answers
from layer3.models import DealInputs, ScenarioParams
from layer4 import run_scenarios
from layer4.models import MonteCarloResult, ScenarioResults


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_CNY_M = 1_000_000
_CNY_K = 1_000

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
_VERDICT_KEY = {
    "go":        "verdict_go",
    "borderline":"verdict_borderline",
    "no-go":     "verdict_no_go",
}


def _fmt(v: float, currency: str = "CNY") -> str:
    if abs(v) >= _CNY_M:
        return f"{v/_CNY_M:.2f}M {currency}"
    if abs(v) >= _CNY_K:
        return f"{v/_CNY_K:.0f}K {currency}"
    return f"{v:,.0f} {currency}"


def _find_xlsx_files() -> List[Path]:
    candidates: List[Path] = []
    for directory in [_REPO / "data", _REPO]:
        candidates.extend(sorted(directory.glob("*filled*.xlsx")))
    seen: set = set()
    out: List[Path] = []
    for p in candidates:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


# ---------------------------------------------------------------------------
# Cached loaders
# ---------------------------------------------------------------------------

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


@st.cache_data
def _run_mc(
    xlsx_path: str,
    product_key: str,
    hardware_cost: float,
    installation_cost: float,
    platform_fee: float,
    annual_service_fee: float,
    contract_yrs: int,
    adaptive_dimming_pct: float,
    inspection_reduction_pct: float,
    ticket_reduction_pct: float,
    failure_reduction_pct: float,
    solar_grid_offset_pct: float,
    annual_fee_escalator_pct: float,
    hpwinner_wacc_pct: float,
    contingency_pct: float,
    residual_value_pct: float,
    n_simulations: int = 1000,
    seed: int = 42,
) -> MonteCarloResult:
    products_cfg, savings_cfg, financial_cfg = _get_configs()
    answers = _load_answers(xlsx_path)
    deal = from_answers(answers)
    product = products_cfg.get(product_key)

    params = ScenarioParams(
        product_key=product_key,
        hardware_cost_per_light=hardware_cost,
        installation_cost_per_light=installation_cost,
        platform_fee_per_light_yr=platform_fee,
        annual_service_fee_per_light=annual_service_fee,
        contract_yrs=contract_yrs,
        adaptive_dimming_pct=adaptive_dimming_pct,
        inspection_reduction_pct=inspection_reduction_pct,
        ticket_reduction_pct=ticket_reduction_pct,
        failure_reduction_pct=failure_reduction_pct,
        solar_grid_offset_pct=solar_grid_offset_pct,
        annual_fee_escalator_pct=annual_fee_escalator_pct,
        hpwinner_wacc_pct=hpwinner_wacc_pct,
        contingency_pct=contingency_pct,
        residual_value_pct=residual_value_pct,
        om_cost_per_person_day=financial_cfg.om_cost_per_person_day.default,
        om_cost_per_vehicle_day=financial_cfg.om_cost_per_vehicle_day.default,
        repair_cost_per_ticket=financial_cfg.repair_cost_per_ticket.default,
    )
    from layer4.sensitivity import build_specs
    from layer4.montecarlo import run_montecarlo
    specs = build_specs(params, savings_cfg, financial_cfg)
    return run_montecarlo(deal, product, params, specs,
                          n_simulations=n_simulations, seed=seed)


# ---------------------------------------------------------------------------
# Chart builders  (accept currency so axis labels are correct)
# ---------------------------------------------------------------------------

def _cashflow_chart(results: ScenarioResults) -> go.Figure:
    rows = results.point_estimate.yearly_cashflows
    years = [r.year for r in rows]
    cumulative = [r.cumulative_cashflow for r in rows]
    net = [r.net_cashflow for r in rows]

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=years, y=net,
        name=t("chart_cf_net"),
        marker_color=["#EF553B" if v < 0 else "#00CC96" for v in net],
    ))
    fig.add_trace(go.Scatter(
        x=years, y=cumulative,
        name=t("chart_cf_cum"),
        mode="lines+markers",
        line=dict(color="#636EFA", width=2),
    ))
    fig.add_hline(y=0, line_dash="dash", line_color="gray", line_width=1)
    fig.update_layout(
        title=t("chart_cf_title"),
        xaxis_title=t("chart_cf_x"),
        yaxis_title="CNY",
        legend=dict(orientation="h", y=1.1),
        hovermode="x unified",
        height=400,
    )
    return fig


def _cost_stack_chart(results: ScenarioResults) -> go.Figure:
    cap = results.point_estimate.capex
    labels = t("chart_capex_labels")
    values = [cap.hardware, cap.installation, cap.trenching, cap.contingency]
    colors = ["#636EFA", "#EF553B", "#00CC96", "#FECB52"]

    fig = go.Figure(go.Bar(
        x=labels, y=values,
        marker_color=colors,
        text=[f"{v:,.0f}" for v in values],
        textposition="outside",
    ))
    fig.update_layout(
        title=t("chart_capex_title", total=_fmt(cap.total)),
        yaxis_title="CNY",
        height=380,
    )
    return fig


def _baseline_comparison_chart(results: ScenarioResults, deal: DealInputs) -> go.Figure:
    bl = results.point_estimate.baselines
    N = results.point_estimate.yearly_cashflows[-1].year
    names = t("chart_tco_x")
    values = [bl.status_quo_total, bl.led_replacement_total, bl.laas_customer_total]
    colors = ["#EF553B", "#FFA15A", "#00CC96"]

    fig = go.Figure(go.Bar(
        x=names, y=values,
        marker_color=colors,
        text=[_fmt(v, deal.currency) for v in values],
        textposition="outside",
    ))
    fig.update_layout(
        title=t("chart_tco_title", N=N),
        yaxis_title=t("chart_tco_y", currency=deal.currency),
        height=380,
    )
    return fig


def _savings_waterfall(results: ScenarioResults, deal: DealInputs) -> go.Figure:
    s = results.point_estimate.annual_savings
    labels = t("chart_wf_labels")
    raw_values = [
        s.wattage_reduction, s.adaptive_dimming, s.inspection_reduction,
        s.ticket_reduction, s.failure_rate_reduction,
    ]
    # Solar offset is the 6th label; only include if non-zero
    if s.solar_grid_offset > 0:
        display_labels = labels[:6] + [labels[-1]]
        raw_values.append(s.solar_grid_offset)
    else:
        display_labels = labels[:5] + [labels[-1]]
    raw_values.append(s.total)

    measure = ["relative"] * (len(display_labels) - 1) + ["total"]

    fig = go.Figure(go.Waterfall(
        name=t("row_total").replace("**", ""),
        orientation="v",
        measure=measure,
        x=display_labels,
        y=raw_values,
        connector=dict(line=dict(color="rgb(63, 63, 63)")),
        increasing=dict(marker_color="#00CC96"),
        totals=dict(marker_color="#636EFA"),
    ))
    fig.update_layout(
        title=t("chart_wf_title"),
        yaxis_title=t("chart_wf_y", currency=deal.currency),
        height=420,
    )
    return fig


def _tornado_chart(results: ScenarioResults, currency: str = "CNY") -> go.Figure:
    rows = results.tornado.rows[:10]
    if not rows:
        return go.Figure()

    names = [r.display_name for r in rows]
    base = results.tornado.base_npv
    low_delta = [r.npv_at_low - base for r in rows]
    high_delta = [r.npv_at_high - base for r in rows]

    fig = go.Figure()
    fig.add_trace(go.Bar(
        y=names, x=low_delta, orientation="h",
        name=t("chart_tornado_low"), marker_color="#EF553B",
    ))
    fig.add_trace(go.Bar(
        y=names, x=high_delta, orientation="h",
        name=t("chart_tornado_high"), marker_color="#00CC96",
    ))
    fig.add_vline(x=0, line_dash="dash", line_color="gray")
    fig.update_layout(
        title=t("chart_tornado_title", base=_fmt(base, currency)),
        xaxis_title=t("chart_tornado_x", currency=currency),
        barmode="overlay",
        height=50 + 40 * len(rows),
        legend=dict(orientation="h", y=1.05),
    )
    return fig


def _mc_histogram(mc: MonteCarloResult, currency: str = "CNY") -> go.Figure:
    samples = [v for v in mc.npv_samples if v == v]
    fig = go.Figure()
    fig.add_trace(go.Histogram(
        x=samples, nbinsx=50,
        marker_color="#636EFA", opacity=0.75,
        name="NPV",
    ))
    for pct, val, color in [
        ("P10", mc.npv_p10, "#EF553B"),
        ("P50", mc.npv_p50, "#FECB52"),
        ("P90", mc.npv_p90, "#00CC96"),
    ]:
        fig.add_vline(x=val, line_dash="dash", line_color=color,
                      annotation_text=f"{pct} {_fmt(val, currency)}",
                      annotation_position="top right")
    fig.add_vline(x=0, line_color="white", line_width=1.5)
    fig.update_layout(
        title=t("chart_mc_title", n=mc.n_simulations),
        xaxis_title=t("chart_mc_x", currency=currency),
        yaxis_title=t("chart_mc_y"),
        height=380,
    )
    return fig


# ---------------------------------------------------------------------------
# Main app
# ---------------------------------------------------------------------------

def main() -> None:
    st.set_page_config(
        page_title="HPWinner LaaS",
        page_icon="💡",
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
        # Language selector FIRST — controls all labels below
        lang = st.radio(
            "Language / 语言",
            options=["EN", "中文"],
            horizontal=True,
        )
        _i18n.set_lang("en" if lang == "EN" else "zh")

        st.title(t("sidebar_title"))
        st.caption(t("sidebar_caption"))
        st.divider()

        # --- Deal file ---
        st.subheader(t("deal_file_header"))
        unique_files = _find_xlsx_files()
        if not unique_files:
            st.error(t("no_files_error"))
            st.stop()

        file_labels = {f.name: f for f in unique_files}
        chosen_name = st.selectbox(t("select_questionnaire"), list(file_labels))
        chosen_xlsx = file_labels[chosen_name]

        try:
            answers = _load_answers(str(chosen_xlsx))
            deal = from_answers(answers)
        except Exception as e:
            st.error(t("load_error", error=e))
            st.stop()

        st.caption(t("deal_caption",
                     deal_id=deal.deal_id, n_lights=deal.n_lights,
                     currency=deal.currency))

        # --- Product ---
        st.subheader(t("product_header"))
        product_key = st.radio(
            t("select_product"),
            _PRODUCT_KEYS,
            format_func=lambda k: t(_PROD_KEY_MAP[k]),
        )
        product = products_cfg.get(product_key)

        default_params = ScenarioParams.from_defaults(
            product_key, product, financial_cfg, deal
        )
        suggested_fee = default_params.suggest_fee_per_light(deal)
        fee_max = max(suggested_fee * 2.5, 1000.0)

        # --- Service fee ---
        st.subheader(t("fee_header"))
        annual_service_fee = st.slider(
            t("fee_label", currency=deal.currency),
            min_value=0.0,
            max_value=float(fee_max),
            value=float(suggested_fee),
            step=10.0,
            help=t("fee_help", suggested_fee=suggested_fee, currency=deal.currency),
        )

        # --- Contract & costs ---
        st.subheader(t("contract_header"))
        fin = financial_cfg

        hardware_cost = st.number_input(
            t("hardware_label", currency=deal.currency),
            min_value=0.0,
            value=float(product.hardware_cost_per_light_cny),
            step=100.0,
        )
        installation_cost = st.number_input(
            t("installation_label", currency=deal.currency),
            min_value=0.0,
            value=float(product.installation_cost_per_light_cny),
            step=50.0,
        )
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
                step=1.0,
                format="%g%%",
                help=mech.description,
            )
            _slider_vals[_field_map[key]] = val

        adaptive_dimming_pct     = _slider_vals.get("adaptive_dimming_pct", 12.0)
        inspection_reduction_pct = _slider_vals.get("inspection_reduction_pct", 30.0)
        ticket_reduction_pct     = _slider_vals.get("ticket_reduction_pct", 25.0)
        failure_reduction_pct    = _slider_vals.get("failure_reduction_pct", 60.0)
        solar_grid_offset_pct    = _slider_vals.get("solar_grid_offset_pct", 75.0)

        # --- Financial assumptions ---
        with st.expander(t("fin_expander"), expanded=False):
            wacc = st.slider(
                f"{t('wacc_label')} — {t(_CONF_KEY[fin.hpwinner_wacc.confidence])}",
                min_value=float(fin.hpwinner_wacc.min),
                max_value=float(fin.hpwinner_wacc.max),
                value=float(fin.hpwinner_wacc.default),
                step=0.5,
            )
            escalator = st.slider(
                f"{t('escalator_label')} — {t(_CONF_KEY[fin.annual_fee_escalator.confidence])}",
                min_value=float(fin.annual_fee_escalator.min),
                max_value=float(fin.annual_fee_escalator.max),
                value=float(fin.annual_fee_escalator.default),
                step=0.5,
            )
            contingency = st.slider(
                f"{t('contingency_label')} — {t(_CONF_KEY[fin.contingency_on_capex.confidence])}",
                min_value=float(fin.contingency_on_capex.min),
                max_value=float(fin.contingency_on_capex.max),
                value=float(fin.contingency_on_capex.default),
                step=1.0,
            )
            residual = st.slider(
                f"{t('residual_label')} — {t(_CONF_KEY[fin.residual_value_pct.confidence])}",
                min_value=float(fin.residual_value_pct.min),
                max_value=float(fin.residual_value_pct.max),
                value=float(fin.residual_value_pct.default),
                step=1.0,
            )

        n_mc = st.select_slider(
            t("mc_runs_label"),
            options=[500, 1000, 2000, 5000],
            value=1000,
            help=t("mc_runs_help"),
        )

    # ----------------------------------------------------------------
    # Build params and run point estimate
    # ----------------------------------------------------------------
    params = ScenarioParams(
        product_key=product_key,
        hardware_cost_per_light=hardware_cost,
        installation_cost_per_light=installation_cost,
        platform_fee_per_light_yr=product.platform_fee_per_light_yr_cny,
        annual_service_fee_per_light=annual_service_fee,
        contract_yrs=contract_yrs,
        adaptive_dimming_pct=adaptive_dimming_pct,
        inspection_reduction_pct=inspection_reduction_pct,
        ticket_reduction_pct=ticket_reduction_pct,
        failure_reduction_pct=failure_reduction_pct,
        solar_grid_offset_pct=solar_grid_offset_pct,
        annual_fee_escalator_pct=escalator,
        hpwinner_wacc_pct=wacc,
        contingency_pct=contingency,
        residual_value_pct=residual,
        om_cost_per_person_day=financial_cfg.om_cost_per_person_day.default,
        om_cost_per_vehicle_day=financial_cfg.om_cost_per_vehicle_day.default,
        repair_cost_per_ticket=financial_cfg.repair_cost_per_ticket.default,
    )

    if annual_service_fee <= 0:
        st.warning(t("fee_zero_warn",
                     suggested_fee=suggested_fee, currency=deal.currency))
        st.stop()

    with st.spinner(t("spinner_model")):
        cv = config_versions()
        results = run_scenarios(
            deal, product, params, savings_cfg, financial_cfg,
            config_versions=cv,
            n_simulations=1,
            mc_seed=42,
        )
    pt = results.point_estimate

    # ----------------------------------------------------------------
    # Hero strip
    # ----------------------------------------------------------------
    st.header(t("hero_title", deal_id=deal.deal_id))

    verdict_label = t(_VERDICT_KEY.get(pt.go_nogo, "verdict_borderline"))
    irr_label = f"{pt.irr * 100:.1f}%" if pt.irr is not None else "N/A"
    payback_label = (f"{pt.payback_years:.1f} yr"
                     if pt.payback_years is not None else t("payback_over"))
    cust_save_label = _fmt(pt.customer_net_saving_y1, deal.currency)

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric(t("hero_npv"),       _fmt(pt.npv, deal.currency))
    c2.metric(t("hero_irr"),       irr_label)
    c3.metric(t("hero_payback"),   payback_label)
    c4.metric(t("hero_cust_save"), cust_save_label)
    c5.metric(t("hero_verdict"),   verdict_label)

    for reason in pt.go_nogo_reasons:
        st.warning(reason)
    if pt.warnings:
        with st.expander(t("data_warn_expander")):
            for w in pt.warnings:
                st.caption(f"• {w}")

    # ----------------------------------------------------------------
    # Tabs
    # ----------------------------------------------------------------
    tab_cf, tab_cost, tab_savings, tab_risk = st.tabs([
        t("tab_cashflow"), t("tab_cost"), t("tab_savings"), t("tab_risk"),
    ])

    with tab_cf:
        st.plotly_chart(_cashflow_chart(results), use_container_width=True)
        rows_data = pt.yearly_cashflows
        col_yr, col_fee, col_net, col_cum = st.columns(4)
        col_yr.write(t("cf_year"))
        col_fee.write(t("cf_fee"))
        col_net.write(t("cf_net"))
        col_cum.write(t("cf_cum"))
        for row in rows_data:
            col_yr.write(str(row.year))
            col_fee.write(f"{row.service_fee_revenue:,.0f}")
            col_net.write(f"{row.net_cashflow:,.0f}")
            col_cum.write(f"{row.cumulative_cashflow:,.0f}")

    with tab_cost:
        left, right = st.columns(2)
        with left:
            st.plotly_chart(_cost_stack_chart(results), use_container_width=True)
        with right:
            st.plotly_chart(_baseline_comparison_chart(results, deal),
                            use_container_width=True)

        bl = pt.baselines
        share_str = (f"{pt.hpwinner_implied_savings_share_pct:.1f}%"
                     if pt.hpwinner_implied_savings_share_pct else "N/A")
        st.markdown(f"""
| {t('tbl_metric')} | {t('tbl_value')} |
|---|---|
| {t('tbl_total_capex')} | {_fmt(pt.capex.total, deal.currency)} |
| {t('tbl_fee_y1')} | {_fmt(pt.annual_service_fee_y1, deal.currency)} |
| {t('tbl_cust_vs_sq')} | {_fmt(bl.laas_customer_saving_vs_status_quo, deal.currency)} |
| {t('tbl_cust_vs_led')} | {_fmt(bl.laas_customer_saving_vs_led, deal.currency)} |
| {t('tbl_savings_share')} | {share_str} |
        """)

    with tab_savings:
        st.plotly_chart(_savings_waterfall(results, deal), use_container_width=True)

        s = pt.annual_savings
        st.markdown(f"""
| {t('tbl_mechanism')} | {t('tbl_annual_saving', currency=deal.currency)} | {t('tbl_pct')} |
|---|---:|---:|
| {t('row_wattage')} | {s.wattage_reduction:,.0f} | {s.wattage_reduction/s.total*100:.1f}% |
| {t('row_dimming')} | {s.adaptive_dimming:,.0f} | {s.adaptive_dimming/s.total*100:.1f}% |
| {t('row_inspection')} | {s.inspection_reduction:,.0f} | {s.inspection_reduction/s.total*100:.1f}% |
| {t('row_ticket')} | {s.ticket_reduction:,.0f} | {s.ticket_reduction/s.total*100:.1f}% |
| {t('row_failure')} | {s.failure_rate_reduction:,.0f} | {s.failure_rate_reduction/s.total*100:.1f}% |
| {t('row_solar')} | {s.solar_grid_offset:,.0f} | {s.solar_grid_offset/s.total*100:.1f}% |
| {t('row_total')} | **{s.total:,.0f}** | 100% |
        """)

    with tab_risk:
        st.subheader(t("tornado_header"))
        st.plotly_chart(_tornado_chart(results, deal.currency),
                        use_container_width=True)

        st.subheader(t("mc_header"))
        with st.spinner(t("spinner_mc")):
            mc = _run_mc(
                xlsx_path=str(chosen_xlsx),
                product_key=product_key,
                hardware_cost=hardware_cost,
                installation_cost=installation_cost,
                platform_fee=product.platform_fee_per_light_yr_cny,
                annual_service_fee=annual_service_fee,
                contract_yrs=contract_yrs,
                adaptive_dimming_pct=adaptive_dimming_pct,
                inspection_reduction_pct=inspection_reduction_pct,
                ticket_reduction_pct=ticket_reduction_pct,
                failure_reduction_pct=failure_reduction_pct,
                solar_grid_offset_pct=solar_grid_offset_pct,
                annual_fee_escalator_pct=escalator,
                hpwinner_wacc_pct=wacc,
                contingency_pct=contingency,
                residual_value_pct=residual,
                n_simulations=n_mc,
                seed=42,
            )

        st.caption(t("mc_caption",
                     npv_range=mc.npv_range_label,
                     prob=mc.prob_positive_npv,
                     params=", ".join(mc.varied_parameters)))
        st.plotly_chart(_mc_histogram(mc, deal.currency), use_container_width=True)

        if mc.payback_p50 is not None:
            st.caption(t("pb_caption",
                         pb_range=mc.payback_range_label,
                         yrs=contract_yrs,
                         prob=mc.prob_payback_in_contract))
        if mc.irr_p50 is not None:
            st.caption(t("irr_caption", irr_range=mc.irr_range_label))


if __name__ == "__main__":
    main()
