"""
Measured manufacturing energy -> openLCA processes and LCIA results.

Register operations with measured energy (from a power meter, a CSV export,
or a DataFrame), insert one openLCA process per operation, and calculate
each operation's impacts with a background database.

Each process records the monitoring operation ID, machine, energy, duration,
and average power in its description, so a result traces back to the meter
data behind it.

How electricity is linked: in ecoinvent-style databases the electricity
flow (e.g. "electricity, medium voltage") has no location. The region is on
the provider, e.g. a market process at "US-RFC". So you pick the grid by
`provider_location`, not by filtering flows.
"""

import logging
import uuid
from dataclasses import dataclass, field

import olca_schema as o

from .builders import ProcessBuilder
from .patches import find_by

log = logging.getLogger(__name__)


@dataclass
class Operation:
    """One manufacturing operation with measured energy."""

    name: str
    operation_id: str
    energy_kwh: float
    duration_seconds: float = 0.0
    machine: str = ""
    grid_region: str = ""
    metadata: dict = field(default_factory=dict)

    @property
    def power_kw(self) -> float:
        if self.duration_seconds <= 0:
            return 0.0
        return self.energy_kwh / (self.duration_seconds / 3600)

    @property
    def energy_mj(self) -> float:
        return self.energy_kwh * 3.6


@dataclass
class ManufacturingSystem:
    """A set of operations that make up one part or process chain."""

    name: str
    operations: list[Operation]
    total_energy_kwh: float = 0.0

    def __post_init__(self):
        self.total_energy_kwh = sum(op.energy_kwh for op in self.operations)


@dataclass
class BridgeResults:
    """Per-operation impacts and their totals."""

    system: ManufacturingSystem
    method: str
    operation_impacts: dict[str, dict[str, float]] = field(default_factory=dict)
    process_refs: dict[str, o.Ref] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)

    @property
    def total_impacts(self) -> dict[str, float]:
        totals: dict[str, float] = {}
        for impacts in self.operation_impacts.values():
            for cat, value in impacts.items():
                totals[cat] = totals.get(cat, 0.0) + value
        return totals

    def to_dataframe(self):
        """One row per operation: energy, duration, then one column per
        impact category."""
        import pandas as pd

        rows = []
        for op in self.system.operations:
            if op.name not in self.operation_impacts:
                continue
            rows.append({
                "operation": op.name,
                "energy_kwh": op.energy_kwh,
                "duration_s": op.duration_seconds,
                **self.operation_impacts[op.name],
            })
        if not rows:
            return pd.DataFrame()
        return pd.DataFrame(rows).set_index("operation")

    def share_dataframe(self):
        """Each operation's share of the system total, per category (%)."""
        df = self.to_dataframe()
        if df.empty:
            return df
        cats = [c for c in df.columns if c not in ("energy_kwh", "duration_s")]
        shares = df[cats].copy()
        for c in cats:
            total = shares[c].sum()
            shares[c] = shares[c] / total * 100 if total else 0.0
        return shares


class EnergyBridge:
    """Bridge between manufacturing energy monitoring and openLCA.

    Example:
        bridge = EnergyBridge(client, provider_location="US-RFC")
        bridge.register_from_csv("data/operations_single_run.csv")
        system = bridge.build_system("Pump housing, machining")
        results = bridge.calculate(system, method="ReCiPe 2016 Midpoint (H)")
        print(results.to_dataframe())
    """

    def __init__(
        self,
        client,
        *,
        electricity_flow: str = "electricity, medium voltage",
        provider_location: str | None = None,
        process_location: str | None = None,
        category: str = "olca-contrib/measured operations",
    ):
        self._client = client
        self._operations: dict[str, Operation] = {}
        self.electricity_flow = electricity_flow
        self.provider_location = provider_location
        self.process_location = process_location
        self.category = category

    # --- registration ---

    def register_operation(
        self,
        name: str,
        operation_id: str | None = None,
        energy_kwh: float = 0.0,
        duration_seconds: float = 0.0,
        machine: str = "",
        grid_region: str = "",
        *,
        replace: bool = False,
        **metadata,
    ) -> Operation:
        """Register one operation. A name that is already registered raises,
        unless replace=True, so that repeated runs are not lost silently."""
        if energy_kwh < 0:
            raise ValueError(f"energy_kwh must be >= 0, got {energy_kwh}")
        if name in self._operations and not replace:
            raise ValueError(
                f"operation {name!r} is already registered; pass replace=True "
                "to overwrite it, or load repeated runs with "
                "register_from_dataframe(..., repeated='mean')")
        op = Operation(
            name=name,
            operation_id=operation_id or str(uuid.uuid4()),
            energy_kwh=energy_kwh,
            duration_seconds=duration_seconds,
            machine=machine,
            grid_region=grid_region,
            metadata=metadata,
        )
        self._operations[name] = op
        return op

    def register_from_dataframe(
        self,
        df,
        *,
        name_col: str = "operation_name",
        id_col: str = "uuid",
        energy_col: str = "energy_kwh",
        duration_col: str = "duration_s",
        machine_col: str = "machine",
        region_col: str = "grid_region",
        repeated: str = "raise",
    ):
        """Register the operations in a table; optional columns may be absent.

        repeated="raise" (default) expects one row per operation and raises
        if a name repeats. repeated="mean" treats rows with the same name as
        repeated runs and registers one operation with the mean energy and
        duration; the run count, the standard deviation of the energy, and
        the run IDs are kept in the operation's metadata.
        """
        if repeated not in ("raise", "mean"):
            raise ValueError(
                f"repeated must be 'raise' or 'mean', got {repeated!r}")
        cols = set(df.columns)
        names = df[name_col].astype(str)
        dupes = sorted(names[names.duplicated()].unique())
        if dupes and repeated == "raise":
            raise ValueError(
                f"{len(dupes)} operation names repeat, e.g. {dupes[:3]}; "
                "pass repeated='mean' to average repeated runs")
        new = [n for n in names.unique() if n in self._operations]
        if new:
            raise ValueError(f"operations already registered: {new[:3]}")

        def first(rows, col: str) -> str:
            return str(rows[col].iloc[0]) if col in cols else ""

        for name, rows in df.groupby(names, sort=False):
            energy = rows[energy_col].astype(float)
            metadata = {}
            if len(rows) > 1:
                metadata = {
                    "n_runs": len(rows),
                    "energy_kwh_std": float(energy.std()),
                    "run_ids": (rows[id_col].astype(str).tolist()
                                if id_col in cols else []),
                }
            self.register_operation(
                name=str(name),
                operation_id=first(rows, id_col) if len(rows) == 1 else None,
                energy_kwh=float(energy.mean()),
                duration_seconds=(float(rows[duration_col].astype(float).mean())
                                  if duration_col in cols else 0.0),
                machine=first(rows, machine_col),
                grid_region=first(rows, region_col),
                **metadata,
            )

    def register_from_csv(self, path: str, **kwargs):
        import pandas as pd

        self.register_from_dataframe(pd.read_csv(path), **kwargs)

    def build_system(
        self, name: str, *, operations: list[str] | None = None
    ) -> ManufacturingSystem:
        if operations is None:
            ops = list(self._operations.values())
        else:
            missing = [n for n in operations if n not in self._operations]
            if missing:
                raise ValueError(
                    f"operations not registered: {missing}; "
                    f"registered: {list(self._operations)}")
            ops = [self._operations[n] for n in operations]
        return ManufacturingSystem(name=name, operations=ops)

    # --- openLCA ---

    def process_builder(self, op: Operation) -> ProcessBuilder:
        """The builder for one operation's process, before insertion. Use it
        to add material inputs or other exchanges."""
        n_runs = op.metadata.get("n_runs", 1)
        if n_runs > 1:
            runs = (f"Mean of {n_runs} runs, energy std "
                    f"{op.metadata.get('energy_kwh_std', 0.0):.4f} kWh\n"
                    f"Run IDs: {', '.join(op.metadata.get('run_ids', []))}\n")
        else:
            runs = f"Operation ID: {op.operation_id}\n"
        b = (
            ProcessBuilder(self._client, f"{op.name} (measured)")
            .category(self.category)
            .description(
                "Measured operation from manufacturing energy monitoring.\n"
                + runs +
                f"Machine: {op.machine}\n"
                f"Energy: {op.energy_kwh:.4f} kWh over "
                f"{op.duration_seconds:.1f} s\n"
                f"Average power: {op.power_kw:.3f} kW\n"
                f"Grid region: {op.grid_region}")
            .tag("measured")
            .output_new(f"{op.name}, completed", 1.0, "Item(s)",
                        is_reference=True)
            .input_from_db(self.electricity_flow, op.energy_kwh, "kWh",
                           provider_location=self.provider_location)
        )
        if self.process_location:
            b.location(self.process_location)
        return b

    def insert_system(self, system: ManufacturingSystem) -> dict[str, o.Ref]:
        """Insert one process per operation. Returns {operation: ref}."""
        if find_by(self._client, o.Flow, self.electricity_flow) is None:
            raise ValueError(
                f"electricity flow {self.electricity_flow!r} not found; "
                "pass electricity_flow= with the name used in your database")
        refs = {}
        for op in system.operations:
            ref = self.process_builder(op).build_and_insert()
            if ref is None:
                raise RuntimeError(f"failed to insert process for {op.name!r}")
            refs[op.name] = ref
        return refs

    def calculate(
        self,
        system: ManufacturingSystem,
        *,
        method: str,
        cleanup: bool = True,
    ) -> BridgeResults:
        """Insert the operations, build a product system for each, and
        calculate its impacts with the given LCIA method.

        With cleanup=True (default) the created product systems are deleted
        afterwards; the processes stay in the database.
        """
        method_ref = find_by(self._client, o.ImpactMethod, method)
        if method_ref is None:
            raise ValueError(f"impact method {method!r} not found")

        results = BridgeResults(system=system, method=method)
        results.process_refs = self.insert_system(system)
        for op in system.operations:
            ps = self._client.create_product_system(results.process_refs[op.name])
            if ps is None:
                results.errors[op.name] = "could not create product system"
                continue
            setup = o.CalculationSetup(
                target=ps, impact_method=method_ref, amount=1.0)
            result = self._client.calculate(setup)
            try:
                state = result.wait_until_ready()
                if state.error:
                    results.errors[op.name] = str(state.error)
                else:
                    results.operation_impacts[op.name] = {
                        iv.impact_category.name: iv.amount or 0.0
                        for iv in result.get_total_impacts()
                        if iv.impact_category and iv.impact_category.name
                    }
            finally:
                result.dispose()
                if cleanup:
                    self._client.delete(ps)
        return results

    # --- analysis ---

    def operation_summary(self):
        """One row per registered operation. For run-to-run variability, see
        ComparisonEngine.variability_report."""
        import pandas as pd

        return pd.DataFrame([{
            "operation": op.name,
            "operation_id": op.operation_id,
            "energy_kwh": op.energy_kwh,
            "duration_s": op.duration_seconds,
            "power_kw": round(op.power_kw, 3),
            "n_runs": op.metadata.get("n_runs", 1),
            "energy_kwh_std": op.metadata.get("energy_kwh_std", 0.0),
            "machine": op.machine,
            "grid_region": op.grid_region,
        } for op in self._operations.values()])

    @property
    def operations(self) -> dict[str, Operation]:
        return dict(self._operations)

    def clear(self):
        self._operations.clear()
