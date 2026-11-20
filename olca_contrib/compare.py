"""
Measured vs. database-default comparison framework.

Compares what a background database's default energy values predict
against what operation-level monitoring actually measures, and reports
how much of total impact each side accounts for.
"""

import logging
from dataclasses import dataclass, field

log = logging.getLogger(__name__)


@dataclass
class ComparisonResult:
    """Measured vs. default comparison for one operation."""
    name: str
    category: str = ""
    measured_value: float = 0.0
    default_value: float = 0.0
    unit: str = ""

    @property
    def absolute_difference(self) -> float:
        return self.measured_value - self.default_value

    @property
    def relative_difference_pct(self) -> float:
        if self.default_value == 0:
            return float("inf") if self.measured_value != 0 else 0.0
        return (self.measured_value - self.default_value) / abs(self.default_value) * 100

    @property
    def ratio(self) -> float:
        if self.default_value == 0:
            return float("inf") if self.measured_value != 0 else 1.0
        return self.measured_value / self.default_value


@dataclass
class SystemComparison:
    system_name: str
    operation_comparisons: list[ComparisonResult] = field(default_factory=list)
    energy_measured_total: float = 0.0
    energy_default_total: float = 0.0
    material_total_gwp: float = 0.0
    energy_measured_gwp: float = 0.0
    energy_default_gwp: float = 0.0

    @property
    def measured_energy_share_pct(self) -> float:
        total = self.material_total_gwp + self.energy_measured_gwp
        return self.energy_measured_gwp / total * 100 if total else 0.0

    @property
    def default_energy_share_pct(self) -> float:
        total = self.material_total_gwp + self.energy_default_gwp
        return self.energy_default_gwp / total * 100 if total else 0.0

    def to_dataframe(self):
        import pandas as pd
        return pd.DataFrame([{
            "operation": c.name,
            "measured": c.measured_value,
            "default": c.default_value,
            "unit": c.unit,
            "diff_abs": round(c.absolute_difference, 6),
            "diff_pct": round(c.relative_difference_pct, 1),
            "ratio": round(c.ratio, 3),
        } for c in self.operation_comparisons])

    def summary(self) -> str:
        ratio = self.energy_measured_total / max(self.energy_default_total, 1e-9)
        lines = [
            f"System: {self.system_name}",
            f"Operations compared: {len(self.operation_comparisons)}",
            "",
            "Energy totals:",
            f"  Measured:  {self.energy_measured_total:.4f} kWh",
            f"  Default:   {self.energy_default_total:.4f} kWh",
            f"  Ratio:     {ratio:.2f}x",
            "",
        ]
        if self.material_total_gwp > 0:
            lines.extend([
                "GWP attribution:",
                f"  Material:        {self.material_total_gwp:.4f} kg CO2-eq "
                f"({100 - self.measured_energy_share_pct:.1f}%)",
                f"  Energy (meas.):  {self.energy_measured_gwp:.4f} kg CO2-eq "
                f"({self.measured_energy_share_pct:.1f}%)",
                f"  Energy (deflt.): {self.energy_default_gwp:.4f} kg CO2-eq "
                f"({self.default_energy_share_pct:.1f}%)",
            ])
        return "\n".join(lines)


class ComparisonEngine:
    """Compare measured manufacturing energy against database defaults.

    Usage:
        engine = ComparisonEngine()
        engine.add_measured_batch({"face": 0.347, "drill": 0.156})
        engine.add_default_batch({"face": 0.500, "drill": 0.250})
        engine.set_material_gwp(12.5)
        print(engine.compare("Pump Housing").summary())
    """

    def __init__(self):
        self._measured: dict[str, float] = {}
        self._defaults: dict[str, float] = {}
        self._material_gwp: float = 0.0
        self._emission_factor: float = 0.489

    def add_measured(self, operation: str, energy_kwh: float):
        self._measured[operation] = energy_kwh

    def add_default(self, operation: str, energy_kwh: float):
        self._defaults[operation] = energy_kwh

    def add_measured_batch(self, data: dict[str, float]):
        self._measured.update(data)

    def add_default_batch(self, data: dict[str, float]):
        self._defaults.update(data)

    def set_material_gwp(self, total_kg_co2: float):
        """Set total material GWP from an LCA calculation, for context."""
        self._material_gwp = total_kg_co2

    def set_emission_factor(self, kg_co2_per_kwh: float):
        """Set the grid emission factor used to convert energy to GWP."""
        self._emission_factor = kg_co2_per_kwh

    def from_dataframe(self, df, *, name_col: str = "operation",
                       measured_col: str = "measured_kwh",
                       default_col: str = "default_kwh"):
        for _, row in df.iterrows():
            name = str(row[name_col])
            if measured_col in df.columns:
                self._measured[name] = float(row[measured_col])
            if default_col in df.columns:
                self._defaults[name] = float(row[default_col])

    def compare(self, system_name: str = "Manufacturing System") -> SystemComparison:
        all_ops = set(self._measured) | set(self._defaults)
        comparisons = [
            ComparisonResult(
                name=op, category="energy",
                measured_value=self._measured.get(op, 0.0),
                default_value=self._defaults.get(op, 0.0),
                unit="kWh",
            )
            for op in sorted(all_ops)
        ]
        meas_total = sum(self._measured.values())
        dflt_total = sum(self._defaults.values())

        return SystemComparison(
            system_name=system_name,
            operation_comparisons=comparisons,
            energy_measured_total=meas_total,
            energy_default_total=dflt_total,
            material_total_gwp=self._material_gwp,
            energy_measured_gwp=meas_total * self._emission_factor,
            energy_default_gwp=dflt_total * self._emission_factor,
        )

    def variability_report(self, measurements: dict[str, list[float]]):
        """Run-to-run variability across repeated measurements per operation."""
        import pandas as pd
        import numpy as np

        rows = []
        for op, values in measurements.items():
            arr = np.array(values, dtype=float)
            mean = arr.mean()
            std = arr.std(ddof=1) if len(arr) > 1 else 0.0
            rows.append({
                "operation": op,
                "n": len(arr),
                "mean_kwh": round(mean, 6),
                "std_kwh": round(std, 6),
                "cv_pct": round(std / mean * 100, 1) if mean > 0 else 0.0,
                "min_kwh": round(arr.min(), 6),
                "max_kwh": round(arr.max(), 6),
                "range_kwh": round(arr.max() - arr.min(), 6),
            })
        return pd.DataFrame(rows)
