"""Database inspection and diagnostic tools."""

import logging
from typing import Any

import olca_schema as o

log = logging.getLogger(__name__)


class DatabaseInspector:
    """Inspect and diagnose an openLCA database via IPC.

    Usage:
        inspector = DatabaseInspector(client)
        inspector.summary()
        inspector.search("electricity", o.Flow)
        inspector.find_duplicates()
    """

    def __init__(self, client):
        self._client = client

    def _count(self, model_type) -> int:
        return len(self._client.get_descriptors(model_type))

    def summary(self) -> dict[str, int]:
        types = {
            "Processes": o.Process,
            "Flows": o.Flow,
            "Product Systems": o.ProductSystem,
            "Impact Methods": o.ImpactMethod,
            "Impact Categories": o.ImpactCategory,
            "Flow Properties": o.FlowProperty,
            "Unit Groups": o.UnitGroup,
            "Sources": o.Source,
            "Actors": o.Actor,
            "Locations": o.Location,
            "Parameters": o.Parameter,
            "Projects": o.Project,
        }
        counts = {}
        for name, mtype in types.items():
            try:
                counts[name] = self._count(mtype)
            except Exception:
                counts[name] = -1
        return counts

    def summary_df(self):
        import pandas as pd
        counts = self.summary()
        df = pd.DataFrame([{"entity_type": k, "count": v} for k, v in counts.items()])
        return df.sort_values("count", ascending=False).reset_index(drop=True)

    def impact_methods(self) -> list[o.Ref]:
        return self._client.get_descriptors(o.ImpactMethod)

    def impact_methods_df(self):
        import pandas as pd
        return pd.DataFrame([{"name": m.name, "id": m.id, "category": m.category}
                             for m in self.impact_methods()])

    def impact_categories_for(self, method_name: str) -> list[o.Ref]:
        method_ref = self._client.find(o.ImpactMethod, method_name)
        if method_ref is None:
            raise ValueError(f"Method '{method_name}' not found")
        method = self._client.get(o.ImpactMethod, method_ref.id)
        if method and method.impact_categories:
            return method.impact_categories
        return []

    def inspect_process(self, name: str, location: str | None = None) -> dict[str, Any]:
        from .patches import find_by
        ref = find_by(self._client, o.Process, name, location=location)
        if ref is None:
            raise ValueError(f"Process '{name}' not found")

        process = self._client.get(o.Process, ref.id)
        if process is None:
            raise ValueError(f"Could not fetch process {ref.id}")

        info = {
            "name": process.name,
            "id": process.id,
            "location": ref.location,
            "category": process.category,
            "process_type": str(process.process_type) if process.process_type else None,
            "description": process.description,
            "exchanges": [],
        }
        for ex in (process.exchanges or []):
            info["exchanges"].append({
                "flow": ex.flow.name if ex.flow else "unknown",
                "amount": ex.amount,
                "unit": ex.unit.name if ex.unit else None,
                "is_input": ex.is_input,
                "is_reference": ex.is_quantitative_reference,
                "provider": ex.default_provider.name if ex.default_provider else None,
            })
        return info

    def inspect_process_df(self, name: str, location: str | None = None):
        import pandas as pd
        return pd.DataFrame(self.inspect_process(name, location)["exchanges"])

    def find_duplicates(self, model_type=o.Process) -> dict[str, list[o.Ref]]:
        """Find entities sharing the same name."""
        groups: dict[str, list[o.Ref]] = {}
        for d in self._client.get_descriptors(model_type):
            if d.name:
                groups.setdefault(d.name, []).append(d)
        return {name: refs for name, refs in groups.items() if len(refs) > 1}

    def find_duplicates_df(self, model_type=o.Process):
        import pandas as pd
        rows = []
        for name, refs in self.find_duplicates(model_type).items():
            for ref in refs:
                rows.append({"name": name, "id": ref.id, "location": ref.location,
                             "category": ref.category, "library": ref.library})
        df = pd.DataFrame(rows)
        if not df.empty:
            df = df.sort_values(["name", "location"]).reset_index(drop=True)
        return df

    def entity_inventory(self, model_type=o.Process):
        import pandas as pd
        return pd.DataFrame([{
            "name": d.name, "id": d.id, "location": d.location,
            "category": d.category, "library": d.library,
        } for d in self._client.get_descriptors(model_type)])

    def search(self, query: str, model_type=o.Process) -> list[o.Ref]:
        """Case-insensitive substring search across entity names."""
        q = query.lower()
        return [d for d in self._client.get_descriptors(model_type)
                if d.name and q in d.name.lower()]

    def search_df(self, query: str, model_type=o.Process):
        import pandas as pd
        return pd.DataFrame([{
            "name": d.name, "id": d.id,
            "location": d.location, "category": d.category,
        } for d in self.search(query, model_type)])

    def electricity_flows(self) -> list[o.Ref]:
        return self.search("electricity", o.Flow)

    def validate_product_system(self, name: str) -> dict[str, Any]:
        ref = self._client.find(o.ProductSystem, name)
        if ref is None:
            return {"valid": False, "error": f"Product system '{name}' not found"}

        ps = self._client.get(o.ProductSystem, ref.id)
        if ps is None:
            return {"valid": False, "error": "Could not fetch product system"}

        issues = []
        if ps.ref_process is None:
            issues.append("No reference process defined")
        if ps.ref_exchange is None:
            issues.append("No reference exchange defined")

        return {
            "valid": len(issues) == 0,
            "name": ps.name,
            "id": ps.id,
            "ref_process": ps.ref_process.name if ps.ref_process else None,
            "issues": issues,
        }
