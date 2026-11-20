"""
Command-line interface for common openLCA IPC operations.

    olca summary
    olca search "electricity" -t Flow
    olca methods
    olca inspect "process name" -l US
    olca duplicates
    olca carbon 0.347 --region RFCW --compare-regions
    olca variability data.csv
"""

import argparse
import logging


def _get_client(port: int = 8080):
    import olca_ipc as ipc
    return ipc.Client(port)


def cmd_summary(args):
    from .inspector import DatabaseInspector
    counts = DatabaseInspector(_get_client(args.port)).summary()
    print(f"\n{'Entity Type':<25} {'Count':>8}")
    print("-" * 35)
    for name, count in sorted(counts.items(), key=lambda x: -x[1]):
        print(f"  {name:<23} {count:>8,}")
    print()


def cmd_search(args):
    import olca_schema as o
    from .inspector import DatabaseInspector
    type_map = {"process": o.Process, "flow": o.Flow,
                "productsystem": o.ProductSystem, "method": o.ImpactMethod}
    model_type = type_map.get(args.type.lower(), o.Process)
    matches = DatabaseInspector(_get_client(args.port)).search(args.query, model_type)
    if not matches:
        print(f"No matches for '{args.query}'")
        return
    print(f"\n{len(matches)} matches for '{args.query}':\n")
    for m in matches[:args.limit]:
        loc = f" [{m.location}]" if m.location else ""
        cat = f" ({m.category})" if m.category else ""
        print(f"  {m.name}{loc}{cat}")
        if args.verbose:
            print(f"    id: {m.id}")
    if len(matches) > args.limit:
        print(f"\n  ... and {len(matches) - args.limit} more (use --limit)")
    print()


def cmd_methods(args):
    from .inspector import DatabaseInspector
    methods = DatabaseInspector(_get_client(args.port)).impact_methods()
    print(f"\n{len(methods)} impact methods available:\n")
    for m in methods:
        print(f"  {m.name}")
    print()


def cmd_inspect(args):
    from .inspector import DatabaseInspector
    try:
        info = DatabaseInspector(_get_client(args.port)).inspect_process(
            args.name, location=args.location)
    except ValueError as e:
        print(f"Error: {e}")
        return

    print(f"\nProcess: {info['name']}")
    if info["location"]:
        print(f"Location: {info['location']}")
    if info["category"]:
        print(f"Category: {info['category']}")
    if info["description"]:
        print(f"Description: {info['description'][:200]}")
    print(f"\nExchanges ({len(info['exchanges'])}):")
    for ex in info["exchanges"]:
        direction = "IN " if ex["is_input"] else "OUT"
        ref = " [REF]" if ex["is_reference"] else ""
        amount = ex["amount"] if ex["amount"] is not None else 0.0
        print(f"  {direction} {amount:>12.4f} {ex['unit'] or '':<8} {ex['flow']}{ref}")
    print()


def cmd_duplicates(args):
    import olca_schema as o
    from .inspector import DatabaseInspector
    type_map = {"process": o.Process, "flow": o.Flow}
    model_type = type_map.get(args.type.lower(), o.Process)
    dupes = DatabaseInspector(_get_client(args.port)).find_duplicates(model_type)
    if not dupes:
        print(f"No duplicate {args.type} names found.")
        return
    print(f"\n{len(dupes)} names with duplicates:\n")
    for name, refs in sorted(dupes.items())[:args.limit]:
        print(f"  {name} ({len(refs)} instances):")
        for r in refs:
            loc = f" [{r.location}]" if r.location else ""
            lib = f" (library: {r.library})" if r.library else ""
            print(f"    {r.id}{loc}{lib}")
    print()


def cmd_carbon(args):
    from .carbon import CarbonCalculator
    calc = CarbonCalculator(default_region=args.region)
    profile = calc.from_egrid("operation", args.energy_kwh, region=args.region)
    ef = profile.emission_factor
    print(f"\nEnergy:      {args.energy_kwh:.4f} kWh")
    print(f"Region:      {ef.region if ef else 'unknown'}")
    print(f"Factor:      {ef.value_kg_co2_per_kwh if ef else 0:.4f} kg CO2/kWh")
    print(f"Emissions:   {profile.emissions_kg_co2:.6f} kg CO2")
    print(f"Source:      {ef.source if ef else 'unknown'}")

    if args.compare_regions:
        print(f"\nAll eGRID regions for {args.energy_kwh:.4f} kWh:")
        df = calc.compare_regions(args.energy_kwh)
        print(f"\n{'Region':<8} {'Factor':>10} {'Emissions':>12} {'vs Min':>10}")
        print("-" * 42)
        for _, row in df.iterrows():
            print(f"  {row['region']:<6} {row['factor_kg_co2_kwh']:>10.4f} "
                  f"{row['emissions_kg_co2']:>12.6f} {row.get('relative_pct', 0):>+9.1f}%")
    print()


def cmd_variability(args):
    import pandas as pd
    from .compare import ComparisonEngine

    df = pd.read_csv(args.csv_file)
    if args.name_col not in df.columns or args.energy_col not in df.columns:
        print(f"Error: CSV needs columns '{args.name_col}' and '{args.energy_col}'")
        print(f"Found: {list(df.columns)}")
        return

    measurements = {name: group[args.energy_col].tolist()
                    for name, group in df.groupby(args.name_col)}
    report = ComparisonEngine().variability_report(measurements)

    print(f"\nVariability ({len(measurements)} operations, {len(df)} measurements):\n")
    print(f"{'Operation':<30} {'N':>4} {'Mean kWh':>10} {'Std':>10} {'CV%':>8} {'Range':>10}")
    print("-" * 74)
    for _, row in report.iterrows():
        print(f"  {row['operation']:<28} {row['n']:>4} {row['mean_kwh']:>10.4f} "
              f"{row['std_kwh']:>10.4f} {row['cv_pct']:>7.1f}% {row['range_kwh']:>10.4f}")
    print()


def main():
    parser = argparse.ArgumentParser(prog="olca",
                                     description="openLCA IPC utility commands")
    parser.add_argument("--port", type=int, default=8080,
                        help="IPC server port (default: 8080)")
    parser.add_argument("-v", "--verbose", action="store_true")
    subs = parser.add_subparsers(dest="command")

    subs.add_parser("summary", help="Database entity counts")

    p = subs.add_parser("search", help="Search entities by name")
    p.add_argument("query")
    p.add_argument("-t", "--type", default="Process")
    p.add_argument("--limit", type=int, default=20)

    subs.add_parser("methods", help="List impact assessment methods")

    p = subs.add_parser("inspect", help="Inspect a process")
    p.add_argument("name")
    p.add_argument("-l", "--location")

    p = subs.add_parser("duplicates", help="Find duplicate entity names")
    p.add_argument("-t", "--type", default="Process")
    p.add_argument("--limit", type=int, default=50)

    p = subs.add_parser("carbon", help="Calculate grid carbon emissions")
    p.add_argument("energy_kwh", type=float)
    p.add_argument("--region", default="RFCW")
    p.add_argument("--compare-regions", action="store_true")

    p = subs.add_parser("variability", help="Energy variability from CSV")
    p.add_argument("csv_file")
    p.add_argument("--name-col", default="operation_name")
    p.add_argument("--energy-col", default="energy_kwh")

    args = parser.parse_args()
    if args.verbose:
        logging.basicConfig(level=logging.DEBUG)

    commands = {
        "summary": cmd_summary, "search": cmd_search, "methods": cmd_methods,
        "inspect": cmd_inspect, "duplicates": cmd_duplicates,
        "carbon": cmd_carbon, "variability": cmd_variability,
    }
    if args.command is None:
        parser.print_help()
        return
    commands[args.command](args)


if __name__ == "__main__":
    main()
