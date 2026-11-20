"""Batch calculation API with auto-disposal and DataFrame output."""

import logging
import time
from dataclasses import dataclass, field
from typing import Any

import olca_schema as o

log = logging.getLogger(__name__)


@dataclass
class BatchResult:
    index: int
    setup: o.CalculationSetup
    impacts: dict[str, float] | None = None
    inventory: dict[str, float] | None = None
    error: str | None = None
    elapsed_seconds: float = 0.0


@dataclass
class BatchResults:
    results: list[BatchResult] = field(default_factory=list)
    total_elapsed_seconds: float = 0.0
    n_succeeded: int = 0
    n_failed: int = 0

    def to_impacts_dataframe(self):
        import pandas as pd
        rows = [{"batch_index": r.index, **r.impacts, "elapsed_s": r.elapsed_seconds}
                for r in self.results if r.impacts]
        if not rows:
            return pd.DataFrame()
        return pd.DataFrame(rows).set_index("batch_index")

    def to_inventory_dataframe(self):
        import pandas as pd
        rows = [{"batch_index": r.index, **r.inventory}
                for r in self.results if r.inventory]
        if not rows:
            return pd.DataFrame()
        return pd.DataFrame(rows).set_index("batch_index")

    def errors(self) -> list[BatchResult]:
        return [r for r in self.results if r.error is not None]

    def succeeded(self) -> list[BatchResult]:
        return [r for r in self.results if r.error is None]


def _extract_impacts(result) -> dict[str, float]:
    impacts = {}
    try:
        for iv in result.get_total_impacts():
            name = iv.impact_category.name if iv.impact_category else "unknown"
            impacts[name] = iv.amount if iv.amount is not None else 0.0
    except Exception as e:
        log.warning("Failed to extract impacts: %s", e)
    return impacts


def _extract_inventory(result) -> dict[str, float]:
    inventory = {}
    try:
        for fv in result.get_total_flows():
            if fv.envi_flow and fv.envi_flow.flow:
                name = fv.envi_flow.flow.name or "unknown"
                key = f"{'input' if fv.envi_flow.is_input else 'output'}:{name}"
                inventory[key] = fv.amount if fv.amount is not None else 0.0
    except Exception as e:
        log.warning("Failed to extract inventory: %s", e)
    return inventory


def calculate_batch(client, setups: list[o.CalculationSetup], *,
                    include_inventory: bool = False,
                    on_error: str = "skip",
                    progress: bool = False,
                    progress_callback: Any | None = None) -> BatchResults:
    """Run N calculations with guaranteed result disposal.

    Args:
        client: olca_ipc.Client instance
        setups: CalculationSetup objects to run
        include_inventory: also extract LCI flow results (slower)
        on_error: "skip" logs and continues, "raise" aborts the batch
        progress: show a tqdm progress bar
        progress_callback: callable(done, total, elapsed) for custom reporting
    """
    if on_error not in ("skip", "raise"):
        raise ValueError(f"on_error must be 'skip' or 'raise', got '{on_error}'")

    batch = BatchResults()
    total = len(setups)
    batch_start = time.monotonic()

    iterator = enumerate(setups)
    if progress:
        try:
            from tqdm import tqdm
            iterator = tqdm(list(iterator), desc="Calculating", unit="calc")
        except ImportError:
            log.warning("tqdm not installed; progress=True ignored")

    for idx, setup in iterator:
        t0 = time.monotonic()
        br = BatchResult(index=idx, setup=setup)
        try:
            result = client.calculate(setup)
            state = result.wait_until_ready()
            if state.error:
                br.error = state.error
                if on_error == "raise":
                    raise RuntimeError(f"Calc {idx}/{total} failed: {state.error}")
                batch.n_failed += 1
            else:
                br.impacts = _extract_impacts(result)
                if include_inventory:
                    br.inventory = _extract_inventory(result)
                batch.n_succeeded += 1
            try:
                result.dispose()
            except Exception:
                pass
        except RuntimeError:
            raise
        except Exception as e:
            br.error = str(e)
            if on_error == "raise":
                raise
            batch.n_failed += 1

        br.elapsed_seconds = time.monotonic() - t0
        batch.results.append(br)
        if progress_callback:
            progress_callback(idx + 1, total, br.elapsed_seconds)

    batch.total_elapsed_seconds = time.monotonic() - batch_start
    return batch
