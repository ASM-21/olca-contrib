# Development

## Setup

```bash
git clone https://github.com/ASM-21/olca-contrib.git
cd olca-contrib
pip install -e ".[dev]"
```

Requires Python 3.12 or newer, like upstream olca-ipc master.

## Tests

```bash
python -m pytest tests/ -v
```

No test needs an openLCA server, and the whole suite runs in about a
second. Keep it that way: a test that needs a live server is a test that
will not run in CI. There are two kinds:

- `tests/test_real_client.py` runs the real `olca_ipc.Client` and
  `olca_ipc.rest.RestClient` against `tests/fake_server.py`, an in-memory
  fake of the JSON-RPC server. Only the transport is replaced
  (`Client.rpc_call`, or `requests` for the REST client), so a rename or
  a changed signature upstream fails here. This file was added after the
  mock-only suite missed the `IpcProtocol` to `ProtoClient` rename.
  Prefer it for anything that talks to the client.
- `tests/test_core.py` and `tests/test_modules.py` use the mocks in
  `tests/mock_client.py` (`make_client`, `make_result`, `make_setups`).
  They are fine for logic that does not depend on the client's API,
  such as statistics, grid factors, and comparisons.

`FakeServer` serves descriptors, full flows and flow properties, unit
groups, locations, providers, product systems, and results. It records
every call, so tests can assert that results were disposed and product
systems deleted. Set `fail_next_calc = True` to make the next
calculation return an error.

CI (`.github/workflows/ci.yml`) runs the suite and the two offline
examples on Python 3.12 and 3.13 against the latest released packages,
on the minimum versions in `pyproject.toml` (olca-ipc 2.6.3, olca-schema
2.6.2), and against olca-ipc and olca-schema from upstream master. The master
job may fail without failing the build; it is the early warning for
upstream changes. It also runs weekly.

## Examples

```bash
python examples/01_offline_workflow.py      # no server needed
python examples/02_live_server.py           # needs IPC on port 8080
python examples/03_issue_reproductions.py   # no server needed
```

Example 2 accepts `--insert` to write operation processes into the
connected database. Without that flag it only reads.

## Sample data

```bash
python data/generate_sample_data.py
```

Regenerates the three CSVs under `data/`. The numbers are synthetic,
produced from a fixed random seed, and shaped to be plausible for
small-part CNC and desktop AM work. They are not measurements. Do not
cite them as data.

## Layout

```
olca_contrib/
  patches.py        find_by, get_by_name, UnitCache (#5, #4)
  batch.py          batch calculation
  monte_carlo.py    simulate_safe (#41)
  builders.py       ProcessBuilder
  extractors.py     result to DataFrame
  energy_bridge.py  measured energy to openLCA
  carbon.py         grid emission factors
  inspector.py      database diagnostics
  compare.py        measured vs. default
  cli.py            command line entry point
tests/
  fake_server.py    in-memory JSON-RPC server for the real clients
  test_real_client.py  the real clients against the fake server
  mock_client.py    mock fixtures
  test_core.py      lookups, batch (mocks)
  test_modules.py   bridge logic, carbon, inspector, compare (mocks)
examples/           three scripts; 01 and 03 run offline
data/               synthetic CSVs plus the generator
docs/               API reference and this file
upstream/           patch, PR text, and issue comments for olca-ipc.py
```

## Conventions

- Type hints use the modern union syntax (`str | None`), matching
  upstream olca-ipc.
- Tests use plain `unittest`, also matching upstream.
- Public functions take the client as the first positional argument so
  they read like methods that could later move onto the client itself.
- Anything that creates a result on the server disposes it, including
  on the error path. That is the whole point of several of these
  modules.

## Relationship to upstream

This package is not a fork. It sits on top of `olca-ipc` and only adds
things. Where a fix belongs upstream, the intent is to propose it
there and eventually delete the local version.

Status of each local piece:

| Local | Upstream |
|---|---|
| `get_by_name` | works around the RestClient name bug; fix in `upstream/` |
| `find_by`, `find_all_by` | first-match `find()` is documented (#5, closed); stays a helper |
| `UnitCache` | #4 is open; offered upstream, waiting on the API shape |
| `simulate_safe` | server fix in olca-modules 2.7.1 (#41); `mode="next"` once released |

When a fix lands upstream, keep the helper working on older versions
until the fixed release is the minimum in `pyproject.toml`, then
deprecate it.

See `ACTION_PLAN.md` for the status of each issue and the steps.
