"""
Example 3: the upstream issues, reproduced without a server.

Every section runs offline. The Monte Carlo section uses the in-memory fake
server from the test suite, which runs the real olca-ipc client classes.

Run:
    python examples/03_issue_reproductions.py
"""

import pathlib
import sys
from unittest import mock
from urllib.parse import urlsplit

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import olca_schema as o  # noqa: E402
import requests  # noqa: E402


def section(title: str):
    print(f"\n{'=' * 70}\n{title}\n{'=' * 70}")


def issue_38():
    section("#38  put() rejected timestamps  (closed, fixed in olca-schema 2.2.2)")
    import datetime as dt

    old = dt.datetime.now(dt.UTC).isoformat() + "Z"
    print(f"\nBefore 2.2.2 the schema generated:  {old}")
    print("The `+00:00` offset followed by `Z` is not valid ISO 8601, so the")
    print("Java parser returned null and put() failed.")
    print(f"\nolca-schema now generates:          {o.Source(name='x').last_change}")
    print("That form parses fine on the Java side. Nothing to patch any more.")


def issue_5():
    section("#5  find() returns the first of several same-named entities")
    from olca_contrib import find_all_by, find_by

    name = "electricity production, wind, 1-3MW turbine"
    refs = [o.Ref(id=f"ei-{loc}", name=name, location=loc)
            for loc in ("RER", "US", "RoW", "DE")]
    client = mock.MagicMock()
    client.get_descriptors.return_value = refs

    print(f"\n{len(refs)} processes share the name {name!r}.")
    print("find() and get(name=...) return the first one; that is documented")
    print("upstream, so this is a helper rather than a bug fix.\n")
    for loc in ("US", "DE"):
        print(f"  find_by(..., location={loc!r})  ->  "
              f"{find_by(client, o.Process, name, location=loc).id}")
    try:
        find_by(client, o.Process, name)
    except ValueError as e:
        print(f"\n  find_by without a filter raises instead of guessing:\n"
              f"  {str(e).splitlines()[0]}")
    print(f"\n  find_all_by returns all {len(find_all_by(client, o.Process, name))}")


def rest_names():
    section("RestClient names with # or ?  (fix submitted upstream)")
    base = "http://localhost:8080/data/processes/name/"
    print("\nWhat requests sends for RestClient.get(name=...) in olca-ipc <= 2.7.0:\n")
    for name in ["#2 fuel oil", "steel? or iron", "blend 50%41"]:
        u = urlsplit(requests.Request("GET", base + name).prepare().url)
        got = requests.utils.unquote(u.path.split("/name/", 1)[1])
        print(f"  {name!r:18} server sees {got!r:16} query={u.query!r} "
              f"fragment={u.fragment!r}")
    print("\nget_by_name resolves the name through the descriptors and then")
    print("fetches by ID, so the name never goes into a URL.")


def issue_41():
    section("#41  Monte Carlo leaks server memory  (fixed in olca-modules master)")
    from olca_contrib import simulate_safe
    from tests.fake_server import ipc_client

    print("""
Up to openLCA 2.7.0, each simulate_next() replaced the previous result
without disposing it. The result holds a matrix factorization in native
memory, which only dispose() frees, so every run leaks one. Fixed upstream
in olca-modules c895e0e (2026-11-03), which is in the olca-modules
v2.7.1 tag but not yet in a desktop release.

Running the earlier simulate_next() in chunks does not help: disposing
the simulator frees only the current run.""")

    setup = o.CalculationSetup()
    for mode in ("fresh", "next"):
        with ipc_client() as (client, server):
            r = simulate_safe(client, setup, iterations=50, mode=mode)
            calls = server.methods()
        print(f"\n  mode={mode!r:8} iterations={r.n_iterations}  "
              f"simulate={calls.count('result/simulate'):>2}  "
              f"simulate/next={calls.count('result/simulate/next'):>2}  "
              f"left on server={len(server.live)}")
    print("\n  'fresh' never calls simulate_next, so nothing is orphaned on a")
    print("  leaking server. Use 'next' once the server has the fix.")


def issue_4():
    section("#4  no get/find for units  (open)")
    from olca_contrib import UnitCache

    mass = o.UnitGroup(id="ug-mass", name="Units of mass")
    mass.units = [o.Unit(id="u-kg", name="kg"), o.Unit(id="u-g", name="g")]
    mass.default_flow_property = o.Ref(id="fp-mass", name="Mass")
    energy = o.UnitGroup(id="ug-energy", name="Units of energy")
    energy.units = [o.Unit(id="u-kwh", name="kWh"), o.Unit(id="u-mj", name="MJ")]
    energy.default_flow_property = o.Ref(id="fp-energy", name="Energy")
    client = mock.MagicMock()
    client.get_all.return_value = [mass, energy]

    cache = UnitCache(client)
    print()
    for n in ["kg", "kWh", "furlong"]:
        hit = cache.find(n)
        print(f"  find({n!r:9}) -> " +
              (f"{hit[0].id} in {hit[1].name!r}, flow property "
               f"{cache.flow_property_of(n).name!r}" if hit else "None"))
    print(f"\n  one get_all call for {len(cache.all_units())} units")


if __name__ == "__main__":
    issue_38()
    issue_5()
    rest_names()
    issue_41()
    issue_4()
    print()
