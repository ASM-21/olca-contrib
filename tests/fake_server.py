"""An in-memory stand-in for the openLCA JSON-RPC server.

Tests patch `olca_ipc.ipc.Client.rpc_call` with `FakeServer.rpc`, so the real
olca-ipc client classes run end to end: request building, `from_dict`
parsing, `wait_until_ready`, `dispose`. Payloads are built with olca-schema's
own `to_dict()`, so their shape matches what the real server sends.

The server tracks live results. A test can check `server.live` to prove that
nothing was left undisposed, which is the property that matters for the
Monte Carlo leak.
"""

import itertools
from contextlib import contextmanager
from unittest import mock

import olca_schema as o


def _ref(type_name: str, uid: str, name: str, **kw) -> dict:
    d = {"@type": type_name, "@id": uid, "name": name}
    d.update(kw)
    return d


class FakeServer:
    def __init__(self):
        self.calls: list[tuple[str, object]] = []
        self.live: set[str] = set()
        self.disposed: list[str] = []
        self.created_systems: list[str] = []
        self.deleted: list[str] = []
        self.put_entities: list[dict] = []
        self._ids = itertools.count(1)
        self._draws = itertools.count(1)
        self.fail_next_calc = False

        mass = o.UnitGroup(id="ug-mass", name="Units of mass")
        mass.units = [o.Unit(id="u-kg", name="kg", is_ref_unit=True,
                             conversion_factor=1.0)]
        mass.default_flow_property = o.Ref(
            ref_type=o.RefType.FlowProperty, id="fp-mass", name="Mass")
        energy = o.UnitGroup(id="ug-energy", name="Units of energy")
        energy.units = [
            o.Unit(id="u-mj", name="MJ", is_ref_unit=True, conversion_factor=1.0),
            o.Unit(id="u-kwh", name="kWh", conversion_factor=3.6),
        ]
        energy.default_flow_property = o.Ref(
            ref_type=o.RefType.FlowProperty, id="fp-energy", name="Energy")
        items = o.UnitGroup(id="ug-items", name="Units of items")
        items.units = [o.Unit(id="u-item", name="Item(s)", is_ref_unit=True,
                              conversion_factor=1.0)]
        items.default_flow_property = o.Ref(
            ref_type=o.RefType.FlowProperty, id="fp-items",
            name="Number of items")
        self.unit_groups = [g.to_dict() for g in (mass, energy, items)]

        # full flows and flow properties, served by data/get; a flow can
        # have several properties, e.g. steel in kg (reference) and items
        def prop(uid, name, group):
            return o.FlowProperty(id=uid, name=name, unit_group=o.Ref(
                ref_type=o.RefType.UnitGroup, id=group.id, name=group.name))

        def factor(p, cf=1.0, is_ref=False):
            return o.FlowPropertyFactor(
                flow_property=o.as_ref(p), conversion_factor=cf,
                is_ref_flow_property=is_ref)

        fp_mass = prop("fp-mass", "Mass", mass)
        fp_energy = prop("fp-energy", "Energy", energy)
        fp_items = prop("fp-items", "Number of items", items)
        self.full = {p.id: p.to_dict() for p in (fp_mass, fp_energy, fp_items)}
        for f in (
            o.Flow(id="f-elec", name="electricity, medium voltage",
                   flow_type=o.FlowType.PRODUCT_FLOW,
                   flow_properties=[factor(fp_energy, is_ref=True)]),
            o.Flow(id="f-steel", name="steel",
                   flow_type=o.FlowType.PRODUCT_FLOW,
                   flow_properties=[factor(fp_mass, is_ref=True),
                                    factor(fp_items, cf=0.5)]),
        ):
            self.full[f.id] = f.to_dict()

        self.locations = [
            o.Location(id="loc-us", name="United States", code="US").to_dict(),
            o.Location(id="loc-de", name="Germany", code="DE").to_dict(),
        ]

        self.descriptors: dict[str, list[dict]] = {
            "Flow": [
                _ref("Flow", "f-elec", "electricity, medium voltage"),
                _ref("Flow", "f-steel", "steel"),
            ],
            "Process": [
                _ref("Process", "p-wind-rer", "wind power", location="RER"),
                _ref("Process", "p-wind-us", "wind power", location="US"),
                _ref("Process", "p-hash", "#2 fuel oil burner"),
            ],
            "ImpactMethod": [_ref("ImpactMethod", "m-1", "Test method")],
            "UnitGroup": [_ref("UnitGroup", g["@id"], g["name"])
                          for g in self.unit_groups],
            "Location": [_ref("Location", d["@id"], d["name"])
                         for d in self.locations],
        }
        self.providers = {
            "f-elec": [
                {"provider": _ref("Process", "p-mkt-rfc",
                                  "market for electricity", location="US-RFC"),
                 "flow": _ref("Flow", "f-elec", "electricity, medium voltage")},
                {"provider": _ref("Process", "p-mkt-wecc",
                                  "market for electricity", location="US-WECC"),
                 "flow": _ref("Flow", "f-elec", "electricity, medium voltage")},
            ]
        }

    # --- JSON-RPC dispatch, signature of Client.rpc_call(method, params) ---

    def rpc(self, method: str, params=None):
        self.calls.append((method, params))
        handler = getattr(self, "_" + method.replace("/", "_").replace("-", "_"),
                          None)
        if handler is None:
            return None, f"-32601: Does not understand: {method}"
        return handler(params or {})

    def methods(self) -> list[str]:
        return [m for m, _ in self.calls]

    # --- data ---

    def _data_get_descriptors(self, p):
        return self.descriptors.get(p.get("@type"), []), None

    def _data_get_all(self, p):
        t = p.get("@type")
        if t == "UnitGroup":
            return self.unit_groups, None
        if t == "Location":
            return self.locations, None
        return [], None

    def _data_get(self, p):
        # a full entity, not a descriptor: there `location` is a reference
        # object, while in a descriptor it is just the location code
        t, uid = p.get("@type"), p.get("@id")
        if uid in self.full and self.full[uid]["@type"] == t:
            return self.full[uid], None
        for d in self.descriptors.get(t, []):
            if d["@id"] == uid:
                entity = {k: v for k, v in d.items() if k != "location"}
                if "location" in d:
                    entity["location"] = _ref("Location", f"loc-{d['location']}",
                                              d["location"])
                return entity, None
        return None, "-32000: not found"

    def _data_get_providers(self, p):
        return self.providers.get(p.get("@id"), []), None

    def _data_put(self, p):
        self.put_entities.append(p)
        return _ref(p.get("@type"), p.get("@id"), p.get("name", "")), None

    def _data_create_system(self, p):
        uid = f"ps-{next(self._ids)}"
        self.created_systems.append(uid)
        return _ref("ProductSystem", uid, "system"), None

    def _data_delete(self, p):
        self.deleted.append(p.get("@id"))
        return dict(p), None

    # --- results ---

    def _new_result(self):
        if self.fail_next_calc:
            self.fail_next_calc = False
            return None, "-32000: calculation failed"
        uid = f"r-{next(self._ids)}"
        self.live.add(uid)
        return {"@id": uid, "isReady": False, "isScheduled": True}, None

    def _result_calculate(self, p):
        return self._new_result()

    def _result_simulate(self, p):
        return self._new_result()

    def _result_simulate_next(self, p):
        return {"@id": p["@id"], "isReady": False, "isScheduled": True}, None

    def _result_state(self, p):
        uid = p.get("@id")
        if uid not in self.live:
            return None, f"-32000: no result with id {uid}"
        return {"@id": uid, "isReady": True, "isScheduled": False}, None

    def _result_total_impacts(self, p):
        n = next(self._draws)
        gwp = 1.0 + 0.01 * (n % 7)
        return [
            {"impactCategory": _ref("ImpactCategory", "ic-gwp",
                                    "Climate change", refUnit="kg CO2-eq"),
             "amount": gwp},
            {"impactCategory": _ref("ImpactCategory", "ic-ap",
                                    "Acidification", refUnit="kg SO2-eq"),
             "amount": gwp / 30},
        ], None

    def _result_dispose(self, p):
        uid = p.get("@id")
        self.live.discard(uid)
        self.disposed.append(uid)
        return {"@id": uid}, None


@contextmanager
def ipc_client(server: FakeServer | None = None):
    """A real olca_ipc.Client whose transport is the fake server."""
    from olca_ipc.ipc import Client

    server = server or FakeServer()
    with mock.patch.object(Client, "rpc_call", side_effect=server.rpc):
        yield Client(), server
