"""
olca-contrib: community extensions for the openLCA Python IPC client.

Modules:
    patches       - name lookups that handle duplicates; unit lookup (#4)
    batch         - batch calculations with guaranteed disposal
    monte_carlo   - Monte Carlo without the server memory leak (#41)
    builders      - fluent ProcessBuilder that creates its new flows
    extractors    - results as DataFrames
    energy_bridge - measured manufacturing energy -> openLCA processes
    carbon        - grid emission factors (eGRID averages, WattTime MOER)
    inspector     - database inspection and diagnostics
    compare       - measured vs. database-default energy
    cli           - command line interface
"""

from olca_contrib.patches import find_by, find_all_by, get_by_name, UnitCache
from olca_contrib.batch import calculate_batch, BatchResult, BatchResults
from olca_contrib.monte_carlo import simulate_safe, MonteCarloResults
from olca_contrib.builders import ProcessBuilder
from olca_contrib.extractors import ResultExtractor
from olca_contrib.energy_bridge import (
    EnergyBridge,
    Operation,
    ManufacturingSystem,
    BridgeResults,
)
from olca_contrib.carbon import CarbonCalculator, EGRID_FACTORS
from olca_contrib.compare import ComparisonEngine
from olca_contrib.inspector import DatabaseInspector

__version__ = "0.4.0"

__all__ = [
    "find_by",
    "find_all_by",
    "get_by_name",
    "UnitCache",
    "calculate_batch",
    "BatchResult",
    "BatchResults",
    "simulate_safe",
    "MonteCarloResults",
    "ProcessBuilder",
    "ResultExtractor",
    "EnergyBridge",
    "Operation",
    "ManufacturingSystem",
    "BridgeResults",
    "CarbonCalculator",
    "EGRID_FACTORS",
    "ComparisonEngine",
    "DatabaseInspector",
]
