"""Shared mock IPC client used across the test suite.

Lets every test run without a live openLCA server. The mock implements
the subset of the client surface that olca-contrib actually touches.
"""

from unittest.mock import MagicMock

import olca_schema as o


def make_unit_groups() -> list[o.UnitGroup]:
    mass = o.UnitGroup(id="ug-mass", name="Units of mass")
    mass.units = [
        o.Unit(id="u-kg", name="kg", conversion_factor=1.0),
        o.Unit(id="u-g", name="g", conversion_factor=0.001),
        o.Unit(id="u-t", name="t", conversion_factor=1000.0),
    ]
    mass.default_flow_property = o.Ref(id="fp-mass", name="Mass")

    energy = o.UnitGroup(id="ug-energy", name="Units of energy")
    energy.units = [
        o.Unit(id="u-kwh", name="kWh", conversion_factor=1.0),
        o.Unit(id="u-mj", name="MJ", conversion_factor=3.6),
    ]
    energy.default_flow_property = o.Ref(id="fp-energy", name="Energy")

    items = o.UnitGroup(id="ug-items", name="Units of items")
    items.units = [o.Unit(id="u-item", name="Item(s)", conversion_factor=1.0)]
    items.default_flow_property = o.Ref(id="fp-items", name="Number of items")

    return [mass, energy, items]


def make_result(error: str | None = None, impacts: list | None = None):
    """Build a mock calculation/simulation Result."""
    result = MagicMock()
    state = o.ResultState(id="result-1", error=error)
    result.get_state.return_value = state
    result.wait_until_ready.return_value = state
    result.simulate_next.return_value = state

    if impacts is None:
        impacts = [
            o.ImpactValue(amount=1.23, impact_category=o.Ref(
                name="Climate change", id="ic-gwp", ref_unit="kg CO2-eq")),
            o.ImpactValue(amount=0.045, impact_category=o.Ref(
                name="Acidification", id="ic-ap", ref_unit="kg SO2-eq")),
        ]
    result.get_total_impacts.return_value = impacts
    result.get_impact_categories.return_value = [
        iv.impact_category for iv in impacts if iv.impact_category]
    result.get_total_flows.return_value = [
        o.EnviFlowValue(amount=1.5, envi_flow=o.EnviFlow(
            flow=o.Ref(name="Carbon dioxide", ref_unit="kg"), is_input=False)),
        o.EnviFlowValue(amount=0.3, envi_flow=o.EnviFlow(
            flow=o.Ref(name="Water", ref_unit="m3"), is_input=True)),
    ]
    result.get_impact_contributions_of.return_value = [
        o.TechFlowValue(amount=0.9, tech_flow=o.TechFlow(
            provider=o.Ref(name="electricity production", location="US"),
            flow=o.Ref(name="electricity"))),
        o.TechFlowValue(amount=0.33, tech_flow=o.TechFlow(
            provider=o.Ref(name="aluminium production", location="RER"),
            flow=o.Ref(name="aluminium"))),
    ]
    result.get_demand.return_value = o.TechFlowValue(
        amount=1.0, tech_flow=o.TechFlow(
            provider=o.Ref(name="assembly"), flow=o.Ref(name="product")))
    result.dispose.return_value = None
    return result


def make_client(descriptors: list[o.Ref] | None = None,
                fail_at: int | None = None):
    """Build a mock IPC client.

    Args:
        descriptors: what get_descriptors returns for every type
        fail_at: index of the calculate() call that should return an error
    """
    client = MagicMock()

    if descriptors is None:
        descriptors = [
            o.Ref(id="p1", name="steel production", location="US",
                  category="Metals"),
            o.Ref(id="p2", name="steel production", location="RER",
                  category="Metals"),
            o.Ref(id="p3", name="electricity, medium voltage", location="US",
                  category="Energy"),
        ]
    client.get_descriptors.return_value = descriptors
    client.get_all.return_value = make_unit_groups()

    def _find(model_type, name, **kwargs):
        for d in descriptors:
            if d.name == name:
                return d
        if model_type is o.ImpactMethod:
            return o.Ref(id="method-1", name=name)
        return None

    client.find.side_effect = _find
    client.get_providers.return_value = []
    client.put.side_effect = lambda entity: o.Ref(
        id=getattr(entity, "id", "new-id"), name=getattr(entity, "name", ""))

    counter = [0]

    def _calculate(_setup):
        i = counter[0]
        counter[0] += 1
        return make_result(error="Calculation failed" if fail_at == i else None)

    client.calculate.side_effect = _calculate
    client.simulate.side_effect = lambda _setup: make_result()
    return client


def make_setups(n: int = 3) -> list[o.CalculationSetup]:
    return [
        o.CalculationSetup(
            target=o.Ref(ref_type=o.RefType.ProductSystem, id=f"ps-{i}"),
            impact_method=o.Ref(id="method-1"),
        )
        for i in range(n)
    ]
