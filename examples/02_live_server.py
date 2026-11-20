"""
Example 2: Live openLCA server workflow.

Requires a running openLCA IPC server on port 8080 with a background
database loaded (ecoinvent, USLCI, or similar).

To start the server in openLCA desktop:
    Tools > Developer tools > IPC Server > set port 8080 > Start

Run:
    python examples/02_live_server.py
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

DATA = pathlib.Path(__file__).resolve().parents[1] / "data"


def section(title: str):
    print(f"\n{'=' * 68}\n{title}\n{'=' * 68}")


def main():
    import olca_ipc as ipc
    import olca_schema as o

    from olca_contrib import (
        DatabaseInspector, EnergyBridge, ResultExtractor,
        calculate_batch, find_by,
    )

    try:
        client = ipc.Client(8080)
        inspector = DatabaseInspector(client)
        counts = inspector.summary()
    except Exception as e:
        print(f"Could not reach the IPC server on port 8080: {e}")
        print("Start it in openLCA: Tools > Developer tools > IPC Server")
        return

    # ------------------------------------------------------------------
    section("1. What is in this database?")
    # ------------------------------------------------------------------
    for name, count in sorted(counts.items(), key=lambda x: -x[1]):
        if count > 0:
            print(f"  {name:<22} {count:>8,}")

    # ------------------------------------------------------------------
    section("2. Available impact methods")
    # ------------------------------------------------------------------
    methods = inspector.impact_methods()
    for m in methods[:10]:
        print(f"  {m.name}")
    if len(methods) > 10:
        print(f"  ... and {len(methods) - 10} more")

    if not methods:
        print("  No impact methods found. Load an LCIA method pack first.")
        return

    # ------------------------------------------------------------------
    section("3. Duplicate names (the Issue #5 problem, made visible)")
    # ------------------------------------------------------------------
    dupes = inspector.find_duplicates(o.Process)
    print(f"\n{len(dupes)} process names appear more than once.")
    for name, refs in list(dupes.items())[:3]:
        print(f"\n  '{name}' has {len(refs)} instances:")
        for r in refs[:5]:
            print(f"    [{r.location or 'no location'}] {r.id}")

    if dupes:
        name, refs = next(iter(dupes.items()))
        loc = refs[0].location
        if loc:
            resolved = find_by(client, o.Process, name, location=loc)
            print(f"\n  find_by(..., location='{loc}') resolves to: {resolved.id}")

    # ------------------------------------------------------------------
    section("4. Electricity flows available for the energy bridge")
    # ------------------------------------------------------------------
    elec = inspector.electricity_flows()
    print(f"\n{len(elec)} electricity flows found. First 10:")
    for f in elec[:10]:
        print(f"  {f.name} [{f.location or '-'}]")

    # ------------------------------------------------------------------
    section("5. Register measured operations and build a system")
    # ------------------------------------------------------------------
    # In ecoinvent the grid region is on the provider, e.g. US-RFC.
    bridge = EnergyBridge(client, provider_location="US-RFC")
    bridge.register_from_csv(str(DATA / "operations_single_run.csv"))
    print()
    print(bridge.operation_summary().to_string(index=False))

    system = bridge.build_system("Sample Part - Machining Phase")
    print(f"\nSystem total: {system.total_energy_kwh:.3f} kWh "
          f"across {len(system.operations)} operations")

    # Writing processes into the database is destructive, so it is opt-in.
    if "--insert" in sys.argv:
        refs = bridge.insert_system(system)
        print(f"Inserted {len(refs)} operation processes into the database.")
    else:
        print("(pass --insert to write these operations into the database)")

    # ------------------------------------------------------------------
    section("6. Calculate an existing product system")
    # ------------------------------------------------------------------
    systems = client.get_descriptors(o.ProductSystem)
    if not systems:
        print("\nNo product systems in this database, so nothing to calculate.")
        print("Build one in openLCA, or run with --insert and link the")
        print("operation processes into a system first.")
        return

    target = systems[0]
    method = methods[0]
    print(f"\nTarget: {target.name}")
    print(f"Method: {method.name}")

    setup = o.CalculationSetup(
        target=o.Ref(ref_type=o.RefType.ProductSystem, id=target.id),
        impact_method=o.Ref(id=method.id),
    )

    with ResultExtractor.from_setup(client, setup) as ext:
        impacts = ext.impacts_df()
        print(f"\n{len(impacts)} impact categories:")
        for _, r in impacts.head(8).iterrows():
            print(f"  {r['category']:<42} {r['value']:>14.6g} {r['ref_unit'] or ''}")

        first = impacts.iloc[0]["category"]
        print(f"\nTop contributors to {first}:")
        for _, r in ext.top_contributors(first, n=5).iterrows():
            loc = f" [{r['location']}]" if r["location"] else ""
            print(f"  {r['contribution_pct']:>6.1f}%  {r['process']}{loc}")

    # ------------------------------------------------------------------
    section("7. Batch calculation across product systems")
    # ------------------------------------------------------------------
    targets = systems[:5]
    setups = [
        o.CalculationSetup(
            target=o.Ref(ref_type=o.RefType.ProductSystem, id=t.id),
            impact_method=o.Ref(id=method.id),
        )
        for t in targets
    ]

    results = calculate_batch(client, setups, progress=True)
    print(f"\n{results.n_succeeded} succeeded, {results.n_failed} failed "
          f"in {results.total_elapsed_seconds:.1f}s")

    df = results.to_impacts_dataframe()
    if not df.empty:
        df.index = [t.name[:38] for t in targets[:len(df)]]
        print()
        print(df.iloc[:, :3].to_string())

    for err in results.errors():
        print(f"  failed [{err.index}]: {err.error}")

    print()


if __name__ == "__main__":
    main()
