"""Monte Carlo simulation over uncertain savings assumptions.

Sampling rules by confidence level:
  high        → not varied. These are spec-sheet facts; randomising them misleads.
  medium      → triangular(min, mode=current_value, max).
                Assumes the current slider value is the most likely outcome,
                but acknowledges the full range from Layer 2 YAML is possible.
  speculative → uniform(min, max).
                We genuinely don't know where in the range we'll land;
                the flat distribution reflects that ignorance honestly.

The service fee is NOT varied — it's a decision variable set by the team,
not an uncertain assumption about the world.

Outputs P10/P50/P90 for NPV and IRR, plus the full sample list for a histogram.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, List, Optional

import numpy as np

from layer3.engine import run_model
from layer4.models import MonteCarloResult
from layer4.sensitivity import SensitivitySpec

if TYPE_CHECKING:
    from layer3.models import DealInputs, ScenarioParams


def run_montecarlo(
    deal: "DealInputs",
    product,
    params: "ScenarioParams",
    specs: List[SensitivitySpec],
    n_simulations: int = 1000,
    seed: Optional[int] = None,
) -> MonteCarloResult:
    """Run the engine N times, sampling uncertain parameters each time.

    Args:
        deal:         Fixed deal inputs (never varied — these are facts).
        product:      Product config (never varied — spec sheets are high-confidence).
        params:       Base scenario params; service fee held fixed throughout.
        specs:        Sensitivity specs from build_specs() — provides min/max/confidence.
        n_simulations: Number of Monte Carlo draws. 1000 is fast (~1s); use 5000 for final.
        seed:         Optional random seed for reproducibility in tests.
    """
    if seed is not None:
        np.random.seed(seed)

    # Only vary medium- and speculative-confidence parameters
    uncertain = [s for s in specs if s.confidence in ("medium", "speculative")]
    # Never vary the service fee — it's a team decision, not a random variable
    uncertain = [s for s in uncertain if s.field != "annual_service_fee_per_light"]

    npv_samples: List[float] = []
    irr_samples: List[float] = []
    payback_samples: List[float] = []

    for _ in range(n_simulations):
        overrides = {}
        for spec in uncertain:
            current = getattr(params, spec.field)
            lo, hi = spec.low, spec.high

            if spec.confidence == "speculative":
                # Uniform — equal probability across the full range
                val = float(np.random.uniform(lo, hi))
            else:
                # Triangular — current value is the mode (most likely)
                # Clamp mode to [lo, hi] in case slider was moved outside YAML range
                mode = float(np.clip(current, lo, hi))
                val = float(np.random.triangular(lo, mode, hi))

            overrides[spec.field] = val

        p = params.model_copy(update=overrides)
        r = run_model(deal, product, p)

        npv_samples.append(r.npv)
        irr_samples.append(float(r.irr * 100.0) if r.irr is not None else float("nan"))
        if r.payback_years is not None:
            payback_samples.append(r.payback_years)

    npv_arr = np.array(npv_samples)

    irr_p10 = irr_p50 = irr_p90 = None
    irr_mean = irr_std = None
    irr_finite = np.array(irr_samples, dtype=float)
    irr_finite = irr_finite[np.isfinite(irr_finite)]
    if irr_finite.size >= n_simulations * 0.5:
        irr_p10 = float(np.percentile(irr_finite, 10))
        irr_p50 = float(np.percentile(irr_finite, 50))
        irr_p90 = float(np.percentile(irr_finite, 90))
        irr_mean = float(np.mean(irr_finite))
        irr_std = float(np.std(irr_finite))

    payback_p10 = payback_p50 = payback_p90 = None
    payback_mean = payback_std = None
    prob_payback_in_contract = None
    if len(payback_samples) >= n_simulations * 0.5:  # only report if payback computed in >50% of sims
        pb_arr = np.array(payback_samples)
        payback_p10 = float(np.percentile(pb_arr, 10))
        payback_p50 = float(np.percentile(pb_arr, 50))
        payback_p90 = float(np.percentile(pb_arr, 90))
        payback_mean = float(np.mean(pb_arr))
        payback_std = float(np.std(pb_arr))
        prob_payback_in_contract = float(np.mean(pb_arr <= params.contract_yrs))

    return MonteCarloResult(
        n_simulations=n_simulations,
        npv_p10=float(np.percentile(npv_arr, 10)),
        npv_p50=float(np.percentile(npv_arr, 50)),
        npv_p90=float(np.percentile(npv_arr, 90)),
        npv_mean=float(np.mean(npv_arr)),
        npv_std=float(np.std(npv_arr)),
        prob_positive_npv=float(np.mean(npv_arr > 0)),
        npv_samples=npv_samples,
        irr_p10=irr_p10,
        irr_p50=irr_p50,
        irr_p90=irr_p90,
        irr_mean=irr_mean,
        irr_std=irr_std,
        irr_samples=irr_samples,
        payback_p10=payback_p10,
        payback_p50=payback_p50,
        payback_p90=payback_p90,
        payback_mean=payback_mean,
        payback_std=payback_std,
        prob_payback_in_contract=prob_payback_in_contract,
        payback_samples=payback_samples,
        varied_parameters=[s.field for s in uncertain],
    )
