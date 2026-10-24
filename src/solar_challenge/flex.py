# SPDX-License-Identifier: AGPL-3.0-or-later
"""Flexibility value-model for domestic battery storage in the Bristol community energy project.

Encodes the canonical Low/Central/High banded flexibility-value decomposition
from the consulting model (2026-06-16-flexibility-value-buildability-model.md §1.1/§1.4)
and the companion buildability note (docs/flexibility-buildability.md).

The two revenue streams modelled here are:

* **Time-shift / arbitrage** — buying cheap overnight electricity and displacing
  peak imports; from consulting §1.1.
* **Grid services (firm flex capacity)** — payments for contracted kW of dispatchable
  discharge power; from docs/prds/flexibility-value-finance-integration.md §6,
  resolved decision 2 (per-kW basis).  The per-kW rates are the flat rates of
  :data:`~solar_challenge.gridservices.GRID_SERVICES_RATE_BANDS`.

Three uncertainty bands (Low / Central / High) bound the plausible range for
a 2-kW-ish domestic battery in the Bristol context.  The ``total_gbp`` headline
figure is the *documented* increment quoted in the consulting model — it is
*not necessarily* the arithmetic sum of the two streams, because arbitrage and
self-consumption contend for the same battery capacity (consulting §1.1 warns
against simple column-maxima addition). The contention is material only for
the low band (100 + 4 = 104 ≠ 120); central and high happen to sum exactly.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from solar_challenge.errors import ConfigurationError
from solar_challenge.gridservices import GRID_SERVICES_RATE_BANDS, GridServicesBand


@dataclass(frozen=True)
class FlexibilityValueBand:
    """Canonical flexibility-value decomposition for one uncertainty band.

    Stores the two revenue streams (time-shift arbitrage and grid-services
    capacity payment) and the documented headline total, together with a
    provenance string that anchors the numbers to the source document and
    section.

    All monetary fields are in **£ / battery-home / yr** (per-home figures),
    except ``grid_services_per_kw_gbp`` which is **£ / kW of max-discharge /
    yr** and is the rate consumed by finance's grid-services income formula
    (Σ max_discharge_kw × rate).

    Attributes:
        name: Band identifier — one of ``"low"``, ``"central"``, ``"high"``.
        time_shift_gbp: Arbitrage / time-shift revenue in £/home/yr
            (consulting §1.1).
        grid_services_per_home_gbp: Grid-services capacity payment in
            £/home/yr for a representative 2.5-kW battery (consulting §1.1).
        grid_services_per_kw_gbp: Grid-services rate in £/kW-discharge/yr; in
            :data:`FLEX_VALUE_BANDS` it is the band's flat rate in
            :data:`~solar_challenge.gridservices.GRID_SERVICES_RATE_BANDS`
            (rate × 2.5 ≈ per_home within the doc's banding tolerance).
        total_gbp: Documented headline total increment in £/home/yr
            (consulting §1.1).  Not necessarily the arithmetic sum of the two
            streams — consulting §1.1 warns against simple column-maxima
            addition due to capacity contention.  The adjustment is material
            only for the low band (100 + 4 = 104 ≠ 120); central and high
            happen to sum exactly.
        provenance: Source reference for the numbers in this band, e.g.
            ``"consulting §1.1 + docs/prds/flexibility-value-finance-integration.md §6"``.
    """

    name: str
    time_shift_gbp: float
    grid_services_per_home_gbp: float
    grid_services_per_kw_gbp: float
    total_gbp: float
    provenance: str

    def __post_init__(self) -> None:
        """Validate domain constraints, raising ConfigurationError on violation."""
        if not self.name:
            raise ConfigurationError("name must be a non-empty string")
        if not self.provenance:
            raise ConfigurationError("provenance must be a non-empty string")
        if self.time_shift_gbp < 0:
            raise ConfigurationError(
                f"time_shift_gbp must be non-negative, got {self.time_shift_gbp}"
            )
        if self.grid_services_per_home_gbp < 0:
            raise ConfigurationError(
                f"grid_services_per_home_gbp must be non-negative, "
                f"got {self.grid_services_per_home_gbp}"
            )
        if self.grid_services_per_kw_gbp < 0:
            raise ConfigurationError(
                f"grid_services_per_kw_gbp must be non-negative, "
                f"got {self.grid_services_per_kw_gbp}"
            )
        if self.total_gbp < 0:
            raise ConfigurationError(
                f"total_gbp must be non-negative, got {self.total_gbp}"
            )


# Representative battery discharge power in kW — matches the default of
# BatteryConfig.max_discharge_kw.  Used to anchor the per-kW ↔ per-home cross-check in the
# consulting §1.1 table.  Finance's grid-services formula uses each home's ACTUAL
# max_discharge_kw; 2.5 is the consulting model's representative figure only.
REPRESENTATIVE_DISCHARGE_POWER_KW: float = 2.5  # kW; the default of BatteryConfig.max_discharge_kw

_PROVENANCE = (
    "per-home figures: consulting 2026-06-16-flexibility-value-buildability-model.md §1.1/§1.4; "
    "per-kW rate: the band's flat rate in solar_challenge.gridservices.GRID_SERVICES_RATE_BANDS, "
    "whose provenance cites its source"
)


def _consulting_band(
    band: GridServicesBand,
    *,
    time_shift_gbp: float,
    grid_services_per_home_gbp: float,
    total_gbp: float,
) -> FlexibilityValueBand:
    """*band*'s consulting §1.1 per-home figures, with the rate table's flat rate for *band* as its per-kW rate."""
    return FlexibilityValueBand(
        name=band.value,
        time_shift_gbp=time_shift_gbp,
        grid_services_per_home_gbp=grid_services_per_home_gbp,
        grid_services_per_kw_gbp=GRID_SERVICES_RATE_BANDS.resolve(band).flat_gbp_per_kw_per_year,
        total_gbp=total_gbp,
        provenance=_PROVENANCE,
    )


# Canonical band presets keyed by GridServicesBand, in band order.
# Numbers from consulting §1.1 (time-shift, grid-services per-home, headline total);
# each band's grid-services per-kW rate is GRID_SERVICES_RATE_BANDS' flat rate.
#
# NOTE: total_gbp is the DOCUMENTED HEADLINE INCREMENT, not necessarily the
# arithmetic sum of time_shift_gbp + grid_services_per_home_gbp.  Consulting
# §1.1 warns against simple column-maxima addition due to capacity contention.
# The adjustment is material only for the low band (100+4=104 ≠ 120); central
# (250+30=280) and high (330+120=450) happen to sum exactly.
#
# Each band's per-kW rate × REPRESENTATIVE_DISCHARGE_POWER_KW ≈ its per-home figure,
# within ±£1.0:
# tests/unit/test_flex.py::TestFlexValueBands::test_per_kw_rate_at_the_representative_power_is_the_per_home_figure
FLEX_VALUE_BANDS: Mapping[GridServicesBand, FlexibilityValueBand] = MappingProxyType({
    GridServicesBand.LOW: _consulting_band(
        GridServicesBand.LOW, time_shift_gbp=100.0, grid_services_per_home_gbp=4.0, total_gbp=120.0
    ),
    GridServicesBand.CENTRAL: _consulting_band(
        GridServicesBand.CENTRAL, time_shift_gbp=250.0, grid_services_per_home_gbp=30.0, total_gbp=280.0
    ),
    GridServicesBand.HIGH: _consulting_band(
        GridServicesBand.HIGH, time_shift_gbp=330.0, grid_services_per_home_gbp=120.0, total_gbp=450.0
    ),
})


def resolve_flex_band(band: str) -> FlexibilityValueBand:
    """Validate *band* and return the corresponding :class:`FlexibilityValueBand`.

    Args:
        band: Uncertainty band name — ``"low"``, ``"central"``, or ``"high"`` — or a
            :class:`~solar_challenge.gridservices.GridServicesBand`.

    Returns:
        The matching :class:`FlexibilityValueBand` from :data:`FLEX_VALUE_BANDS`.

    Raises:
        ConfigurationError: If *band* is not a band (a ValueError).  The message
            lists the bands.
    """
    return FLEX_VALUE_BANDS[GridServicesBand.parse(band, what="flexibility band")]
