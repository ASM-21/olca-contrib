"""
Lookup helpers that work around gaps in the olca-ipc client.

find_by / find_all_by
    `find()` and `get(name=...)` return the first entity with a name. That is
    documented behavior, but ecoinvent has many processes that share a name
    and differ only by location, so you need a way to pick one.

get_by_name
    Resolves the name through the descriptors and then fetches by ID. On the
    RestClient of olca-ipc <= 2.7.0, a name with `#` or `?` is cut off in the
    request path and `get_descriptor(name=...)` hits a route that does not
    exist (fixed upstream in a pending pull request). Going through the ID
    avoids both and works the same on the JSON-RPC and REST clients.

UnitCache
    Units live inside unit groups and have no `get`/`find` of their own
    (GreenDelta/olca-ipc.py#4, still open).

Note: earlier versions of this module patched `last_change` timestamps. That
bug (`+00:00Z` rejected by the Java parser) was fixed in olca-schema 2.2.2,
and this package requires a newer version, so the patch was removed.
"""

import logging
from typing import TypeVar

import olca_schema as o

log = logging.getLogger(__name__)
E = TypeVar("E", bound=o.RootEntity)


def find_all_by(
    client,
    model_type: type[E],
    name: str,
    *,
    location: str | None = None,
    category: str | None = None,
) -> list[o.Ref]:
    """Return every descriptor with the name, optionally filtered.

    `location` matches the location code exactly (e.g. "US", "RER", "RoW").
    `category` matches if it is a substring of the category path.
    """
    matches = [d for d in client.get_descriptors(model_type) if d.name == name]
    if location is not None:
        matches = [d for d in matches if d.location == location]
    if category is not None:
        matches = [d for d in matches if d.category and category in d.category]
    return matches


def find_by(
    client,
    model_type: type[E],
    name: str,
    *,
    location: str | None = None,
    category: str | None = None,
) -> o.Ref | None:
    """Return the one descriptor with the name, or None if there is none.

    Raises ValueError if several remain after filtering, listing them so the
    caller can add `location=` or `category=`. This is stricter than the
    client's `find()`, which silently returns the first match.
    """
    matches = find_all_by(
        client, model_type, name, location=location, category=category
    )
    if not matches:
        return None
    if len(matches) == 1:
        return matches[0]
    shown = "\n".join(
        f"  - id={d.id}, location={d.location}, category={d.category}"
        for d in matches[:10]
    )
    more = f"\n  ... and {len(matches) - 10} more" if len(matches) > 10 else ""
    raise ValueError(
        f"{len(matches)} {model_type.__name__} entities named {name!r}"
        f"{f' at location {location!r}' if location else ''}"
        f"{f' in category {category!r}' if category else ''}:\n"
        f"{shown}{more}\n"
        "Pass location= or category= to pick one."
    )


def get_by_name(
    client,
    model_type: type[E],
    name: str,
    *,
    location: str | None = None,
    category: str | None = None,
) -> E | None:
    """Fetch the full entity with the name, resolved through its ID."""
    ref = find_by(client, model_type, name, location=location, category=category)
    if ref is None:
        return None
    return client.get(model_type, uid=ref.id)


class UnitCache:
    """Look up units by name across all unit groups.

    Fetches the unit groups once and indexes every unit by name. Call
    `invalidate()` after changing unit groups in the database.
    """

    def __init__(self, client):
        self._client = client
        self._cache: dict[str, tuple[o.Unit, o.UnitGroup]] | None = None

    def _ensure_loaded(self) -> dict[str, tuple[o.Unit, o.UnitGroup]]:
        if self._cache is None:
            cache: dict[str, tuple[o.Unit, o.UnitGroup]] = {}
            for group in self._client.get_all(o.UnitGroup):
                for unit in group.units or []:
                    if unit.name and unit.name not in cache:
                        cache[unit.name] = (unit, group)
            self._cache = cache
        return self._cache

    def find(self, unit_name: str) -> tuple[o.Unit, o.UnitGroup] | None:
        return self._ensure_loaded().get(unit_name)

    def find_unit(self, unit_name: str) -> o.Unit | None:
        hit = self.find(unit_name)
        return hit[0] if hit else None

    def find_group(self, unit_name: str) -> o.UnitGroup | None:
        hit = self.find(unit_name)
        return hit[1] if hit else None

    def flow_property_of(self, unit_name: str) -> o.Ref | None:
        """The default flow property of the unit's group, e.g. Mass for kg."""
        group = self.find_group(unit_name)
        return group.default_flow_property if group else None

    def all_units(self) -> dict[str, tuple[o.Unit, o.UnitGroup]]:
        return dict(self._ensure_loaded())

    def invalidate(self):
        self._cache = None
