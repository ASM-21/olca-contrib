"""
Example 1: Offline workflow (no openLCA server required).

Demonstrates the parts of olca-contrib that work on measurement data
alone: energy registration, variability analysis, carbon accounting,
and measured-vs-default comparison.

Run:
    python examples/01_offline_workflow.py
"""

import pathlib
import sys

import pandas as pd

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from olca_contrib.carbon import CarbonCalculator
from olca_contrib.compare import ComparisonEngine

DATA = pathlib.Path(__file__).resolve().parents[1] / "data"


def section(title: str):
    print(f"\n{'=' * 68}\n{title}\n{'=' * 68}")


def main():
    # ------------------------------------------------------------------
    section("1. Run-to-run variability")
    # ------------------------------------------------------------------
    repeated = pd.read_csv(DATA / "operations_repeated.csv")
    measurements = {
        name: group["energy_kwh"].tolist()
        for name, group in repeated.groupby("operation_name")
    }

    engine = ComparisonEngine()
    report = engine.variability_report(measurements)
    report = report.sort_values("cv_pct", ascending=False)

    print(f"\n{'Operation':<22} {'N':>3} {'Mean kWh':>10} {'CV%':>7} {'Range kWh':>11}")
    print("-" * 58)
    for _, r in report.iterrows():
        print(f"  {r['operation']:<20} {r['n']:>3} {r['mean_kwh']:>10.4f} "
              f"{r['cv_pct']:>6.1f}% {r['range_kwh']:>11.4f}")

    print(f"\nCV spread: {report['cv_pct'].min():.1f}% to {report['cv_pct'].max():.1f}%")
    print("Operations with the highest CV are short, low-energy steps where")
    print("fixed overhead (spindle spin-up, tool change) dominates.")

    # ------------------------------------------------------------------
    section("2. Carbon accounting by grid region")
    # ------------------------------------------------------------------
    single = pd.read_csv(DATA / "operations_single_run.csv")
    total_kwh = single["energy_kwh"].sum()

    calc = CarbonCalculator(default_region="RFCW")
    profiles = [
        calc.from_egrid(row["operation_name"], row["energy_kwh"],
                        region=row["grid_region"])
        for _, row in single.iterrows()
    ]
    df = calc.to_dataframe(profiles).sort_values("emissions_kg_co2", ascending=False)

    print(f"\nTotal energy across {len(single)} operations: {total_kwh:.3f} kWh")
    print(f"Total emissions: {calc.total_emissions(profiles):.4f} kg CO2\n")
    print(f"{'Operation':<22} {'kWh':>8} {'kg CO2':>10}")
    print("-" * 42)
    for _, r in df.iterrows():
        print(f"  {r['operation']:<20} {r['energy_kwh']:>8.3f} "
              f"{r['emissions_kg_co2']:>10.4f}")

    # ------------------------------------------------------------------
    section("3. How much does grid location matter?")
    # ------------------------------------------------------------------
    regions = ["NYUP", "NEWE", "CAMX", "NWPP", "ERCT", "RFCW", "SRMW", "HIOA"]
    comp = calc.compare_regions(total_kwh, regions=regions)

    print(f"\nSame {total_kwh:.3f} kWh of production, different grids:\n")
    print(f"{'Region':<8} {'kg CO2/kWh':>12} {'kg CO2':>10} {'vs cleanest':>13}")
    print("-" * 46)
    for _, r in comp.iterrows():
        print(f"  {r['region']:<6} {r['factor_kg_co2_kwh']:>12.3f} "
              f"{r['emissions_kg_co2']:>10.4f} {r['relative_pct']:>+12.1f}%")

    spread = comp["emissions_kg_co2"].max() / comp["emissions_kg_co2"].min()
    print(f"\nSpread across these regions: {spread:.1f}x")
    print("Siting decisions can move Scope 2 emissions more than most")
    print("process efficiency work on the shop floor.")

    # ------------------------------------------------------------------
    section("4. Measured vs. database-default energy")
    # ------------------------------------------------------------------
    mvd = pd.read_csv(DATA / "measured_vs_default.csv")

    engine = ComparisonEngine()
    engine.from_dataframe(mvd)
    engine.set_emission_factor(calc.get_factor("RFCW"))
    # Stand-in material baseline so the shares are meaningful.
    engine.set_material_gwp(12.5)

    result = engine.compare("Sample Part")
    print()
    print(result.summary())

    diff = result.to_dataframe().sort_values("diff_pct")
    print(f"\n{'Operation':<22} {'Measured':>10} {'Default':>10} {'Diff':>9}")
    print("-" * 54)
    for _, r in diff.iterrows():
        print(f"  {r['operation']:<20} {r['measured']:>10.4f} "
              f"{r['default']:>10.4f} {r['diff_pct']:>8.1f}%")

    print("\nTakeaway: energy is a small share of total GWP for this part,")
    print("but the measured/default gap is large in relative terms. If you")
    print("are optimizing the process itself, that gap is the whole signal.")

    print()


if __name__ == "__main__":
    main()
