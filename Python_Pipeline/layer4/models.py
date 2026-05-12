"""Output models for Layer 4 — scenario orchestration.

Three result types:
  TornadoResult    — one-at-a-time sensitivity, sorted by NPV swing (feeds tornado chart)
  MonteCarloResult — NPV/IRR distribution over N simulations (feeds P10/P50/P90 chart)
  ScenarioResults  — all three runs bundled together (consumed by Layer 5)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class SensitivityRow:
    """One parameter's contribution to NPV swing — one bar in the tornado chart."""
    parameter: str            # ScenarioParams field name
    display_name: str         # human label from Layer 2 YAML
    confidence: str           # "high" | "medium" | "speculative"
    base_value: float         # value used in the point-estimate run
    low_value: float          # min end of the range tested
    high_value: float         # max end of the range tested
    npv_at_low: float
    npv_at_high: float
    base_npv: float

    @property
    def npv_swing(self) -> float:
        return abs(self.npv_at_high - self.npv_at_low)

    @property
    def direction(self) -> str:
        """'positive' if higher param value → higher NPV, else 'negative'."""
        return "positive" if self.npv_at_high >= self.npv_at_low else "negative"


@dataclass
class TornadoResult:
    """Full tornado: base NPV + all rows sorted by swing descending."""
    base_npv: float
    rows: List[SensitivityRow]

    @property
    def top_drivers(self) -> List[SensitivityRow]:
        """Top 5 NPV drivers — enough for a CEO chart."""
        return self.rows[:5]


@dataclass
class MonteCarloResult:
    """NPV, IRR, and payback distributions from N simulations."""
    n_simulations: int
    # NPV distribution
    npv_p10: float
    npv_p50: float
    npv_p90: float
    npv_mean: float
    npv_std: float
    prob_positive_npv: float      # fraction of sims where NPV > 0
    npv_samples: List[float]      # all samples — for histogram in UI

    # IRR distribution (None if IRR not computable in most sims)
    irr_p10: Optional[float] = None
    irr_p50: Optional[float] = None
    irr_p90: Optional[float] = None
    irr_mean: Optional[float] = None
    irr_std: Optional[float] = None
    irr_samples: List[float] = field(default_factory=list)  # % per year; nan entries if that draw had no IRR

    # Payback distribution (None if payback not computable in most sims)
    payback_p10: Optional[float] = None
    payback_p50: Optional[float] = None
    payback_p90: Optional[float] = None
    payback_mean: Optional[float] = None
    payback_std: Optional[float] = None
    prob_payback_in_contract: Optional[float] = None  # fraction where payback <= contract_yrs
    payback_samples: List[float] = field(default_factory=list)

    # Which parameters were varied (for display)
    varied_parameters: List[str] = field(default_factory=list)

    @property
    def npv_range_label(self) -> str:
        fmt = lambda v: f"{v/1e6:.1f}M" if abs(v) >= 1e6 else f"{v:,.0f}"
        return f"P10 {fmt(self.npv_p10)} / P50 {fmt(self.npv_p50)} / P90 {fmt(self.npv_p90)}"

    @property
    def payback_range_label(self) -> str:
        if self.payback_p10 is None:
            return "N/A (insufficient data)"
        return f"P10 {self.payback_p10:.1f}yr / P50 {self.payback_p50:.1f}yr / P90 {self.payback_p90:.1f}yr"

    @property
    def irr_range_label(self) -> str:
        if self.irr_p10 is None:
            return "N/A (insufficient data)"
        return f"P10 {self.irr_p10:.1f}% / P50 {self.irr_p50:.1f}% / P90 {self.irr_p90:.1f}%"


@dataclass
class ScenarioResults:
    """Everything Layer 5 needs — one object, one call."""
    point_estimate: object        # ModelOutputs from layer3
    tornado: TornadoResult
    montecarlo: MonteCarloResult
    deal_id: str
    product_key: str
    config_versions: Dict[str, str]
