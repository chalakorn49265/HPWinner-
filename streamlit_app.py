"""Chongqing sales-rep questionnaire — client economics dashboard (MVED / skill-aligned).

Run locally (macOS often has no ``pip`` / ``streamlit`` on PATH — use ``python3 -m``)::

    python3 -m pip install -r requirements.txt
    python3 -m streamlit run streamlit_app.py

Regenerate survey JSON from the dropdown / numeric workbook::

    python3 read_questionnaire_input.py \\
      --input questionnaire_01_filled_chongqing_sales_rep_dropdown_number_only.xlsx \\
      --sheet both --answers-only --compact > data/chongqing_answers.json

Cashflows and KPIs are **illustrative** (E3×A3 CAPEX proxy + energy-savings share); not a contractual model.
"""

from __future__ import annotations

import json
from pathlib import Path

import plotly.graph_objects as go
import streamlit as st

from chongqing.economics import baseline_annual_spend_parts, build_economics
from chongqing.routing import (
    RouteStory,
    collect_validation_warnings,
    group_fixed_facts,
    load_answers,
    parse_horizon_years,
    parse_tariff_kw,
    route_dashboard,
)

REPO_ROOT = Path(__file__).resolve().parent


def _facts_table(rows: dict[str, object]) -> None:
    if not rows:
        st.caption("_No rows._")
        return
    st.dataframe(
        [{"ID": k, "Answer": v} for k, v in rows.items()],
        hide_index=True,
        use_container_width=True,
    )


def _fmt_money(v: float | None, cur: str) -> str:
    if v is None:
        return "—"
    return f"{v:,.0f} {cur}"


@st.cache_data
def _cached_answers():
    return load_answers(REPO_ROOT)


def main() -> None:
    st.set_page_config(
        page_title="Chongqing — client economics",
        layout="wide",
    )

    try:
        answers = _cached_answers()
    except FileNotFoundError as e:
        st.error(str(e))
        st.stop()

    route = route_dashboard(answers)
    warnings = collect_validation_warnings(answers)
    grouped = group_fixed_facts(answers)

    st.title("Chongqing — client economics (submitted baseline + scenarios)")
    st.caption(route.summary)

    st.info(
        "**Illustrative model:** CAPEX ≈ **E3×A3** (per-lamp × quantity); annual inflows = "
        "**electricity savings × savings % × client fee-split %**. Civil trench (**E2**, CNY/km) "
        "is shown in the cost stack but not rolled into CAPEX without route length. Replace with "
        "CSV/project CAPEX pack when available."
    )

    # Sidebar sensitivities (defaults from survey where parseable)
    c4_default = parse_tariff_kw(answers.get("C4")) or 0.82
    h_years, _ = parse_horizon_years(answers.get("H10"))
    horizon_default = float(h_years or 8.0)

    with st.sidebar:
        st.header("Sensitivity (not re-surveyed)")
        eff_tariff = st.number_input(
            "Effective tariff λ (CNY/kWh)",
            min_value=0.0,
            max_value=5.0,
            value=float(c4_default),
            step=0.01,
            help="Used for implied kWh scenario table.",
        )
        horizon = st.slider(
            "Analysis horizon (years)",
            min_value=1.0,
            max_value=20.0,
            value=min(horizon_default, 20.0),
            step=0.5,
            help="IRR / cumulative net use this horizon.",
        )
        fee_split = st.slider(
            "Client share of verified savings (%)",
            min_value=0,
            max_value=100,
            value=50,
            help="Illustrative split of annual electricity savings accruing to the client.",
        )
        savings_pct = st.slider(
            "Assumed energy savings vs baseline bill (%)",
            min_value=0,
            max_value=60,
            value=25,
        )

    ec = build_economics(
        answers,
        horizon_years=horizon,
        fee_split_client_pct=fee_split,
        savings_pct=savings_pct,
    )
    cur = ec.currency

    if warnings:
        st.subheader("Validation / reconcile")
        for w in warnings:
            st.warning(w)

    # --- KPI strip (MVED) ---
    st.subheader("KPI strip")
    k1, k2, k3, k4, k5, k6 = st.columns(6)
    k1.metric(
        "Client CAPEX proxy",
        _fmt_money(ec.client_investment, cur),
        help="E3 × A3 (+ illustrative civil rates only when modeled)",
    )
    k2.metric(
        "Annual client cash-in",
        _fmt_money(ec.annual_client_cash_in, cur),
        help="Share of annual electricity savings",
    )
    pb = ec.simple_payback_years
    k3.metric(
        "Simple payback",
        f"{pb:.1f} yr" if pb is not None and pb < 500 else ("—" if pb is None else f"{pb:.0f} yr"),
        help="CAPEX ÷ annual client cash-in",
    )
    k4.metric(
        f"Cumulative net ({ec.horizon_years} yr)",
        _fmt_money(ec.cumulative_net, cur),
        help="Sum of annual net cashflows including year-0 CAPEX",
    )
    irr = ec.annual_irr
    irr_disp = f"{irr * 100:.1f} %" if irr is not None else "—"
    k5.metric("Annual IRR (equal inflows)", irr_disp, help="numpy_financial.irr on yearly series")
    k6.metric(
        "Annual electricity savings",
        _fmt_money(ec.annual_elec_savings, cur),
        help="B2 × savings %",
    )

    # --- Cumulative cashflow chart + table ---
    st.subheader("累计现金流与回收期")
    xs = [r["year_index"] for r in ec.rows]
    ys = [r["cumulative_net"] for r in ec.rows]
    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=xs,
            y=ys,
            mode="lines+markers",
            name="Cumulative net",
            line=dict(width=2),
        )
    )
    fig.add_hline(y=0, line_dash="dash", line_color="gray")
    if ec.simple_payback_years is not None and ec.simple_payback_years == ec.simple_payback_years:
        if ec.simple_payback_years <= ec.horizon_years:
            fig.add_vline(
                x=ec.simple_payback_years,
                line_dash="dot",
                line_color="orange",
                annotation_text="Simple payback",
                annotation_position="top",
            )
    fig.update_layout(
        xaxis_title="Year index (0 = CAPEX)",
        yaxis_title=f"Cumulative net ({cur})",
        hovermode="x unified",
        height=420,
    )
    st.plotly_chart(fig, use_container_width=True)

    with st.expander("Cashflow detail", expanded=False):
        st.dataframe(
            [
                {
                    "year": r["year_index"],
                    "net_cashflow": r["net_cashflow"],
                    "cumulative_net": r["cumulative_net"],
                }
                for r in ec.rows
            ],
            column_config={
                "net_cashflow": st.column_config.NumberColumn(format="%.0f"),
                "cumulative_net": st.column_config.NumberColumn(format="%.0f"),
            },
            use_container_width=True,
            hide_index=True,
        )

    # --- Cost stack CAPEX vs OPEX ---
    st.subheader("Cost stack — CAPEX vs annual operating lines")
    parts = baseline_annual_spend_parts(answers)
    capex_row = {"category": "One-time CAPEX (proxy)", "amount": ec.client_investment, "notes": "E3 × A3"}
    e2 = answers.get("E2")
    civil_note = f"E2 unit rate (CNY/km): {e2}; add km × rate when known."
    st.caption(civil_note)

    stack_tbl = [
        capex_row,
        {
            "category": "Annual electricity (baseline B2)",
            "amount": parts["annual_electricity"],
            "notes": "Survey annual bill proxy",
        },
        {
            "category": "Annual O&M / repairs (B3)",
            "amount": parts["annual_om_style"],
            "notes": "Baseline",
        },
        {
            "category": "Annual outsourced O&M contract (D2)",
            "amount": parts["annual_outsourced_om"],
            "notes": "Baseline",
        },
    ]
    st.dataframe(stack_tbl, use_container_width=True, hide_index=True)

    vols = []
    labels = []
    for row in stack_tbl[1:]:
        if row["amount"] is not None and row["amount"] > 0:
            vols.append(row["amount"])
            labels.append(row["category"])
    if vols:
        fig2 = go.Figure(
            data=[
                go.Pie(
                    labels=labels,
                    values=vols,
                    hole=0.35,
                    textinfo="label+percent",
                )
            ]
        )
        fig2.update_layout(title="Share of annual operating baseline (ex-CAPEX)", height=380)
        st.plotly_chart(fig2, use_container_width=True)

    # --- Scenario comparison table ---
    st.subheader("Electricity scenario comparison")
    bl_kwh = (
        (ec.annual_electricity_baseline / eff_tariff)
        if eff_tariff > 0
        else None
    )
    af_kwh = (
        (ec.annual_electricity_after / eff_tariff)
        if eff_tariff > 0
        else None
    )
    scen = [
        {
            "Line": "Annual electricity cost",
            "Baseline": _fmt_money(ec.annual_electricity_baseline, cur),
            "After retrofit (scenario)": _fmt_money(ec.annual_electricity_after, cur),
        },
        {
            "Line": "Implied kWh (if λ applied)",
            "Baseline": f"{bl_kwh:,.0f} kWh" if bl_kwh else "—",
            "After retrofit (scenario)": f"{af_kwh:,.0f} kWh" if af_kwh else "—",
        },
    ]
    st.dataframe(scen, use_container_width=True, hide_index=True)

    st.subheader("Dashboard routing")
    st.info(
        f"**Pattern:** `{route.story.value}` — EMC incumbent: **{route.emc_incumbent}**, "
        f"LaaS emphasis: **{route.laas_emphasis}**"
    )

    if route.story in (RouteStory.EMC_INCUMBENT, RouteStory.EMC_AND_LAAS):
        with st.expander("Existing arrangement (J1–J6 disclosure)", expanded=True):
            _facts_table(grouped.get("J", {}))

    if route.story in (RouteStory.LAAS_STYLE, RouteStory.EMC_AND_LAAS):
        with st.expander("Ownership / term appetite (H/I — LaaS-style framing)", expanded=False):
            cols = st.columns(3)
            with cols[0]:
                st.markdown("**H7**")
                st.write(answers.get("H7"))
            with cols[1]:
                st.markdown("**H10**")
                st.write(answers.get("H10"))
            with cols[2]:
                st.markdown("**I2 / I5**")
                st.write(answers.get("I2"))
                st.write(answers.get("I5"))
            st.caption(
                "Full feasible-envelope / provider-customer IRR splits live in NEW_BUS_MOD_DB "
                "reference pages when available; KPI IRR above is from the simplified annual series only."
            )

    with st.expander("Submitted baseline (fixed facts)", expanded=False):
        layer_labels = {
            "INT": "Metadata (INT*)",
            "A": "Scope & inventory (A*)",
            "B": "Money baseline (B*)",
            "C": "Energy & tariffs (C*)",
            "D": "O&M (D*)",
            "E": "Civil / CAPEX priors (E*)",
            "J": "Incumbent EMC (J*) — also summarized above when routed",
            "G": "Payer / budget (G*)",
            "H": "Term / registration (H*)",
            "I": "Ownership / usership (I*)",
            "K": "Other structure (K*)",
            "Other": "Other",
        }
        skip_layers: set[str] = set()
        if route.story in (RouteStory.EMC_INCUMBENT, RouteStory.EMC_AND_LAAS):
            skip_layers.add("J")

        for layer in ("INT", "A", "B", "C", "D", "E", "J", "G", "H", "I", "K", "Other"):
            if layer in skip_layers:
                continue
            block = grouped.get(layer, {})
            if not block:
                continue
            with st.expander(layer_labels.get(layer, layer), expanded=(layer in ("INT", "B", "C"))):
                _facts_table(block)

    with st.expander("Raw answers JSON"):
        st.code(json.dumps(answers, ensure_ascii=False, indent=2), language="json")


if __name__ == "__main__":
    main()
