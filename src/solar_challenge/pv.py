# SPDX-License-Identifier: AGPL-3.0-or-later
"""PV system configuration and modelling."""

import functools
import math
import warnings
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Optional, TypeAlias

import numpy as np
import pandas as pd
import pvlib
from pvlib.location import Location as PVLibLocation
from pvlib.modelchain import ModelChain
from pvlib.pvsystem import Array, FixedMount, PVSystem
from scipy.optimize import brentq

from solar_challenge.boolean_fields import as_boolean
from solar_challenge.errors import ConfigurationError
from solar_challenge.number_fields import (
    FRACTION,
    NON_NEGATIVE,
    POSITIVE,
    UNIT_INTERVAL,
    Interval,
    as_finite_float,
    as_finite_real,
    read_field,
)

if TYPE_CHECKING:
    from solar_challenge.location import Location


_TRANSMITTANCE_ABSORPTANCE = 0.9
"""NOCT-SAM's transmittance-absorptance, pvlib's noct_sam default, passed in each array's parameters so that the model and the bound on a module's efficiency read one value."""

_STEEPEST_TEMPERATURE_COEFFICIENT_PER_K = -0.01
"""The steepest temperature coefficient of maximum power a PVConfig sets: -1 %/K, steeper than every CECMod row's modelled one (docs/pv-module-settings.md)."""

_SETTABLE_MODULE_EFFICIENCY = Interval(0, _TRANSMITTANCE_ABSORPTANCE, low_open=True, high_open=True)
"""The module efficiencies a PVConfig sets: above 0 and below NOCT-SAM's transmittance-absorptance, at which a cell no longer heats (docs/pv-module-settings.md)."""

_SETTABLE_TEMPERATURE_COEFFICIENT_PER_K = Interval(
    _STEEPEST_TEMPERATURE_COEFFICIENT_PER_K, 0, high_open=True
)
"""The temperature coefficients of maximum power a PVConfig sets, per K: from the steepest to below 0."""

_SYSTEM_AGE_YEARS = NON_NEGATIVE
"""The system ages, in years, that PVConfig and calculate_degradation_factor admit."""

_DEGRADATION_RATE_PER_YEAR = UNIT_INTERVAL
"""The annual degradation rates, as fractions of rated capacity, that PVConfig and calculate_degradation_factor admit."""

_PVWATTS_MODULE_KEYS = frozenset({"pdc0", "gamma_pdc"})

_CEC_SINGLE_DIODE_MODULE_KEYS = frozenset(
    {"alpha_sc", "a_ref", "I_L_ref", "I_o_ref", "R_sh_ref", "R_s", "Adjust"}
)
"""calcparams_cec's module parameters, which pvlib's CEC single-diode model reads."""

_SAPM_DC_MODULE_KEYS = frozenset(
    {
        "C0", "C1", "C2", "C3", "Isco", "Impo", "Voco", "Vmpo",
        "Aisc", "Aimp", "Bvoco", "Mbvoc", "Bvmpo", "Mbvmp", "N", "Cells_in_Series",
    }
)
"""The module parameters pvlib's sapm reads into the power and voltages an inverter reads. IXO, IXXO and C4 to C7 are left out: pvlib marks them not required and reads them only into i_x and i_xx, which no inverter model reads, and 10 SandiaMod rows give them NaN."""

_PVSYST_ONLY_MODULE_KEYS = frozenset({"gamma_ref", "mu_gamma", "R_sh_0", "R_sh_exp", "cells_in_series"})
"""The module parameters only pvlib's PVsyst single-diode model reads: calcparams_pvsyst's, less those _CEC_SINGLE_DIODE_MODULE_KEYS and _OPTIONAL_MODULE_KEYS hold, so not the whole PVsyst form."""

_OPTIONAL_MODULE_KEYS = frozenset(
    {"EgRef", "dEgdT", "irrad_ref", "temp_ref", "k", "FD", "n", "K", "L", "n_ar"}
)
"""The module parameters pvlib defaults when a module lacks them: calcparams_cec and calcparams_desoto read EgRef, dEgdT, irrad_ref and temp_ref, and calcparams_pvsyst all but dEgdT; pvwatts_dc reads temp_ref and k; ModelChain's effective irradiance reads FD; the physical IAM reads n, K, L and n_ar."""

_MODULE_KEYS_READ_AS_NUMBERS = (
    frozenset({"gamma_pdc", "T_NOCT", "A_c", "V_mp_ref"})
    | _CEC_SINGLE_DIODE_MODULE_KEYS
    | _SAPM_DC_MODULE_KEYS
    | _PVSYST_ONLY_MODULE_KEYS
    | _OPTIONAL_MODULE_KEYS
)
"""The module parameters besides its rating (_module_rating_w) that pvlib's model chain, NOCT-SAM and the string wiring read as numbers, which _require_module_values checks as finite numbers, each inside its _MODULE_NUMBER_DOMAINS domain where it has one: PVWatts' gamma_pdc, the CEC single-diode, SAPM DC and PVsyst parameters, the keys pvlib defaults, NOCT-SAM's T_NOCT and A_c, and the V_mp_ref that wires the strings. No other key is read as a number: SAPM's i_x and i_xx parameters, which no inverter model reads (_SAPM_DC_MODULE_KEYS), go unchecked; so do keys this chain's models never read, such as SAPM's A0 to A4, B0 to B5, A, B and DTC, read only by SAPM's spectral, IAM and temperature models, none of which the chain runs, and a CECMod row's Technology; and pvwatts_dc's cap_adjustment is a flag (_MODULE_KEYS_READ_AS_FLAGS)."""

_ABSOLUTE_ZERO_C = -273.15
"""Absolute zero in °C: pvlib adds 273.15 to a module's temp_ref to get kelvin."""

_MODULE_NUMBER_DOMAINS: Mapping[str, Interval] = MappingProxyType(
    {
        "temp_ref": Interval(_ABSOLUTE_ZERO_C, math.inf, low_open=True),
        "irrad_ref": POSITIVE,
        "I_L_ref": POSITIVE,
    }
)
"""The domains of the module numbers a model divides by or whose sign it assumes, inside which _require_module_values reads them: pvlib's single-diode models divide by temp_ref in kelvin and by irrad_ref, and _adjust_bracket's photocurrent-positive bracket needs a positive I_L_ref. Each key is one of _MODULE_KEYS_READ_AS_NUMBERS, as _number_families checks at import; the rule reads every other key of that set as any finite number (docs/pv-module-settings.md §2)."""

_MODULE_KEYS_READ_AS_FLAGS = frozenset({"cap_adjustment"})
"""The module parameters pvlib reads by their truthiness, which _require_module_values checks as true or false: pvwatts_dc's cap_adjustment, which applies its k adjustment only at and below 1000 W/m² when true."""

_ModuleValueReader: TypeAlias = Callable[[object, str], object]
"""A reader of a module parameter's value under its field name, refusing a value it does not admit with a ConfigurationError naming the field and the value."""


def _one_reader_per_key(
    *families: tuple[frozenset[str], _ModuleValueReader],
) -> Mapping[str, _ModuleValueReader]:
    """Each key of the (keys, reader) families mapped to its family's reader, refusing a key two families hold, whose second reader would silently replace the first."""
    readers: dict[str, _ModuleValueReader] = {}
    for keys, reader in families:
        if shared := sorted(keys & readers.keys()):
            raise RuntimeError(f"Module parameters {shared} are in two families of checked keys")
        readers.update(dict.fromkeys(keys, reader))
    return MappingProxyType(readers)


def _number_families(
    keys: frozenset[str], domains: Mapping[str, Interval]
) -> tuple[tuple[frozenset[str], _ModuleValueReader], ...]:
    """The (keys, reader) families that read each of keys as a finite number, inside its domain for a key domains holds, refusing a domain whose key is not one of keys, which would check a key no model reads as a number and leave the key meant read as any finite number."""
    if stray := sorted(domains.keys() - keys):
        raise RuntimeError(f"Module parameters {stray} have a domain but are not read as numbers")
    return (
        (keys.difference(domains.keys()), as_finite_real),
        *(
            (frozenset({key}), functools.partial(as_finite_real, within=domain))
            for key, domain in domains.items()
        ),
    )


_MODULE_VALUE_READERS = _one_reader_per_key(
    *_number_families(_MODULE_KEYS_READ_AS_NUMBERS, _MODULE_NUMBER_DOMAINS),
    (_MODULE_KEYS_READ_AS_FLAGS, as_boolean),
)
"""The reader with which _require_module_values reads each module parameter it checks: as_finite_real for a number, inside its _MODULE_NUMBER_DOMAINS domain for a key that has one, and as_boolean for a flag."""


def _is_pvwatts_module(module_params: Mapping[str, float]) -> bool:
    """Whether the module has the parameters pvlib infers its PVWatts DC model from."""
    return _PVWATTS_MODULE_KEYS <= module_params.keys()


def _is_cec_single_diode_module(module_params: Mapping[str, float]) -> bool:
    """Whether the module has every parameter pvlib's CEC single-diode model reads."""
    return _CEC_SINGLE_DIODE_MODULE_KEYS <= module_params.keys()


def _require_module_values(module_params: Mapping[str, object]) -> None:
    """Refuse a module that gives a key _MODULE_VALUE_READERS names a value its reader refuses: one of _MODULE_KEYS_READ_AS_NUMBERS as anything but a finite number, text that reads as one included, or as one outside its _MODULE_NUMBER_DOMAINS domain, or one of _MODULE_KEYS_READ_AS_FLAGS as anything but true or false, since pvlib, NOCT-SAM and the wiring read the module's own values; no other key is checked, such as a CECMod row's Technology text, which no model reads.

    A key the module lacks takes pvlib's default; one given as None is refused. The keys
    are read in sorted order, so when several are bad the first refusal does not vary with
    PYTHONHASHSEED, as the iteration order of a set of strings does.
    """
    for key in sorted(_MODULE_VALUE_READERS.keys() & module_params.keys()):
        _MODULE_VALUE_READERS[key](module_params[key], f"Module parameter {key}")


def _require_template_takes_temperature_coefficient(
    template: Mapping[str, float], coefficient: float
) -> None:
    """Refuse a template from which coefficient cannot derive the module.

    That is one in neither form (CEC single-diode, whose Adjust coefficient solves, or
    PVWatts, whose gamma_pdc it sets), or a CEC template on which no Adjust in
    _adjust_bracket reaches it (_require_adjust_reaches).
    """
    if _is_cec_single_diode_module(template):
        _require_adjust_reaches(template, coefficient)
    elif not _is_pvwatts_module(template):
        raise ConfigurationError(
            f"temperature_coefficient={coefficient} needs module parameters in CEC "
            f"single-diode form ({', '.join(sorted(_CEC_SINGLE_DIODE_MODULE_KEYS))}), whose "
            f"Adjust it solves, or in PVWatts form ({', '.join(sorted(_PVWATTS_MODULE_KEYS))}), "
            "whose gamma_pdc it sets; the module is in neither"
        )


PVWATTS_DEFAULT_SYSTEM_LOSSES = float(pvlib.pvsystem.pvwatts_losses()) / 100
"""PVWatts v5's default loss budget, pvlib's pvwatts_losses() as a fraction: PVConfig.system_losses's default (docs/pv-system-losses.md)."""


@dataclass(frozen=True)
class PVConfig:
    """Configuration for a photovoltaic system.

    Construction reads every number setting as a finite number inside its range and holds
    it as a float, each refusal a ConfigurationError naming the field and the value.

    Attributes:
        capacity_kw: Rated DC capacity in kilowatts
        azimuth: Panel orientation in degrees (0=North, 90=East, 180=South, 270=West)
        tilt: Panel tilt angle from horizontal in degrees (0=flat, 90=vertical)
        name: Optional identifier for the system

        # Panel parameters (PV-004; docs/pv-module-settings.md)
        module_efficiency: The module's efficiency at STC, its rating over A_c × 1000 W/m².
            None keeps the template module's own; a set value, above 0 and below 0.9, sets
            the template's A_c, so it acts through NOCT-SAM's cell temperature
        temperature_coefficient: The module's temperature coefficient of maximum power at
            STC, per K. None keeps the template module's own modelled one; a set value,
            from -0.01 to below 0, solves a CEC single-diode template's Adjust, keeping its
            STC point, and sets its gamma_r, or sets a PVWatts template's gamma_pdc. A
            template in neither form is refused, and so is a custom CEC template whose
            alpha_sc is 0 or on which no Adjust reaches the value, at construction and at use
        custom_module_params: Optional custom pvlib module parameters dict, the template
            the two fields above derive from; None takes DEFAULT_CEC_MODULE's row
            (cec_module_params reads any other CEC row). The cells take NOCT-SAM's
            temperature from the module's T_NOCT and its rating / (A_c × 1000), with
            DEFAULT_CEC_MODULE's value for either key the module lacks
            (docs/pv-cell-temperature.md). Construction and use refuse custom
            parameters that give a key the number rule checks as anything but a
            finite number, text that reads as one included, temp_ref at or below
            -273.15, irrad_ref or I_L_ref at or below 0, or cap_adjustment as
            anything but true or false (_require_module_values;
            docs/pv-module-settings.md), even where a set field replaces that key.
            They also refuse
            custom parameters with no rating or a rating (pdc0 or STC) that is not a
            finite number above 0, or whose cells NOCT-SAM cannot heat, reading the
            area a set module_efficiency gives

        # Inverter parameters (PV-005)
        inverter_efficiency: Inverter efficiency at rated output (default 0.96 = 96%), as the
            CEC inverter's Paco / Pdco and the PVWatts inverter's nominal efficiency;
            custom_inverter_params carry their own (docs/pv-inverter-efficiency.md)
        inverter_capacity_kw: AC capacity in kW (default = DC capacity)
        custom_inverter_params: Optional custom pvlib inverter parameters dict

        # Degradation parameters (PV-DGR)
        system_age_years: Age of the PV system in years (default 0.0 = new system); its
            ageing lowers each array's DC power before the inverter, with the system losses
        degradation_rate_per_year: Annual capacity degradation as a fraction
            (default 0.005 = 0.5%/year, typical for crystalline silicon panels)

        # System losses
        system_losses: Fraction of each array's DC power lost before the inverter to soiling,
            shading, mismatch, wiring, connections, light-induced degradation, nameplate rating
            and availability (default PVWatts v5's 14.08%; docs/pv-system-losses.md)
    """

    capacity_kw: float
    azimuth: float = 180.0  # South-facing default (UK optimal)
    tilt: float = 35.0  # Optimal for UK latitude
    name: str = ""

    # Panel parameters (PV-004)
    module_efficiency: Optional[float] = None
    temperature_coefficient: Optional[float] = None
    custom_module_params: Optional[dict[str, float]] = None

    # Inverter parameters (PV-005)
    inverter_efficiency: float = 0.96  # 96% efficiency
    inverter_capacity_kw: Optional[float] = None  # Defaults to DC capacity
    custom_inverter_params: Optional[dict[str, float]] = None

    # Degradation parameters (PV-DGR)
    system_age_years: float = 0.0  # New system (no degradation)
    degradation_rate_per_year: float = 0.005  # 0.5%/year (typical crystalline silicon)

    # System losses
    system_losses: float = PVWATTS_DEFAULT_SYSTEM_LOSSES

    def __post_init__(self) -> None:
        """Read each number setting, then refuse custom module parameters that give a key a value _require_module_values refuses, that cannot take a set temperature coefficient (_require_template_takes_temperature_coefficient), or that have no rating, or one that is not a finite number above 0, or cells NOCT-SAM cannot heat (_require_cells_noct_sam_can_heat); use runs these rules too."""
        read_field(self, "capacity_kw", as_finite_float, POSITIVE)
        read_field(self, "azimuth", as_finite_float, Interval(0, 360))
        read_field(self, "tilt", as_finite_float, Interval(0, 90))
        read_field(self, "module_efficiency", as_finite_float, _SETTABLE_MODULE_EFFICIENCY, optional=True)
        read_field(
            self,
            "temperature_coefficient",
            as_finite_float,
            _SETTABLE_TEMPERATURE_COEFFICIENT_PER_K,
            optional=True,
        )
        read_field(self, "inverter_efficiency", as_finite_float, FRACTION)
        read_field(self, "inverter_capacity_kw", as_finite_float, POSITIVE, optional=True)
        read_field(self, "system_age_years", as_finite_float, _SYSTEM_AGE_YEARS)
        read_field(self, "degradation_rate_per_year", as_finite_float, _DEGRADATION_RATE_PER_YEAR)
        read_field(self, "system_losses", as_finite_float, Interval(0, 1, high_open=True))
        if self.custom_module_params is not None:
            _require_module_values(self.custom_module_params)
            if self.temperature_coefficient is not None:
                _require_template_takes_temperature_coefficient(
                    self.custom_module_params, self.temperature_coefficient
                )
            _require_cells_noct_sam_can_heat(_template_with_set_efficiency(self))

    @property
    def effective_inverter_capacity_kw(self) -> float:
        """Get effective inverter capacity (defaults to DC capacity)."""
        return self.inverter_capacity_kw if self.inverter_capacity_kw is not None else self.capacity_kw

    @classmethod
    def default_4kw(cls) -> "PVConfig":
        """Create a typical UK domestic 4 kW system.

        Returns:
            PVConfig with 4 kW, south-facing, 35° tilt
        """
        return cls(
            capacity_kw=4.0,
            azimuth=180.0,
            tilt=35.0,
            name="4 kW domestic system"
        )


@functools.cache
def _shared_sam_library(name: str) -> pd.DataFrame:
    """pvlib's parsed SAM parameter library `name`, read once per process and shared by every reader.

    No reader edits it, and none gives a caller a view of it: what leaves it is
    values the caller owns, such as _cec_library_row's dict or the frozen
    CecInverter values usable_cec_inverters builds.
    """
    return pvlib.pvsystem.retrieve_sam(name)


def _require_cec_library_row(library: str, name: str) -> None:
    """Refuse a name with no row in pvlib's CEC library `library`, CECMod or CECInverter, from which a system takes that row's parameters."""
    if name not in _shared_sam_library(library).columns:
        raise ValueError(f"pvlib's {library} library has no row named {name!r}")


def _cec_library_row(library: str, name: str) -> dict[str, float]:
    """The named row of pvlib's CEC library `library` as parameters of the caller's own, refusing a name with no row there."""
    _require_cec_library_row(library, name)
    return dict(_shared_sam_library(library)[name])


DEFAULT_CEC_MODULE = "Canadian_Solar_Inc__CS1U_400MS"
"""The row of pvlib's CEC module library (CECMod) that a PVConfig without custom_module_params wires: a 400 W-class monocrystalline module representative of modern domestic panels."""


def cec_module_params(name: str) -> dict[str, float]:
    """The named row of pvlib's CEC module library as module parameters of the caller's own, e.g. for PVConfig.custom_module_params."""
    return _cec_library_row("CECMod", name)


def create_simple_module_params(
    efficiency: float = 0.20,
    temperature_coefficient: float = -0.004,
    module_power_w: float = 400.0,
) -> dict[str, float]:
    """Create simplified module parameters from basic specifications.

    Uses the PVWatts model, which needs only each module's power at STC and its
    temperature coefficient. This allows users to specify custom panel
    characteristics without needing the full CEC parameter set.

    Args:
        efficiency: Module efficiency as fraction (e.g., 0.20 for 20%). It sets the
            module's area, A_c = module_power_w / (efficiency × 1000 W/m²), and so,
            through NOCT-SAM, how hot its cells run (docs/pv-cell-temperature.md)
        temperature_coefficient: Power temperature coefficient per °C
            (e.g., -0.004 for -0.4%/°C)
        module_power_w: Each module's power at STC in watts. A system holds
            capacity_kw / module_power_w modules, and pvlib's PVWatts DC model
            scales this rating by that module count.

    Returns:
        Dict of module parameters compatible with pvlib PVWatts model

    Example:
        >>> params = create_simple_module_params(efficiency=0.22, temperature_coefficient=-0.003)
        >>> params['pdc0']  # Each module's power at STC
        400.0
    """
    # PVWatts model parameters
    # pdc0 is each module's nominal DC power at STC (1000 W/m² irradiance)
    # gamma_pdc is the temperature coefficient (negative)
    return {
        "pdc0": module_power_w,
        "gamma_pdc": temperature_coefficient,
        "A_c": module_power_w / (efficiency * 1000),
        "STC": module_power_w,
    }


def create_simple_inverter_params(
    efficiency: float = 0.96,
    capacity_w: float = 4000.0,
) -> dict[str, float]:
    """Create simplified inverter parameters from basic specifications.

    Uses a simple efficiency model. When DC power exceeds inverter
    capacity, output is clipped to the rated capacity. Its Sandia-form
    parameters read the DC voltage, so they suit a module with a voltage model
    such as the default CEC module; a create_simple_module_params module takes
    the automatic PVWatts inverter instead, or the parameters that
    create_pvwatts_inverter_params returns.

    Args:
        efficiency: Inverter efficiency as fraction (e.g., 0.96 for 96%)
        capacity_w: AC power capacity in watts

    Returns:
        Dict of inverter parameters for a simple efficiency model

    Example:
        >>> params = create_simple_inverter_params(efficiency=0.97, capacity_w=5000.0)
        >>> params['Paco']
        5000.0
    """
    # Simple inverter model: efficiency-based with capacity limit
    # Paco is the AC power output rating (used for clipping)
    return {
        "Paco": capacity_w,  # AC power capacity (watts)
        "Pdco": capacity_w / efficiency,  # DC power at which Paco is reached
        "Vdco": 400.0,  # Nominal DC voltage (typical)
        "Pso": 0.0,  # Self-consumption (watts)
        "C0": -0.0,  # Coefficient for Paco formula
        "C1": 0.0,  # Coefficient for Pso formula
        "C2": 0.0,  # Coefficient for Co formula
        "C3": 0.0,  # Coefficient for C1 formula
        "Pnt": 0.0,  # Night tare loss (watts)
        "efficiency": efficiency,  # Store for reference
    }


def create_pvwatts_inverter_params(
    efficiency: float = 0.96,
    capacity_w: float = 4000.0,
) -> dict[str, float]:
    """Create pvlib PVWatts inverter parameters from basic specifications.

    pvlib's PVWatts inverter reads no DC voltage, so it is the inverter for a
    create_simple_module_params module. When DC power exceeds the inverter's
    capacity, output is clipped to capacity_w.

    Args:
        efficiency: Inverter nominal efficiency as fraction (e.g., 0.96 for 96%)
        capacity_w: AC power capacity in watts

    Returns:
        Dict of inverter parameters compatible with pvlib PVWatts inverter model

    Example:
        >>> params = create_pvwatts_inverter_params(efficiency=0.97, capacity_w=5000)
        >>> params['eta_inv_nom']
        0.97
    """
    # pvlib caps AC output at eta_inv_nom x pdc0, so pdc0 is the DC power at
    # which the inverter reaches capacity_w
    return {
        "pdc0": capacity_w / efficiency,
        "eta_inv_nom": efficiency,
    }


@dataclass(frozen=True)
class _StringGroup:
    """Equal series strings that share one MPPT input."""

    modules_per_string: int
    strings: int


_Wiring = tuple[_StringGroup, ...]

_BATTERY_BUS_MAX_V = 60.0
_MICROINVERTER_MAX_W = 1500.0


@dataclass(frozen=True)
class CecInverter:
    """The catalogue numbers that decide whether a CEC inverter suits an array, under the name of its row in pvlib's CEC library."""

    name: str
    paco_w: float
    vdco_v: float
    mppt_low_v: float
    mppt_high_v: float

    def __post_init__(self) -> None:
        _require_cec_library_row("CECInverter", self.name)

    def admits(self, string_voltage_v: float) -> bool:
        return self.mppt_low_v <= string_voltage_v <= self.mppt_high_v

    @property
    def is_battery_inverter(self) -> bool:
        """Whether its DC input is a battery bus, which PV reaches only through a charge controller.

        That is a nominal DC voltage no higher than a 48 V bank's, at a rating
        above any module-level inverter's. The CEC does not flag these;
        docs/pv-inverter-string-matching.md §7 lists the rows this matches and
        why the cut sits there.
        """
        return self.vdco_v <= _BATTERY_BUS_MAX_V and self.paco_w > _MICROINVERTER_MAX_W


@functools.cache
def usable_cec_inverters() -> tuple[CecInverter, ...]:
    """CEC inverters with a positive finite rating, start-up power, nominal voltage and MPPT window.

    Read once per process. A positive start-up power (Pso) keeps pvlib's
    multi-input Sandia model finite where the DC power is zero.
    """
    catalogue = _shared_sam_library("CECInverter")
    numbers = catalogue.loc[["Paco", "Pso", "Vdco", "Mppt_low", "Mppt_high"]].T.apply(
        pd.to_numeric, errors="coerce"
    )
    usable = numbers[((numbers > 0) & (numbers < float("inf"))).all(axis=1)]
    return tuple(
        CecInverter(name, paco_w, vdco_v, mppt_low_v, mppt_high_v)
        for name, paco_w, vdco_v, mppt_low_v, mppt_high_v in zip(
            usable.index,
            usable["Paco"],
            usable["Vdco"],
            usable["Mppt_low"],
            usable["Mppt_high"],
        )
    )


@functools.cache
def candidate_cec_inverters() -> tuple[CecInverter, ...]:
    """The usable CEC inverters a PV array can be wired to, which create_pv_system and create_model_chain pick from: every one but the battery inverter/chargers."""
    return tuple(
        inverter for inverter in usable_cec_inverters() if not inverter.is_battery_inverter
    )


def _wiring_within_window(
    module_count: int, module_vmp_v: float, inverter: CecInverter
) -> Optional[_Wiring]:
    """The fewest near-equal series strings whose STC voltage (modules × V_mp_ref) lies inside the inverter's MPPT window.

    Fewer strings are longer strings, so if the shortest of these misses the
    window's floor, every other near-equal split does too.

    Colder cells lift the operating V_mp above the window's ceiling on some
    hours; docs/pv-inverter-string-matching.md measures that and records why
    strings are not sized on a cold-corrected V_mp.
    """
    longest = math.floor(inverter.mppt_high_v / module_vmp_v)
    if longest < 1:
        return None
    string_count = math.ceil(module_count / longest)
    shorter, longer_count = divmod(module_count, string_count)
    wiring = tuple(
        group
        for group in (
            _StringGroup(shorter + 1, longer_count),
            _StringGroup(shorter, string_count - longer_count),
        )
        if group.strings > 0
    )
    if all(inverter.admits(group.modules_per_string * module_vmp_v) for group in wiring):
        return wiring
    return None


def _inverters_with_wiring(
    module_count: int, module_vmp_v: float, candidates: Iterable[CecInverter]
) -> Iterator[tuple[CecInverter, _Wiring]]:
    """Each candidate whose MPPT window takes the strings, with that wiring."""
    for inverter in candidates:
        wiring = _wiring_within_window(module_count, module_vmp_v, inverter)
        if wiring is not None:
            yield inverter, wiring


def _ranking_key(
    target_w: float,
    module_count: int,
    module_vmp_v: float,
    inverter: CecInverter,
    wiring: _Wiring,
) -> tuple[float, int, float, str]:
    """Nearest rating, then the simplest wiring, then the nominal voltage nearest the strings', then the name.

    The name comes last so the catalogue's column order never decides a tie.
    """
    string_count = sum(group.strings for group in wiring)
    mean_string_vmp_v = module_count / string_count * module_vmp_v
    return (
        abs(inverter.paco_w - target_w),
        string_count,
        abs(inverter.vdco_v - mean_string_vmp_v),
        inverter.name,
    )


def _voltage_matched_cec_inverter(
    ac_capacity_kw: float,
    module_count: int,
    module_vmp_v: float,
    candidates: Iterable[CecInverter],
) -> tuple[CecInverter, _Wiring]:
    """The candidate rated nearest the AC capacity whose MPPT window takes the strings, and that wiring."""
    target_w = ac_capacity_kw * 1000
    admitted = list(_inverters_with_wiring(module_count, module_vmp_v, candidates))
    if not admitted:
        raise ValueError(
            f"No candidate CEC inverter's MPPT window admits a series string of {module_count} "
            f"modules at V_mp_ref={module_vmp_v} V"
        )
    return min(
        admitted,
        key=lambda pair: _ranking_key(target_w, module_count, module_vmp_v, *pair),
    )


@dataclass(frozen=True)
class _Inverter:
    """A PVSystem's inverter: its pvlib parameters, under the name of the CEC library row they come from, or None for custom or PVWatts parameters."""

    name: Optional[str]
    parameters: dict[str, float]


def _cec_library_inverter(name: str, efficiency: float) -> _Inverter:
    """The named row of pvlib's CEC inverter library, with Pdco set so that it runs at efficiency at rated output."""
    parameters = _cec_library_row("CECInverter", name)
    parameters["Pdco"] = parameters["Paco"] / efficiency
    return _Inverter(name, parameters)


def _pvwatts_inverter(config: PVConfig) -> dict[str, float]:
    """pvlib's PVWatts inverter at the configured AC capacity and nominal efficiency."""
    return create_pvwatts_inverter_params(
        efficiency=config.inverter_efficiency,
        capacity_w=config.effective_inverter_capacity_kw * 1000,
    )


def _module_parameters(config: PVConfig) -> dict[str, float]:
    """The module's parameters, of the caller's own: its template with each set field applied in the template's own terms.

    The template is a copy of the custom module parameters, or DEFAULT_CEC_MODULE's
    row (_template_with_set_efficiency). An unset field leaves the template as it is
    (docs/pv-module-settings.md). Custom parameters are first refused, as at
    construction, if they give a key a value _require_module_values refuses.
    """
    if config.custom_module_params is not None:
        _require_module_values(config.custom_module_params)
    module_params = _template_with_set_efficiency(config)
    if config.temperature_coefficient is None:
        return module_params
    return _with_temperature_coefficient(module_params, config.temperature_coefficient)


def _template_with_set_efficiency(config: PVConfig) -> dict[str, float]:
    """The module config wires but for a set temperature coefficient, which changes none of the keys NOCT-SAM's check reads (the rating, T_NOCT and A_c): a copy of the custom module parameters, or DEFAULT_CEC_MODULE's row, with a set module_efficiency's area."""
    if config.custom_module_params is not None:
        template = dict(config.custom_module_params)
    else:
        template = cec_module_params(DEFAULT_CEC_MODULE)
    if config.module_efficiency is None:
        return template
    return _with_module_efficiency(template, config.module_efficiency)


def _with_module_efficiency(template: Mapping[str, float], efficiency: float) -> dict[str, float]:
    """The template with the area A_c over which its rating is efficiency: rating / (efficiency × 1000 W/m²)."""
    return {**template, "A_c": _module_rating_w(template) / (efficiency * 1000)}


_GAMMA_HALF_STEP_K = 0.5
"""The half-width, in K, of the central difference over 25 °C that models a module's temperature coefficient."""

_SERVICE_CELL_TEMPERATURES_C = (-40.0, 85.0)
"""IEC 61215's thermal-cycling range of cell temperatures, in °C, over which a derived module's photocurrent stays positive."""


def _with_temperature_coefficient(
    template: Mapping[str, float], coefficient: float
) -> dict[str, float]:
    """The template with coefficient as its temperature coefficient of maximum power, in the template's own form.

    A CEC single-diode template gets the Adjust at which its modelled coefficient is
    coefficient (_adjust_giving), which keeps its STC point, and gamma_r = 100 ×
    coefficient; a PVWatts template gets gamma_pdc = coefficient; a template in both
    forms gets both, so whichever DC model pvlib infers reads it. A template from which
    coefficient cannot derive the module is refused first
    (_require_template_takes_temperature_coefficient).
    """
    _require_template_takes_temperature_coefficient(template, coefficient)
    module_params = dict(template)
    if _is_cec_single_diode_module(template):
        module_params["Adjust"] = _adjust_giving(template, coefficient)
        module_params["gamma_r"] = 100 * coefficient
    if _is_pvwatts_module(template):
        module_params["gamma_pdc"] = coefficient
    return module_params


def _require_adjust_reaches(template: Mapping[str, float], coefficient: float) -> None:
    """Refuse a coefficient beyond the CEC template's reach: its alpha_sc is 0 (_adjust_bracket), or its modelled temperature coefficients at the bracket's ends do not straddle coefficient, which a NaN end never does, such as that of a module with no power at STC (_modelled_gamma).

    Construction and use both run it (_require_template_takes_temperature_coefficient).
    """
    low, high = _adjust_bracket(template, coefficient)
    at_low = _modelled_gamma({**template, "Adjust": low})
    at_high = _modelled_gamma({**template, "Adjust": high})
    if not (at_low - coefficient) * (at_high - coefficient) <= 0:
        steepest, shallowest = sorted((at_low, at_high))
        raise ConfigurationError(
            f"temperature_coefficient={coefficient} is beyond the module's reach: between "
            f"Adjust {low:.6g} and {high:.6g}, which keep its photocurrent positive from "
            f"{_SERVICE_CELL_TEMPERATURES_C[0]:g} to {_SERVICE_CELL_TEMPERATURES_C[1]:g} °C, "
            f"its modelled temperature coefficient runs only from {steepest:.6g} to "
            f"{shallowest:.6g} per K"
        )


def _adjust_giving(template: Mapping[str, float], coefficient: float) -> float:
    """The Adjust in _adjust_bracket at which the template's modelled temperature coefficient is coefficient.

    The template must reach coefficient: _with_temperature_coefficient checks that first
    (_require_template_takes_temperature_coefficient).
    """
    low, high = _adjust_bracket(template, coefficient)

    def excess_per_k(adjust: float) -> float:
        return _modelled_gamma({**template, "Adjust": adjust}) - coefficient

    return float(brentq(excess_per_k, low, high))


def _adjust_bracket(template: Mapping[str, float], coefficient: float) -> tuple[float, float]:
    """The Adjusts between which the derived module's photocurrent stays positive at every cell temperature in _SERVICE_CELL_TEMPERATURES_C.

    At 1000 W/m² calcparams_cec's photocurrent is I_L_ref + alpha_sc (1 - Adjust / 100)
    (T - 25), so the bracket is 100 (1 ∓ I_L_ref / (swing |alpha_sc|)), the swing being
    the farthest the range reaches from 25 °C. A template whose alpha_sc is 0 is refused:
    Adjust scales only alpha_sc, so no Adjust moves its modelled temperature coefficient.
    """
    alpha_sc = template["alpha_sc"]
    if alpha_sc == 0:
        raise ConfigurationError(
            f"temperature_coefficient={coefficient} cannot be set on a CEC module whose "
            "alpha_sc is 0: Adjust scales only alpha_sc, so no Adjust moves its modelled "
            "temperature coefficient"
        )
    swing_k = max(abs(temperature_c - 25.0) for temperature_c in _SERVICE_CELL_TEMPERATURES_C)
    half_width = 100 * template["I_L_ref"] / (swing_k * abs(alpha_sc))
    return 100 - half_width, 100 + half_width


def _modelled_gamma(module_params: Mapping[str, float]) -> float:
    """The module's temperature coefficient of maximum power, per K, as the model chain models it.

    That is dP_mp/dT / P_mp at 1000 W/m² and 25 °C, a central difference over
    ±_GAMMA_HALF_STEP_K through pvlib's calcparams_cec, which reads the module's keys, and
    the single-diode solution the model chain takes. A module whose modelled P_mp at STC
    is not above 0 W has no temperature coefficient of maximum power, so the result is
    NaN, never a division by 0; _require_adjust_reaches refuses that NaN as it refuses
    any NaN end.

    Such a module makes scipy's _chandrupatla, which pvlib's single-diode solution runs to
    find the maximum-power point, divide 0 by 0, so this solve ignores the "invalid value
    encountered" RuntimeWarning that raises; the module's refusal is PVConfig's, through
    that NaN.
    """
    cell_temperatures_c = 25.0 + _GAMMA_HALF_STEP_K * np.array([-1.0, 0.0, 1.0])
    diode = PVSystem(module_parameters=dict(module_params)).calcparams_cec(
        np.full(3, 1000.0), cell_temperatures_c
    )
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            message="invalid value encountered",
            category=RuntimeWarning,
            module=r"scipy\.optimize\._chandrupatla",
        )
        p_cold, p_stc, p_hot = pvlib.pvsystem.singlediode(*diode)["p_mp"]
    if not p_stc > 0:
        return math.nan
    return float((p_hot - p_cold) / (2 * _GAMMA_HALF_STEP_K * p_stc))


def _inverter_and_wiring(
    config: PVConfig,
    module_params: dict[str, float],
    module_count: int,
    candidates: Iterable[CecInverter],
) -> tuple[_Inverter, _Wiring]:
    """The inverter and how to wire the modules to it.

    Custom inverter parameters take one string of every module, as does the
    PVWatts inverter that a module with PVWatts parameters gets, because
    pvlib's PVWatts models ignore voltage. PVWatts parameters are the keys
    pvlib infers its PVWatts DC model from. A module with a V_mp_ref gets the
    CEC inverter among candidates voltage-matched to its strings, running at
    the configured inverter_efficiency at rated output. Any other module needs
    custom inverter parameters.
    """
    one_string = (_StringGroup(module_count, 1),)
    if config.custom_inverter_params is not None:
        return _Inverter(name=None, parameters=config.custom_inverter_params), one_string
    if _is_pvwatts_module(module_params):
        return _Inverter(name=None, parameters=_pvwatts_inverter(config)), one_string
    if "V_mp_ref" not in module_params:
        raise ValueError(
            "Module parameters have neither pdc0 and gamma_pdc, for a PVWatts "
            "inverter, nor a V_mp_ref, to voltage-match a CEC inverter to the "
            "strings; supply PVConfig.custom_inverter_params"
        )
    picked, wiring = _voltage_matched_cec_inverter(
        config.effective_inverter_capacity_kw, module_count, module_params["V_mp_ref"], candidates
    )
    return _cec_library_inverter(picked.name, config.inverter_efficiency), wiring


def _arrays(
    config: PVConfig, module_params: dict[str, float], wiring: _Wiring
) -> list[Array]:
    """One array, so one MPPT input, for each group of strings, its cells at NOCT-SAM's temperature from the module (_temperature_model_parameters; docs/pv-cell-temperature.md)."""
    mount = FixedMount(surface_tilt=config.tilt, surface_azimuth=config.azimuth)
    temperature_model_parameters = _temperature_model_parameters(module_params)
    return [
        Array(
            mount=mount,
            module_parameters=module_params,
            modules_per_string=group.modules_per_string,
            strings=group.strings,
            temperature_model_parameters=temperature_model_parameters,
        )
        for group in wiring
    ]


def _module_rating_w(module_params: Mapping[str, float]) -> float:
    """Each module's rated DC power in watts: a PVWatts module's pdc0, which pvlib's PVWatts DC model scales by the module count, else its STC.

    Whichever key gives it, the rating must be a finite number above 0 and never text,
    even text that reads as one (docs/pv-cell-temperature.md §1 says why).
    """
    if _is_pvwatts_module(module_params):
        key = "pdc0"
    elif "STC" in module_params:
        key = "STC"
    else:
        raise ConfigurationError(
            "Module parameters have neither pdc0 and gamma_pdc, whose pdc0 rates a PVWatts "
            "module, nor an STC rating, so the modules cannot be counted; add STC, the "
            "module's DC power in W at standard test conditions"
        )
    return as_finite_real(module_params[key], f"Module parameter {key}", POSITIVE)


_NOCT_TEST_AIR_C = 20.0
"""The air temperature, in °C, at which a module's NOCT is measured."""


@dataclass(frozen=True)
class _NoctSamInput:
    """A module's T_NOCT or A_c as NOCT-SAM reads it: the module's own value, or DEFAULT_CEC_MODULE's for a key the module lacks (docs/pv-cell-temperature.md)."""

    key: str
    value: float
    from_default_module: bool

    @classmethod
    def for_module(cls, module_params: Mapping[str, float], key: str) -> "_NoctSamInput":
        if key in module_params:
            return cls(key, module_params[key], from_default_module=False)
        return cls(key, cec_module_params(DEFAULT_CEC_MODULE)[key], from_default_module=True)

    def refusal(self, domain: str) -> ConfigurationError:
        """The ConfigurationError for a value outside domain, naming a value the module lacks as DEFAULT_CEC_MODULE's, for the module to give its own."""
        why = (
            "NOCT-SAM heats a sunlit cell above the air only inside that domain, since pvlib's "
            f"noct_sam raises it in proportion to (T_NOCT - {_NOCT_TEST_AIR_C:g} °C)"
            "(1 - efficiency / transmittance-absorptance)"
        )
        if not self.from_default_module:
            return ConfigurationError(
                f"Module parameter {self.key}={self.value} is not {domain}. {why}"
            )
        return ConfigurationError(
            f"{self.key}={self.value} (DEFAULT_CEC_MODULE's, since the module gives none) is not "
            f"{domain}. {why}. Give the module its own {self.key}"
        )


@dataclass(frozen=True)
class _NoctSamModule:
    """A module as NOCT-SAM reads it, its T_NOCT and A_c (_NoctSamInput) and its rating (_module_rating_w), inside the domain in which NOCT-SAM heats a sunlit cell above the air.

    That takes a finite T_NOCT above NOCT's test air, and a finite area A_c over
    which the rating is an efficiency, rating / (A_c × 1000), below
    _TRANSMITTANCE_ABSORPTANCE. Construction refuses a T_NOCT or an A_c outside it,
    but takes the rating as checked: build the record with
    _require_cells_noct_sam_can_heat, which reads the rating through
    _module_rating_w, the check that refuses one that is not a finite number above 0.
    """

    t_noct: _NoctSamInput
    area: _NoctSamInput
    rating_w: float

    def __post_init__(self) -> None:
        """Refuse a T_NOCT, then an A_c, outside NOCT-SAM's domain (_NoctSamInput.refusal)."""
        if not _NOCT_TEST_AIR_C < self.t_noct.value < math.inf:
            raise self.t_noct.refusal(
                f"a finite temperature above {_NOCT_TEST_AIR_C:g} °C, the air temperature at which "
                "NOCT is measured"
            )
        smallest_area_m2 = self.rating_w / (_TRANSMITTANCE_ABSORPTANCE * 1000)
        if not max(0.0, smallest_area_m2) < self.area.value < math.inf:
            raise self.area.refusal(
                f"a finite area above {smallest_area_m2:.4g} m², over which the module's {self.rating_w} W "
                "rating is an efficiency, rating / (A_c × 1000), below NOCT-SAM's "
                f"{_TRANSMITTANCE_ABSORPTANCE} transmittance-absorptance"
            )

    @property
    def efficiency(self) -> float:
        """The rating over the area, A_c × 1000 W/m²."""
        return self.rating_w / (self.area.value * 1000)


def _require_cells_noct_sam_can_heat(module_params: Mapping[str, float]) -> _NoctSamModule:
    """The module as NOCT-SAM reads it (_NoctSamModule), refusing a module with no rating, or one that is not a finite number above 0 (_module_rating_w), or whose cells NOCT-SAM cannot heat above the air.

    A module that lacks T_NOCT or A_c is read with DEFAULT_CEC_MODULE's value of
    that key (_NoctSamInput).
    """
    return _NoctSamModule(
        t_noct=_NoctSamInput.for_module(module_params, "T_NOCT"),
        area=_NoctSamInput.for_module(module_params, "A_c"),
        rating_w=_module_rating_w(module_params),
    )


def _temperature_model_parameters(module_params: Mapping[str, float]) -> dict[str, float]:
    """pvlib's NOCT-SAM parameters for the module's cells, from the inputs _require_cells_noct_sam_can_heat reads and checks: its T_NOCT, and its rating over its area, A_c × 1000 W/m², as its efficiency (docs/pv-cell-temperature.md)."""
    module = _require_cells_noct_sam_can_heat(module_params)
    return {
        "noct": module.t_noct.value,
        "module_efficiency": module.efficiency,
        "transmittance_absorptance": _TRANSMITTANCE_ABSORPTANCE,
    }


def _module_count(config: PVConfig, module_params: dict[str, float]) -> int:
    """The whole number of modules nearest the configured capacity, and at least one."""
    return max(1, round(config.capacity_kw * 1000 / _module_rating_w(module_params)))


def _pv_system(config: PVConfig, candidates: Iterable[CecInverter]) -> PVSystem:
    """The PVSystem for config, any CEC inverter it takes voltage-matched from candidates."""
    module_params = _module_parameters(config)
    module_count = _module_count(config, module_params)
    inverter, wiring = _inverter_and_wiring(config, module_params, module_count, candidates)
    return PVSystem(
        arrays=_arrays(config, module_params, wiring),
        inverter=inverter.name,
        inverter_parameters=inverter.parameters,
    )


def create_pv_system(config: PVConfig) -> PVSystem:
    """Create a pvlib PVSystem from configuration.

    Creates a PVSystem using CEC module and inverter databases for realistic
    modelling parameters, or custom parameters if provided; it wires
    DEFAULT_CEC_MODULE unless custom module parameters are given. The CEC
    inverter is voltage-matched to the strings and runs at the configured
    inverter_efficiency at rated output; see _ranking_key and
    _wiring_within_window for how it is chosen from candidate_cec_inverters and
    how the modules are wired to it. A module with PVWatts parameters (pdc0 and
    gamma_pdc, e.g. one from create_simple_module_params) gets pvlib's PVWatts
    inverter at the configured AC capacity and efficiency instead. It wires the
    whole number of modules nearest capacity_kw, each rated at its pdc0 if it
    has PVWatts parameters and at its STC otherwise (_module_rating_w). Each
    array's cells run at pvlib's NOCT-SAM temperature, from the module's T_NOCT
    and efficiency (_temperature_model_parameters; docs/pv-cell-temperature.md).

    Args:
        config: PV system configuration with capacity, azimuth, tilt, and
            optional custom module/inverter parameters

    Returns:
        pvlib PVSystem ready for use in ModelChain simulation; its inverter
        attribute names the picked CEC library row, None for custom or PVWatts
        inverter parameters

    Raises:
        ValueError: If custom module parameters give a key a value
            _require_module_values refuses, if
            the module parameters rate the module by neither a PVWatts module's
            pdc0 nor an STC, or by one that is not a finite number above 0, if
            they have neither PVWatts parameters nor a V_mp_ref and no custom
            inverter parameters are given, if no CEC inverter's MPPT window admits a
            string of the module's voltage, if NOCT-SAM cannot heat the
            module's cells above the air with its T_NOCT and A_c
            (_require_cells_noct_sam_can_heat), or if a set
            temperature_coefficient cannot derive the module: no Adjust in
            _adjust_bracket reaches it for a custom CEC module, or the
            module's alpha_sc is 0 (_with_temperature_coefficient). The
            module-value, rating, NOCT-SAM and temperature-coefficient refusals
            are ConfigurationError, as at PVConfig's construction.

    Example:
        >>> config = PVConfig(capacity_kw=4.0, azimuth=180.0, tilt=35.0)
        >>> system = create_pv_system(config)
        >>> system.arrays[0].mount.surface_tilt
        35.0
    """
    return _pv_system(config, candidate_cec_inverters())


def wired_dc_capacity_kw(config: PVConfig) -> float:
    """The DC capacity, in kW, of the modules create_pv_system wires for config.

    It sums each array's modules per string × strings × module rating
    (_module_rating_w) over the arrays of the PVSystem that create_pv_system
    builds for config. The system holds a whole number of modules, so this
    differs from config.capacity_kw unless the module's rating divides it:
    0.3 kW of DEFAULT_CEC_MODULE, 400.428 W at STC, wires one module.

    Raises:
        ValueError: Whatever create_pv_system raises for config.

    Example:
        >>> round(wired_dc_capacity_kw(PVConfig(capacity_kw=0.3)), 3)
        0.4
    """
    wired_w = sum(
        array.modules_per_string * array.strings * _module_rating_w(array.module_parameters)
        for array in create_pv_system(config).arrays
    )
    return float(wired_w) / 1000


def _require_compatible_dc_and_ac_models(model_chain: ModelChain) -> None:
    """Refuse a model chain whose inverter model can not read its DC model's output.

    PVWatts DC gives power alone, which only the PVWatts inverter takes; every
    other DC model gives the voltage that the Sandia and ADR inverters read.
    """
    dc_is_pvwatts = model_chain.dc_model == model_chain.pvwatts_dc
    ac_is_pvwatts = model_chain.ac_model == model_chain.pvwatts_inverter
    if dc_is_pvwatts != ac_is_pvwatts:
        raise ValueError(
            f"pvlib cannot feed its {model_chain.dc_model.__name__} DC model to its "
            f"{model_chain.ac_model.__name__} inverter model: PVWatts module "
            "parameters (pdc0, gamma_pdc) go only with PVWatts inverter parameters "
            "(pdc0, eta_inv_nom), and a module with a voltage model needs a Sandia "
            "or ADR inverter"
        )


def _dc_after_losses(
    dc: pd.DataFrame | pd.Series, kept_fraction: float
) -> pd.DataFrame | pd.Series:
    """One array's DC output with its maximum-power-point power and current scaled by kept_fraction, at unchanged voltage.

    PVWatts DC output is a power series; a voltage model's is a frame whose
    p_mp and v_mp the Sandia and ADR inverters read.
    """
    if isinstance(dc, pd.Series):
        return dc * kept_fraction
    return dc.assign(i_mp=dc["i_mp"] * kept_fraction, p_mp=dc["p_mp"] * kept_fraction)


def _dc_kept_fraction(config: PVConfig) -> float:
    """The fraction of each array's DC power that reaches the inverter: what the system losses and the modules' ageing leave, combined as PVWatts combines its loss categories."""
    return (1 - config.system_losses) * calculate_degradation_factor(
        config.system_age_years, config.degradation_rate_per_year
    )


def _deduct_dc_losses(model_chain: ModelChain, kept_fraction: float) -> ModelChain:
    """pvlib's losses-model step: each array's DC output scaled to kept_fraction, for the inverter model to read.

    Like pvlib's own losses models, it records the kept fraction in
    results.losses.
    """
    model_chain.results.losses = kept_fraction
    dc = model_chain.results.dc
    if isinstance(dc, tuple):
        model_chain.results.dc = tuple(_dc_after_losses(array_dc, kept_fraction) for array_dc in dc)
    else:
        model_chain.results.dc = _dc_after_losses(dc, kept_fraction)
    return model_chain


def create_model_chain_picking_from(
    config: PVConfig,
    location: "Location",
    candidates: Iterable[CecInverter],
) -> ModelChain:
    """Create a pvlib ModelChain for AC power simulation, with any CEC inverter voltage-matched from candidates.

    A candidate's numbers decide only whether and how it is picked: the system
    takes the picked inverter's parameters from pvlib's CEC library by name,
    with Pdco set so that it runs at config.inverter_efficiency at rated
    output, and carries that name as PVSystem.inverter, which is why a
    CecInverter must name a row there. Custom inverter parameters and PVWatts
    modules ignore the candidates, and their system's inverter is None.

    Each array's DC power falls by config.system_losses and by the modules'
    ageing (calculate_degradation_factor of config.system_age_years and
    config.degradation_rate_per_year) before the inverter model reads it, at
    unchanged voltage (docs/pv-system-losses.md).

    Args:
        config: PV system configuration
        location: Geographic location for solar position calculations
        candidates: The CEC inverters to pick from

    Returns:
        ModelChain ready to run simulations with weather data

    Raises:
        ValueError: If custom module parameters give a key a value
            _require_module_values refuses, if
            the module parameters rate the module by neither a PVWatts module's
            pdc0 nor an STC, or by one that is not a finite number above 0, if
            they have neither PVWatts parameters nor a V_mp_ref and no custom
            inverter parameters are given, if no candidate's MPPT window admits the
            strings, if NOCT-SAM cannot heat the module's cells above the air
            with its T_NOCT and A_c (_require_cells_noct_sam_can_heat), if a
            set temperature_coefficient cannot derive the module
            (_with_temperature_coefficient, as for create_pv_system), or if
            pvlib infers an inverter model that can not read its DC model's
            output, e.g. custom Sandia inverter parameters with PVWatts module
            parameters. The module-value, rating, NOCT-SAM and
            temperature-coefficient refusals are ConfigurationError, as for
            create_pv_system.
    """
    pv_system = _pv_system(config, candidates)

    # Convert our Location to pvlib Location
    pvlib_location = PVLibLocation(
        latitude=location.latitude,
        longitude=location.longitude,
        tz=location.timezone,
        altitude=location.altitude,
        name=location.name,
    )

    # Create ModelChain with appropriate models
    model_chain = ModelChain(
        system=pv_system,
        location=pvlib_location,
        aoi_model="physical",
        spectral_model="no_loss",
        losses_model=functools.partial(_deduct_dc_losses, kept_fraction=_dc_kept_fraction(config)),
    )
    _require_compatible_dc_and_ac_models(model_chain)

    return model_chain


def create_model_chain(
    config: PVConfig,
    location: "Location",
) -> ModelChain:
    """Create a pvlib ModelChain for AC power simulation, with any CEC inverter picked from candidate_cec_inverters(); create_model_chain_picking_from documents the arguments, result and errors."""
    return create_model_chain_picking_from(config, location, candidate_cec_inverters())


def run_model_chain(model_chain: ModelChain, weather_data: pd.DataFrame) -> ModelChain:
    """Run model_chain over weather_data and return it, run.

    It is the one way the project runs a pvlib ModelChain, which
    simulate_pv_output, the measurement scripts and the tests share. Every
    chain create_model_chain_picking_from builds already applies the system
    losses and ageing to each array's DC power. Building and running stay
    separate because measure_mppt_window's census reads a chain's inverter
    pick before it runs the chain.
    """
    model_chain.run_model(weather_data)
    return model_chain


def ac_power_kw(model_chain: ModelChain) -> pd.Series:
    """A run chain's AC power in kW, clipped at 0 so the inverter's night tare never reads as negative generation."""
    return (model_chain.results.ac / 1000.0).clip(lower=0.0)


def simulate_pv_output(
    config: PVConfig,
    location: "Location",
    weather_data: pd.DataFrame,
) -> pd.Series:
    """Run PV simulation and return AC power output.

    Args:
        config: PV system configuration
        location: Geographic location
        weather_data: DataFrame with ghi, dni, dhi, temp_air, wind_speed columns

    Returns:
        Series of AC power output at config.system_age_years, in kW, with the
        same index as weather_data
    """
    return ac_power_kw(run_model_chain(create_model_chain(config, location), weather_data))


def calculate_degradation_factor(
    system_age_years: float,
    degradation_rate_per_year: float = 0.005,
) -> float:
    """Calculate PV degradation factor based on system age.

    PV panels degrade over time, typically losing ~0.5% of their
    rated capacity per year. This function calculates the remaining
    capacity as a fraction of original.

    Args:
        system_age_years: Age of the PV system in years (can be fractional)
        degradation_rate_per_year: Annual degradation rate as decimal
            (default 0.005 = 0.5%/year)

    Returns:
        Degradation factor as fraction of original capacity (0 to 1)
        Year 0: 1.0 (100%)
        Year 1: 0.995 (99.5%)
        Year 10: 0.95 (95%)

    Raises:
        ConfigurationError: As PVConfig refuses its system_age_years or
            degradation_rate_per_year, naming the argument and its value

    Example:
        >>> calculate_degradation_factor(0)
        1.0
        >>> calculate_degradation_factor(10, 0.005)
        0.95
    """
    age = as_finite_float(system_age_years, "system_age_years", _SYSTEM_AGE_YEARS)
    rate = as_finite_float(degradation_rate_per_year, "degradation_rate_per_year", _DEGRADATION_RATE_PER_YEAR)

    # Linear degradation: factor = 1 - (age * rate)
    factor = 1.0 - (age * rate)

    # Clamp to minimum of 0 (can't have negative generation)
    return max(0.0, factor)


def apply_degradation(
    generation: pd.Series,
    system_age_years: float,
    degradation_rate_per_year: float = 0.005,
) -> pd.Series:
    """Apply degradation factor to PV generation time series.

    simulate_pv_output and create_model_chain already apply a PVConfig's ageing
    to each array's DC power, so applying this to their output for an aged
    PVConfig ages the array twice.

    Args:
        generation: PV generation time series in kW
        system_age_years: Age of the PV system in years
        degradation_rate_per_year: Annual degradation rate as decimal
            (default 0.005 = 0.5%/year)

    Returns:
        Degraded generation series (same index, reduced values)

    Example:
        >>> import pandas as pd
        >>> gen = pd.Series([1.0, 2.0, 3.0])
        >>> degraded = apply_degradation(gen, system_age_years=10)
        >>> degraded.equals(gen * 0.95)
        True
    """
    factor = calculate_degradation_factor(system_age_years, degradation_rate_per_year)
    return generation * factor


def interpolate_to_minute_resolution(
    hourly_power: pd.Series,
) -> pd.Series:
    """Interpolate hourly power to 1-minute resolution preserving energy.

    Divides each hourly energy total into 60 equal 1-minute values.
    This simple approach preserves total energy while providing
    high-resolution data for battery simulation.

    Args:
        hourly_power: Power series with hourly frequency (kW)

    Returns:
        Power series with 1-minute frequency (kW)
        Same values within each hour, preserving energy totals.
    """
    # Create 1-minute index
    start = hourly_power.index[0]
    end = hourly_power.index[-1] + pd.Timedelta(hours=1) - pd.Timedelta(minutes=1)

    minute_index = pd.date_range(
        start=start,
        end=end,
        freq="1min",
        tz=hourly_power.index.tz if hasattr(hourly_power.index, "tz") else None,
    )

    # Forward-fill to expand hourly values to minutes
    # This gives same power (kW) for each minute, preserving energy
    minute_power = hourly_power.reindex(minute_index, method="ffill")

    # Handle any remaining NaN at the end
    minute_power = minute_power.ffill()

    return minute_power
