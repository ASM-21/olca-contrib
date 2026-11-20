"""Mock-based tests for lookups, units, and batch calculation."""

import unittest
from unittest.mock import MagicMock

import olca_schema as o

from olca_contrib.batch import calculate_batch
from olca_contrib.patches import UnitCache, find_all_by, find_by, get_by_name
from tests.mock_client import make_client, make_setups


class TestFindBy(unittest.TestCase):
    def test_single_match(self):
        c = make_client([o.Ref(id="1", name="steel", location="US")])
        self.assertEqual("1", find_by(c, o.Process, "steel").id)

    def test_no_match(self):
        c = make_client([o.Ref(id="1", name="other")])
        self.assertIsNone(find_by(c, o.Process, "steel"))

    def test_by_location(self):
        c = make_client([
            o.Ref(id="1", name="elec", location="RER"),
            o.Ref(id="2", name="elec", location="US"),
        ])
        self.assertEqual("2", find_by(c, o.Process, "elec", location="US").id)

    def test_by_category(self):
        c = make_client([
            o.Ref(id="1", name="steel", category="Metals/Basic"),
            o.Ref(id="2", name="steel", category="Metals/Alloy"),
        ])
        self.assertEqual("2", find_by(c, o.Process, "steel", category="Alloy").id)

    def test_filter_with_no_survivor(self):
        c = make_client([o.Ref(id="1", name="steel", location="US")])
        self.assertIsNone(find_by(c, o.Process, "steel", location="DE"))

    def test_ambiguous_lists_candidates(self):
        c = make_client([
            o.Ref(id="1", name="e", location="US", category="A"),
            o.Ref(id="2", name="e", location="US", category="B"),
        ])
        with self.assertRaises(ValueError) as ctx:
            find_by(c, o.Process, "e", location="US")
        msg = str(ctx.exception)
        self.assertIn("id=1", msg)
        self.assertIn("id=2", msg)
        self.assertIn("location=", msg)

    def test_find_all(self):
        c = make_client([
            o.Ref(id="1", name="e", location="US"),
            o.Ref(id="2", name="e", location="RER"),
            o.Ref(id="3", name="other"),
        ])
        self.assertEqual(2, len(find_all_by(c, o.Process, "e")))
        self.assertEqual(1, len(find_all_by(c, o.Process, "e", location="US")))

    def test_get_by_name_uses_id(self):
        c = make_client([o.Ref(id="p9", name="steel")])
        c.get = MagicMock(return_value=o.Process(id="p9", name="steel"))
        p = get_by_name(c, o.Process, "steel")
        c.get.assert_called_once_with(o.Process, uid="p9")
        self.assertEqual("p9", p.id)

    def test_get_by_name_missing(self):
        c = make_client([])
        c.get = MagicMock()
        self.assertIsNone(get_by_name(c, o.Process, "steel"))
        c.get.assert_not_called()


class TestUnitCache(unittest.TestCase):
    def test_find(self):
        u, g = UnitCache(make_client()).find("kg")
        self.assertEqual("kg", u.name)
        self.assertEqual("Units of mass", g.name)

    def test_flow_property(self):
        prop = UnitCache(make_client()).flow_property_of("kWh")
        self.assertEqual("Energy", prop.name)

    def test_not_found(self):
        cache = UnitCache(make_client())
        self.assertIsNone(cache.find("furlongs"))
        self.assertIsNone(cache.flow_property_of("furlongs"))

    def test_cache_reuse_and_invalidate(self):
        c = make_client()
        cache = UnitCache(c)
        cache.find("kg")
        cache.find("kWh")
        self.assertEqual(1, c.get_all.call_count)
        cache.invalidate()
        cache.find("kg")
        self.assertEqual(2, c.get_all.call_count)


class TestBatch(unittest.TestCase):
    def test_basic(self):
        r = calculate_batch(make_client(), make_setups(3))
        self.assertEqual((3, 0), (r.n_succeeded, r.n_failed))

    def test_error_skip(self):
        r = calculate_batch(make_client(fail_at=1), make_setups(3))
        self.assertEqual((2, 1), (r.n_succeeded, r.n_failed))
        self.assertIsNotNone(r.results[1].error)

    def test_error_raise(self):
        with self.assertRaises(RuntimeError):
            calculate_batch(make_client(fail_at=0), make_setups(3),
                            on_error="raise")

    def test_invalid_on_error(self):
        with self.assertRaises(ValueError):
            calculate_batch(make_client(), make_setups(1), on_error="bogus")

    def test_empty(self):
        self.assertEqual(0, calculate_batch(make_client(), []).n_succeeded)

    def test_dataframe(self):
        df = calculate_batch(make_client(), make_setups(3)).to_impacts_dataframe()
        self.assertEqual(3, len(df))
        self.assertIn("Climate change", df.columns)

    def test_inventory(self):
        r = calculate_batch(make_client(), make_setups(2), include_inventory=True)
        self.assertIn("output:Carbon dioxide", r.results[0].inventory)

    def test_progress_callback(self):
        seen = []
        calculate_batch(make_client(), make_setups(3),
                        progress_callback=lambda d, t, e: seen.append((d, t)))
        self.assertEqual([(1, 3), (2, 3), (3, 3)], seen)


if __name__ == "__main__":
    unittest.main()
