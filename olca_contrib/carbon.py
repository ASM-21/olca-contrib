"""
Grid emissions integration.

openLCA uses static emission factors from the background database. This
module adds regional and time-varying grid carbon intensity: eGRID
subregion averages for offline use, and a WattTime MOER client for
marginal emissions when real-time data is available.
"""

import logging
from dataclasses import dataclass
from enum import Enum

log = logging.getLogger(__name__)


class EmissionFactorType(Enum):
    AVERAGE = "average"
    MARGINAL = "marginal"
    LONG_RUN_MARGINAL = "long_run_marginal"


@dataclass
class GridEmissionFactor:
    region: str
    timestamp: str
    value_kg_co2_per_kwh: float
    factor_type: EmissionFactorType = EmissionFactorType.AVERAGE
    source: str = ""


@dataclass
class CarbonProfile:
    operation_name: str
    energy_kwh: float
    emission_factor: GridEmissionFactor | None = None
    emissions_kg_co2: float = 0.0
    marginal_emissions_kg_co2: float | None = None

    def __post_init__(self):
        if self.emission_factor:
            self.emissions_kg_co2 = (
                self.energy_kwh * self.emission_factor.value_kg_co2_per_kwh)


# eGRID subregion average CO2 emission factors, kg CO2/kWh.
# Approximate values for planning use; verify against the current eGRID
# release before using in a published assessment.
EGRID_FACTORS: dict[str, float] = {
    "AKGD": 0.432, "AKMS": 0.213, "AZNM": 0.366, "CAMX": 0.206,
    "ERCT": 0.373, "FRCC": 0.371, "HIMS": 0.515, "HIOA": 0.650,
    "MROE": 0.525, "MROW": 0.446, "NEWE": 0.169, "NWPP": 0.246,
    "NYCW": 0.188, "NYLI": 0.331, "NYUP": 0.097, "PRMS": 0.434,
    "RFCE": 0.274, "RFCM": 0.472, "RFCW": 0.489, "RMPA": 0.495,
    "SPNO": 0.449, "SPSO": 0.388, "SRMV": 0.317, "SRMW": 0.574,
    "SRSO": 0.349, "SRTV": 0.374, "SRVC": 0.287,
}

# Rough mapping from ISO/RTO names to eGRID subregions. ISO footprints do
# not align cleanly with eGRID boundaries, so treat these as approximations.
REGION_TO_EGRID: dict[str, str] = {
    "MISO_INDY": "RFCW",
    "PJM": "RFCE",
    "ERCOT": "ERCT",
    "CAISO": "CAMX",
    "NYISO": "NYCW",
    "ISONE": "NEWE",
    "SPP": "SPNO",
}


class CarbonCalculator:
    """Calculate grid carbon emissions for manufacturing operations.

    Usage:
        calc = CarbonCalculator(default_region="RFCW")
        profile = calc.from_egrid("CNC_Facing", 0.347, region="MISO_INDY")
        df = calc.compare_regions(0.347)
    """

    def __init__(self, *, default_region: str = "RFCW",
                 custom_factors: dict[str, float] | None = None):
        self._default_region = default_region
        self._factors = {**EGRID_FACTORS}
        if custom_factors:
            self._factors.update(custom_factors)

    def get_factor(self, region: str) -> float | None:
        if region in self._factors:
            return self._factors[region]
        mapped = REGION_TO_EGRID.get(region)
        if mapped and mapped in self._factors:
            return self._factors[mapped]
        return None

    def from_egrid(self, operation_name: str, energy_kwh: float, *,
                   region: str | None = None) -> CarbonProfile:
        r = region or self._default_region
        factor_val = self.get_factor(r)
        if factor_val is None:
            log.warning("No factor for region '%s'; falling back to '%s'",
                        r, self._default_region)
            r = self._default_region
            factor_val = self._factors.get(r, 0.489)

        ef = GridEmissionFactor(
            region=r, timestamp="annual_average",
            value_kg_co2_per_kwh=factor_val,
            factor_type=EmissionFactorType.AVERAGE,
            source="EPA eGRID subregion average",
        )
        return CarbonProfile(operation_name=operation_name,
                             energy_kwh=energy_kwh, emission_factor=ef)

    def from_factor(self, operation_name: str, energy_kwh: float, *,
                    factor_kg_per_kwh: float,
                    source: str = "custom") -> CarbonProfile:
        ef = GridEmissionFactor(region="custom", timestamp="custom",
                                value_kg_co2_per_kwh=factor_kg_per_kwh,
                                source=source)
        return CarbonProfile(operation_name=operation_name,
                             energy_kwh=energy_kwh, emission_factor=ef)

    def profile_operations(self, operations: dict) -> list[CarbonProfile]:
        """Build carbon profiles for every operation in an EnergyBridge."""
        return [
            self.from_egrid(name, op.energy_kwh,
                            region=op.grid_region or self._default_region)
            for name, op in operations.items()
        ]

    def to_dataframe(self, profiles: list[CarbonProfile]):
        import pandas as pd
        return pd.DataFrame([{
            "operation": p.operation_name,
            "energy_kwh": p.energy_kwh,
            "region": p.emission_factor.region if p.emission_factor else "",
            "factor_kg_co2_kwh": (p.emission_factor.value_kg_co2_per_kwh
                                  if p.emission_factor else 0),
            "emissions_kg_co2": p.emissions_kg_co2,
            "factor_source": p.emission_factor.source if p.emission_factor else "",
        } for p in profiles])

    def total_emissions(self, profiles: list[CarbonProfile]) -> float:
        return sum(p.emissions_kg_co2 for p in profiles)

    def compare_regions(self, energy_kwh: float,
                        regions: list[str] | None = None):
        """Compare emissions across grid regions for the same energy use."""
        import pandas as pd
        if regions is None:
            regions = list(EGRID_FACTORS.keys())
        rows = []
        for r in regions:
            factor = self.get_factor(r)
            if factor is None:
                continue
            rows.append({"region": r, "factor_kg_co2_kwh": factor,
                         "emissions_kg_co2": energy_kwh * factor})
        df = pd.DataFrame(rows)
        if not df.empty:
            df = df.sort_values("emissions_kg_co2").reset_index(drop=True)
            min_val = df["emissions_kg_co2"].min()
            if min_val > 0:
                df["relative_pct"] = ((df["emissions_kg_co2"] / min_val - 1) * 100).round(1)
        return df


class WattTimeClient:
    """Client for WattTime marginal operating emissions rate (MOER) data.

    Requires a WattTime account. Endpoints and response shapes change
    between API versions, so verify against current WattTime docs.
    """

    BASE_URL = "https://api.watttime.org/v3"

    def __init__(self, username: str = "", password: str = "", token: str = ""):
        self._username = username
        self._password = password
        self._token = token

    def _get_token(self) -> str:
        if self._token:
            return self._token
        try:
            import httpx
        except ImportError:
            raise ImportError(
                "httpx required for WattTime. pip install httpx") from None
        resp = httpx.get(f"{self.BASE_URL}/login",
                         auth=(self._username, self._password))
        resp.raise_for_status()
        self._token = resp.json()["token"]
        return self._token

    def get_current_moer(self, *, latitude: float, longitude: float) -> float | None:
        try:
            import httpx
            token = self._get_token()
            resp = httpx.get(
                f"{self.BASE_URL}/signal-index",
                headers={"Authorization": f"Bearer {token}"},
                params={"latitude": str(latitude), "longitude": str(longitude),
                        "signal_type": "co2_moer"},
            )
            resp.raise_for_status()
            data = resp.json()
            if data.get("data"):
                return data["data"][0].get("value")
        except Exception as e:
            log.error("WattTime API error: %s", e)
        return None

    def get_historical_moer(self, *, latitude: float, longitude: float,
                            start: str, end: str) -> list[dict]:
        try:
            import httpx
            token = self._get_token()
            resp = httpx.get(
                f"{self.BASE_URL}/historical",
                headers={"Authorization": f"Bearer {token}"},
                params={"latitude": str(latitude), "longitude": str(longitude),
                        "signal_type": "co2_moer", "start": start, "end": end},
            )
            resp.raise_for_status()
            return resp.json().get("data", [])
        except Exception as e:
            log.error("WattTime API error: %s", e)
            return []
