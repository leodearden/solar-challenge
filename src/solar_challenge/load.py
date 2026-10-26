# SPDX-License-Identifier: AGPL-3.0-or-later
"""Load profile generation for domestic energy consumption."""

import contextlib
import datetime
import logging
import os
import random
import threading
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass
from typing import Optional, TYPE_CHECKING, TypeAlias

import numpy as np
import numpy.typing as npt
import pandas as pd

from solar_challenge.number_fields import POSITIVE, Interval, as_finite_float, as_whole_number, read_field
from solar_challenge.timebase import MINUTES_PER_DAY, MINUTES_PER_HOUR, SimulationWindow

if TYPE_CHECKING:
    from solar_challenge.ev import EVConfig

logger = logging.getLogger(__name__)


# The simulator's default annual electricity consumption by number of occupants, in
# kWh/year, excluding electric heating. It is the project's own interpolation by
# occupants, not Ofgem's Typical Domestic Consumption Values, which Ofgem publishes as
# low, medium and high bands. The name is frozen (FROZEN_SURFACE in
# tests/unit/test_public_api_surface.py).
OFGEM_TDCV_BY_OCCUPANTS: dict[int, float] = {
    1: 1800.0,
    2: 2700.0,
    3: 3200.0,
    4: 3900.0,
    5: 4500.0,  # 5 or more occupants: LoadConfig.get_annual_consumption extrapolates above 5
}


_HOUSEHOLD_OCCUPANTS = Interval(1, 10)


def household_occupant_count(occupants: float) -> int:
    """Return *occupants* as the household occupant count a LoadConfig holds, a whole number from 1 to 10.

    LoadConfig holds every count it is given to this rule. A caller holding a count as a
    float, such as a drawn or swept value, passes it through here to give LoadConfig the
    int its field is typed as. A whole-number float such as 3.0, or a numpy integer,
    gives the plain int it equals.

    Raises:
        ConfigurationError: If *occupants* is not a whole number from 1 to 10, naming
            household_occupants; a bool, Python's or numpy's, is not one.
    """
    return as_whole_number(occupants, "household_occupants", _HOUSEHOLD_OCCUPANTS)


@dataclass(frozen=True)
class LoadConfig:
    """Configuration for household load profile.

    Attributes:
        annual_consumption_kwh: Target annual electricity consumption in kWh.
            If not specified and household_occupants is set, derived from OFGEM_TDCV_BY_OCCUPANTS.
        household_occupants: Number of household occupants, read by the rule
            household_occupant_count states and held as the int it is. Affects
            consumption and profile shape.
        name: Optional identifier for the load profile
        use_stochastic: Use the windowed richardsonpy stochastic model (default True).
            richardsonpy is a hard dependency so this path is always available.
            Set False to force the deterministic Elexon Profile Class 1 shape.
        seed: Seed of the stochastic profile, read as a whole number and held as the
            int it is: any int reproduces its profile, and None draws fresh entropy on
            each call
    """

    annual_consumption_kwh: Optional[float] = None
    household_occupants: int = 3  # Default UK average household size
    name: str = ""
    # use_stochastic: richardsonpy is a hard dep so True uses the windowed
    # stochastic path by default; False forces the deterministic Elexon path.
    use_stochastic: bool = True
    seed: Optional[int] = None  # Seed for reproducible stochastic profiles

    def __post_init__(self) -> None:
        """Read each number setting."""
        read_field(self, "annual_consumption_kwh", as_finite_float, POSITIVE, optional=True)
        read_field(self, "household_occupants", as_whole_number, _HOUSEHOLD_OCCUPANTS)
        read_field(self, "seed", as_whole_number, optional=True)

    def get_annual_consumption(self) -> float:
        """Get annual consumption, deriving from occupants if not explicitly set.

        Returns:
            Annual consumption in kWh
        """
        if self.annual_consumption_kwh is not None:
            return self.annual_consumption_kwh

        # Derive from the by-occupants table, OFGEM_TDCV_BY_OCCUPANTS
        occupants = min(self.household_occupants, 5)  # Cap at 5 for lookup
        base_consumption = OFGEM_TDCV_BY_OCCUPANTS[occupants]

        # For households larger than 5, add 400 kWh per additional person
        if self.household_occupants > 5:
            extra_people = self.household_occupants - 5
            base_consumption += extra_people * 400.0

        return base_consumption


# One local calendar day's 1,440 one-minute power values in W, wall clock 00:00 to 23:59, in no time zone.
DaySimulator: TypeAlias = Callable[[datetime.date], npt.NDArray[np.float64]]

# One window's household. It draws randomness only from the module-level random and numpy.random
# generators, and never generates a load profile, which _rng_hand_off refuses inside a window.
HouseholdModel: TypeAlias = Callable[[LoadConfig, Sequence[datetime.date]], DaySimulator]


# Elexon Profile Class 1 (Domestic Unrestricted) typical shape
# Simplified as 48 half-hourly values representing relative demand
# Values normalized so sum = 1.0 for one day
# Based on typical UK domestic unrestricted profile shape
ELEXON_PROFILE_CLASS_1: list[float] = [
    # 00:00-05:30 (overnight low)
    0.012, 0.011, 0.010, 0.010, 0.009, 0.009, 0.009, 0.009, 0.010, 0.010, 0.012, 0.014,
    # 06:00-11:30 (morning rise and plateau)
    0.018, 0.024, 0.030, 0.034, 0.036, 0.035, 0.032, 0.030, 0.028, 0.026, 0.024, 0.023,
    # 12:00-17:30 (afternoon)
    0.022, 0.021, 0.021, 0.021, 0.022, 0.024, 0.028, 0.032, 0.036, 0.040, 0.044, 0.046,
    # 18:00-23:30 (evening peak and decline)
    0.046, 0.044, 0.040, 0.036, 0.032, 0.028, 0.024, 0.020, 0.017, 0.015, 0.014, 0.013,
]


# Seasonal scaling factors (higher in winter, lower in summer)
# Based on UK domestic consumption patterns
SEASONAL_FACTORS: dict[int, float] = {
    1: 1.25,   # January
    2: 1.20,   # February
    3: 1.10,   # March
    4: 0.95,   # April
    5: 0.85,   # May
    6: 0.80,   # June
    7: 0.75,   # July
    8: 0.75,   # August
    9: 0.85,   # September
    10: 0.95,  # October
    11: 1.10,  # November
    12: 1.20,  # December
}


def _normalize_profile(profile: list[float]) -> "np.ndarray[tuple[int], np.dtype[np.float64]]":
    """Normalize profile so it sums to 1.0."""
    arr: np.ndarray[tuple[int], np.dtype[np.float64]] = np.array(profile, dtype=np.float64)
    result: np.ndarray[tuple[int], np.dtype[np.float64]] = arr / arr.sum()
    return result


def _get_daily_profile_kwh(
    date: pd.Timestamp,
    annual_consumption_kwh: float,
) -> np.ndarray:
    """Get daily load profile in kWh for a specific date.

    Args:
        date: Date for the profile
        annual_consumption_kwh: Target annual consumption

    Returns:
        Array of 48 half-hourly energy values in kWh
    """
    # Base daily consumption (uniform across year)
    base_daily = annual_consumption_kwh / 365.0

    # Apply seasonal factor
    month = date.month
    seasonal_factor = SEASONAL_FACTORS.get(month, 1.0)

    # Scale base profile to get daily consumption
    daily_consumption = base_daily * seasonal_factor
    normalized_profile = _normalize_profile(ELEXON_PROFILE_CLASS_1)

    # Energy per half-hour period in kWh
    half_hourly_kwh = normalized_profile * daily_consumption

    return half_hourly_kwh


def _interpolate_half_hourly_to_minute(
    half_hourly_kwh: np.ndarray,
) -> np.ndarray:
    """Interpolate half-hourly energy to 1-minute power.

    Converts half-hourly energy (kWh) to 1-minute power (kW).
    Each half-hour's energy is divided equally across 30 minutes.

    Args:
        half_hourly_kwh: 48 half-hourly energy values in kWh

    Returns:
        1440 minute-by-minute power values in kW
    """
    # Each half-hour value becomes 30 identical minute values
    # Energy (kWh) per half hour = Power (kW) * 0.5 hours
    # So Power (kW) = Energy (kWh) / 0.5 = Energy (kWh) * 2
    minute_power = np.repeat(half_hourly_kwh * 2, 30)
    return minute_power


def richardsonpy_household(config: LoadConfig, days: Sequence[datetime.date]) -> DaySimulator:
    """The default HouseholdModel: richardsonpy's household for the window of days.

    It bypasses richardsonpy's ElectricLoad, which always simulates a full year: one
    occupancy chain runs over the window, with one set of appliances and lights, and
    the day simulator calls ElectricityProfile.power_sim once per date it is given.
    The day simulator refuses a date outside the window.
    """
    from richardsonpy.classes.occupancy import Occupancy
    from richardsonpy.classes.appliance import Appliances
    from richardsonpy.classes.lighting import load_lighting_profile
    from richardsonpy.classes.stochastic_el_load_wrapper import ElectricityProfile
    import richardsonpy.classes.electric_load as _el_mod

    inputs_dir = os.path.join(os.path.dirname(os.path.dirname(_el_mod.__file__)), "inputs")
    occupancy = Occupancy(
        number_occupants=min(config.household_occupants, 5),  # richardsonpy's cap
        initial_day=days[0].isoweekday(),
        nb_days=len(days),
    )
    # Appliances take 91% of the annual demand and lighting the rest, as in
    # ElectricLoad.calc_stoch_el_profile.
    appliances = Appliances(
        os.path.join(inputs_dir, "Appliances.csv"),
        annual_consumption=0.91 * config.get_annual_consumption(),
    )
    lights = load_lighting_profile(filename=os.path.join(inputs_dir, "LightBulbs.csv"), index=0)
    electricity = ElectricityProfile(appliances, lights)

    # A sinusoidal daylight for the lighting model, in W/m²: 6 am to 8 pm, peak at 1 pm.
    hour = np.arange(MINUTES_PER_DAY) / MINUTES_PER_HOUR
    daylight_irradiance = np.where(
        (hour >= 6.0) & (hour <= 20.0),
        100.0 * np.maximum(0.0, np.sin((hour - 6.0) * np.pi / 14.0)),
        0.0,
    )
    ten_minute_steps_per_day = 144

    def simulate_day(day: datetime.date) -> npt.NDArray[np.float64]:
        position = (day - days[0]).days
        if not 0 <= position < len(days):
            raise ValueError(
                f"richardsonpy_household was built for {days[0]} to {days[-1]}; "
                f"it cannot simulate {day}"
            )
        total_w, _lights_w, _appliances_w = electricity.power_sim(
            irradiation=daylight_irradiance,
            weekend=day.isoweekday() >= 6,
            day=day.timetuple().tm_yday,
            occupancy=occupancy.occupancy[
                ten_minute_steps_per_day * position : ten_minute_steps_per_day * (position + 1)
            ],
        )
        return np.asarray(total_w, dtype=np.float64)

    return simulate_day


def _calendar_days(first: datetime.date, last: datetime.date) -> list[datetime.date]:
    """The calendar dates from first through last, consecutive and ascending."""
    return [first + datetime.timedelta(days=offset) for offset in range((last - first).days + 1)]


_rng_lock = threading.Lock()


def _replace_rng_lock_in_forked_child() -> None:
    """A forked child must not inherit the lock held by a thread that does not exist in it."""
    global _rng_lock
    _rng_lock = threading.Lock()


if hasattr(os, "register_at_fork"):  # only where os.fork exists
    os.register_at_fork(after_in_child=_replace_rng_lock_in_forked_child)


class _HandOffThreadState(threading.local):
    """Whether the thread reading it is inside an RNG hand-off window; each thread reads its own."""

    in_window: bool = False


_this_thread = _HandOffThreadState()


def _generator_seeds(seed: Optional[int]) -> tuple[int, int | npt.NDArray[np.uint32 | np.uint64]]:
    """The seeds for random.seed and numpy.random.seed that a LoadConfig's seed stands for.

    A seed from 0 to 2**32 - 1 is both seeds, as it always was. Any other int seeds both
    from one numpy.random.SeedSequence of its magnitude and sign, so s and -s differ, and
    None from a fresh SeedSequence.
    """
    if seed is not None and 0 <= seed < 2**32:
        return seed, seed
    sequence = (
        np.random.SeedSequence()
        if seed is None
        else np.random.SeedSequence((abs(seed), int(seed < 0)))
    )
    state = sequence.generate_state(4)
    return int.from_bytes(state.tobytes(), "little"), state


@contextlib.contextmanager
def _rng_hand_off(seed: Optional[int]) -> Iterator[None]:
    """Hand the module-level random and numpy.random generators to one stochastic window at a time across threads.

    The window draws from both seeded from seed, fresh entropy when it is None, and the
    caller gets both back in the states it left them in, however the window ends.

    Raises:
        RuntimeError: If the calling thread is already inside a window, as when a household
            model generates a load profile: the hand-off's lock is not re-entrant, so that
            thread would otherwise wait on it forever.
    """
    if _this_thread.in_window:
        raise RuntimeError(
            "a household model must not generate a load profile: "
            "the RNG hand-off is not re-entrant"
        )
    random_seed, numpy_seed = _generator_seeds(seed)
    with _rng_lock:
        random_state, numpy_state = random.getstate(), np.random.get_state()
        _this_thread.in_window = True
        try:
            random.seed(random_seed)
            np.random.seed(numpy_seed)
            yield
        finally:
            _this_thread.in_window = False
            random.setstate(random_state)
            np.random.set_state(numpy_state)


def _household_day_watts(
    household_model: HouseholdModel, config: LoadConfig, days: Sequence[datetime.date]
) -> list[npt.NDArray[np.float64]]:
    """Each of days' power in W, simulated inside the RNG hand-off by the one household that household_model builds for them.

    Raises:
        ValueError: If a day's power is not 1,440 one-minute values.
    """
    with _rng_hand_off(config.seed):
        simulate_day = household_model(config, days)
        day_watts = []
        for day in days:
            watts = simulate_day(day)
            if len(watts) != MINUTES_PER_DAY:
                raise ValueError(
                    f"the household model simulated {len(watts)} minutes for {day}, "
                    f"not {MINUTES_PER_DAY}"
                )
            day_watts.append(watts)
    return day_watts


def _try_richardsonpy_profile(
    config: LoadConfig,
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
    timezone: str,
    household_model: HouseholdModel,
) -> Optional[pd.Series]:
    """Generate a windowed stochastic load profile from household_model, richardsonpy's by default.

    Builds one household for the window and simulates each of the window's
    calendar days once, in order: a 1-day request simulates 1 day, a 7-day
    request 7.

    Normalization is performed by scaling the raw stochastic shape, with
    scale_profile_to_energy, to the seasonal energy of those calendar days,
    each at the Elexon path's daily energy for its own month:
    target_window_kwh = Σ_days (annual/365 × SEASONAL_FACTORS[day's month]).

    The Elexon path is a defensive fallback: any exception returns None,
    including an error from the household model, a day that is not 1,440
    minutes long, and a window with no energy, which scale_profile_to_energy
    refuses to scale.

    Args:
        config: Load configuration
        start_date: Start of simulation period
        end_date: End of simulation period (inclusive)
        timezone: IANA timezone string
        household_model: Builds the window's household, whose day simulator
            gives each day's power in W

    Returns:
        Load profile Series if successful, None otherwise (triggers Elexon fallback)
    """
    try:
        # Normalise dates (strip any intra-day time component)
        start_norm = start_date.normalize()
        end_norm = end_date.normalize()
        if start_norm.tz is None:
            start_norm = start_norm.tz_localize(timezone)
        if end_norm.tz is None:
            end_norm = end_norm.tz_localize(timezone)

        # Calendar dates, not timedelta.days, which undercounts a window
        # across the 23-hour spring-forward day.
        days = _calendar_days(start_norm.date(), end_norm.date())

        # Concatenate all days and convert W → kW
        power_kw: np.ndarray = (
            np.concatenate(_household_day_watts(household_model, config, days)) / 1000.0
        )

        # Build 1-minute DatetimeIndex for the requested window.
        # Reuse the Elexon DST trim/pad pattern so index length is consistent.
        minute_index = pd.date_range(
            start=start_norm,
            end=end_norm + pd.Timedelta(days=1) - pd.Timedelta(minutes=1),
            freq="1min",
            tz=timezone,
        )

        # Trim or extend to match index length (handles DST transitions)
        if len(power_kw) > len(minute_index):
            power_kw = power_kw[: len(minute_index)]
        elif len(power_kw) < len(minute_index):
            avg = (
                power_kw[-MINUTES_PER_DAY:].mean()
                if len(power_kw) >= MINUTES_PER_DAY
                else power_kw.mean()
            )
            padding = np.full(len(minute_index) - len(power_kw), avg)
            power_kw = np.concatenate([power_kw, padding])

        profile = pd.Series(power_kw, index=minute_index, name="demand_kw")

        # Do NOT use ElectricLoad's do_normalization — on a 1-day window it
        # would force the full annual demand (~3400 kWh) into a single day.
        annual_kwh = config.get_annual_consumption()
        target_window_kwh = sum(
            annual_kwh / 365.0 * SEASONAL_FACTORS.get(day.month, 1.0) for day in days
        )
        return scale_profile_to_energy(profile, target_window_kwh)

    except Exception as exc:  # noqa: BLE001
        # Log a warning so the fallback is observable; a silent fallback would
        # hide API-mismatch regressions in production (only unit tests, via the
        # call-count assertions, would catch the silent degradation).
        logger.warning(
            "richardsonpy stochastic generation failed; falling back to Elexon "
            "deterministic profile: %s: %s",
            type(exc).__name__,
            exc,
        )
        return None


def generate_load_profile(
    config: LoadConfig,
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
    timezone: str = "Europe/London",
    ev_config: "Optional[EVConfig]" = None,
    *,
    household_model: HouseholdModel = richardsonpy_household,
) -> pd.Series:
    """Generate domestic load profile.

    Uses the windowed stochastic household_model, richardsonpy's by default,
    when config.use_stochastic is True (the default).  richardsonpy is a hard
    dependency so this path is always available.  Falls back to the
    deterministic Elexon Profile Class 1 shape only when use_stochastic=False,
    or defensively if the stochastic profile cannot be built: the household
    model raises an error, or its window has no energy to scale.

    A stochastic profile depends only on its LoadConfig: the call leaves the
    module-level random and numpy.random generators in the states it found
    them in, and stochastic windows run one at a time across threads.

    Creates a 1-minute resolution load profile for the specified date range,
    scaled to match the configured annual consumption using seasonal factors.

    If an EV configuration is provided, EV charging load is added to the
    household base load.

    Args:
        config: Load configuration with consumption and household parameters
        start_date: Start of simulation period
        end_date: End of simulation period (inclusive)
        timezone: IANA timezone string for output index
        ev_config: Optional EV configuration for charging load
        household_model: Called once per stochastic window with config and the
            window's dates; the day simulator it returns is called once per
            date. Unused when config.use_stochastic is False.

    Returns:
        Series with 1-minute DatetimeIndex and power values in kW
    """
    # Try the stochastic household model first if enabled
    if config.use_stochastic:
        result = _try_richardsonpy_profile(
            config, start_date, end_date, timezone, household_model
        )
        if result is not None:
            base_load = result
        else:
            # Fall back to Elexon Profile Class 1
            base_load = _generate_elexon_profile(config, start_date, end_date, timezone)
    else:
        # Fall back to Elexon Profile Class 1
        base_load = _generate_elexon_profile(config, start_date, end_date, timezone)

    # Add EV charging if configured
    if ev_config is not None:
        from solar_challenge.ev import generate_ev_charging_profile

        ev_load = generate_ev_charging_profile(
            ev_config, start_date, end_date, timezone
        )

        # Combine household and EV load
        # Align the profiles in case of any index mismatch
        combined_load = base_load.add(ev_load, fill_value=0.0)
        combined_load.name = "demand_kw"
        return combined_load

    return base_load


def _generate_elexon_profile(
    config: LoadConfig,
    start_date: pd.Timestamp,
    end_date: pd.Timestamp,
    timezone: str = "Europe/London",
) -> pd.Series:
    """Generate domestic load profile using Elexon Profile Class 1 shape.

    Creates a 1-minute resolution load profile for the specified date range,
    scaled to match the configured annual consumption.

    Args:
        config: Load configuration with annual consumption target
        start_date: Start of simulation period
        end_date: End of simulation period (inclusive)
        timezone: IANA timezone string for output index

    Returns:
        Series with 1-minute DatetimeIndex and power values in kW
    """
    # Get annual consumption from config (may be derived from occupants)
    annual_consumption = config.get_annual_consumption()

    # Ensure dates are timezone-aware
    if start_date.tz is None:
        start_date = start_date.tz_localize(timezone)
    if end_date.tz is None:
        end_date = end_date.tz_localize(timezone)

    # Create minute-by-minute index
    minute_index = pd.date_range(
        start=start_date,
        end=end_date + pd.Timedelta(days=1) - pd.Timedelta(minutes=1),
        freq="1min",
        tz=timezone,
    )

    # Generate profile for each day
    all_power: list[np.ndarray] = []
    current_date = start_date.normalize()

    while current_date <= end_date:
        daily_kwh = _get_daily_profile_kwh(current_date, annual_consumption)
        minute_power = _interpolate_half_hourly_to_minute(daily_kwh)
        all_power.append(minute_power)
        current_date += pd.Timedelta(days=1)

    # Concatenate all days
    power_values = np.concatenate(all_power)

    # Trim or extend to match index length (handle DST transitions)
    if len(power_values) > len(minute_index):
        power_values = power_values[: len(minute_index)]
    elif len(power_values) < len(minute_index):
        # Extend with last day's average
        avg = (
            power_values[-MINUTES_PER_DAY:].mean()
            if len(power_values) >= MINUTES_PER_DAY
            else power_values.mean()
        )
        padding = np.full(len(minute_index) - len(power_values), avg)
        power_values = np.concatenate([power_values, padding])

    return pd.Series(power_values, index=minute_index, name="demand_kw")


def energy_kwh(profile: pd.Series) -> float:
    """The energy in kWh a kW profile delivers: each row's kW times the hours its row lasts, the cadence SimulationWindow.of_index reads from its index.

    Args:
        profile: Power series in kW

    Returns:
        Total energy in kWh

    Raises:
        ValueError: As SimulationWindow.of_index does, if the profile's index is not
            a DatetimeIndex, is empty, has one row and no fixed-duration freq, or is
            not evenly spaced.
    """
    return SimulationWindow.of_index(profile.index).energy_kwh(profile)


def scale_profile_to_energy(
    profile: pd.Series,
    target_kwh: float,
) -> pd.Series:
    """Scale a power profile so that its energy_kwh is target_kwh.

    Args:
        profile: Power series in kW
        target_kwh: Target total energy in kWh

    Returns:
        Scaled power series in kW

    Raises:
        ValueError: If the profile's energy is zero, since no factor scales it
            to target_kwh; or as energy_kwh does, if no window describes the
            profile's index.
    """
    current_kwh = energy_kwh(profile)
    if current_kwh == 0:
        raise ValueError("Cannot scale profile with zero consumption")

    scale_factor = target_kwh / current_kwh
    return profile * scale_factor
