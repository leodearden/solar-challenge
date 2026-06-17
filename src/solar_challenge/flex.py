# SPDX-License-Identifier: AGPL-3.0-or-later
"""Flexibility value-model for domestic battery storage in the Bristol community energy project.

Encodes the canonical Low/Central/High banded flexibility-value decomposition
from the consulting model (2026-06-16-flexibility-value-buildability-model.md §1.1/§1.4)
and the companion buildability note (docs/flexibility-buildability.md §ε).

The two revenue streams modelled here are:

* **Time-shift / arbitrage** — buying cheap overnight electricity and displacing
  peak imports; from consulting §1.1.
* **Grid services (firm flex capacity)** — payments for contracted kW of dispatchable
  discharge power; from PRD §6 (resolved decision 2: per-kW basis).

Three uncertainty bands (Low / Central / High) bound the plausible range for
a 2-kW-ish domestic battery in the Bristol context.  The ``total_gbp`` headline
figure is the *documented* increment quoted in the consulting model — it is NOT
the arithmetic sum of the two streams, because arbitrage and self-consumption
contend for the same battery capacity (consulting §1.1 warns against simple
column-maxima addition).
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class FlexibilityValueBand:
    """Canonical flexibility-value decomposition for one uncertainty band.

    Stores the two revenue streams (time-shift arbitrage and grid-services
    capacity payment) and the documented headline total, together with a
    provenance string that anchors the numbers to the source document and
    section.

    All monetary fields are in **£ / battery-home / yr** (per-home figures),
    except ``grid_services_per_kw_gbp`` which is **£ / kW of max-discharge /
    yr** and is the rate consumed by the W2 grid-services income formula
    (Σ max_discharge_kw × rate).

    Attributes:
        name: Band identifier — one of ``"low"``, ``"central"``, ``"high"``.
        time_shift_gbp: Arbitrage / time-shift revenue in £/home/yr
            (consulting §1.1).
        grid_services_per_home_gbp: Grid-services capacity payment in
            £/home/yr for a representative 2.5-kW battery (consulting §1.1).
        grid_services_per_kw_gbp: Grid-services rate in £/kW-discharge/yr
            (PRD §6; rate × 2.5 ≈ per_home within the doc's banding tolerance).
        total_gbp: Documented headline total increment in £/home/yr
            (consulting §1.1).  **Not** the arithmetic sum of the two streams —
            see consulting §1.1 caveat on capacity contention.
        provenance: Source reference for the numbers in this band, e.g.
            ``"consulting §1.1 + PRD §6"``.
    """

    name: str
    time_shift_gbp: float
    grid_services_per_home_gbp: float
    grid_services_per_kw_gbp: float
    total_gbp: float
    provenance: str

    def __post_init__(self) -> None:
        """Validate domain constraints."""
        if not self.name:
            raise ValueError("name must be a non-empty string")
        if not self.provenance:
            raise ValueError("provenance must be a non-empty string")
        if self.time_shift_gbp < 0:
            raise ValueError(
                f"time_shift_gbp must be non-negative, got {self.time_shift_gbp}"
            )
        if self.grid_services_per_home_gbp < 0:
            raise ValueError(
                f"grid_services_per_home_gbp must be non-negative, "
                f"got {self.grid_services_per_home_gbp}"
            )
        if self.grid_services_per_kw_gbp < 0:
            raise ValueError(
                f"grid_services_per_kw_gbp must be non-negative, "
                f"got {self.grid_services_per_kw_gbp}"
            )
        if self.total_gbp < 0:
            raise ValueError(
                f"total_gbp must be non-negative, got {self.total_gbp}"
            )


# Representative battery discharge power in kW — matches BatteryConfig.max_discharge_kw
# default (config.py:264).  Used to anchor the per-kW ↔ per-home cross-check in the
# consulting §1.1 table.  The W2 consuming formula uses each home's ACTUAL
# max_discharge_kw; 2.5 is the consulting model's representative figure only.
# Populated in step-4.
REPRESENTATIVE_DISCHARGE_POWER_KW: float = 2.5  # kW; config.py:264 default

# Canonical band presets keyed "low"/"central"/"high".  Populated in step-4.
FLEX_VALUE_BANDS: dict[str, FlexibilityValueBand] = {}


def resolve_flex_band(band: str) -> FlexibilityValueBand:
    """Validate *band* and return the corresponding :class:`FlexibilityValueBand`.

    Args:
        band: Uncertainty band name — ``"low"``, ``"central"``, or ``"high"``.

    Returns:
        The matching :class:`FlexibilityValueBand` from :data:`FLEX_VALUE_BANDS`.

    Raises:
        ValueError: If *band* is not a known key.  The message lists available
            bands (mirroring :func:`~solar_challenge.seg.resolve_seg_tariff`).
    """
    if band in FLEX_VALUE_BANDS:
        return FLEX_VALUE_BANDS[band]
    available = ", ".join(sorted(FLEX_VALUE_BANDS.keys()))
    raise ValueError(
        f"Unknown flexibility band '{band}'. Available: {available}"
    )


def resolve_grid_services_band(band: str) -> float:
    """Return the grid-services rate in £/kW-of-max-discharge/yr for *band*.

    Delegates to :func:`resolve_flex_band` (single validation path) and
    returns the ``grid_services_per_kw_gbp`` field.

    The W2 grid-services income formula is: income = Σ max_discharge_kw × rate,
    where *rate* is the value returned here (central exactly £12.0/kW/yr).

    Args:
        band: Uncertainty band name — ``"low"``, ``"central"``, or ``"high"``.

    Returns:
        £/kW-of-max-discharge/yr rate for the requested band.

    Raises:
        ValueError: If *band* is unknown (propagated from :func:`resolve_flex_band`).
    """
    return resolve_flex_band(band).grid_services_per_kw_gbp
