# olca-contrib

Extensions for the [openLCA Python IPC client](https://github.com/GreenDelta/olca-ipc.py):
safer Monte Carlo, name lookups that handle duplicates, batch calculations
that always clean up, a process builder, and a bridge from measured
manufacturing energy to openLCA processes.

It sits on top of `olca-ipc` and only adds things. It is not a fork.

```bash
pip install -e .            # Python 3.12+, olca-ipc 2.6.3 or 2.7.0
pip install -e ".[all]"     # plus tqdm and httpx
```

Try it without a server:

```bash
python examples/03_issue_reproductions.py   # each upstream issue, reproduced
python examples/01_offline_workflow.py      # variability, grid carbon, comparison
```

---

## Monte Carlo without the memory leak

Up to openLCA 2.7.0, every `simulate_next()` leaves a matrix factorization in
native memory on the server, so long runs grow until something gives out
([#41](https://github.com/GreenDelta/olca-ipc.py/issues/41)). GreenDelta fixed
the server in olca-modules `c895e0e`, which is in the olca-modules v2.7.1 tag
but not yet in a desktop release.

```python
from olca_contrib import simulate_safe

results = simulate_safe(client, setup, iterations=1000)               # any server
results = simulate_safe(client, setup, iterations=1000, mode="next")  # 2.7.1+
print(results.stats_dataframe())
```

`mode="fresh"` (the default) runs a new simulation per iteration and disposes
it, so nothing is orphaned. It is slower because the simulator is rebuilt
each time (about 7x per iteration in the report on #41). `mode="next"` reuses
one simulator and is only safe once the server has the fix. Running
`simulate_next()` in chunks does not help on a leaking server, because
disposing frees only the current run.

## Names that repeat, or contain `#` and `?`

`find()` and `get(name=...)` return the first entity with a name. That is
documented upstream, but ecoinvent has many processes that share a name and
differ only by location.

```python
from olca_contrib import find_by, find_all_by, get_by_name

ref = find_by(client, o.Process, "electricity production, wind", location="US")
proc = get_by_name(client, o.Process, "market for steel", location="GLO")
```

`find_by` raises and lists the candidates if the name is still ambiguous.
`get_by_name` resolves through the descriptors and fetches by ID. That
also avoids a `RestClient` bug in olca-ipc 2.7.0 and earlier, where a name
with `#` or `?` is cut off in the request. A fix is ready for upstream.

## Units

Units live inside unit groups and have no `get` or `find` of their own
([#4](https://github.com/GreenDelta/olca-ipc.py/issues/4)).

```python
from olca_contrib import UnitCache

units = UnitCache(client)
kwh = units.find_unit("kWh")
energy = units.flow_property_of("kWh")    # the flow property to use for it
```

## Batch calculations

```python
from olca_contrib import calculate_batch

results = calculate_batch(client, setups, progress=True)
df = results.to_impacts_dataframe()
print(f"{results.n_succeeded} ok, {results.n_failed} failed")
```

A failed calculation does not stop the batch, and every result is disposed,
including on the error path.

## Building processes

```python
from olca_contrib import ProcessBuilder

ref = (ProcessBuilder(client, "CNC facing")
    .location("US")
    .category("Manufacturing/CNC")
    .output_new("faced part", 1.0, "Item(s)", is_reference=True)
    .input_from_db("electricity, medium voltage", 0.347, "kWh",
                   provider_location="US-RFC")
    .build_and_insert())
```

New flows are created and inserted before the process. Units, flow
properties, locations, and providers are resolved against the database, and
an unknown flow, unit, or location raises instead of writing a broken
reference.

## Measured energy to LCIA results

```python
from olca_contrib import EnergyBridge

bridge = EnergyBridge(client, provider_location="US-RFC")
bridge.register_from_csv("data/operations_single_run.csv")
results = bridge.calculate(bridge.build_system("Pump housing"),
                           method="ReCiPe 2016 Midpoint (H)")
print(results.to_dataframe())        # impacts per operation
print(results.share_dataframe())     # each operation's share, %
```

One process per operation, linked to the grid provider you choose. In
ecoinvent the region is on the provider (for example `US-RFC`), not on the
electricity flow. Each process description records the monitoring operation
ID, machine, energy, duration, and average power, so a result traces back to
the meter data. The product systems used for the calculation are deleted
afterwards unless you pass `cleanup=False`.

A table with several runs per operation raises instead of keeping only
the last run. Pass `repeated="mean"` to average them; the process then
records the run count, the spread, and the run IDs:

```python
bridge.register_from_csv("data/operations_repeated.csv", repeated="mean")
```

## Results as DataFrames

```python
from olca_contrib import ResultExtractor

with ResultExtractor.from_setup(client, setup) as ext:
    impacts = ext.impacts_df()
    top = ext.top_contributors("Climate change", n=5)
```

## Grid carbon and measured vs. default

`CarbonCalculator` has eGRID subregion averages for offline use and a
WattTime client for marginal rates. The bundled factors are approximate;
check them against the current eGRID release before publishing anything.
`ComparisonEngine` compares measured energy with database defaults and
reports run-to-run variability. See [docs/API.md](docs/API.md).

## Command line

```bash
olca summary                                   # needs a server
olca search "electricity" -t Flow
olca inspect "steel production" -l US
olca carbon 0.347 --compare-regions            # offline
olca variability data/operations_repeated.csv  # offline
```

---

## Tests

```bash
python -m pytest
```

There are 114 tests and none need a server. `tests/test_real_client.py` runs
the real `olca_ipc.Client` and `RestClient` classes against an in-memory
fake of the JSON-RPC server, so it fails if the upstream API we depend on
changes. CI runs the suite against the released packages and against
upstream master.

## Upstream

See [ACTION_PLAN.md](ACTION_PLAN.md) for the status of each upstream issue
and the contribution steps, and [CHANGES.md](CHANGES.md) for what changed
and why.

## License

MPL-2.0, matching openLCA.
