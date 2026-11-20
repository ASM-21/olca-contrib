"""Result-to-DataFrame extraction helpers."""

import logging
from typing import Any

import olca_schema as o

log = logging.getLogger(__name__)


class ResultExtractor:
    """Wraps an IPC Result with DataFrame-returning convenience methods.

    Usage as a context manager (auto-disposes):
        with ResultExtractor.from_setup(client, setup) as ext:
            df = ext.impacts_df()
            contrib = ext.process_contributions("Climate change")
    """

    def __init__(self, result):
        self._result = result
        self._impact_cats: list[o.Ref] | None = None

    @classmethod
    def from_setup(cls, client, setup: o.CalculationSetup) -> "ResultExtractor":
        result = client.calculate(setup)
        state = result.wait_until_ready()
        if state.error:
            raise RuntimeError(f"Calculation failed: {state.error}")
        return cls(result)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.dispose()
        return False

    def dispose(self):
        try:
            self._result.dispose()
        except Exception as e:
            log.debug("Dispose failed: %s", e)

    @property
    def result(self):
        return self._result

    def _get_impact_cats(self) -> list[o.Ref]:
        if self._impact_cats is None:
            self._impact_cats = self._result.get_impact_categories()
        return self._impact_cats

    def impacts_df(self):
        import pandas as pd
        rows = []
        for iv in self._result.get_total_impacts():
            cat = iv.impact_category
            rows.append({
                "category": cat.name if cat else "unknown",
                "category_id": cat.id if cat else None,
                "value": iv.amount if iv.amount is not None else 0.0,
                "ref_unit": cat.ref_unit if cat else None,
            })
        return pd.DataFrame(rows)

    def impacts_dict(self) -> dict[str, float]:
        return {(iv.impact_category.name if iv.impact_category else "unknown"):
                (iv.amount if iv.amount is not None else 0.0)
                for iv in self._result.get_total_impacts()}

    def process_contributions(self, impact_name: str):
        import pandas as pd
        cat_ref = None
        for cat in self._get_impact_cats():
            if cat.name == impact_name:
                cat_ref = cat
                break
        if cat_ref is None:
            available = [c.name for c in self._get_impact_cats()]
            raise ValueError(f"'{impact_name}' not found. Available: {available}")

        contribs = self._result.get_impact_contributions_of(cat_ref)
        total = sum(abs(c.amount) for c in contribs if c.amount is not None)
        rows = []
        for c in contribs:
            prov = c.tech_flow.provider if c.tech_flow else None
            amt = c.amount if c.amount is not None else 0.0
            rows.append({
                "process": prov.name if prov else "unknown",
                "process_id": prov.id if prov else None,
                "location": prov.location if prov else None,
                "value": amt,
                "contribution_pct": abs(amt) / total * 100 if total > 0 else 0.0,
            })
        df = pd.DataFrame(rows)
        if not df.empty:
            df = df.sort_values("contribution_pct", ascending=False).reset_index(drop=True)
        return df

    def top_contributors(self, impact_name: str, n: int = 10):
        return self.process_contributions(impact_name).head(n)

    def inventory_df(self, inputs_only: bool = False, outputs_only: bool = False):
        import pandas as pd
        rows = []
        for fv in self._result.get_total_flows():
            ef = fv.envi_flow
            if ef is None:
                continue
            is_in = ef.is_input if ef.is_input is not None else False
            if inputs_only and not is_in:
                continue
            if outputs_only and is_in:
                continue
            fr = ef.flow
            rows.append({
                "flow": fr.name if fr else "unknown",
                "flow_id": fr.id if fr else None,
                "category": fr.category if fr else None,
                "is_input": is_in,
                "value": fv.amount if fv.amount is not None else 0.0,
                "unit": fr.ref_unit if fr else None,
            })
        df = pd.DataFrame(rows)
        if not df.empty:
            df = df.sort_values("value", key=abs, ascending=False).reset_index(drop=True)
        return df

    def demand(self) -> dict[str, Any] | None:
        d = self._result.get_demand()
        if d is None:
            return None
        return {
            "amount": d.amount,
            "process": d.tech_flow.provider.name if d.tech_flow and d.tech_flow.provider else None,
            "flow": d.tech_flow.flow.name if d.tech_flow and d.tech_flow.flow else None,
        }

    def summary(self) -> str:
        lines = []
        d = self.demand()
        if d:
            lines.append(f"Demand: {d['amount']} of {d['flow']} from {d['process']}\n")
        df = self.impacts_df()
        if not df.empty:
            lines.append("Impact Results:")
            for _, row in df.iterrows():
                unit = row.get("ref_unit") or ""
                lines.append(f"  {row['category']}: {row['value']:.6g} {unit}")
        return "\n".join(lines)
