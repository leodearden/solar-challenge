# SPDX-License-Identifier: AGPL-3.0-or-later
"""Load profile generation for domestic energy consumption."""

import calendar
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

from solar_challenge.boolean_fields import as_boolean
from solar_challenge.number_fields import POSITIVE, Interval, as_finite_float, as_whole_number, read_field
from solar_challenge.timebase import MINUTES_PER_DAY, MINUTES_PER_HOUR, ONE_MINUTE, LocalDay, SimulationWindow

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
            Set False to force the deterministic Elexon Profile Class 1 shape. Read as
            true or false: a bool, Python's or numpy's, is held as the Python bool it
            is, and any other value is refused
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
        """Read each number setting and the use_stochastic flag."""
        read_field(self, "annual_consumption_kwh", as_finite_float, POSITIVE, optional=True)
        read_field(self, "household_occupants", as_whole_number, _HOUSEHOLD_OCCUPANTS)
        object.__setattr__(self, "use_stochastic", as_boolean(self.use_stochastic, "use_stochastic"))
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


def _seasonal_day_energy_kwh(annual_kwh: float, day: datetime.date) -> float:
    """The household's energy on day: annual_kwh shared over the days of day's calendar year by their months' SEASONAL_FACTORS, so a whole calendar year delivers annual_kwh (docs/prds/load-composition-and-calendar-days.md decision 6)."""
    year_weight = sum(
        SEASONAL_FACTORS[month] * calendar.monthrange(day.year, month)[1] for month in SEASONAL_FACTORS
    )
    return annual_kwh * SEASONAL_FACTORS[day.month] / year_weight


def _elexon_minute_shape() -> npt.NDArray[np.float64]:
    """Elexon Profile Class 1's relative demand at each minute of the wall clock from 00:00: each half hour's value at each of its minutes."""
    return np.repeat(
        np.asarray(ELEXON_PROFILE_CLASS_1, dtype=np.float64),
        MINUTES_PER_DAY // len(ELEXON_PROFILE_CLASS_1),
    )


def _minutes_per_row(window: SimulationWindow) -> int:
    """How many minutes of the wall clock each of window's rows spans.

    Raises:
        ValueError: If window's cadence is not a whole number of minutes, naming it: a household
            profile gives each minute of the day, which a row must hold whole.
    """
    if window.cadence % ONE_MINUTE:
        raise ValueError(
            "A household profile gives each minute of the day, so its rows must span whole minutes: "
            f"got cadence={window.cadence!r}, {window.step_minutes:g} minutes"
        )
    return window.cadence // ONE_MINUTE


def _on_wall_clock(minute_profile: npt.NDArray[np.float64], day: LocalDay, minutes_per_row: int) -> pd.Series:
    """minute_profile, one value per minute of the wall clock from 00:00, on day's rows: each row the mean of the minutes it spans.

    A day the clocks go forward skips the hour they skip, and a day they go back plays the hour they repeat twice.
    """
    row_means = minute_profile.reshape(-1, minutes_per_row).mean(axis=1)
    return pd.Series(row_means[day.minute_of_day() // minutes_per_row], index=day.rows)


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


def _elexon_household_kw(annual_kwh: float, window: SimulationWindow) -> pd.Series:
    """The deterministic household on window's rows: the Elexon shape on each of its local days by wall clock, scaled to that day's seasonal energy.

    Raises:
        ValueError: If window's cadence is not a whole number of minutes dividing one hour, naming it.
    """
    minute_shape = _elexon_minute_shape()
    minutes_per_row = _minutes_per_row(window)
    return pd.concat(
        scale_profile_to_energy(
            _on_wall_clock(minute_shape, day, minutes_per_row), _seasonal_day_energy_kwh(annual_kwh, day.date)
        )
        for day in window.local_days()
    ).rename("demand_kw")


def _simulated_household_kw(
    config: LoadConfig, window: SimulationWindow, household_model: HouseholdModel
) -> Optional[pd.Series]:
    """The stochastic household on window's rows: household_model's days on the wall clock, the window scaled once to its days' seasonal energy.

    None, with a warning naming the failure, when the household model fails: it raises, as
    richardsonpy's imports, data files or day simulation can, or gives a day that is not
    1,440 minutes long. Reading the window, and placing and scaling the days, are the
    project's own steps, so their errors propagate.

    Raises:
        ValueError: If window's cadence is not a whole number of minutes dividing one hour,
            naming it, before the household is built; or if the simulated days have no
            energy, which scale_profile_to_energy refuses to scale.
    """
    minutes_per_row = _minutes_per_row(window)
    days = list(window.local_days())
    try:
        day_watts = _household_day_watts(household_model, config, [day.date for day in days])
    except Exception as exc:  # noqa: BLE001
        # Log a warning so the fallback is observable; a silent fallback would
        # hide API-mismatch regressions in production.
        logger.warning(
            "the household model failed; falling back to Elexon deterministic profile: %s: %s",
            type(exc).__name__,
            exc,
        )
        return None

    placed_kw = pd.concat(
        _on_wall_clock(np.asarray(watts, dtype=np.float64) / 1000.0, day, minutes_per_row)
        for watts, day in zip(day_watts, days, strict=True)
    )
    annual_kwh = config.get_annual_consumption()
    return scale_profile_to_energy(
        placed_kw.rename("demand_kw"), sum(_seasonal_day_energy_kwh(annual_kwh, day.date) for day in days)
    )


def generate_load_profile(
    config: LoadConfig,
    window: SimulationWindow,
    ev_config: "Optional[EVConfig]" = None,
    *,
    household_model: HouseholdModel = richardsonpy_household,
) -> pd.Series:
    """The household's demand in kW on window.rows(), EV charging included when ev_config is set.

    Each of the window's local days takes a profile of the minutes of its wall clock from 00:00
    to 23:59, placed on its rows by each row's local minute of the day: a day the clocks go
    forward skips 01:00-01:59, and a day they go back plays it twice. A row's value is the mean
    of the minutes it spans. Day d's seasonal energy E_d is the annual consumption times its
    month's SEASONAL_FACTORS weight over the weights of every day of its calendar year, so a
    whole calendar year delivers config.get_annual_consumption()
    (docs/prds/load-composition-and-calendar-days.md decisions 5, 6 and 15).

    With config.use_stochastic, the default, household_model builds one household for the
    window's dates and simulates each date once, in order, and the window is scaled once to
    the sum of its days' E_d, keeping the variation between its days. A stochastic profile
    depends only on its LoadConfig: the call leaves the module-level random and numpy.random
    generators in the states it found them in, and stochastic windows run one at a time
    across threads. Otherwise each day is the Elexon Profile Class 1 shape scaled to its own
    E_d. The Elexon profile also stands in, with a warning, when the household model itself
    fails: it raises, or gives a day that is not 1,440 minutes long.

    The EV charging profile is laid out a minute to a row from the window's first midnight,
    1,440 minutes a day, and read on the window's rows, so it needs one-minute rows.

    Args:
        config: Load configuration with consumption and household parameters
        window: The calendar days to generate, how long each of their rows lasts, and their
            clock's zone
        ev_config: Optional EV configuration for charging load
        household_model: Called once per stochastic window with config and the window's
            dates; the day simulator it returns is called once per date. Unused when
            config.use_stochastic is False.

    Returns:
        Series of power in kW on window.rows(), named demand_kw

    Raises:
        ValueError: Naming window's cadence, before any household is built, if it is not a
            whole number of minutes dividing one hour, or, with ev_config, not one minute; or
            if a stochastic window's simulated days have no energy.
    """
    if ev_config is not None and window.cadence != ONE_MINUTE:
        raise ValueError(
            "EV charging is laid out a minute to a row, so a profile with ev_config needs one-minute rows: "
            f"got cadence={window.cadence!r}, {window.step_minutes:g} minutes"
        )
    household_kw = None
    if config.use_stochastic:
        household_kw = _simulated_household_kw(config, window, household_model)
    if household_kw is None:
        household_kw = _elexon_household_kw(config.get_annual_consumption(), window)
    if ev_config is None:
        return household_kw

    from solar_challenge.ev import generate_ev_charging_profile

    ev_kw = generate_ev_charging_profile(
        ev_config, pd.Timestamp(window.first_day), pd.Timestamp(window.last_day), window.timezone
    ).reindex(household_kw.index, fill_value=0.0)
    return (household_kw + ev_kw).rename("demand_kw")


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
