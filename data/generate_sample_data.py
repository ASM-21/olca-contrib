"""Generate synthetic sample data for examples and CLI demos.

Produces two CSVs in data/:
    operations_single_run.csv - one row per operation, one run each
    operations_repeated.csv   - multiple runs per operation, for variability

The numbers are synthetic and shaped to be plausible for small-part CNC
and desktop AM work. They are not measurements and should not be cited.
"""

import numpy as np
import pandas as pd

RNG = np.random.default_rng(42)

# (operation, machine, mean kWh, mean seconds, run-to-run CV)
SPECS = [
    ("CNC_Facing",        "VMX30Ui",    0.347,  45,  0.08),
    ("CNC_Roughing",      "VMX30Ui",    0.892, 210,  0.12),
    ("CNC_Drilling",      "VMX30Ui",    0.156,  28,  0.09),
    ("CNC_Boring",        "VMX30Ui",    0.203,  38,  0.11),
    ("CNC_Tapping",       "VMX30Ui",    0.098,  19,  0.15),
    ("CNC_Finishing",     "VMX30Ui",    0.421,  96,  0.07),
    ("CNC_Deburring",     "VMX30Ui",    0.067,  14,  0.22),
    ("FDM_Print_Bracket", "UltimakerS5", 1.840, 6300, 0.06),
    ("FDM_Print_Jig",     "UltimakerS5", 0.960, 3240, 0.09),
    ("PolyJet_Print_Cap", "StratasysJ55", 2.310, 5400, 0.11),
]

GRID_REGION = "MISO_INDY"


def build_single_run() -> pd.DataFrame:
    rows = []
    for i, (name, machine, kwh, secs, _cv) in enumerate(SPECS):
        rows.append({
            "operation_name": name,
            "uuid": f"op-{i:04d}-{name.lower()}",
            "energy_kwh": round(kwh, 4),
            "duration_s": secs,
            "machine": machine,
            "grid_region": GRID_REGION,
        })
    return pd.DataFrame(rows)


def build_repeated(runs_per_op: int = 12) -> pd.DataFrame:
    rows = []
    for i, (name, machine, kwh, secs, cv) in enumerate(SPECS):
        for run in range(runs_per_op):
            e = max(RNG.normal(kwh, kwh * cv), kwh * 0.4)
            d = max(RNG.normal(secs, secs * cv * 0.6), secs * 0.5)
            rows.append({
                "operation_name": name,
                "uuid": f"op-{i:04d}-run{run:02d}",
                "run": run + 1,
                "energy_kwh": round(float(e), 5),
                "duration_s": round(float(d), 1),
                "machine": machine,
                "grid_region": GRID_REGION,
            })
    return pd.DataFrame(rows)


def build_measured_vs_default() -> pd.DataFrame:
    """Measured values alongside a coarser database-default estimate."""
    rows = []
    for name, _machine, kwh, _secs, _cv in SPECS:
        # Database defaults are typically coarser and biased high for
        # small-part work, since they are aggregated over larger jobs.
        default = kwh * RNG.uniform(1.15, 1.75)
        rows.append({
            "operation": name,
            "measured_kwh": round(kwh, 4),
            "default_kwh": round(float(default), 4),
        })
    return pd.DataFrame(rows)


if __name__ == "__main__":
    import pathlib
    out = pathlib.Path(__file__).parent

    single = build_single_run()
    single.to_csv(out / "operations_single_run.csv", index=False)
    print(f"operations_single_run.csv    {len(single):>4} rows")

    repeated = build_repeated()
    repeated.to_csv(out / "operations_repeated.csv", index=False)
    print(f"operations_repeated.csv      {len(repeated):>4} rows")

    mvd = build_measured_vs_default()
    mvd.to_csv(out / "measured_vs_default.csv", index=False)
    print(f"measured_vs_default.csv      {len(mvd):>4} rows")
