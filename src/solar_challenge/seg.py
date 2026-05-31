# SPDX-License-Identifier: AGPL-3.0-or-later
"""Smart Export Guarantee (SEG) tariff configuration and revenue calculation."""

from dataclasses import dataclass


@dataclass(frozen=True)
class SEGTariff:
    """Configuration for a Smart Export Guarantee export tariff.

    The SEG scheme requires licensed electricity suppliers with 150,000+ customers
    to offer export tariffs to eligible solar generators in the UK.

    Attributes:
        name: Supplier or tariff name identifier
        rate_pence_per_kwh: Export rate in pence per kilowatt-hour
    """

    name: str
    rate_pence_per_kwh: float

    def __post_init__(self) -> None:
        """Validate SEG tariff parameters."""
        if self.rate_pence_per_kwh < 0:
            raise ValueError(
                f"SEG rate must be non-negative, got {self.rate_pence_per_kwh} p/kWh"
            )


# UK supplier SEG tariff presets (rates in pence per kWh, as of 2024/2025)
SEG_PRESETS: dict[str, SEGTariff] = {
    "Octopus": SEGTariff(name="Octopus Energy", rate_pence_per_kwh=4.1),
    "British Gas": SEGTariff(name="British Gas", rate_pence_per_kwh=3.0),
    "EDF": SEGTariff(name="EDF Energy", rate_pence_per_kwh=3.0),
    "E.ON": SEGTariff(name="E.ON Next", rate_pence_per_kwh=3.5),
    "Scottish Power": SEGTariff(name="Scottish Power", rate_pence_per_kwh=3.0),
    "OVO": SEGTariff(name="OVO Energy", rate_pence_per_kwh=4.0),
}


def resolve_seg_tariff(name: str) -> SEGTariff:
    """Look up a named SEG tariff from the preset catalogue.

    Provides the named-preset resolver intended for production/web/CLI SEG
    selectors.  Wiring into those selectors (web UI, CLI ``--seg-preset``
    flag) is owned by subsequent tasks; this function establishes the
    in-scope seam so callers can use ``HomeConfig(seg_tariff=resolve_seg_tariff("Octopus"))``
    today without further infrastructure.

    Args:
        name: Preset key to look up (e.g. ``"Octopus"``)

    Returns:
        The corresponding :class:`SEGTariff` from :data:`SEG_PRESETS`.

    Raises:
        ValueError: If *name* is not found in the preset catalogue.
            The error message lists all available preset names.
    """
    if name in SEG_PRESETS:
        return SEG_PRESETS[name]
    available = ", ".join(sorted(SEG_PRESETS.keys()))
    raise ValueError(
        f"Unknown SEG preset '{name}'. Available presets: {available}"
    )


def calculate_seg_revenue(export_kwh: float, tariff: SEGTariff) -> float:
    """Calculate SEG revenue from grid-exported electricity.

    Converts exported energy at the given tariff rate to pounds sterling.

    Args:
        export_kwh: Total grid export energy in kilowatt-hours
        tariff: SEG tariff configuration with export rate

    Returns:
        SEG revenue in GBP (pounds sterling)

    Raises:
        ValueError: If export_kwh is negative
    """
    if export_kwh < 0:
        raise ValueError(f"Export energy must be non-negative, got {export_kwh} kWh")

    return export_kwh * tariff.rate_pence_per_kwh / 100.0
