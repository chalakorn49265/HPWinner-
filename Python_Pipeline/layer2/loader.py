"""YAML loaders for the three assumption configs.

Each function is cached with functools.cache so repeated calls within a process
pay only one disk read + one Pydantic validation. In Streamlit, wrap the call with
@st.cache_resource (not @st.cache_data) at the UI layer so the cache survives re-runs.

To reload during development without restarting the process, call clear_cache().
"""

from __future__ import annotations

import functools
from pathlib import Path

import yaml

from layer2.models import FinancialConfig, ProductsConfig, SavingsConfig

_ASSUMPTIONS_DIR = Path(__file__).resolve().parent.parent / "assumptions"


def _load_yaml(filename: str) -> dict:
    path = _ASSUMPTIONS_DIR / filename
    if not path.is_file():
        raise FileNotFoundError(
            f"Assumption file not found: {path}\n"
            f"Expected directory: {_ASSUMPTIONS_DIR}"
        )
    return yaml.safe_load(path.read_text(encoding="utf-8"))


@functools.cache
def load_products() -> ProductsConfig:
    """Load and validate assumptions/products.yaml."""
    return ProductsConfig.model_validate(_load_yaml("products.yaml"))


@functools.cache
def load_savings() -> SavingsConfig:
    """Load and validate assumptions/savings.yaml."""
    return SavingsConfig.model_validate(_load_yaml("savings.yaml"))


@functools.cache
def load_financial() -> FinancialConfig:
    """Load and validate assumptions/financial.yaml."""
    return FinancialConfig.model_validate(_load_yaml("financial.yaml"))


def clear_cache() -> None:
    """Invalidate all cached configs — use in development or after YAML edits."""
    load_products.cache_clear()
    load_savings.cache_clear()
    load_financial.cache_clear()


def config_versions() -> dict[str, str]:
    """Return the config_version string from each loaded YAML — use for audit stamping."""
    return {
        "products": load_products().config_version,
        "savings": load_savings().config_version,
        "financial": load_financial().config_version,
    }
