"""Chongqing sales-rep questionnaire — client dashboard shell (skill-aligned).

Run locally (macOS often has no ``pip`` / ``streamlit`` on PATH — use ``python3 -m``)::

    python3 -m pip install -r requirements.txt
    python3 -m streamlit run streamlit_app.py

If ``pip`` / ``streamlit`` work as commands on your machine, those forms are equivalent.

Survey JSON is produced with::

    python3 read_questionnaire_input.py \\
      --input questionnaire_01_filled_chongqing_sales_rep.xlsx \\
      --sheet both --answers-only --compact > data/chongqing_answers.json

Fixed facts load from ``data/chongqing_answers.json``; sidebar knobs are sensitivity-only.
"""

from __future__ import annotations

import json
from pathlib import Path

import streamlit as st

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


@st.cache_data
def _cached_answers():
    return load_answers(REPO_ROOT)


def main() -> None:
    st.set_page_config(
        page_title="Chongqing — client baseline",
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

    st.title("Chongqing — submitted baseline & sensitivities")
    st.caption(route.summary)

    if warnings:
        st.subheader("Validation / reconcile")
        for w in warnings:
            st.warning(w)

    # Sidebar sensitivities (defaults from survey where parseable)
    c4_default = parse_tariff_kw(answers.get("C4")) or 0.82
    h_years, _ = parse_horizon_years(answers.get("H10"))
    horizon_default = float(h_years or 7.0)

    with st.sidebar:
        st.header("Sensitivity (not re-surveyed)")
        eff_tariff = st.number_input(
            "Effective tariff λ (CNY/kWh)",
            min_value=0.0,
            max_value=5.0,
            value=float(c4_default),
            step=0.01,
            help="Initialized from C4 where possible; adjust for scenario stress-testing.",
        )
        horizon = st.slider(
            "Analysis horizon (years)",
            min_value=1.0,
            max_value=20.0,
            value=min(horizon_default, 20.0),
            step=0.5,
            help="If H10 suggests a term band, default is a mid-point guess — verify with client.",
        )
        fee_split = st.slider(
            "Fee split — client share (%)",
            min_value=0,
            max_value=100,
            value=50,
            help="Illustrative only; not contractual.",
        )
        savings_pct = st.slider(
            "Assumed energy savings (%)",
            min_value=0,
            max_value=60,
            value=25,
        )

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
                "No IRR or envelope math is computed here — structure-only, per skill guidance."
            )

    with st.expander("Submitted baseline (fixed facts)", expanded=True):
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

    st.subheader("Sensitivity snapshot")
    st.json(
        {
            "effective_tariff_cny_per_kwh": eff_tariff,
            "horizon_years": horizon,
            "fee_split_client_pct": fee_split,
            "assumed_savings_pct": savings_pct,
        }
    )

    with st.expander("Raw answers JSON"):
        st.code(
            json.dumps(answers, ensure_ascii=False, indent=2),
            language="json",
        )


if __name__ == "__main__":
    main()
