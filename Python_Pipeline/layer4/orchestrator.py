"""Single entry point for Layer 4 — runs all scenarios in one call.

Typical usage:
    from layer4 import run_scenarios
    results = run_scenarios(deal, product, params, savings_cfg, financial_cfg, cv)

    results.point_estimate   # ModelOutputs from layer3
    results.tornado          # TornadoResult — feeds tornado chart
    results.montecarlo       # MonteCarloResult — feeds P10/P50/P90 histogram
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from layer2.loader import config_versions as _default_config_versions
from layer3.engine import run_model
from layer4.models import ScenarioResults
from layer4.montecarlo import run_montecarlo
from layer4.sensitivity import build_specs, run_tornado

if TYPE_CHECKING:
    from layer2.models import FinancialConfig, SavingsConfig
    from layer3.models import DealInputs, ScenarioParams


def run_scenarios(
    deal: "DealInputs",
    product,
    params: "ScenarioParams",
    savings_cfg: "SavingsConfig",
    financial_cfg: "FinancialConfig",
    config_versions: Optional[dict] = None,
    n_simulations: int = 1000,
    mc_seed: Optional[int] = None,
) -> ScenarioResults:
    """Run point estimate + tornado + Monte Carlo and return everything.

    Args:
        deal:           Fixed deal inputs (Layer 1).
        product:        Chosen product config (Layer 2).
        params:         Current slider values including service fee (Layer 3).
        savings_cfg:    Loaded SavingsConfig — provides slider bounds for specs.
        financial_cfg:  Loaded FinancialConfig — provides financial param bounds.
        config_versions: Layer 2 version stamp for audit trail.
        n_simulations:  Monte Carlo draws. 1000 for interactive; 5000 for final report.
        mc_seed:        Random seed — set for reproducible notebook runs.
    """
    cv = config_versions or _default_config_versions()

    # 1. Point estimate — the base run the team is looking at
    point = run_model(deal, product, params, cv)

    # 2. Build sensitivity specs from Layer 2 YAML bounds
    specs = build_specs(params, savings_cfg, financial_cfg)

    # 3. Tornado — one-at-a-time sensitivity
    tornado = run_tornado(deal, product, params, specs, cv)

    # 4. Monte Carlo — distribution over uncertain assumptions
    mc = run_montecarlo(
        deal, product, params, specs,
        n_simulations=n_simulations,
        seed=mc_seed,
    )

    return ScenarioResults(
        point_estimate=point,
        tornado=tornado,
        montecarlo=mc,
        deal_id=deal.deal_id,
        product_key=params.product_key,
        config_versions=cv,
    )
