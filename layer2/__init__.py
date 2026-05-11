"""Layer 2 — Assumption store.

Public API for the rest of the pipeline:

    from layer2 import load_products, load_savings, load_financial, config_versions
    from layer2 import ProductConfig, SavingsMechanism, RangedParam

Call the loaders once; results are cached in-process.
"""

from layer2.loader import (
    clear_cache,
    config_versions,
    load_financial,
    load_products,
    load_savings,
)
from layer2.models import (
    Confidence,
    Driver,
    FinancialConfig,
    GridDependency,
    ProductConfig,
    ProductsConfig,
    RangedParam,
    SavingsConfig,
    SavingsMechanism,
)

__all__ = [
    # loaders
    "load_products",
    "load_savings",
    "load_financial",
    "config_versions",
    "clear_cache",
    # model types
    "ProductConfig",
    "ProductsConfig",
    "SavingsMechanism",
    "SavingsConfig",
    "RangedParam",
    "FinancialConfig",
    # literal aliases
    "Confidence",
    "Driver",
    "GridDependency",
]
