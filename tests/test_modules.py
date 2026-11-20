"""Tests for energy_bridge, carbon, inspector, compare, builders, extractors."""

import unittest

import pandas as pd
import olca_schema as o

from olca_contrib.energy_bridge import EnergyBridge, Operation, ManufacturingSystem
from olca_contrib.carbon import (
    CarbonCalculator, EGRID_FACTORS, REGION_TO_EGRID,
)
from olca_contrib.inspector import DatabaseInspector
from olca_contrib.compare import ComparisonEngine, ComparisonResult
from olca_contrib.extractors import ResultExtractor

from tests.mock_client import make_client, make_result


# --- Energy bridge ---

class TestOperation(unittest.TestCase):
    def test_power_kw(self):
        op = Operation(name="face", operation_id="x",
                       energy_kwh=0.5, duration_seconds=120)
        self.assertAlmostEqual(op.power_kw, 15.0)

    def test_zero_duration(self):
        op = Operation(name="x", operation_id="x", energy_kwh=0.5)
        self.assertEqual(op.power_kw, 0.0)

    def test_energy_mj(self):
        op = Operation(name="x", operation_id="x", energy_kwh=1.0)
        self.assertAlmostEqual(op.energy_mj, 3.6)


class TestManufacturingSystem(unittest.TestCase):
    def test_total_energy(self):
        sys = ManufacturingSystem(name="t", operations=[
            Operation(name="a", operation_id="1", energy_kwh=0.3),
            Operation(name="b", operation_id="2", energy_kwh=0.7),
        ])
        self.assertAlmostEqual(sys.total_energy_kwh, 1.0)


class TestEnergyBridge(unittest.TestCase):
    def test_register(self):
        b = EnergyBridge(make_client())
        op = b.register_operation("face", energy_kwh=0.347, duration_seconds=45)
        self.assertAlmostEqual(op.energy_kwh, 0.347)
        self.assertEqual(len(b.operations), 1)

    def test_register_generates_uuid(self):
        b = EnergyBridge(make_client())
        op = b.register_operation("face", energy_kwh=0.1)
        self.assertTrue(len(op.operation_id) > 10)

    def test_register_from_dataframe(self):
        b = EnergyBridge(make_client())
        df = pd.DataFrame({
            "operation_name": ["op1", "op2", "op3"],
            "uuid": ["a", "b", "c"],
            "energy_kwh": [0.1, 0.2, 0.3],
            "duration_s": [10, 20, 30],
        })
        b.register_from_dataframe(df)
        self.assertEqual(len(b.operations), 3)
        self.assertEqual(b.operations["op1"].operation_id, "a")

    def test_register_df_missing_optional_cols(self):
        b = EnergyBridge(make_client())
        df = pd.DataFrame({"operation_name": ["op1"], "energy_kwh": [0.5]})
        b.register_from_dataframe(df)
        self.assertEqual(b.operations["op1"].machine, "")

    def test_build_system(self):
        b = EnergyBridge(make_client())
        b.register_operation("a", energy_kwh=0.3)
        b.register_operation("b", energy_kwh=0.7)
        sys = b.build_system("test", operations=["a", "b"])
        self.assertAlmostEqual(sys.total_energy_kwh, 1.0)

    def test_build_system_all(self):
        b = EnergyBridge(make_client())
        b.register_operation("a", energy_kwh=0.3)
        b.register_operation("b", energy_kwh=0.7)
        self.assertEqual(len(b.build_system("test").operations), 2)

    def test_build_system_missing_op(self):
        b = EnergyBridge(make_client())
        b.register_operation("a", energy_kwh=0.3)
        with self.assertRaises(ValueError):
            b.build_system("test", operations=["a", "nope"])

    def test_operation_summary(self):
        b = EnergyBridge(make_client())
        b.register_operation("face", energy_kwh=0.347, duration_seconds=45,
                             machine="VMX30Ui", grid_region="MISO_INDY")
        df = b.operation_summary()
        self.assertEqual(df.iloc[0]["machine"], "VMX30Ui")

    def test_clear(self):
        b = EnergyBridge(make_client())
        b.register_operation("a", energy_kwh=0.3)
        b.clear()
        self.assertEqual(len(b.operations), 0)

    def test_duplicate_name_raises(self):
        b = EnergyBridge(make_client())
        b.register_operation("a", energy_kwh=0.3)
        with self.assertRaises(ValueError):
            b.register_operation("a", energy_kwh=0.4)
        self.assertAlmostEqual(b.operations["a"].energy_kwh, 0.3)
        b.register_operation("a", energy_kwh=0.4, replace=True)
        self.assertAlmostEqual(b.operations["a"].energy_kwh, 0.4)

    def test_repeated_rows_raise_by_default(self):
        b = EnergyBridge(make_client())
        df = pd.DataFrame({"operation_name": ["a", "a", "b"],
                           "energy_kwh": [0.1, 0.3, 0.5]})
        with self.assertRaises(ValueError):
            b.register_from_dataframe(df)
        self.assertEqual(len(b.operations), 0)   # nothing half-registered

    def test_repeated_runs_mean(self):
        path = "data/operations_repeated.csv"
        raw = pd.read_csv(path)
        b = EnergyBridge(make_client())
        b.register_from_csv(path, repeated="mean")
        self.assertEqual(len(b.operations), raw["operation_name"].nunique())
        face = raw[raw["operation_name"] == "CNC_Facing"]
        op = b.operations["CNC_Facing"]
        self.assertAlmostEqual(op.energy_kwh, face["energy_kwh"].mean())
        self.assertAlmostEqual(op.duration_seconds, face["duration_s"].mean())
        self.assertEqual(op.metadata["n_runs"], len(face))
        self.assertAlmostEqual(op.metadata["energy_kwh_std"],
                               face["energy_kwh"].std())
        self.assertEqual(op.metadata["run_ids"], face["uuid"].tolist())
        self.assertEqual(op.machine, "VMX30Ui")
        desc = b.process_builder(op)._description
        self.assertIn(f"Mean of {len(face)} runs", desc)
        self.assertIn("op-0000-run00", desc)

    def test_single_run_keeps_operation_id(self):
        b = EnergyBridge(make_client())
        b.register_from_csv("data/operations_single_run.csv", repeated="mean")
        op = next(iter(b.operations.values()))
        self.assertNotIn("n_runs", op.metadata)
        self.assertIn(f"Operation ID: {op.operation_id}",
                      b.process_builder(op)._description)









# --- Carbon ---

class TestCarbonCalculator(unittest.TestCase):
    def test_egrid(self):
        p = CarbonCalculator().from_egrid("op", 1.0, region="RFCW")
        self.assertAlmostEqual(p.emissions_kg_co2, EGRID_FACTORS["RFCW"])

    def test_custom_factor(self):
        p = CarbonCalculator().from_factor("op", 2.0, factor_kg_per_kwh=0.5)
        self.assertAlmostEqual(p.emissions_kg_co2, 1.0)

    def test_region_alias(self):
        self.assertEqual(CarbonCalculator().get_factor("MISO_INDY"),
                         EGRID_FACTORS["RFCW"])

    def test_unknown_region_falls_back(self):
        calc = CarbonCalculator(default_region="RFCW")
        p = calc.from_egrid("op", 1.0, region="ATLANTIS")
        self.assertAlmostEqual(p.emissions_kg_co2, EGRID_FACTORS["RFCW"])

    def test_custom_factors_override(self):
        calc = CarbonCalculator(custom_factors={"RFCW": 0.100})
        self.assertAlmostEqual(calc.get_factor("RFCW"), 0.100)

    def test_compare_regions_sorted(self):
        df = CarbonCalculator().compare_regions(
            1.0, regions=["NEWE", "ERCT", "CAMX"])
        self.assertEqual(len(df), 3)
        self.assertEqual(df.iloc[0]["region"], "NEWE")
        self.assertIn("relative_pct", df.columns)

    def test_compare_all_regions(self):
        df = CarbonCalculator().compare_regions(1.0)
        self.assertEqual(len(df), len(EGRID_FACTORS))

    def test_profile_operations(self):
        calc = CarbonCalculator()
        ops = {
            "a": Operation(name="a", operation_id="1",
                           energy_kwh=0.5, grid_region="RFCW"),
            "b": Operation(name="b", operation_id="2",
                           energy_kwh=0.3, grid_region="ERCT"),
        }
        profiles = calc.profile_operations(ops)
        self.assertEqual(len(profiles), 2)
        self.assertGreater(calc.total_emissions(profiles), 0)

    def test_to_dataframe(self):
        calc = CarbonCalculator()
        df = calc.to_dataframe([calc.from_egrid("op", 1.0)])
        self.assertIn("emissions_kg_co2", df.columns)

    def test_profile_zero_energy(self):
        p = CarbonCalculator().from_egrid("idle", 0.0)
        self.assertEqual(p.emissions_kg_co2, 0.0)

    def test_egrid_coverage(self):
        self.assertGreaterEqual(len(EGRID_FACTORS), 27)
        for r in ["RFCW", "ERCT", "CAMX", "NEWE", "NYUP"]:
            self.assertIn(r, EGRID_FACTORS)

    def test_aliases_valid(self):
        for alias, egrid in REGION_TO_EGRID.items():
            self.assertIn(egrid, EGRID_FACTORS,
                          f"{alias} maps to unknown region {egrid}")

    def test_factors_plausible(self):
        for region, val in EGRID_FACTORS.items():
            self.assertGreater(val, 0.0, region)
            self.assertLess(val, 1.5, region)


# --- Inspector ---

class TestDatabaseInspector(unittest.TestCase):
    def test_search(self):
        self.assertEqual(len(DatabaseInspector(make_client()).search("steel")), 2)

    def test_search_case_insensitive(self):
        self.assertEqual(len(DatabaseInspector(make_client()).search("STEEL")), 2)

    def test_search_no_match(self):
        self.assertEqual(len(DatabaseInspector(make_client()).search("zzz")), 0)

    def test_find_duplicates(self):
        dupes = DatabaseInspector(make_client()).find_duplicates()
        self.assertIn("steel production", dupes)
        self.assertEqual(len(dupes["steel production"]), 2)

    def test_no_duplicates(self):
        c = make_client([o.Ref(id="1", name="a"), o.Ref(id="2", name="b")])
        self.assertEqual(len(DatabaseInspector(c).find_duplicates()), 0)

    def test_duplicates_df(self):
        df = DatabaseInspector(make_client()).find_duplicates_df()
        self.assertEqual(len(df), 2)

    def test_summary(self):
        counts = DatabaseInspector(make_client()).summary()
        self.assertIn("Processes", counts)
        self.assertEqual(counts["Processes"], 3)

    def test_summary_df(self):
        df = DatabaseInspector(make_client()).summary_df()
        self.assertIn("entity_type", df.columns)

    def test_entity_inventory(self):
        self.assertEqual(len(DatabaseInspector(make_client()).entity_inventory()), 3)

    def test_search_df(self):
        df = DatabaseInspector(make_client()).search_df("electricity")
        self.assertEqual(len(df), 1)

    def test_electricity_flows(self):
        self.assertEqual(len(DatabaseInspector(make_client()).electricity_flows()), 1)


# --- Compare ---

class TestComparisonResult(unittest.TestCase):
    def test_difference(self):
        r = ComparisonResult(name="op", measured_value=0.35, default_value=0.50)
        self.assertAlmostEqual(r.absolute_difference, -0.15)
        self.assertAlmostEqual(r.relative_difference_pct, -30.0)
        self.assertAlmostEqual(r.ratio, 0.7)

    def test_zero_default(self):
        r = ComparisonResult(name="op", measured_value=0.5, default_value=0.0)
        self.assertEqual(r.relative_difference_pct, float("inf"))

    def test_both_zero(self):
        r = ComparisonResult(name="op", measured_value=0.0, default_value=0.0)
        self.assertEqual(r.relative_difference_pct, 0.0)
        self.assertEqual(r.ratio, 1.0)


class TestComparisonEngine(unittest.TestCase):
    def test_basic(self):
        e = ComparisonEngine()
        e.add_measured("face", 0.347)
        e.add_default("face", 0.500)
        r = e.compare("Test")
        self.assertEqual(len(r.operation_comparisons), 1)
        self.assertAlmostEqual(r.energy_measured_total, 0.347)

    def test_batch_add(self):
        e = ComparisonEngine()
        e.add_measured_batch({"a": 0.3, "b": 0.5})
        e.add_default_batch({"a": 0.4, "b": 0.6})
        r = e.compare()
        self.assertEqual(len(r.operation_comparisons), 2)
        self.assertAlmostEqual(r.energy_measured_total, 0.8)

    def test_material_share(self):
        e = ComparisonEngine()
        e.add_measured("a", 0.5)
        e.add_default("a", 0.5)
        e.set_material_gwp(12.5)
        e.set_emission_factor(0.489)
        r = e.compare()
        self.assertLess(r.measured_energy_share_pct, 5.0)
        self.assertGreater(r.measured_energy_share_pct, 0.0)

    def test_dataframe(self):
        e = ComparisonEngine()
        e.add_measured("a", 0.3)
        e.add_default("a", 0.5)
        df = e.compare().to_dataframe()
        self.assertIn("diff_pct", df.columns)
        self.assertAlmostEqual(df.iloc[0]["ratio"], 0.6)

    def test_summary_text(self):
        e = ComparisonEngine()
        e.add_measured("a", 0.347)
        e.add_default("a", 0.500)
        text = e.compare("Housing").summary()
        self.assertIn("Housing", text)
        self.assertIn("Measured", text)

    def test_from_dataframe(self):
        e = ComparisonEngine()
        e.from_dataframe(pd.DataFrame({
            "operation": ["face", "drill"],
            "measured_kwh": [0.347, 0.156],
            "default_kwh": [0.500, 0.250],
        }))
        self.assertEqual(len(e.compare().operation_comparisons), 2)

    def test_operation_only_in_one_side(self):
        e = ComparisonEngine()
        e.add_measured("only_measured", 0.3)
        e.add_default("only_default", 0.4)
        self.assertEqual(len(e.compare().operation_comparisons), 2)

    def test_variability_report(self):
        report = ComparisonEngine().variability_report({
            "face": [0.34, 0.36, 0.35, 0.33, 0.37],
            "drill": [0.15, 0.16, 0.14],
        })
        self.assertEqual(len(report), 2)
        self.assertIn("cv_pct", report.columns)
        for _, row in report.iterrows():
            self.assertGreater(row["cv_pct"], 0)
            self.assertLess(row["cv_pct"], 50)

    def test_variability_single_measurement(self):
        report = ComparisonEngine().variability_report({"a": [0.5]})
        self.assertEqual(report.iloc[0]["cv_pct"], 0.0)



# --- Extractors ---

class TestResultExtractor(unittest.TestCase):
    def test_impacts_df(self):
        df = ResultExtractor(make_result()).impacts_df()
        self.assertEqual(len(df), 2)
        self.assertIn("Climate change", df["category"].values)

    def test_impacts_dict(self):
        d = ResultExtractor(make_result()).impacts_dict()
        self.assertAlmostEqual(d["Climate change"], 1.23)

    def test_process_contributions(self):
        df = ResultExtractor(make_result()).process_contributions("Climate change")
        self.assertEqual(len(df), 2)
        self.assertIn("contribution_pct", df.columns)
        self.assertAlmostEqual(df["contribution_pct"].sum(), 100.0, places=4)

    def test_contributions_sorted(self):
        df = ResultExtractor(make_result()).process_contributions("Climate change")
        self.assertGreaterEqual(df.iloc[0]["contribution_pct"],
                                df.iloc[1]["contribution_pct"])

    def test_unknown_category(self):
        with self.assertRaises(ValueError):
            ResultExtractor(make_result()).process_contributions("Nope")

    def test_top_contributors(self):
        self.assertEqual(
            len(ResultExtractor(make_result()).top_contributors("Climate change", n=1)), 1)

    def test_inventory_df(self):
        self.assertEqual(len(ResultExtractor(make_result()).inventory_df()), 2)

    def test_inventory_inputs_only(self):
        df = ResultExtractor(make_result()).inventory_df(inputs_only=True)
        self.assertEqual(len(df), 1)
        self.assertTrue(df.iloc[0]["is_input"])

    def test_demand(self):
        d = ResultExtractor(make_result()).demand()
        self.assertEqual(d["process"], "assembly")

    def test_summary(self):
        text = ResultExtractor(make_result()).summary()
        self.assertIn("Climate change", text)

    def test_context_manager_disposes(self):
        result = make_result()
        with ResultExtractor(result) as ext:
            ext.impacts_df()
        result.dispose.assert_called_once()

    def test_from_setup(self):
        ext = ResultExtractor.from_setup(make_client(), o.CalculationSetup())
        self.assertEqual(len(ext.impacts_df()), 2)

    def test_from_setup_error(self):
        with self.assertRaises(RuntimeError):
            ResultExtractor.from_setup(make_client(fail_at=0), o.CalculationSetup())


if __name__ == "__main__":
    unittest.main()
