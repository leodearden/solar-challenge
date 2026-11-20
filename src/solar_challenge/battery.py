# SPDX-License-Identifier: AGPL-3.0-or-later
"""Battery storage configuration and modelling."""

import dataclasses
import math
from dataclasses import dataclass
from typing import Final, Literal, Optional

from solar_challenge.dispatch import DispatchStrategyConfig, GridChargeConfig
from solar_challenge.errors import ConfigurationError
from solar_challenge.number_fields import (
    FRACTION,
    NON_NEGATIVE,
    POSITIVE,
    UNIT_INTERVAL,
    as_finite_float,
    read_field,
)
from solar_challenge.timebase import HOURS_PER_MINUTE, require_valid_duration


def _read_soc_limits_and_efficiencies(instance: object) -> None:
    """Read *instance*'s SOC limits, each from 0 to 1, and its per-direction efficiencies, each above 0 and at most 1.

    The one home of these four bounds, shared by BatteryConfig and a Battery's
    _SocLimitsAndEfficiencies.

    Raises:
        ConfigurationError: If a value is not a finite number inside its bounds, naming
            its field and the value.
    """
    read_field(instance, "min_soc_fraction", as_finite_float, UNIT_INTERVAL)
    read_field(instance, "max_soc_fraction", as_finite_float, UNIT_INTERVAL)
    read_field(instance, "charge_efficiency", as_finite_float, FRACTION)
    read_field(instance, "discharge_efficiency", as_finite_float, FRACTION)


def _require_soc_limits_in_order(min_soc_fraction: float, max_soc_fraction: float) -> None:
    """Refuse SOC limits whose minimum is not below their maximum, naming both."""
    if not min_soc_fraction < max_soc_fraction:
        raise ConfigurationError(
            "min_soc_fraction must be less than max_soc_fraction, got "
            f"min_soc_fraction={min_soc_fraction!r} and max_soc_fraction={max_soc_fraction!r}"
        )


_ROUND_TRIP_EFFICIENCY: Final = FRACTION
"""The round-trip efficiencies that BatteryConfig.efficiency and _one_way_efficiency admit."""

_DEFAULT_ONE_WAY_EFFICIENCY: Final = 0.975
"""The declared default of BatteryConfig.charge_efficiency and discharge_efficiency."""


def _one_way_efficiency(round_trip_efficiency: float) -> float:
    """The charge (and discharge) efficiency of a battery whose round trip is round_trip_efficiency: its square root.

    Raises:
        ConfigurationError: If *round_trip_efficiency* is not a finite number above 0 and at
            most 1, naming round-trip efficiency and the value.
    """
    return math.sqrt(as_finite_float(round_trip_efficiency, "round-trip efficiency", _ROUND_TRIP_EFFICIENCY))


def _refuse_a_pair_contradicting_its_round_trip(
    efficiency: float, one_way: float, charge_efficiency: float, discharge_efficiency: float
) -> None:
    """Refuse a per-direction efficiency that is neither *one_way*, the square root of *efficiency*, nor its default, naming each such field."""
    contradictions = [
        f"{field}={value!r}"
        for field, value in (
            ("charge_efficiency", charge_efficiency),
            ("discharge_efficiency", discharge_efficiency),
        )
        if value not in (one_way, _DEFAULT_ONE_WAY_EFFICIENCY)
    ]
    if contradictions:
        raise ConfigurationError(
            f"efficiency={efficiency!r} makes charge_efficiency and discharge_efficiency each its "
            f"square root, {one_way!r}, but got {' and '.join(contradictions)}; use "
            f"BatteryConfig.with_round_trip({efficiency!r}), or pass charge_efficiency and "
            "discharge_efficiency without efficiency"
        )


_POWER_LIMIT_KW = POSITIVE
"""The maximum charge and discharge powers, in kW, that BatteryConfig and require_valid_power_limit admit."""


def require_valid_power_limit(kw: float, direction: Literal["charge", "discharge"]) -> float:
    """Return a battery's maximum *direction* power *kw* read as BatteryConfig reads its max_<direction>_kw.

    Raises:
        ConfigurationError: If *kw* is not a positive finite number, naming
            max_<direction>_kw and *kw*.
    """
    return as_finite_float(kw, f"max_{direction}_kw", _POWER_LIMIT_KW)


def _require_valid_request(
    direction: Literal["charge", "discharge"], power_kw: float, duration_minutes: float
) -> None:
    """Refuse a *direction* request unless its power is finite and at least 0 and its duration is positive and finite."""
    if not NON_NEGATIVE.admits(power_kw):
        raise ValueError(
            f"{direction.capitalize()} power must be non-negative and finite, got {power_kw} kW"
        )
    require_valid_duration(duration_minutes, f"{direction.capitalize()} duration")


CAPACITY_SETTING_KWH: Final = NON_NEGATIVE
"""The battery capacity settings, in kWh, that require_valid_capacity_setting admits, where 0 means no battery; BatteryConfig.capacity_kwh, a battery's own capacity, is above 0."""


def require_valid_capacity_setting(capacity_kwh: object, setting: str) -> float:
    """Return a battery capacity setting read as a finite number CAPACITY_SETTING_KWH admits; 0 means no battery.

    Raises:
        ConfigurationError: If *capacity_kwh* is not a finite number CAPACITY_SETTING_KWH
            admits, naming *setting* and *capacity_kwh*.
    """
    return as_finite_float(capacity_kwh, setting, CAPACITY_SETTING_KWH)


def has_battery(capacity_kwh: object, setting: str) -> bool:
    """Whether a battery capacity setting, read by require_valid_capacity_setting, asks for a battery (> 0); an invalid one is refused."""
    return require_valid_capacity_setting(capacity_kwh, setting) > 0


def compute_soh(
    system_age_years: float,
    cumulative_throughput_kwh: float,
    usable_capacity_kwh: float,
    params: "BatteryConfig",
) -> float:
    """Compute battery State of Health from calendar + cycle degradation.

    Uses a linear calendar fade and equivalent-full-cycle (EFC) cycle fade:

    - ``calendar_fade = params.calendar_fade_rate_per_year * system_age_years``
    - ``efc = cumulative_throughput_kwh / usable_capacity_kwh`` if
      ``usable_capacity_kwh > 0`` else ``0.0``
    - ``cycle_fade = params.cycle_fade_per_equivalent_full_cycle * efc``
    - ``soh = clamp(1 - calendar_fade - cycle_fade, [soh_floor, 1.0])``

    The result is monotone non-increasing in both *system_age_years* and
    *cumulative_throughput_kwh* (both partial derivatives are ≤ 0).  The
    clamp preserves this property.

    Args:
        system_age_years: Age of the battery in years (≥ 0).
        cumulative_throughput_kwh: The energy the battery has discharged since
            installation, in kWh (≥ 0), as
            ``SummaryStatistics.total_battery_discharge_kwh`` counts it (the
            output of ``Battery.discharge``).
        usable_capacity_kwh: The battery's nominal usable capacity in kWh
            (``BatteryConfig.nominal_usable_capacity_kwh``), not de-rated by
            SOH.  One equivalent full cycle is this much throughput.  Pass 0.0
            to disable cycle fade.
        params: BatteryConfig carrying the fade-rate and floor parameters.

    Returns:
        SOH in [params.soh_floor, 1.0].
    """
    calendar_fade = params.calendar_fade_rate_per_year * system_age_years
    efc = (
        cumulative_throughput_kwh / usable_capacity_kwh
        if usable_capacity_kwh > 0
        else 0.0
    )
    cycle_fade = params.cycle_fade_per_equivalent_full_cycle * efc
    raw_soh = 1.0 - calendar_fade - cycle_fade
    return max(params.soh_floor, min(1.0, raw_soh))


@dataclass(frozen=True)
class SocEnvelope:
    """A battery's SOH-derated SOC envelope in kWh: its effective capacity and the SOC limits within it."""

    effective_capacity_kwh: float
    min_soc_kwh: float
    max_soc_kwh: float

    def __post_init__(self) -> None:
        """Read each field as a finite number in its range, held as a float, then refuse limits out of order."""
        read_field(self, "effective_capacity_kwh", as_finite_float, POSITIVE)
        read_field(self, "min_soc_kwh", as_finite_float, NON_NEGATIVE)
        read_field(self, "max_soc_kwh", as_finite_float, NON_NEGATIVE)
        if not self.min_soc_kwh <= self.max_soc_kwh <= self.effective_capacity_kwh:
            raise ConfigurationError(
                "min_soc_kwh must be at most max_soc_kwh, and max_soc_kwh at most effective_capacity_kwh, got "
                f"min_soc_kwh={self.min_soc_kwh!r}, max_soc_kwh={self.max_soc_kwh!r} "
                f"and effective_capacity_kwh={self.effective_capacity_kwh!r}"
            )

    def target_kwh(self, fraction: float) -> float:
        """The SOC at *fraction* of the effective capacity, capped at max_soc_kwh.

        Raises:
            ConfigurationError: If *fraction* is not a finite number from 0 to 1, naming it and the value.
        """
        return min(as_finite_float(fraction, "fraction", UNIT_INTERVAL) * self.effective_capacity_kwh, self.max_soc_kwh)


def _derated_soc_envelope(
    capacity_kwh: float, soh: float, min_soc_fraction: float, max_soc_fraction: float
) -> SocEnvelope:
    """The envelope of a *capacity_kwh* battery at *soh*, its SOC limits those fractions of its effective capacity."""
    effective_capacity_kwh = capacity_kwh * soh
    return SocEnvelope(
        effective_capacity_kwh,
        effective_capacity_kwh * min_soc_fraction,
        effective_capacity_kwh * max_soc_fraction,
    )


@dataclass(frozen=True)
class BatteryConfig:
    """Configuration for a battery storage system.

    Construction reads every number setting as a finite number inside its range and
    holds it as a float, then refuses SOC limits whose minimum is not below their
    maximum and a round-trip efficiency that a per-direction efficiency contradicts,
    each with a ConfigurationError.

    Attributes:
        capacity_kwh: Total energy capacity in kilowatt-hours
        max_charge_kw: Maximum charging power in kilowatts
        max_discharge_kw: Maximum discharging power in kilowatts
        name: Optional identifier for the battery
        dispatch_strategy: Optional dispatch strategy configuration, one of
            dispatch.DispatchStrategyConfig's variants
        grid_charging: Optional grid-charge (arbitrage) configuration; None means disabled
        min_soc_fraction: Minimum state of charge as fraction of capacity (default 0.1)
        max_soc_fraction: Maximum state of charge as fraction of capacity (default 0.9)
        charge_efficiency: Charging efficiency, fraction of energy stored (default 0.975)
        discharge_efficiency: Discharging efficiency, fraction of stored energy output (default 0.975)
        efficiency: Transitional round-trip efficiency, retired at the surface bump; when set,
            charge_efficiency and discharge_efficiency are its square root, and one set to
            neither that nor its default is refused. Use with_round_trip instead.
        system_age_years: Age of the battery system in years (≥ 0); used to
            compute calendar fade when no ``soh`` override is provided.
        calendar_fade_rate_per_year: Linear calendar SOH fade rate per year
            (≥ 0; default 0.02/yr ≈ 70 % SOH at 15-yr warranty horizon).
        cycle_fade_per_equivalent_full_cycle: SOH fade per equivalent full
            cycle as :func:`compute_soh` counts one (≥ 0; default 5e-5/EFC
            ≈ 30 % fade over ~6 000 EFC).
            ``resolved_soh`` computes calendar fade only (throughput 0); cycle
            fade takes effect only through an ``soh`` computed by
            :func:`compute_soh` from accrued throughput.
        soh_floor: Minimum allowed SOH after clamping (0 < soh_floor ≤ 1;
            default 0.5, reflecting end-of-useful-life convention).
        soh: Optional direct SOH override (0 < soh ≤ 1).  When set, the
            computed calendar+cycle fade is bypassed and ``resolved_soh``
            returns this value directly.
    """

    capacity_kwh: float
    max_charge_kw: float = 2.5
    max_discharge_kw: float = 2.5
    name: str = ""
    dispatch_strategy: Optional[DispatchStrategyConfig] = None
    grid_charging: Optional[GridChargeConfig] = None
    min_soc_fraction: float = 0.1
    max_soc_fraction: float = 0.9
    charge_efficiency: float = _DEFAULT_ONE_WAY_EFFICIENCY
    discharge_efficiency: float = _DEFAULT_ONE_WAY_EFFICIENCY
    efficiency: Optional[float] = None
    system_age_years: float = 0.0
    calendar_fade_rate_per_year: float = 0.02
    cycle_fade_per_equivalent_full_cycle: float = 5e-5
    soh_floor: float = 0.5
    soh: Optional[float] = None

    def __post_init__(self) -> None:
        """Read each number setting, then refuse SOC limits out of order, and derive the per-direction efficiencies from a set round-trip one, refusing one that contradicts it."""
        read_field(self, "capacity_kwh", as_finite_float, POSITIVE)
        read_field(self, "max_charge_kw", as_finite_float, _POWER_LIMIT_KW)
        read_field(self, "max_discharge_kw", as_finite_float, _POWER_LIMIT_KW)
        _read_soc_limits_and_efficiencies(self)
        read_field(self, "efficiency", as_finite_float, _ROUND_TRIP_EFFICIENCY, optional=True)
        read_field(self, "system_age_years", as_finite_float, NON_NEGATIVE)
        read_field(self, "calendar_fade_rate_per_year", as_finite_float, NON_NEGATIVE)
        read_field(self, "cycle_fade_per_equivalent_full_cycle", as_finite_float, NON_NEGATIVE)
        read_field(self, "soh_floor", as_finite_float, FRACTION)
        read_field(self, "soh", as_finite_float, FRACTION, optional=True)
        _require_soc_limits_in_order(self.min_soc_fraction, self.max_soc_fraction)
        if self.efficiency is not None:
            one_way = _one_way_efficiency(self.efficiency)
            _refuse_a_pair_contradicting_its_round_trip(
                self.efficiency, one_way, self.charge_efficiency, self.discharge_efficiency
            )
            object.__setattr__(self, "charge_efficiency", one_way)
            object.__setattr__(self, "discharge_efficiency", one_way)

    @property
    def nominal_usable_capacity_kwh(self) -> float:
        """Usable capacity between the SOC limits, before SOH de-rating (kWh)."""
        return self.capacity_kwh * (self.max_soc_fraction - self.min_soc_fraction)

    @property
    def resolved_soh(self) -> float:
        """The state of health a Battery built from this config holds, resolved once.

        The ``soh`` override wins and is used as given, without clamping to
        ``soh_floor``: supply one consistent with ``soh_floor`` if the
        ``[soh_floor, 1.0]`` invariant matters for your use case. Without one it is
        :func:`compute_soh` of ``system_age_years`` with zero throughput, calendar
        fade only, because one run accrues no throughput.
        """
        if self.soh is not None:
            return self.soh
        return compute_soh(self.system_age_years, 0.0, self.nominal_usable_capacity_kwh, self)

    def soc_envelope(self) -> SocEnvelope:
        """The SOH-derated SOC envelope at this config's SOC fractions, the one a Battery built from it starts with."""
        return _derated_soc_envelope(
            self.capacity_kwh, self.resolved_soh, self.min_soc_fraction, self.max_soc_fraction
        )

    def with_round_trip(self, round_trip_efficiency: float) -> "BatteryConfig":
        """This battery with charge and discharge efficiency each _one_way_efficiency(round_trip_efficiency).

        Raises:
            ConfigurationError: If *round_trip_efficiency* is not a finite number above 0
                and at most 1, naming round-trip efficiency and the value.
        """
        one_way = _one_way_efficiency(round_trip_efficiency)
        return dataclasses.replace(
            self, efficiency=None, charge_efficiency=one_way, discharge_efficiency=one_way
        )

    @classmethod
    def default_5kwh(cls) -> "BatteryConfig":
        """Create a typical UK domestic 5 kWh battery.

        Returns:
            BatteryConfig with 5 kWh, 2.5 kW charge/discharge
        """
        return cls(
            capacity_kwh=5.0,
            max_charge_kw=2.5,
            max_discharge_kw=2.5,
            name="5 kWh domestic battery"
        )


@dataclass(frozen=True)
class _SocLimitsAndEfficiencies:
    """A Battery's SOC limits and per-direction efficiencies, refused at construction unless valid."""

    min_soc_fraction: float
    max_soc_fraction: float
    charge_efficiency: float
    discharge_efficiency: float

    def __post_init__(self) -> None:
        _read_soc_limits_and_efficiencies(self)
        _require_soc_limits_in_order(self.min_soc_fraction, self.max_soc_fraction)


class Battery:
    """Battery with state of charge tracking.

    Tracks current SOC and enforces charge/discharge limits. Its SOC limits and
    efficiencies can be reassigned after construction, as a device's settings can.
    An assignment is checked against the bounds construction checks for these four
    values: one that breaks them raises a ConfigurationError, which is a ValueError,
    and leaves the battery unchanged.
    A new SOC limit is not checked against the current SOC and may move past it.
    While the SOC is below min_soc_kwh, discharge() moves no energy and returns
    0.0; while it is above max_soc_kwh, charge() does the same.

    Attributes:
        config: BatteryConfig defining capacity and power limits
    """

    config: BatteryConfig
    _soc_limits_and_efficiencies: _SocLimitsAndEfficiencies
    _soc_envelope: SocEnvelope

    def __init__(
        self,
        config: BatteryConfig,
        initial_soc_kwh: Optional[float] = None,
        min_soc_fraction: Optional[float] = None,
        max_soc_fraction: Optional[float] = None,
        charge_efficiency: Optional[float] = None,
        discharge_efficiency: Optional[float] = None,
    ) -> None:
        """Initialize battery with configuration and state.

        Args:
            config: Battery configuration
            initial_soc_kwh: Initial SOC in kWh (default: mid-point of usable range)
            min_soc_fraction: Minimum SOC as fraction (0-1); defaults to config.min_soc_fraction
            max_soc_fraction: Maximum SOC as fraction (0-1); defaults to config.max_soc_fraction
            charge_efficiency: Charging efficiency (0-1); defaults to config.charge_efficiency
            discharge_efficiency: Discharging efficiency (0-1); defaults to config.discharge_efficiency
        """
        self.config = config
        self._soh: float = config.resolved_soh
        self._set_soc_limits_and_efficiencies(
            _SocLimitsAndEfficiencies(
                min_soc_fraction=config.min_soc_fraction if min_soc_fraction is None else min_soc_fraction,
                max_soc_fraction=config.max_soc_fraction if max_soc_fraction is None else max_soc_fraction,
                charge_efficiency=config.charge_efficiency if charge_efficiency is None else charge_efficiency,
                discharge_efficiency=config.discharge_efficiency if discharge_efficiency is None else discharge_efficiency,
            )
        )

        # Set initial SOC
        if initial_soc_kwh is None:
            # Default to midpoint of usable range
            self._soc_kwh = (self.min_soc_kwh + self.max_soc_kwh) / 2
        else:
            if not self.min_soc_kwh <= initial_soc_kwh <= self.max_soc_kwh:
                raise ValueError(
                    f"Initial SOC {initial_soc_kwh} kWh outside allowed range "
                    f"[{self.min_soc_kwh}, {self.max_soc_kwh}]"
                )
            self._soc_kwh = initial_soc_kwh

    def _set_soc_limits_and_efficiencies(self, limits: _SocLimitsAndEfficiencies) -> None:
        """Hold *limits* and the envelope at their SOC fractions, both built before either is stored."""
        envelope = _derated_soc_envelope(
            self.config.capacity_kwh, self._soh, limits.min_soc_fraction, limits.max_soc_fraction
        )
        self._soc_limits_and_efficiencies = limits
        self._soc_envelope = envelope

    @property
    def min_soc_fraction(self) -> float:
        """Minimum SOC as a fraction of effective capacity."""
        return self._soc_limits_and_efficiencies.min_soc_fraction

    @min_soc_fraction.setter
    def min_soc_fraction(self, value: float) -> None:
        self._set_soc_limits_and_efficiencies(
            dataclasses.replace(self._soc_limits_and_efficiencies, min_soc_fraction=value)
        )

    @property
    def max_soc_fraction(self) -> float:
        """Maximum SOC as a fraction of effective capacity."""
        return self._soc_limits_and_efficiencies.max_soc_fraction

    @max_soc_fraction.setter
    def max_soc_fraction(self, value: float) -> None:
        self._set_soc_limits_and_efficiencies(
            dataclasses.replace(self._soc_limits_and_efficiencies, max_soc_fraction=value)
        )

    @property
    def charge_efficiency(self) -> float:
        """Fraction of the energy charged that is stored."""
        return self._soc_limits_and_efficiencies.charge_efficiency

    @charge_efficiency.setter
    def charge_efficiency(self, value: float) -> None:
        self._set_soc_limits_and_efficiencies(
            dataclasses.replace(self._soc_limits_and_efficiencies, charge_efficiency=value)
        )

    @property
    def discharge_efficiency(self) -> float:
        """Fraction of the energy drawn from storage that is output."""
        return self._soc_limits_and_efficiencies.discharge_efficiency

    @discharge_efficiency.setter
    def discharge_efficiency(self, value: float) -> None:
        self._set_soc_limits_and_efficiencies(
            dataclasses.replace(self._soc_limits_and_efficiencies, discharge_efficiency=value)
        )

    @property
    def soh(self) -> float:
        """The battery's state of health as a fraction, its config's resolved_soh."""
        return self._soh

    @property
    def soc_envelope(self) -> SocEnvelope:
        """The SOH-derated envelope at the battery's current SOC fractions, which follows an assignment to either."""
        return self._soc_envelope

    @property
    def effective_capacity_kwh(self) -> float:
        """soc_envelope's effective capacity in kWh, the capacity after SOH de-rating."""
        return self._soc_envelope.effective_capacity_kwh

    @property
    def soc_kwh(self) -> float:
        """Current state of charge in kWh."""
        return self._soc_kwh

    @property
    def soc_fraction(self) -> float:
        """Current state of charge as fraction of soc_envelope's effective capacity."""
        return self._soc_kwh / self._soc_envelope.effective_capacity_kwh

    @property
    def min_soc_kwh(self) -> float:
        """Minimum allowed SOC in kWh, soc_envelope's min_soc_kwh."""
        return self._soc_envelope.min_soc_kwh

    @property
    def max_soc_kwh(self) -> float:
        """Maximum allowed SOC in kWh, soc_envelope's max_soc_kwh."""
        return self._soc_envelope.max_soc_kwh

    @property
    def grid_charge_target_kwh(self) -> Optional[float]:
        """The SOC, in kWh, that grid charging fills the battery to, None when config.grid_charging is None.

        It is soc_envelope's target_kwh at config.grid_charging's target_soc_fraction, so it is at
        most max_soc_kwh.
        """
        grid_charging = self.config.grid_charging
        if grid_charging is None:
            return None
        return self._soc_envelope.target_kwh(grid_charging.target_soc_fraction)

    @property
    def usable_capacity_kwh(self) -> float:
        """Usable capacity in kWh, the energy between soc_envelope's SOC limits."""
        return self.max_soc_kwh - self.min_soc_kwh

    @property
    def available_charge_capacity_kwh(self) -> float:
        """Energy that can still be stored in kWh: 0.0 while the SOC is at or above max_soc_kwh."""
        return max(0.0, self.max_soc_kwh - self._soc_kwh)

    @property
    def available_discharge_capacity_kwh(self) -> float:
        """Energy that can still be discharged in kWh: 0.0 while the SOC is at or below min_soc_kwh."""
        return max(0.0, self._soc_kwh - self.min_soc_kwh)

    @property
    def max_charge_kw(self) -> float:
        """The maximum charging power in kW, the limit charge() applies."""
        return self.config.max_charge_kw

    def charge(self, power_kw: float, duration_minutes: float) -> float:
        """Charge the battery.

        Args:
            power_kw: Charging power in kW (before efficiency losses), finite and at
                least 0; a power above max_charge_kw moves energy at that limit
            duration_minutes: Duration of charging in minutes, positive and finite

        Returns:
            Actual energy charged in kWh (after efficiency losses)

        Raises:
            ValueError: If power_kw is negative, NaN or infinite, or duration_minutes is
                not positive and finite; the battery is left unchanged.
        """
        _require_valid_request("charge", power_kw, duration_minutes)

        # Limit to max charge rate
        actual_power = min(power_kw, self.max_charge_kw)

        # Calculate energy input and stored (with efficiency)
        duration_hours = duration_minutes * HOURS_PER_MINUTE
        energy_input_kwh = actual_power * duration_hours
        energy_stored_kwh = energy_input_kwh * self.charge_efficiency

        # Limit to available capacity
        max_storable = self.available_charge_capacity_kwh
        if energy_stored_kwh > max_storable:
            energy_stored_kwh = max_storable

        # Update SOC
        self._soc_kwh += energy_stored_kwh

        return energy_stored_kwh

    def discharge(self, power_kw: float, duration_minutes: float) -> float:
        """Discharge the battery.

        Args:
            power_kw: Requested discharge power in kW, finite and at least 0; a power
                above max_discharge_kw moves energy at that limit
            duration_minutes: Duration of discharging in minutes, positive and finite

        Returns:
            Actual energy output in kWh (after efficiency losses), never more than the
            requested power, capped at max_discharge_kw, for duration_minutes

        Raises:
            ValueError: If power_kw is negative, NaN or infinite, or duration_minutes is
                not positive and finite; the battery is left unchanged.
        """
        _require_valid_request("discharge", power_kw, duration_minutes)

        # Limit to max discharge rate
        actual_power = min(power_kw, self.config.max_discharge_kw)

        # Calculate energy requested
        duration_hours = duration_minutes * HOURS_PER_MINUTE
        energy_requested_kwh = actual_power * duration_hours

        # Calculate energy needed from battery (before efficiency)
        # We need to withdraw more than we output due to losses
        energy_needed_kwh = energy_requested_kwh / self.discharge_efficiency

        # Limit to available discharge capacity
        max_available = self.available_discharge_capacity_kwh
        if energy_needed_kwh > max_available:
            energy_needed_kwh = max_available

        energy_output_kwh = min(energy_requested_kwh, energy_needed_kwh * self.discharge_efficiency)

        # Update SOC
        self._soc_kwh -= energy_needed_kwh

        return energy_output_kwh
