"""Fluent builder for openLCA processes.

Built on the olca-schema helpers (`new_process`, `new_input`, `new_output`,
`new_product`), so internal exchange IDs and `last_internal_id` are kept the
way openLCA expects.

Earlier versions of this module had two bugs that would have produced broken
processes: exchanges pointed at "new" flows that were never created, and the
location was set as a name-only reference without an ID. Both are fixed here.
New flows are created and inserted before the process, and locations are
resolved to an existing location by code or name.
"""

import logging
from typing import Self

import olca_schema as o

from .patches import UnitCache, find_by

log = logging.getLogger(__name__)


class ProcessBuilder:
    """Build a process step by step, then insert it with its new flows.

    Example:
        ref = (ProcessBuilder(client, "CNC facing")
            .location("US")
            .category("Manufacturing/CNC")
            .output_new("faced part", 1.0, "Item(s)", is_reference=True)
            .input_from_db("electricity, medium voltage", 0.347, "kWh")
            .build_and_insert())
    """

    def __init__(self, client, name: str):
        self._client = client
        self._name = name
        self._location: str | None = None
        self._category: str | None = None
        self._description: str | None = None
        self._tags: list[str] = []
        self._steps: list[dict] = []
        self._units: UnitCache | None = None
        self._locations: list[o.Location] | None = None
        self._props: dict[str, o.FlowProperty | None] = {}
        self.new_flows: list[o.Flow] = []

    # --- metadata ---

    def location(self, code_or_name: str) -> Self:
        self._location = code_or_name
        return self

    def category(self, path: str) -> Self:
        self._category = path
        return self

    def description(self, text: str) -> Self:
        self._description = text
        return self

    def tag(self, tag: str) -> Self:
        self._tags.append(tag)
        return self

    # --- exchanges ---

    def output_new(
        self, flow_name: str, amount: float, unit: str, *, is_reference=False
    ) -> Self:
        """An output of a new product flow, created on insert."""
        self._steps.append(dict(kind="new", is_input=False, name=flow_name,
                                amount=amount, unit=unit, ref=is_reference))
        return self

    def input_new(self, flow_name: str, amount: float, unit: str) -> Self:
        """An input of a new product flow, created on insert."""
        self._steps.append(dict(kind="new", is_input=True, name=flow_name,
                                amount=amount, unit=unit, ref=False))
        return self

    def input_from_db(
        self,
        flow_name: str,
        amount: float,
        unit: str | None = None,
        *,
        provider: str = "auto",
        provider_location: str | None = None,
    ) -> Self:
        """An input of a flow that already exists in the database.

        provider="auto" links the first provider of the flow, or the one at
        `provider_location` if given; "none" links nothing; anything else is
        taken as the ID of the provider process.
        """
        self._steps.append(dict(kind="db", is_input=True, name=flow_name,
                                amount=amount, unit=unit, ref=False,
                                provider=provider,
                                provider_location=provider_location))
        return self

    def output_from_db(
        self, flow_name: str, amount: float, unit: str | None = None,
        *, is_reference=False,
    ) -> Self:
        """An output of a flow that already exists in the database."""
        self._steps.append(dict(kind="db", is_input=False, name=flow_name,
                                amount=amount, unit=unit, ref=is_reference,
                                provider="none", provider_location=None))
        return self

    # --- build ---

    def build(self) -> o.Process:
        """Build the process (and the new flows in `new_flows`) without
        inserting anything."""
        self.new_flows = []
        process = o.new_process(self._name)
        if self._category:
            process.category = self._category
        if self._description:
            process.description = self._description
        if self._tags:
            process.tags = list(self._tags)
        if self._location:
            process.location = self._resolve_location(self._location)

        for step in self._steps:
            flow_ref, unit_ref, prop_ref = self._flow_and_unit(step)
            add = o.new_input if step["is_input"] else o.new_output
            exchange = add(process, flow_ref, step["amount"], unit_ref)
            if prop_ref is not None:
                exchange.flow_property = prop_ref
            if step["ref"]:
                exchange.is_quantitative_reference = True
            if step["kind"] == "db" and step["is_input"]:
                exchange.default_provider = self._provider(step, flow_ref)

        if not any(e.is_quantitative_reference for e in process.exchanges or []):
            log.warning("process %r has no quantitative reference", self._name)
        return process

    def build_and_insert(self) -> o.Ref | None:
        """Insert the new flows, then the process. Returns the process ref."""
        process = self.build()
        for flow in self.new_flows:
            if self._client.put(flow) is None:
                raise RuntimeError(f"failed to insert flow {flow.name!r}")
        return self._client.put(process)

    # --- helpers ---

    def _unit_cache(self) -> UnitCache:
        if self._units is None:
            self._units = UnitCache(self._client)
        return self._units

    def _flow_and_unit(self, step) -> tuple[o.Ref, o.Ref | None, o.Ref | None]:
        unit_ref = None
        if step["unit"]:
            unit = self._unit_cache().find_unit(step["unit"])
            if unit is None:
                raise ValueError(f"unit {step['unit']!r} not found")
            unit_ref = o.as_ref(unit)

        if step["kind"] == "db":
            ref = find_by(self._client, o.Flow, step["name"])
            if ref is None:
                raise ValueError(
                    f"flow {step['name']!r} not found; use input_new or "
                    "output_new to create a new flow")
            if not step["unit"]:
                return ref, None, None  # the reference unit of the flow
            return ref, unit_ref, self._flow_property_of(ref, step["unit"])

        prop = self._unit_cache().flow_property_of(step["unit"])
        if prop is None:
            raise ValueError(f"no flow property for unit {step['unit']!r}")
        flow = o.new_product(step["name"], prop)
        self.new_flows.append(flow)
        return o.as_ref(flow), unit_ref, None  # prop is the reference

    def _flow_property_of(self, flow_ref: o.Ref, unit_name: str) -> o.Ref:
        """The flow property of an existing flow that the unit belongs to.

        An exchange without a flow property is read in the reference flow
        property, so a unit from another unit group would not convert.
        """
        group = self._unit_cache().find_group(unit_name)
        flow = self._client.get(o.Flow, uid=flow_ref.id)
        if group is None or flow is None:
            raise ValueError(f"could not load flow {flow_ref.name!r}")
        factors = sorted(flow.flow_properties or [],
                         key=lambda f: not f.is_ref_flow_property)
        names = []
        for f in factors:
            if f.flow_property is None or f.flow_property.id is None:
                continue
            pid = f.flow_property.id
            if pid not in self._props:
                self._props[pid] = self._client.get(o.FlowProperty, uid=pid)
            prop = self._props[pid]
            if prop is None:
                continue
            names.append(prop.name or pid)
            if prop.unit_group is not None and prop.unit_group.id == group.id:
                return f.flow_property
        raise ValueError(
            f"unit {unit_name!r} does not fit flow {flow_ref.name!r}; "
            f"its flow properties are: {', '.join(names) or 'none'}")

    def _provider(self, step, flow_ref: o.Ref) -> o.Ref | None:
        spec = step["provider"]
        if spec == "none":
            return None
        if spec != "auto":
            return o.Ref(ref_type=o.RefType.Process, id=spec)
        providers = [tf.provider for tf in self._client.get_providers(flow_ref)
                     if tf.provider is not None]
        if step["provider_location"]:
            providers = [p for p in providers
                         if p.location == step["provider_location"]]
        if not providers:
            log.info("no provider for %r", step["name"])
            return None
        return providers[0]

    def _resolve_location(self, code_or_name: str) -> o.Ref:
        if self._locations is None:
            self._locations = self._client.get_all(o.Location)
        for loc in self._locations:
            if code_or_name in (loc.code, loc.name):
                return o.as_ref(loc)
        raise ValueError(f"location {code_or_name!r} not found in database")
