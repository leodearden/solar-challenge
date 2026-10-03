# SPDX-License-Identifier: AGPL-3.0-or-later
"""Measure how long CEC-inverter strings run outside the MPPT window, and what that costs.

docs/pv-inverter-string-matching.md §3 describes this method and §4-§7 record
what it printed. From the repository root:

    uv run --extra dev python scripts/measure_mppt_window.py --csv /tmp/mppt-window.csv

It reads the Bristol PVGIS TMY through the weather cache, fetching it only when
the cache lacks it. Every configuration gets its inverter and wiring from
pv.py's own selection, once per sizing, and each distinct pick runs one
year-long model chain: about twelve minutes in all. The CSV holds one row per
sizing and configuration. It is not part of the test suite.
"""

import argparse
import dataclasses
import functools
import itertools
import math
import sys
import warnings
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional, Union
from unittest import mock

import numpy as np
import pandas as pd
import pvlib
from pvlib.modelchain import ModelChain

from solar_challenge import pv
from solar_challenge.location import Location
from solar_challenge.pv import PVConfig, create_model_chain, create_pv_system
from solar_challenge.weather import (
    DEFAULT_CACHE_DIR,
    WeatherCache,
    get_tmy_data,
    set_weather_cache,
)

DC_CAPACITIES_KW = tuple(tenths / 10 for tenths in range(3, 251))
INVERTER_CAPACITIES_KW: tuple[Optional[float], ...] = (None, 3.0, 3.68, 5.0)
DESIGN_CELL_TEMPERATURES_C = (10.0, 0.0, -10.0)
HOT_DESIGN_CELL_TEMPERATURES_C = (45.0, 55.0, 65.0)
CEILING_MARGINS = (1.05, 1.10)
NEAR_CEILING = 0.9
HEADLINE_KWP = (3.0, 4.0, 5.0, 6.0)
COLD_RATIO = 1.06
CEILING = "above_ceiling"
FLOOR = "below_floor"


def _column_label(inverter_kw: Optional[float]) -> str:
    return "unset" if inverter_kw is None else f"{inverter_kw:g}"


COLUMNS = [_column_label(inverter_kw) for inverter_kw in INVERTER_CAPACITIES_KW]


@dataclass(frozen=True)
class Sizing:
    """Wire strings so that their STC voltage times ceiling_factor stays at or under Mppt_high, and times floor_factor at or over Mppt_low.

    keeps_battery_inverters picks from every usable CEC row, as pv.py did
    before task 240.
    """

    label: str
    ceiling_factor: float = 1.0
    floor_factor: float = 1.0
    keeps_battery_inverters: bool = False


STC = Sizing("STC")
BATTERY_INVERTERS_KEPT = Sizing(
    "STC, battery inverter/chargers kept", keeps_battery_inverters=True
)


def sizings(module: Mapping[str, Any]) -> tuple[Sizing, ...]:
    """The code's STC sizing; cold-cell ceilings, fixed ceiling margins and hot-cell floors; and STC with the battery inverter/chargers kept.

    The cell temperatures use the beta_oc / V_oc_ref proxy.
    """
    per_kelvin = module["beta_oc"] / module["V_oc_ref"]
    cold = (
        Sizing(f"cell {t:g} °C", ceiling_factor=1 + per_kelvin * (t - 25))
        for t in DESIGN_CELL_TEMPERATURES_C
    )
    margins = (Sizing(f"Mppt_high / {m:.2f}", ceiling_factor=m) for m in CEILING_MARGINS)
    hot = (
        Sizing(f"floor cell {t:g} °C", floor_factor=1 + per_kelvin * (t - 25))
        for t in HOT_DESIGN_CELL_TEMPERATURES_C
    )
    return (STC, *cold, *margins, *hot, BATTERY_INVERTERS_KEPT)


@contextmanager
def picking_by(sizing: Sizing) -> Iterator[None]:
    """pv.py's own inverter pick and wiring, with every catalogue ceiling divided by the sizing's ceiling_factor and every floor by its floor_factor.

    Dividing an edge is the same check as multiplying the string voltage; the
    ranking is untouched.
    """
    catalogue = (
        pv._usable_cec_inverters() if sizing.keeps_battery_inverters else pv._cec_inverters()
    )
    moved = tuple(
        dataclasses.replace(
            inverter,
            mppt_low_v=inverter.mppt_low_v / sizing.floor_factor,
            mppt_high_v=inverter.mppt_high_v / sizing.ceiling_factor,
        )
        for inverter in catalogue
    )
    with mock.patch.object(pv, "_cec_inverters", return_value=moved):
        yield


@dataclass(frozen=True)
class Pick:
    """A configuration's inverter, and its wiring as (modules per string, strings) per MPPT input."""

    inverter: str
    wiring: tuple[tuple[int, int], ...]

    @property
    def wiring_label(self) -> str:
        return "+".join(f"{modules}x{strings}" for modules, strings in self.wiring)

    @property
    def modules(self) -> int:
        return sum(modules * strings for modules, strings in self.wiring)

    @property
    def longest_string(self) -> int:
        return max(modules for modules, _ in self.wiring)


_ParamsKey = tuple[tuple[str, str], ...]


def _params_key(params: Mapping[str, Any]) -> _ParamsKey:
    return tuple(sorted((key, repr(value)) for key, value in params.items()))


@functools.cache
def _catalogue() -> pd.DataFrame:
    return pvlib.pvsystem.retrieve_sam("CECInverter")


@functools.cache
def _inverter_names() -> dict[_ParamsKey, str]:
    """CEC inverter names by parameter set; identical sets keep the first name, as the ranking's tie-break does."""
    return {
        _params_key(_catalogue()[name].to_dict()): name
        for name in sorted(_catalogue().columns, reverse=True)
    }


def _pick(chain: ModelChain) -> Pick:
    system = chain.system
    return Pick(
        _inverter_names()[_params_key(system.inverter_parameters)],
        tuple((array.modules_per_string, array.strings) for array in system.arrays),
    )


@dataclass(frozen=True)
class Excursion:
    """The producing hours a year's strings spend beyond one edge of the MPPT window, and what they change.

    Attributes:
        hours: Producing hours with any string beyond the edge.
        largest_v: The furthest any string's V_mp gets beyond the edge.
        dc_share: The share of the year's DC energy that strings beyond the edge deliver.
        ac_kwh_clipped: (a) Annual AC from the inverter model fed the edge's
            voltage at the same DC power.
        ac_kwh_held: (b) Annual AC with those strings held at the edge, on
            their IV curve.
    """

    hours: int
    largest_v: float
    dc_share: float
    ac_kwh_clipped: float
    ac_kwh_held: float


@dataclass(frozen=True)
class Year:
    """One inverter and wiring over the TMY: the model's annual AC, and both edges of the window."""

    ac_kwh: float
    above_ceiling: Excursion
    below_floor: Excursion


@dataclass(frozen=True)
class _Strings:
    """One MPPT input's hourly string voltage and array power, with its module's diode parameters."""

    modules_per_string: int
    strings: int
    v_mp: pd.Series
    p_mp: pd.Series
    diode: pd.DataFrame

    def power_at(self, string_v: float) -> pd.Series:
        module_v = string_v / self.modules_per_string
        current = pvlib.pvsystem.i_from_v(
            module_v,
            self.diode["I_L"],
            self.diode["I_o"],
            self.diode["R_s"],
            self.diode["R_sh"],
            self.diode["nNsVth"],
        )
        return module_v * current * self.modules_per_string * self.strings


def _per_array(result: Any) -> tuple[Any, ...]:
    """A ModelChain result per array: pvlib gives a bare value for a one-array system."""
    return result if isinstance(result, tuple) else (result,)


def _strings(chain: ModelChain) -> tuple[_Strings, ...]:
    return tuple(
        _Strings(array.modules_per_string, array.strings, dc["v_mp"], dc["p_mp"], diode)
        for array, dc, diode in zip(
            chain.system.arrays,
            _per_array(chain.results.dc),
            _per_array(chain.results.diode_params),
        )
    )


def _producing(chain: ModelChain) -> pd.Series:
    """Hours with sunlight on the cells; at night the diode solver leaves p_mp at about 1e-43 W."""
    return _per_array(chain.results.effective_irradiance)[0] > 0


def _ac_kwh(
    v_dc: Sequence[pd.Series], p_dc: Sequence[pd.Series], inverter: Mapping[str, Any]
) -> float:
    ac_w = pvlib.inverter.sandia_multi(tuple(v_dc), tuple(p_dc), inverter)
    return float(ac_w.clip(lower=0).sum()) / 1000


def _excursion(
    strings: Sequence[_Strings],
    beyond: Sequence[pd.Series],
    edge_v: float,
    inverter: Mapping[str, Any],
) -> Excursion:
    at_edge = [s.v_mp.where(~out, edge_v) for s, out in zip(strings, beyond)]
    held = [s.p_mp.where(~out, s.power_at(edge_v)) for s, out in zip(strings, beyond)]
    distances = [(s.v_mp[out] - edge_v).abs() for s, out in zip(strings, beyond)]
    dc_beyond = sum(float(s.p_mp[out].sum()) for s, out in zip(strings, beyond))
    return Excursion(
        hours=int(pd.concat(beyond, axis=1).any(axis=1).sum()),
        largest_v=max((float(d.max()) for d in distances if len(d)), default=0.0),
        dc_share=dc_beyond / sum(float(s.p_mp.sum()) for s in strings),
        ac_kwh_clipped=_ac_kwh(at_edge, [s.p_mp for s in strings], inverter),
        ac_kwh_held=_ac_kwh(at_edge, held, inverter),
    )


def measure_year(chain: ModelChain, weather: pd.DataFrame) -> Year:
    """Run the chain over the year and measure both edges of its inverter's MPPT window."""
    chain.run_model(weather)
    strings = _strings(chain)
    inverter = chain.system.inverter_parameters
    ac_kwh = _ac_kwh([s.v_mp for s in strings], [s.p_mp for s in strings], inverter)
    chain_ac_kwh = float(chain.results.ac.clip(lower=0).sum()) / 1000
    if not math.isclose(ac_kwh, chain_ac_kwh, rel_tol=1e-12):
        raise RuntimeError(f"sandia_multi gives {ac_kwh} kWh, the chain {chain_ac_kwh} kWh")
    producing = _producing(chain)
    ceiling, floor = inverter["Mppt_high"], inverter["Mppt_low"]
    return Year(
        ac_kwh=ac_kwh,
        above_ceiling=_excursion(
            strings, [producing & (s.v_mp > ceiling) for s in strings], ceiling, inverter
        ),
        below_floor=_excursion(
            strings, [producing & (s.v_mp < floor) for s in strings], floor, inverter
        ),
    )


def census(
    location: Location, weather: pd.DataFrame, module: Mapping[str, Any]
) -> pd.DataFrame:
    """One row per sizing, inverter capacity and DC capacity; each distinct pick runs one year."""
    years: dict[Pick, Year] = {}
    rows = []
    for sizing in sizings(module):
        with picking_by(sizing):
            for inverter_kw, dc_kw in itertools.product(
                INVERTER_CAPACITIES_KW, DC_CAPACITIES_KW
            ):
                config = PVConfig(capacity_kw=dc_kw, inverter_capacity_kw=inverter_kw)
                chain = create_model_chain(config, location)
                pick = _pick(chain)
                if pick not in years:
                    years[pick] = measure_year(chain, weather)
                year = years[pick]
                rows.append(
                    {
                        "sizing": sizing.label,
                        "inverter_kw": _column_label(inverter_kw),
                        "dc_kw": dc_kw,
                        "inverter": pick.inverter,
                        "wiring": pick.wiring_label,
                        "modules": pick.modules,
                        "longest_string_stc_v": pick.longest_string * module["V_mp_ref"],
                        "mppt_low_v": chain.system.inverter_parameters["Mppt_low"],
                        "mppt_high_v": chain.system.inverter_parameters["Mppt_high"],
                        "ac_kwh": year.ac_kwh,
                        **_prefixed(CEILING, year.above_ceiling),
                        **_prefixed(FLOOR, year.below_floor),
                    }
                )
        print(f"{sizing.label}: {len(years)} distinct picks measured", file=sys.stderr)
    return pd.DataFrame(rows)


def _prefixed(prefix: str, excursion: Excursion) -> dict[str, Any]:
    return {f"{prefix}_{name}": value for name, value in dataclasses.asdict(excursion).items()}


def _by_column(values: pd.Series, columns: pd.Series) -> Any:
    return values.groupby(columns, sort=False)


def census_table(stc: pd.DataFrame) -> pd.DataFrame:
    share = stc["longest_string_stc_v"] / stc["mppt_high_v"]
    hours = stc[f"{CEILING}_hours"]
    headline_hours = hours.where(stc["dc_kw"].isin(HEADLINE_KWP), 0)
    columns = stc["inverter_kw"]
    return pd.DataFrame(
        {
            "longest string within 10% of Mppt_high at STC": _by_column(
                share >= NEAR_CEILING, columns
            ).sum(),
            "largest longest-string STC V / Mppt_high": _by_column(share, columns).max(),
            "configs with any hour above Mppt_high": _by_column(hours > 0, columns).sum(),
            "most hours above": _by_column(hours, columns).max(),
            "largest overshoot V": _by_column(stc[f"{CEILING}_largest_v"], columns).max(),
            "most hours above, headline kWp": _by_column(headline_hours, columns).max(),
        }
    ).T[COLUMNS]


def _distinct_pairs(rows: pd.DataFrame) -> pd.DataFrame:
    """Configurations that wire the same modules to the same inverter give the same year: keep the first."""
    return rows.drop_duplicates(["inverter", "wiring"])


def edge_error(stc: pd.DataFrame, edge: str) -> pd.DataFrame:
    """Per distinct pair with any hour beyond the edge, the change (a) and (b) make to the model's annual AC, in %.

    The edge is CEILING or FLOOR, and the largest drop under (b) comes first.
    """
    pairs = _distinct_pairs(stc[stc[f"{edge}_hours"] > 0])
    shown = ["inverter_kw", "dc_kw", "inverter", "wiring", "mppt_low_v", "mppt_high_v"]
    shown += [f"{edge}_{measure}" for measure in ("hours", "largest_v", "dc_share")]
    return pairs.assign(
        clipped_pct=(pairs[f"{edge}_ac_kwh_clipped"] / pairs["ac_kwh"] - 1) * 100,
        held_pct=(pairs[f"{edge}_ac_kwh_held"] / pairs["ac_kwh"] - 1) * 100,
    ).sort_values("held_pct")[[*shown, "clipped_pct", "held_pct"]]


def edge_error_summary(errors: pd.DataFrame) -> pd.Series:
    return pd.Series(
        {
            "distinct inverter/wiring pairs": len(errors),
            "(a) largest |change| %": errors["clipped_pct"].abs().max(),
            "(b) median change %": errors["held_pct"].median(),
            "(b) largest drop %": errors["held_pct"].min(),
        }
    )


def _aligned_with_stc(
    rows: pd.DataFrame, label: str
) -> tuple[pd.DataFrame, pd.DataFrame, pd.Series]:
    """The labelled sizing's rows and STC's, both indexed by configuration, and which configurations the sizing re-picks: another inverter or wiring."""
    keys = ["inverter_kw", "dc_kw"]
    alt = rows[rows["sizing"] == label].set_index(keys)
    stc = rows[rows["sizing"] == STC.label].set_index(keys)
    repicked = (alt["inverter"] != stc["inverter"]) | (alt["wiring"] != stc["wiring"])
    return alt, stc, repicked


def headroom_table(rows: pd.DataFrame) -> pd.DataFrame:
    """Per window-edge sizing and inverter column: re-picked configs, their annual AC change, the hours still beyond each edge."""
    labels = rows["sizing"]
    edge_labels = labels[~labels.isin([STC.label, BATTERY_INVERTERS_KEPT.label])].unique()
    blocks = {}
    for label in edge_labels:
        alt, stc, repicked = _aligned_with_stc(rows, label)
        change = (alt["ac_kwh"] / stc["ac_kwh"] - 1)[repicked] * 100
        column = alt.index.get_level_values("inverter_kw")
        blocks[label] = pd.DataFrame(
            {
                "re-picks": repicked.groupby(column, sort=False).sum(),
                "|dAC| median %": change.abs().groupby(level="inverter_kw").median(),
                "|dAC| max %": change.abs().groupby(level="inverter_kw").max(),
                "mean dAC %": change.groupby(level="inverter_kw").mean(),
                "hours left above": alt[f"{CEILING}_hours"].groupby(column, sort=False).max(),
                "hours left below": alt[f"{FLOOR}_hours"].groupby(column, sort=False).max(),
            }
        ).T[COLUMNS]
    return pd.concat(blocks)


def repicks(rows: pd.DataFrame, sizing: Sizing) -> pd.DataFrame:
    """The configurations the sizing re-picks, with its pick and STC's.

    change % is STC's annual AC over the sizing's, less one: the change from
    the sizing's pick to pv.py's.
    """
    alt, stc, repicked = _aligned_with_stc(rows, sizing.label)
    return pd.DataFrame(
        {
            "sizing's inverter": alt["inverter"],
            "sizing's wiring": alt["wiring"],
            "STC inverter": stc["inverter"],
            "STC wiring": stc["wiring"],
            "change %": (stc["ac_kwh"] / alt["ac_kwh"] - 1) * 100,
        }
    )[repicked].reset_index()


def identical_picks(rows: pd.DataFrame) -> list[tuple[str, str]]:
    """Pairs of sizings that pick the same inverter and wiring for every configuration."""
    picks = rows.set_index(["sizing", "inverter_kw", "dc_kw"])[["inverter", "wiring"]]
    labels = list(dict.fromkeys(rows["sizing"]))
    return [
        (a, b)
        for a, b in itertools.combinations(labels, 2)
        if picks.loc[a].equals(picks.loc[b])
    ]


def annual_yield(stc: pd.DataFrame, module_stc_w: float) -> pd.Series:
    default = stc[stc["inverter_kw"] == _column_label(None)]
    per_wired = default["ac_kwh"] / (default["modules"] * module_stc_w / 1000)
    per_nameplate = default["ac_kwh"] / default["dc_kw"]
    headline = per_nameplate[default["dc_kw"].isin(HEADLINE_KWP)]
    return pd.Series(
        {
            "per wired DC kWp, min": per_wired.min(),
            "per wired DC kWp, median": per_wired.median(),
            "per wired DC kWp, max": per_wired.max(),
            "per nameplate kWp, headline min": headline.min(),
            "per nameplate kWp, headline max": headline.max(),
            "per nameplate kWp, min": per_nameplate.min(),
            "per nameplate kWp, max": per_nameplate.max(),
        }
    )


def operating_voltage(
    location: Location, weather: pd.DataFrame, module: Mapping[str, Any]
) -> tuple[pd.DataFrame, pd.Series]:
    """The default system's hours with module V_mp above COLD_RATIO x V_mp_ref, and its hours above V_mp_ref."""
    chain = create_model_chain(PVConfig.default_4kw(), location)
    chain.run_model(weather)
    (strings,) = _strings(chain)
    ratio = strings.v_mp / strings.modules_per_string / module["V_mp_ref"]
    producing = _producing(chain)
    above = producing & (ratio > 1)
    hours = pd.DataFrame(
        {
            "V_mp / V_mp_ref": ratio,
            "string V": strings.v_mp,
            "POA W/m2": chain.results.total_irrad["poa_global"],
            "cell C": chain.results.cell_temperature,
            "air C": weather["temp_air"],
        }
    )
    pick = _pick(chain)
    inverter = chain.system.inverter_parameters
    default = pd.Series(
        {
            "inverter": pick.inverter,
            "wiring": pick.wiring_label,
            "string STC V": pick.longest_string * module["V_mp_ref"],
            "string STC V_oc": pick.longest_string * module["V_oc_ref"],
            "Mppt_high V": inverter["Mppt_high"],
            "Vdcmax V": inverter["Vdcmax"],
            "annual AC kWh": float(chain.results.ac.clip(lower=0).sum()) / 1000,
            "producing hours": int(producing.sum()),
            "hours above V_mp_ref": int(above.sum()),
            "DC energy share above V_mp_ref": float(
                strings.p_mp[above].sum() / strings.p_mp.sum()
            ),
        }
    )
    return hours[ratio > COLD_RATIO].sort_values("V_mp / V_mp_ref", ascending=False), default


def proxy_coefficient(module: Mapping[str, Any]) -> pd.DataFrame:
    """V_mp at each design cell temperature over V_mp at 25 C: the beta_oc / V_oc_ref proxy, and the single-diode model at 1000 W/m2."""
    temperatures = np.array(DESIGN_CELL_TEMPERATURES_C)
    diode = pvlib.pvsystem.calcparams_cec(
        1000.0,
        np.append(temperatures, 25.0),
        module["alpha_sc"],
        module["a_ref"],
        module["I_L_ref"],
        module["I_o_ref"],
        module["R_sh_ref"],
        module["R_s"],
        module["Adjust"],
    )
    v_mp = np.asarray(pvlib.pvsystem.max_power_point(*diode)["v_mp"])
    single_diode = v_mp[:-1] / v_mp[-1]
    proxy = 1 + module["beta_oc"] / module["V_oc_ref"] * (temperatures - 25)
    return pd.DataFrame(
        {
            "proxy factor": proxy,
            "proxy %/K": (proxy - 1) / (25 - temperatures) * 100,
            "single-diode factor": single_diode,
            "single-diode %/K": (single_diode - 1) / (25 - temperatures) * 100,
        },
        index=pd.Index(temperatures, name="cell C"),
    )


def catalogue_ceilings() -> pd.Series:
    vdcmax = pd.to_numeric(_catalogue().loc["Vdcmax"], errors="coerce")
    mppt_high = pd.to_numeric(_catalogue().loc["Mppt_high"], errors="coerce")
    return pd.Series(
        {
            "CEC inverters": _catalogue().shape[1],
            "with Vdcmax == Mppt_high": int((vdcmax == mppt_high).sum()),
        }
    )


def battery_inverters() -> tuple[pd.DataFrame, pd.Series]:
    """The usable CEC rows pv.py leaves out as battery inverter/chargers, and the gaps between them and the rows it keeps."""
    kept = pd.DataFrame(map(dataclasses.asdict, pv._cec_inverters()))
    left_out = set(pv._usable_cec_inverters()) - set(pv._cec_inverters())
    dropped = pd.DataFrame(map(dataclasses.asdict, left_out)).sort_values(
        ["vdco_v", "paco_w", "name"], ignore_index=True
    )
    largest_vdco_v = dropped["vdco_v"].max()
    smallest_paco_w = dropped["paco_w"].min()
    gaps = pd.Series(
        {
            "left out": len(dropped),
            "their largest Vdco V": largest_vdco_v,
            "their smallest Paco W": smallest_paco_w,
            "largest kept Paco W at Vdco <= theirs": kept.loc[
                kept["vdco_v"] <= largest_vdco_v, "paco_w"
            ].max(),
            "lowest kept Vdco V at Paco >= theirs": kept.loc[
                kept["paco_w"] >= smallest_paco_w, "vdco_v"
            ].min(),
        }
    )
    return dropped, gaps


def _show(title: str, body: Union[pd.DataFrame, pd.Series, str]) -> None:
    print(f"\n## {title}\n")
    with pd.option_context(
        "display.float_format", "{:.3f}".format, "display.width", 200, "display.max_columns", 20
    ):
        print(body if isinstance(body, str) else body.to_string())


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument(
        "--cache-dir", type=Path, default=DEFAULT_CACHE_DIR, help="weather cache holding the TMY"
    )
    parser.add_argument(
        "--csv", type=Path, help="write one row per sizing and configuration here"
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> None:
    args = _parser().parse_args(argv)
    warnings.filterwarnings(
        "ignore",
        message="invalid value encountered",
        category=RuntimeWarning,
        module=r"scipy\.optimize\._chandrupatla",
    )
    set_weather_cache(WeatherCache(args.cache_dir))
    location = Location.bristol()
    weather = get_tmy_data(location)
    module = create_pv_system(PVConfig.default_4kw()).arrays[0].module_parameters
    _show(
        "Weather",
        f"{location.name} PVGIS TMY: {len(weather)} hours, years "
        f"{sorted(set(weather.index.year))}, minimum air {weather['temp_air'].min():.2f} C, "
        f"GHI {weather['ghi'].sum() / 1000:.1f} kWh/m²",
    )
    cold_hours, default = operating_voltage(location, weather, module)
    _show(f"Hours with module V_mp above {COLD_RATIO} x V_mp_ref", cold_hours)
    _show("Default system", default)
    _show("Cold V_mp factors", proxy_coefficient(module))
    _show("Catalogue", catalogue_ceilings())
    left_out, gaps = battery_inverters()
    _show("Battery inverter/chargers left out", left_out)
    _show("Their gaps", gaps)

    rows = census(location, weather, module)
    if args.csv is not None:
        rows.to_csv(args.csv, index=False)
    stc = rows[rows["sizing"] == STC.label]
    _show("Census at STC sizing", census_table(stc))
    ceiling = edge_error(stc, CEILING)
    _show("Ceiling: error of STC sizing", edge_error_summary(ceiling))
    _show("Ceiling: worst pair per inverter column", ceiling.drop_duplicates("inverter_kw"))
    _show("Headroom alternatives", headroom_table(rows))
    same = identical_picks(rows)
    _show("Sizings with identical picks", "\n".join(f"{a} = {b}" for a, b in same))
    floor = edge_error(stc, FLOOR)
    _show("Floor: error of STC sizing", edge_error_summary(floor))
    _show("Floor: worst pairs", floor.head(10))
    kept = rows[rows["sizing"] == BATTERY_INVERTERS_KEPT.label]
    floor_kept = edge_error(kept, FLOOR)
    _show("Floor: error with battery inverter/chargers kept", edge_error_summary(floor_kept))
    _show("Floor: worst pairs with battery inverter/chargers kept", floor_kept.head(10))
    _show(
        "Re-picked by leaving battery inverter/chargers out",
        repicks(rows, BATTERY_INVERTERS_KEPT),
    )
    _show("Annual yield at default rating, kWh/kWp", annual_yield(stc, module["STC"]))


if __name__ == "__main__":
    main()
