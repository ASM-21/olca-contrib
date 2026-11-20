"""
Monte Carlo simulation without the server memory leak (GreenDelta/olca-ipc.py#41).

What leaks, and why
-------------------
Up to and including openLCA 2.7.0, the server's `CalculationQueue.nextSimulation`
replaced the previous run's result without disposing it. Each result holds a
matrix factorization in native memory (Julia/UMFPACK or MKL PARDISO), and that
memory is only freed by an explicit `dispose()`. So every `simulate_next()`
call loses one factorization for good, and memory grows until the JVM or the
OS gives out.

GreenDelta fixed this in olca-modules commit c895e0e (2026-11-03), which now
disposes the previous result. The fix is not in v2.7.0 (2026-08-31) and is
expected in the next release.

Why chunking does not help
--------------------------
An earlier version of this module ran `simulate_next()` in chunks and disposed
the simulator between chunks. That does not bound memory on a leaking server:
disposing frees only the current run, and the runs replaced before it are
already unreachable. With a chunk size of 100, 99 of every 100 runs still leak.

The two modes here
------------------
mode="fresh"  (default) One simulation per iteration: simulate, read, dispose.
              Nothing is orphaned, so it is leak-free on every server version.
              It is slower because the simulator is rebuilt for each run.
mode="next"   One simulator, `simulate_next()` for each further run. Fast, but
              only memory-safe on a server that contains c895e0e.
"""

import logging
import time
from dataclasses import dataclass, field

import olca_schema as o

log = logging.getLogger(__name__)

MODES = ("fresh", "next")


@dataclass
class MonteCarloResults:
    impact_results: list[dict[str, float]] = field(default_factory=list)
    n_iterations: int = 0
    n_failed: int = 0
    mode: str = "fresh"
    total_elapsed_seconds: float = 0.0
    errors: list[str] = field(default_factory=list)

    def to_dataframe(self):
        import pandas as pd

        return pd.DataFrame(self.impact_results)

    def stats(self) -> dict[str, dict[str, float]]:
        df = self.to_dataframe()
        out: dict[str, dict[str, float]] = {}
        for col in df.columns:
            s = df[col]
            mean = float(s.mean())
            std = float(s.std()) if len(s) > 1 else 0.0
            out[col] = {
                "mean": mean,
                "std": std,
                "min": float(s.min()),
                "max": float(s.max()),
                "median": float(s.median()),
                "cv": std / abs(mean) if mean != 0 else float("inf"),
                "p05": float(s.quantile(0.05)),
                "p95": float(s.quantile(0.95)),
            }
        return out

    def stats_dataframe(self):
        import pandas as pd

        s = self.stats()
        return pd.DataFrame(s).T if s else pd.DataFrame()


def _impacts_of(result) -> dict[str, float]:
    return {
        iv.impact_category.name: iv.amount if iv.amount is not None else 0.0
        for iv in result.get_total_impacts()
        if iv.impact_category is not None and iv.impact_category.name
    }


def _dispose(result):
    try:
        result.dispose()
    except Exception as e:  # never let cleanup mask the real outcome
        log.debug("dispose failed: %s", e)


def simulate_safe(
    client,
    setup: o.CalculationSetup,
    *,
    iterations: int = 1000,
    mode: str = "fresh",
    progress: bool = False,
) -> MonteCarloResults:
    """Run a Monte Carlo simulation and collect total impacts per iteration.

    See the module docstring for the difference between the two modes. Use
    `mode="next"` only against a server that has the upstream fix.
    """
    if iterations < 1:
        raise ValueError(f"iterations must be >= 1, got {iterations}")
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}, got {mode!r}")

    mc = MonteCarloResults(mode=mode)
    start = time.monotonic()
    bar = None
    if progress:
        try:
            from tqdm import tqdm

            bar = tqdm(total=iterations, desc="Monte Carlo", unit="iter")
        except ImportError:
            log.warning("tqdm not installed; progress=True ignored")

    def record(result) -> bool:
        state = result.wait_until_ready()
        if state.error:
            mc.n_failed += 1
            mc.errors.append(str(state.error))
            return False
        mc.impact_results.append(_impacts_of(result))
        mc.n_iterations += 1
        if bar:
            bar.update(1)
        return True

    try:
        if mode == "fresh":
            for _ in range(iterations):
                result = client.simulate(setup)
                try:
                    record(result)
                finally:
                    _dispose(result)
        else:
            result = client.simulate(setup)
            try:
                if record(result):
                    for _ in range(iterations - 1):
                        result.simulate_next()
                        if not record(result):
                            break
            finally:
                _dispose(result)
    finally:
        if bar:
            bar.close()
        mc.total_elapsed_seconds = time.monotonic() - start
    return mc
