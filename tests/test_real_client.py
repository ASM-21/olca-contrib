"""Integration tests through the real olca-ipc client classes.

Unlike the mock-based tests, these run `olca_ipc.ipc.Client` and
`olca_ipc.rest.RestClient` themselves, with only the wire replaced. They fail
if the client API we depend on changes (for example, a renamed class or a
changed method), which the mock tests cannot catch.
"""

import inspect
import unittest
from unittest import mock

import olca_schema as o
import olca_ipc.protocol as protocol

from olca_contrib import (
    EnergyBridge,
    ProcessBuilder,
    ResultExtractor,
    UnitCache,
    calculate_batch,
    find_all_by,
    find_by,
    get_by_name,
    simulate_safe,
)
from tests.fake_server import FakeServer, ipc_client


def _setups(n):
    return [o.CalculationSetup(
        target=o.Ref(ref_type=o.RefType.ProductSystem, id=f"ps-{i}"),
        impact_method=o.Ref(ref_type=o.RefType.ImpactMethod, id="m-1"))
        for i in range(n)]


class ApiSurfaceTest(unittest.TestCase):
    """Every client method olca-contrib calls must exist upstream."""

    CLIENT = ["get", "get_all", "get_descriptors", "get_providers", "find",
              "put", "create_product_system", "delete", "calculate",
              "simulate"]
    RESULT = ["wait_until_ready", "get_state", "simulate_next", "dispose",
              "get_total_impacts", "get_total_flows", "get_impact_categories",
              "get_impact_contributions_of", "get_demand"]

    def test_client_methods(self):
        for name in self.CLIENT:
            with self.subTest(name=name):
                self.assertTrue(callable(getattr(protocol.ProtoClient, name)))

    def test_result_methods(self):
        for name in self.RESULT:
            with self.subTest(name=name):
                self.assertTrue(callable(getattr(protocol.ProtoResult, name)))

    def test_get_accepts_uid_keyword(self):
        params = inspect.signature(protocol.ProtoClient.get).parameters
        self.assertIn("uid", params)
        self.assertIn("name", params)


class BatchTest(unittest.TestCase):
    def test_all_results_disposed(self):
        with ipc_client() as (client, server):
            r = calculate_batch(client, _setups(4))
        self.assertEqual(4, r.n_succeeded)
        self.assertEqual(set(), server.live)
        self.assertAlmostEqual(1.01, r.results[0].impacts["Climate change"])

    def test_failure_is_isolated(self):
        server = FakeServer()
        with ipc_client(server) as (client, _):
            server.fail_next_calc = True
            r = calculate_batch(client, _setups(3))
        self.assertEqual((2, 1), (r.n_succeeded, r.n_failed))
        self.assertIn("calculation failed", r.results[0].error)
        self.assertEqual(set(), server.live)


class MonteCarloTest(unittest.TestCase):
    def test_fresh_mode_never_calls_next(self):
        with ipc_client() as (client, server):
            r = simulate_safe(client, _setups(1)[0], iterations=6)
        self.assertEqual(6, r.n_iterations)
        self.assertEqual(6, server.methods().count("result/simulate"))
        self.assertEqual(0, server.methods().count("result/simulate/next"))
        self.assertEqual(set(), server.live)

    def test_next_mode_uses_one_simulator(self):
        with ipc_client() as (client, server):
            r = simulate_safe(client, _setups(1)[0], iterations=6, mode="next")
        self.assertEqual(6, r.n_iterations)
        self.assertEqual(1, server.methods().count("result/simulate"))
        self.assertEqual(5, server.methods().count("result/simulate/next"))
        self.assertEqual(set(), server.live)

    def test_stats(self):
        with ipc_client() as (client, _):
            r = simulate_safe(client, _setups(1)[0], iterations=10)
        s = r.stats()["Climate change"]
        self.assertGreater(s["std"], 0)
        self.assertLessEqual(s["p05"], s["mean"])
        self.assertLessEqual(s["mean"], s["p95"])

    def test_bad_arguments(self):
        with ipc_client() as (client, _):
            with self.assertRaises(ValueError):
                simulate_safe(client, _setups(1)[0], iterations=0)
            with self.assertRaises(ValueError):
                simulate_safe(client, _setups(1)[0], mode="chunked")


class LookupTest(unittest.TestCase):
    def test_find_by_location(self):
        with ipc_client() as (client, _):
            ref = find_by(client, o.Process, "wind power", location="US")
        self.assertEqual("p-wind-us", ref.id)

    def test_find_by_ambiguous(self):
        with ipc_client() as (client, _):
            with self.assertRaises(ValueError) as ctx:
                find_by(client, o.Process, "wind power")
        self.assertIn("p-wind-rer", str(ctx.exception))
        self.assertIn("p-wind-us", str(ctx.exception))

    def test_find_all_by(self):
        with ipc_client() as (client, _):
            self.assertEqual(2, len(find_all_by(client, o.Process, "wind power")))

    def test_get_by_name_fetches_by_id(self):
        with ipc_client() as (client, server):
            p = get_by_name(client, o.Process, "wind power", location="RER")
        self.assertEqual("p-wind-rer", p.id)
        get_calls = [prm for m, prm in server.calls if m == "data/get"]
        self.assertEqual([{"@type": "Process", "@id": "p-wind-rer"}], get_calls)

    def test_unit_cache(self):
        with ipc_client() as (client, server):
            units = UnitCache(client)
            self.assertEqual("u-kwh", units.find_unit("kWh").id)
            self.assertEqual("fp-mass", units.flow_property_of("kg").id)
            units.find("MJ")
        self.assertEqual(1, server.methods().count("data/get/all"))


class RestClientTest(unittest.TestCase):
    """get_by_name never puts the name in a URL, so `#` and `?` are safe."""

    def test_get_by_name_with_hash(self):
        from olca_ipc.rest import RestClient

        server = FakeServer()
        urls = []

        def fake_get(url, **_):
            urls.append(url)
            resp = mock.Mock(status_code=200)
            path = url.split("/data/", 1)[1]
            if path == "processes":
                resp.json.return_value = server.descriptors["Process"]
            else:
                uid = path.split("/")[-1]
                resp.json.return_value = next(
                    d for d in server.descriptors["Process"] if d["@id"] == uid)
            return resp

        client = RestClient("http://localhost:8080")
        with mock.patch("requests.get", side_effect=fake_get):
            p = get_by_name(client, o.Process, "#2 fuel oil burner")
        self.assertEqual("p-hash", p.id)
        self.assertTrue(all("#" not in u for u in urls))


class ProcessBuilderTest(unittest.TestCase):
    def _build(self, client):
        return (ProcessBuilder(client, "CNC facing")
                .location("US")
                .category("Manufacturing/CNC")
                .output_new("faced part", 1.0, "Item(s)", is_reference=True)
                .input_from_db("electricity, medium voltage", 0.347, "kWh",
                               provider_location="US-WECC"))

    def test_build(self):
        with ipc_client() as (client, _):
            b = self._build(client)
            p = b.build()
        self.assertEqual("loc-us", p.location.id)
        self.assertEqual(2, p.last_internal_id)
        out, elec = p.exchanges
        self.assertTrue(out.is_quantitative_reference)
        self.assertFalse(out.is_input)
        self.assertEqual(b.new_flows[0].id, out.flow.id)
        self.assertEqual("f-elec", elec.flow.id)
        self.assertEqual("u-kwh", elec.unit.id)
        self.assertEqual("p-mkt-wecc", elec.default_provider.id)

    def test_new_flow_has_flow_property(self):
        with ipc_client() as (client, _):
            b = self._build(client)
            b.build()
        prop = b.new_flows[0].flow_properties[0].flow_property
        self.assertEqual("fp-items", prop.id)

    def test_insert_puts_flows_first(self):
        with ipc_client() as (client, server):
            ref = self._build(client).build_and_insert()
        types = [e["@type"] for e in server.put_entities]
        self.assertEqual(["Flow", "Process"], types)
        self.assertEqual("CNC facing", ref.name)

    def test_unknown_location(self):
        with ipc_client() as (client, _):
            with self.assertRaises(ValueError):
                ProcessBuilder(client, "x").location("Atlantis").build()

    def test_unknown_flow_and_unit(self):
        with ipc_client() as (client, _):
            with self.assertRaises(ValueError):
                ProcessBuilder(client, "x").input_from_db("unobtainium", 1).build()
            with self.assertRaises(ValueError):
                ProcessBuilder(client, "x").input_new("y", 1, "furlong").build()

    def test_db_flow_gets_the_property_of_its_unit(self):
        # without the flow property, the server reads the unit against the
        # reference property of the flow
        with ipc_client() as (client, _):
            p = (ProcessBuilder(client, "x")
                 .input_from_db("electricity, medium voltage", 1, "kWh",
                                provider="none")
                 .input_from_db("steel", 4, "Item(s)", provider="none")
                 .input_from_db("steel", 2, "kg", provider="none")
                 .build())
        elec, steel_items, steel_kg = p.exchanges
        self.assertEqual("fp-energy", elec.flow_property.id)
        self.assertEqual(("fp-items", "u-item"),
                         (steel_items.flow_property.id, steel_items.unit.id))
        self.assertEqual("fp-mass", steel_kg.flow_property.id)

    def test_db_flow_without_unit_uses_its_reference(self):
        with ipc_client() as (client, _):
            p = (ProcessBuilder(client, "x")
                 .input_from_db("steel", 2, provider="none").build())
        self.assertIsNone(p.exchanges[0].unit)
        self.assertIsNone(p.exchanges[0].flow_property)

    def test_db_flow_with_a_unit_it_cannot_have(self):
        with ipc_client() as (client, _):
            with self.assertRaisesRegex(ValueError, "Mass, Number of items"):
                (ProcessBuilder(client, "x")
                 .input_from_db("steel", 1, "kWh", provider="none").build())


class EnergyBridgeTest(unittest.TestCase):
    def test_calculate_end_to_end(self):
        with ipc_client() as (client, server):
            bridge = EnergyBridge(client, provider_location="US-RFC")
            bridge.register_operation("facing", energy_kwh=0.347,
                                      duration_seconds=45, operation_id="op-1")
            bridge.register_operation("drilling", energy_kwh=0.156,
                                      duration_seconds=28)
            results = bridge.calculate(bridge.build_system("housing"),
                                       method="Test method")

        self.assertEqual({"facing", "drilling"}, set(results.operation_impacts))
        self.assertEqual({}, results.errors)
        self.assertEqual(set(), server.live)
        self.assertEqual(server.created_systems, server.deleted)
        df = results.to_dataframe()
        self.assertIn("Climate change", df.columns)
        self.assertAlmostEqual(100.0, results.share_dataframe()["Climate change"].sum())

        procs = [e for e in server.put_entities if e["@type"] == "Process"]
        self.assertIn("op-1", procs[0]["description"])
        elec = [x for x in procs[0]["exchanges"] if x.get("isInput")][0]
        self.assertEqual("p-mkt-rfc", elec["defaultProvider"]["@id"])

    def test_missing_electricity_flow(self):
        with ipc_client() as (client, _):
            bridge = EnergyBridge(client, electricity_flow="no such flow")
            bridge.register_operation("a", energy_kwh=1.0)
            with self.assertRaises(ValueError):
                bridge.insert_system(bridge.build_system("s"))

    def test_negative_energy_rejected(self):
        with ipc_client() as (client, _):
            with self.assertRaises(ValueError):
                EnergyBridge(client).register_operation("a", energy_kwh=-1)


class ExtractorTest(unittest.TestCase):
    def test_context_manager_disposes(self):
        with ipc_client() as (client, server):
            with ResultExtractor.from_setup(client, _setups(1)[0]) as ext:
                d = ext.impacts_dict()
        self.assertIn("Climate change", d)
        self.assertEqual(set(), server.live)


if __name__ == "__main__":
    unittest.main()
