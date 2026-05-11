"""Layer 3 — Model engine.

Public API:

    from layer3 import run_model, DealInputs, ScenarioParams, ModelOutputs
    from layer3 import from_answers   # Layer 1 → DealInputs bridge

Typical call sequence:

    from layer2 import load_products, load_savings, load_financial, config_versions
    from layer3 import from_answers, run_model, ScenarioParams

    deal    = from_answers(answers_dict)           # Layer 1 output
    product = load_products().get("ai_road_lamp")  # Layer 2 product selector
    params  = ScenarioParams.from_defaults(        # Layer 2 defaults → slider seed
                  "ai_road_lamp", product, load_financial(), deal
              )
    result  = run_model(deal, product, params, config_versions())
"""

from layer3.deal_loader import from_answers
from layer3.engine import run_model
from layer3.models import (
    BaselineCosts,
    CapexBreakdown,
    DealInputs,
    ModelOutputs,
    SavingsAttribution,
    ScenarioParams,
    YearlyCashflow,
)

__all__ = [
    "run_model",
    "from_answers",
    "DealInputs",
    "ScenarioParams",
    "ModelOutputs",
    "SavingsAttribution",
    "CapexBreakdown",
    "YearlyCashflow",
    "BaselineCosts",
]
