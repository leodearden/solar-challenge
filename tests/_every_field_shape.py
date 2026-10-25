# SPDX-License-Identifier: AGPL-3.0-or-later
"""A home whose stored config holds every field shape the stored-run format writes and reads.

home_of_every_field_shape(name) is a HomeConfig whose config.json holds nested dataclasses;
Optional dataclasses, set (the battery, its grid charging, the EV, the heat pump, the tariff
and the SEG tariff) and unset (the PV module's settings, stored as null); a tagged union (the
battery's dispatch strategy, whose tag no constructor takes); a tuple of fixed tuples (its peak
hours); a tuple of dataclasses (the tariff's periods); a Literal (the heat pump's type); and a
dict (the PV custom module params, whose keys are its own, not fields).
"""

from solar_challenge.battery import BatteryConfig
from solar_challenge.dispatch import GridChargeConfig, TOUOptimizedStrategyConfig
from solar_challenge.ev import EVConfig
from solar_challenge.heat_pump import HeatPumpConfig
from solar_challenge.home import HomeConfig
from solar_challenge.load import LoadConfig
from solar_challenge.location import Location
from solar_challenge.pv import PVConfig
from solar_challenge.seg import SEGTariff
from solar_challenge.tariff import TariffConfig


def home_of_every_field_shape(name: str = "Every Shape") -> HomeConfig:
    """A home named *name* whose stored config holds every field shape a save writes, as the module docstring lists them."""
    return HomeConfig(
        pv_config=PVConfig(
            capacity_kw=4.0,
            custom_module_params={"pdc0": 250.0, "gamma_pdc": -0.004},
        ),
        load_config=LoadConfig(annual_consumption_kwh=3200.0),
        battery_config=BatteryConfig(
            capacity_kwh=5.0,
            dispatch_strategy=TOUOptimizedStrategyConfig(peak_hours=((16, 19), (20, 22))),
            grid_charging=GridChargeConfig(target_soc_fraction=0.8),
        ),
        ev_config=EVConfig(charger_type="7kW", arrival_hour=18),
        heat_pump_config=HeatPumpConfig(heat_pump_type="ASHP"),
        location=Location.bristol(),
        name=name,
        tariff_config=TariffConfig.economy_7(),
        seg_tariff=SEGTariff(name="Octopus Outgoing", rate_pence_per_kwh=15.0),
    )
