# API Reference

Every public entry point in olca-contrib, grouped by module.

---

## olca_contrib.patches

Lookup helpers. The module name is historical: it no longer patches
anything (the timestamp patch was removed in 0.4.0, see CHANGES.md).

### `find_by(client, model_type, name, *, location=None, category=None) -> Ref | None`

Finds a descriptor by exact name, narrowing by location and/or
category when several entities share that name. Category matching is a
substring test. Raises `ValueError` listing the candidates when the
result is still ambiguous, rather than returning an arbitrary one.

```python
ref = find_by(client, o.Process,
              "electricity production, wind", location="US")
```

`client.find()` returns the first match, which is documented upstream
([#5](https://github.com/GreenDelta/olca-ipc.py/issues/5), closed). This
is for databases like ecoinvent, where many names repeat by location.

### `find_all_by(client, model_type, name, *, location=None, category=None) -> list[Ref]`

Same filtering, but returns every match and never raises. Use it to
inspect what is available before committing to one.

### `get_by_name(client, model_type, name, *, location=None, category=None) -> entity | None`

`find_by`, then `client.get(model_type, uid=ref.id)`. Fetching by ID
also avoids a `RestClient` bug in olca-ipc 2.7.0 and earlier, where a
name with `#` or `?` is cut off in the request path (fix submitted
upstream).

### `class UnitCache(client)`

Resolves units, which are nested inside `UnitGroup` and have no
`get`/`find` of their own
([#4](https://github.com/GreenDelta/olca-ipc.py/issues/4)). Fetches all
groups on first use and indexes them by unit name.

| Method | Returns |
|---|---|
| `find(name)` | `(Unit, UnitGroup)` or `None` |
| `find_unit(name)` | `Unit` or `None` |
| `find_group(name)` | `UnitGroup` or `None` |
| `flow_property_of(name)` | `Ref` to the group's default flow property, or `None` |
| `all_units()` | `{name: (Unit, UnitGroup)}` |
| `invalidate()` | clears the cache |

---

## olca_contrib.batch

### `calculate_batch(client, setups, *, include_inventory=False, on_error="skip", progress=False, progress_callback=None) -> BatchResults`

Runs a list of `CalculationSetup` objects, extracting results and
disposing each one immediately so the server does not accumulate them.

| Argument | Effect |
|---|---|
| `include_inventory` | also pull LCI flow results (slower) |
| `on_error="skip"` | record the error, keep going |
| `on_error="raise"` | abort the batch on first failure |
| `progress` | tqdm progress bar, if tqdm is installed |
| `progress_callback` | `callable(done, total, elapsed)` |

```python
results = calculate_batch(client, setups, progress=True)
df = results.to_impacts_dataframe()
```

### `class BatchResults`

| Member | Description |
|---|---|
| `results` | list of `BatchResult` |
| `n_succeeded`, `n_failed` | counts |
| `total_elapsed_seconds` | wall clock for the batch |
| `to_impacts_dataframe()` | one row per calculation, one column per category |
| `to_inventory_dataframe()` | same shape for LCI flows |
| `errors()`, `succeeded()` | filtered subsets |

### `class BatchResult`

Fields: `index`, `setup`, `impacts`, `inventory`, `error`,
`elapsed_seconds`.

---

## olca_contrib.monte_carlo

### `simulate_safe(client, setup, *, iterations=1000, mode="fresh", progress=False) -> MonteCarloResults`

Runs a Monte Carlo simulation and collects the total impacts of each
iteration.

| `mode` | How | Safe on |
|---|---|---|
| `"fresh"` (default) | a new simulation per iteration, disposed after reading | any server |
| `"next"` | one simulator, `simulate_next()` per iteration | openLCA 2.7.1+ |

```python
results = simulate_safe(client, setup, iterations=1000)
print(results.stats_dataframe())
```

Up to openLCA 2.7.0 the server leaks one native factorization per
`simulate_next()` ([#41](https://github.com/GreenDelta/olca-ipc.py/issues/41)),
fixed in olca-modules `c895e0e`. `"fresh"` never calls `simulate_next()`
and so avoids the leak, at the cost of rebuilding the simulator each
time. Disposing in chunks would not help: disposing frees only the
current run. A failed iteration is counted and skipped.

### `class MonteCarloResults`

| Member | Description |
|---|---|
| `impact_results` | list of per-iteration `{category: value}` |
| `n_iterations`, `n_failed` | counts |
| `mode` | the mode used |
| `errors` | messages of failed iterations |
| `total_elapsed_seconds` | wall clock |
| `to_dataframe()` | one row per iteration |
| `stats()` | `{category: {mean, std, min, max, median, cv, p05, p95}}` |
| `stats_dataframe()` | the same as a DataFrame |

---

## olca_contrib.builders

### `class ProcessBuilder(client, name)`

Builds a process step by step, then inserts it with any new flows it
needs.

```python
ref = (ProcessBuilder(client, "CNC facing")
    .location("US")
    .category("Manufacturing/CNC")
    .description("0.347 kWh measured over 45 s")
    .output_new("faced part", 1.0, "Item(s)", is_reference=True)
    .input_from_db("electricity, medium voltage", 0.347, "kWh",
                   provider_location="US-RFC")
    .build_and_insert())
```

| Method | Purpose |
|---|---|
| `location(code_or_name)` | resolved to an existing `Location`; unknown raises |
| `category(path)`, `description(text)`, `tag(tag)` | metadata |
| `output_new(flow, amount, unit, *, is_reference=False)` | output of a new product flow |
| `input_new(flow, amount, unit)` | input of a new product flow |
| `input_from_db(flow, amount, unit=None, *, provider="auto", provider_location=None)` | input of an existing flow |
| `output_from_db(flow, amount, unit=None, *, is_reference=False)` | output of an existing flow |
| `build()` | the `Process`; new flows in `new_flows` |
| `build_and_insert()` | inserts the new flows, then the process; returns its `Ref` |

The process, exchanges, and internal IDs come from `o.new_process`,
`o.new_input`, and `o.new_output`. Units are resolved through
`UnitCache`, and an unknown flow or unit raises `ValueError`.

For an existing flow, `unit=None` uses the flow's reference unit. With a
unit, the builder sets the exchange's flow property to the one of the
flow whose unit group contains that unit, so `steel` in `Item(s)` uses
the flow's items property, not its mass. A unit the flow has no property
for (`steel` in `kWh`) raises and lists the flow's properties. Without
this, openLCA would read the amount against the reference property.

`provider="auto"` links the first provider of the flow, or the one at
`provider_location` (for example `"US-RFC"`). `"none"` links nothing;
any other value is taken as the provider's process ID. `build()` logs a
warning if no exchange is the quantitative reference.

---

## olca_contrib.extractors

### `class ResultExtractor(result)`

Wraps a calculation result and returns DataFrames instead of nested
schema objects.

```python
with ResultExtractor.from_setup(client, setup) as ext:
    impacts = ext.impacts_df()
    top = ext.top_contributors("Climate change", n=5)
```

| Method | Returns |
|---|---|
| `from_setup(client, setup)` | classmethod; runs the calculation |
| `impacts_df()` | `category, category_id, value, ref_unit` |
| `impacts_dict()` | `{category: value}` |
| `process_contributions(name)` | `process, location, value, contribution_pct` |
| `top_contributors(name, n=10)` | the first n of the above |
| `inventory_df(inputs_only=, outputs_only=)` | `flow, category, is_input, value, unit` |
| `demand()` | `{amount, process, flow}` |
| `summary()` | short text report |
| `dispose()` | frees the result on the server |

Using it as a context manager disposes automatically.
`process_contributions` raises `ValueError` and lists the available
categories when the name does not match.

---

## olca_contrib.energy_bridge

Turns measured energy per manufacturing operation into openLCA
processes and LCIA results.

### `class Operation`

| Field | Meaning |
|---|---|
| `name` | operation label |
| `operation_id` | traceability ID from the monitoring system |
| `energy_kwh`, `duration_seconds` | measurements |
| `machine`, `grid_region` | context |
| `metadata` | free-form dict; `n_runs`, `energy_kwh_std`, `run_ids` for averaged runs |
| `power_kw` | derived average power |
| `energy_mj` | derived, kWh x 3.6 |

### `class ManufacturingSystem`

Holds `name`, `operations`, and a derived `total_energy_kwh`.

### `class EnergyBridge(client, *, electricity_flow="electricity, medium voltage", provider_location=None, process_location=None, category="olca-contrib/measured operations")`

| Method | Purpose |
|---|---|
| `register_operation(name, operation_id=None, energy_kwh=0, duration_seconds=0, machine="", grid_region="", *, replace=False, **metadata)` | register one operation |
| `register_from_dataframe(df, *, ..., repeated="raise")` | one operation per name; column names configurable |
| `register_from_csv(path, **kwargs)` | same, from a file |
| `build_system(name, *, operations=None)` | the registered operations, or the named ones |
| `process_builder(op)` | the `ProcessBuilder` for one operation, to add materials before inserting |
| `insert_system(system)` | inserts one process per operation; `{operation: Ref}` |
| `calculate(system, *, method, cleanup=True)` | inserts, calculates, returns `BridgeResults` |
| `operation_summary()` | DataFrame of everything registered |
| `operations` | `{name: Operation}` |
| `clear()` | drop all registrations |

Registering a name twice raises, unless `replace=True`. For a table
with repeated runs per operation, `repeated="mean"` registers each
operation once with the mean energy and duration and keeps the run
count, energy standard deviation, and run IDs. For run-to-run
statistics, use `ComparisonEngine.variability_report`.

`provider_location` picks the electricity provider by location. In
ecoinvent the grid region is on the provider (`US-RFC`), not on the
flow. A missing electricity flow raises; pass `electricity_flow=` with
the name your database uses.

Each process description records the operation ID (or run IDs),
machine, energy, duration, and average power, so a result traces back
to the meter data.

`calculate` creates a product system per operation, runs the method,
disposes each result, and deletes the product systems unless
`cleanup=False`. The processes stay in the database.

### `class BridgeResults`

| Member | Description |
|---|---|
| `operation_impacts` | `{operation: {category: value}}` |
| `process_refs` | `{operation: Ref}` of the inserted processes |
| `errors` | `{operation: message}` |
| `total_impacts` | summed over operations |
| `to_dataframe()` | one row per operation |
| `share_dataframe()` | each operation's share of the total, % |

---

## olca_contrib.carbon

### `class CarbonCalculator(*, default_region="RFCW", custom_factors=None)`

| Method | Purpose |
|---|---|
| `get_factor(region)` | kg CO2/kWh, resolving ISO aliases |
| `from_egrid(name, kwh, *, region=None)` | `CarbonProfile` using a subregion average |
| `from_factor(name, kwh, *, factor_kg_per_kwh=)` | `CarbonProfile` with your own factor |
| `profile_operations(operations)` | profiles for an `EnergyBridge.operations` dict |
| `to_dataframe(profiles)` | tabular view |
| `total_emissions(profiles)` | sum in kg CO2 |
| `compare_regions(kwh, regions=None)` | sorted comparison with `relative_pct` |

### `EGRID_FACTORS: dict[str, float]`

eGRID subregion average CO2 factors in kg CO2/kWh. Approximate values
intended for planning and relative comparison. Verify against the
current eGRID release before using them in a published assessment.

### `REGION_TO_EGRID: dict[str, str]`

Rough ISO/RTO to eGRID subregion aliases (`PJM`, `ERCOT`, `CAISO`,
`MISO_INDY`, and others). ISO footprints do not line up cleanly with
eGRID boundaries, so treat these as approximations rather than
authoritative mappings.

### `class WattTimeClient(username=, password=, token=)`

Marginal operating emissions rate lookups. Requires `httpx` and a
WattTime account. Endpoints and response shapes change between API
versions, so check current WattTime documentation.

| Method | Returns |
|---|---|
| `get_current_moer(*, latitude, longitude)` | float or `None` |
| `get_historical_moer(*, latitude, longitude, start, end)` | list of dicts |

---

## olca_contrib.inspector

### `class DatabaseInspector(client)`

| Method | Purpose |
|---|---|
| `summary()` / `summary_df()` | entity counts by type |
| `impact_methods()` / `impact_methods_df()` | available LCIA methods |
| `impact_categories_for(method_name)` | categories inside a method |
| `inspect_process(name, location=None)` | full detail with exchanges |
| `inspect_process_df(name, location=None)` | exchanges as a DataFrame |
| `find_duplicates(model_type)` / `find_duplicates_df()` | shared names |
| `entity_inventory(model_type)` | everything of a type |
| `search(query, model_type)` / `search_df()` | case-insensitive substring |
| `electricity_flows()` | shorthand for searching flows |
| `validate_product_system(name)` | reference process and exchange checks |

---

## olca_contrib.compare

### `class ComparisonEngine()`

| Method | Purpose |
|---|---|
| `add_measured(op, kwh)` / `add_measured_batch(dict)` | measured values |
| `add_default(op, kwh)` / `add_default_batch(dict)` | database defaults |
| `from_dataframe(df, ...)` | load both sides at once |
| `set_material_gwp(kg_co2)` | material baseline for share calculations |
| `set_emission_factor(kg_co2_per_kwh)` | energy to GWP conversion |
| `compare(system_name)` | returns `SystemComparison` |
| `variability_report({op: [values]})` | n, mean, std, cv, min, max, range |

### `class SystemComparison`

Carries the per-operation comparisons plus energy totals and GWP
shares. `to_dataframe()` gives measured, default, absolute and percent
difference, and ratio per operation. `summary()` renders a short text
report. `measured_energy_share_pct` and `default_energy_share_pct`
express energy as a share of material plus energy GWP.

### `class ComparisonResult`

One operation: `measured_value`, `default_value`, and the derived
`absolute_difference`, `relative_difference_pct`, and `ratio`. A zero
default yields `inf` when measured is non-zero, and `0.0` / `1.0` when
both are zero.

---

## Command line

Installing the package registers an `olca` command.

| Command | Purpose |
|---|---|
| `olca summary` | entity counts |
| `olca search QUERY -t Flow --limit 20` | search by name |
| `olca methods` | list impact methods |
| `olca inspect NAME -l US` | process detail |
| `olca duplicates -t Process` | shared names |
| `olca carbon 0.347 --region RFCW --compare-regions` | grid emissions |
| `olca variability data.csv` | run-to-run statistics |

Global flags: `--port` (default 8080) and `-v` for debug logging.
Everything except `carbon` and `variability` needs a live IPC server.
