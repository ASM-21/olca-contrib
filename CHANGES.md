# Changes

## 0.4.0 (2026-11-20)

An audit against upstream source found that several things in 0.3.0 were
wrong. This release fixes them.

### Removed

- **Timestamp patch** (`patch_datetime_serialization`, `normalize_timestamp`,
  `fix_entity_timestamp`). The bug it targeted, a `+00:00Z` suffix that the
  Java parser rejects, was fixed in olca-schema 2.2.2 (commit `8a2ab4e`,
  2024-11-04). The current format parses fine, which was checked by
  compiling upstream `Json.parseDate`. The earlier explanation, that Java
  rejects microseconds, was also wrong.

### Fixed

- **Monte Carlo** (`simulate_safe`). The chunked approach did not bound
  memory on a leaking server: disposing a simulator frees only its current
  run, and every run replaced before it holds native memory that is never
  freed. With `chunk_size=100`, 99 of every 100 runs still leaked. Replaced
  by `mode="fresh"` (default, one simulation per iteration, leak-free on any
  server) and `mode="next"` (one simulator, safe from openLCA 2.7.1). The
  `chunk_size` argument is gone.
- **ProcessBuilder** produced processes that could not be stored correctly:
  - Exchanges pointed at new flows that were never created. New flows are now
    built with `o.new_product` and inserted before the process.
  - The location was a name-only reference without an ID. It is now
    resolved to an existing location by code or name, and an unknown
    location raises.
  - Exchange IDs and `last_internal_id` were set by hand. The builder now
    uses `o.new_process`, `o.new_input`, and `o.new_output`.
  - Exchanges of existing flows had a unit but no flow property, so
    openLCA read the amount against the flow's reference property. The
    builder now sets the flow property that matches the unit, and raises
    for a unit the flow has no property for (for example, steel in kWh).
  - `output()` is now `output_new()`. Added `output_from_db()` and
    `provider_location=` for picking a provider by location.
- **EnergyBridge**:
  - Filtered electricity flows by grid region, but in ecoinvent the region
    is on the provider, not the flow. Use `provider_location="US-RFC"`.
  - Fell back to inventing an `electricity, measured` flow that did not
    exist. A missing electricity flow now raises.
  - `calculate()` did not calculate anything; it echoed the input energies.
    It now inserts the processes, builds a product system per operation,
    runs the LCIA method, and returns impacts per operation. It deletes the
    product systems afterwards unless you pass `cleanup=False`.
  - Removed `material_inputs` from `ManufacturingSystem`. It was never used.
    Add materials through `process_builder(op)`.
  - Operations are keyed by name, so loading a table of repeated runs
    kept only the last run of each operation. `data/operations_repeated.csv`
    went from 120 runs to 10, with no warning. A repeated name now raises.
    `register_from_dataframe(..., repeated="mean")` averages the runs and
    records the run count, energy spread, and run IDs in the process.
    `register_operation(..., replace=True)` overwrites on purpose.
  - Removed `variability_analysis()`. It computed no statistics and
    returned a subset of `operation_summary()`. Use
    `ComparisonEngine.variability_report` for run-to-run statistics.

### Added

- `get_by_name`: resolves a name through the descriptors and fetches by ID.
  This avoids the RestClient name bug in olca-ipc 2.7.0 and earlier (a fix
  is ready upstream) and handles duplicate names.
- `UnitCache.flow_property_of(unit)`.
- `tests/test_real_client.py` and `tests/fake_server.py`. These run the real
  olca-ipc client classes against an in-memory fake server, so API drift
  upstream shows up as a test failure. The 0.3.0 tests were all mock-based
  and would not have caught the `IpcProtocol` to `ProtoClient` rename.
- CI runs against both the released packages and upstream master.
- `upstream/`: a patch, a PR description, and issue comments for
  GreenDelta/olca-ipc.py.

### Changed

- Requires Python 3.12+, olca-ipc 2.6.3+, and olca-schema 2.6.2+. Tested
  on those minimums and on olca-ipc 2.7.0 with olca-schema 2.7.0, released
  2026-11-20.
- `find_by` is no longer described as a fix for #5. First-match behavior is
  documented upstream, so it is a helper.

## 0.3.0

First packaged version.
