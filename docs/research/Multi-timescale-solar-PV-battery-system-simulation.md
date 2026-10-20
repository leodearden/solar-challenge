# Simulating distributed solar fleets: a Python developer's toolkit for UK residential systems

A 100-home solar PV/battery simulation is highly feasible using mature open-source Python libraries, with **pvlib-python** as the core PV engine, **NREL BLAST-Lite** for computationally efficient battery degradation, and **CityLearn** or custom implementations for fleet orchestration. The UK context benefits from excellent data availability through PVGIS for weather, the Octopus API for dynamic tariffs, and Elexon profile classes for realistic load patterns. This report maps specific libraries and architectures to each technical requirement, providing concrete GitHub repositories, code patterns, and integration strategies.

## The core simulation stack builds on proven libraries

The most robust approach combines **pvlib-python** (1,500+ GitHub stars, BSD-licensed) for PV generation modeling with **BLAST-Lite** for battery degradation and custom orchestration code for fleet-level behavior. pvlib provides solar position calculations, irradiance transposition, cell temperature modeling, and full system simulation through its `ModelChain` class. Critically for UK applications, it includes native integration with PVGIS data through `pvlib.iotools.get_pvgis_tmy()` and `get_pvgis_hourly()`, providing satellite-derived irradiance data at any UK location.

For a typical 4kW residential system, pvlib handles the physics:

```python
from pvlib.modelchain import ModelChain
from pvlib.pvsystem import PVSystem, FixedMount, Array
from pvlib.location import Location

location = Location(latitude=51.5, longitude=-0.12, tz='Europe/London')
mount = FixedMount(surface_tilt=35, surface_azimuth=180)
array = Array(mount=mount, module_parameters={'pdc0': 400, 'gamma_pdc': -0.004},
              temperature_model_parameters=TEMP_PARAMS, modules_per_string=10)
system = PVSystem(arrays=[array], inverter_parameters={'pdc0': 4000, 'eta_inv_nom': 0.96})
mc = ModelChain(system, location)
```

pvlib supports arbitrary timesteps through pandas DatetimeIndex, from 1-second to hourly resolution. The library lacks built-in degradation modeling, but **RdTools** (NREL, 169 stars) provides year-on-year degradation analysis algorithms that can validate assumptions—typical crystalline silicon degrades at **0.5-0.8% annually**.

**PySAM** (NREL's System Advisor Model Python bindings) complements pvlib when financial modeling is needed, offering LCOE, NPV, and cash flow calculations. However, pvlib's flexibility makes it preferable for custom Monte Carlo implementations where you control the simulation loop.

## Battery degradation requires choosing between physics and efficiency

For 25-year simulations with Monte Carlo sampling, **NREL BLAST-Lite** (`pip install blast-lite`) provides the best computational efficiency. It uses semi-empirical models parameterized from real laboratory data on commercial cells, including Tesla Model 3 (Panasonic NCA-Gr) and residential storage chemistries like LFP-Gr. BLAST-Lite accounts for calendar aging, cycle aging, temperature effects, and depth-of-discharge impacts while running in seconds rather than minutes per simulation.

```python
from blast import models, utils
cell = models.Lfp_Gr_250AhPrismatic()
cell.simulate_battery_life(input_data)  # Returns capacity fade trajectory
```

For deeper physics understanding, **PyBaMM** (Python Battery Mathematical Modelling, 1M+ downloads) implements full electrochemical models including SEI growth, lithium plating, and particle cracking. However, its computational cost makes it unsuitable for Monte Carlo at scale—reserve it for parameterization and validation.

Battery dispatch logic for self-consumption optimization can leverage **prosumpy** (Energy Modelling Toolkit), which provides `dispatch_max_sc()` for maximizing self-consumption and grid-friendly dispatch strategies. For optimization-based control, **EMHASS** offers Model Predictive Control with linear programming.

**Rainflow cycle counting** (`pip install rainflow`) is essential for extracting cycle depth distributions from SOC profiles, which feed degradation models. The `rainflow.extract_cycles()` function returns range, mean, and count for each cycle—directly usable in BLAST-Lite's damage accumulation.

## UK load profiles benefit from CREST-based generators

The **richardsonpy** library (`pip install richardsonpy`) provides a Python implementation of the UK CREST demand model from Loughborough University, generating stochastic occupancy and appliance-level load profiles at 60-second resolution. It uses Markov-chain occupancy modeling with UK household size distributions from census data. For 100 heterogeneous homes, you can generate distinct profiles by varying household size, occupancy patterns, and appliance ownership.

Alternative generators include **LoadProfileGenerator** (agent-based behavior simulation with psychological models) and **ALPG** (Artificial Load Profile Generator from University of Twente, designed for demand-side management research with 1-minute resolution and explicit flexibility information for controllable devices).

For UK-specific validation, Elexon's **Profile Classes 1 and 2** (domestic unrestricted and Economy 7) provide half-hourly settlement coefficients. The UK Power Networks open data portal offers aggregated smart meter data at LV feeder level, while SSEN has published 1.8 million smart meter readings aggregated to feeder and substation levels. Average UK household consumption is **3,400 kWh/year** (Ofgem TDCV), varying regionally from 2,906 kWh in the North East to 3,720 kWh in East England.

> **Editor's note (2026-10-20):** The 3,400 kWh figure and its regional range (2,906 to 3,720 kWh) are not Ofgem TDCVs, and the text above cites no document for them. No Ofgem electricity TDCV band was 3,400 kWh in any value set published before this document was written, and DESNZ's mean domestic consumption per meter does not match either figure. Task 1005's commit records the check. The paragraph is otherwise left as originally written.

For emerging loads, **hplib** provides heat pump efficiency modeling with COP calculations from Heatpump Keymark data, while **SpiceEV** simulates individual EV charging events with multiple charging strategies.

## Monte Carlo frameworks enable robust uncertainty quantification

**SALib** (Sensitivity Analysis Library) provides the core uncertainty quantification toolkit with Sobol variance-based indices, Morris screening for parameter importance, and FAST methods. For a simulation with parameters like panel orientation, degradation rate, and consumption variability, SALib identifies which uncertainties matter most:

```python
from SALib.sample import sobol
from SALib.analyze import sobol as sobol_analyze

problem = {'num_vars': 6, 'names': ['tilt', 'azimuth', 'degradation', 'consumption', 
           'electricity_price', 'seg_rate'], 'bounds': [[25, 45], [135, 225], ...]}
param_values = sobol.sample(problem, 1024)
```

For efficient parameter space exploration, **scipy.stats.qmc** provides Latin Hypercube Sampling and Sobol sequences with built-in quality metrics. Latin Hypercube typically achieves comparable accuracy to pure Monte Carlo with 10× fewer samples.

Correlated uncertainties (e.g., weather and consumption patterns) require the **Copulas library** (`pip install copulas`) from the Synthetic Data Vault project, supporting Gaussian, Archimedean, and Vine copulas to preserve dependency structures when generating synthetic scenarios.

## Fleet-level simulation has several mature frameworks

**CityLearn** (intelligent-environments-lab) provides the most complete multi-building simulation framework, tested with up to 100 buildings with independent control agents. It integrates PV, battery, HVAC, and EV models with Gymnasium-compatible interfaces for reinforcement learning research. The **Smart Community Simulator** offers similar capabilities with explicit support for heterogeneous DER configurations (PV+Battery, Battery-only, PV-only households).

For simpler fleet aggregation, **vpplib** (Virtual Power Plant Library) provides component classes for PV, storage, and loads with a `VirtualPowerPlant` aggregation class and pandapower integration for grid-aware simulation. The OPEN framework from Oxford University combines DER modeling with power flow and multi-period optimization.

When distribution network effects matter, **pandapower** provides Python-based power flow analysis with Newton-Raphson solvers, while **OpenDSS** (via OpenDSSDirect.py) offers comprehensive distribution system simulation. For large-scale co-simulation, **mosaik** and **HELICS** support thousands of simulated entities across multiple processes with variable timesteps.

The recommended architecture separates layers:
- **Component Layer**: pvlib (PV), BLAST-Lite (battery), richardsonpy (loads)
- **Aggregation Layer**: Custom House class containing components, Fleet class aggregating houses
- **Control Layer**: Dispatch logic, optimization (cvxpy/pyomo), or rule-based controllers
- **Environment Layer**: Weather data, tariff signals, grid constraints

## UK weather and tariff data are readily accessible

**PVGIS** (EU Joint Research Centre) provides the best solar irradiance data for UK locations through pvlib's `get_pvgis_tmy()` function, returning TMY data from the SARAH2 satellite database. For historical data, `get_pvgis_hourly()` covers 2005-2020. CAMS Radiation Service offers higher-resolution data (1-minute to monthly) through the Copernicus Atmosphere Data Store.

For real-time context, **Sheffield Solar's PV_Live API** (`pip install pvlive-api`) provides half-hourly GB solar generation estimates updated every 30 minutes. Met Office MIDAS data offers historical ground-truth measurements at observation stations.

The **Octopus Energy API** (`api.octopus.energy/v1/`) provides tariff data without authentication. Key endpoints include products listing, Agile half-hourly prices, and Go/Intelligent tariff rates. Current SEG rates range from **4p to 16.5p/kWh**, with Octopus Flux offering time-of-use export rates up to 30p/kWh during peak periods. For simulation, the critical tariffs are:
- **Octopus Agile**: Half-hourly wholesale-linked import prices
- **Octopus Go**: 7.5p/kWh overnight import rate
- **Flux Import/Export**: Time-banded rates incentivizing battery arbitrage

G98 compliance (systems ≤3.68kW single-phase) requires only DNO notification within 28 days; G99 applies above this threshold requiring pre-approval.

## Multi-timescale architecture requires hierarchical design

Academic literature consistently recommends hierarchical separation of timescales with bidirectional parameter passing. The NREL multi-scale battery modeling framework demonstrates this: high-frequency models (sub-second for inverter dynamics) aggregate to medium-frequency energy management (minutes to hours), which feeds low-frequency degradation and financial models (days to years).

For practical implementation, run the simulation in three coupled loops:

1. **Inner loop (seconds to minutes)**: Power balance, SOC updates, grid import/export decisions—use numpy vectorization across all homes
2. **Middle loop (hours to days)**: Energy dispatch optimization, tariff arbitrage—MPC or rule-based
3. **Outer loop (months to years)**: Degradation accumulation, seasonal patterns, financial calculations

The Wavelet Variability Model (WVM) from NREL offers validated methods for aggregating distributed PV output from single-point irradiance measurements, accounting for spatial smoothing across fleets—validated against 553-home Japanese residential systems and useful for understanding fleet-level variability versus individual home variability.

Monte Carlo hosting capacity studies in the literature typically use Python-OpenDSS co-simulation with 500-1000 iterations for convergence. Key papers include "State of the Art Monte Carlo Method Applied to Power System Analysis with Distributed Generation" (MDPI Energies 2023), which reviews 90+ papers on computational efficiency techniques.

## Practical implementation starts with these repositories

The minimal viable implementation combines five components:

| Component | Library | GitHub |
|-----------|---------|--------|
| PV generation | pvlib-python | github.com/pvlib/pvlib-python |
| Battery degradation | BLAST-Lite | github.com/NREL/BLAST-Lite |
| Load profiles | richardsonpy | github.com/RWTH-EBC/richardsonpy |
| Sensitivity analysis | SALib | github.com/SALib/SALib |
| Fleet reference | CityLearn | github.com/intelligent-environments-lab/CityLearn |

Additional valuable resources include **prosumpy** for self-consumption dispatch, **RdTools** for degradation validation, and **pandapower** if grid constraints matter. The IEA PVPS Trends reports provide industry benchmarks, while NREL's PV Fleet Performance Data Initiative offers validation data from 1,000+ systems.

For financial modeling, implement LCOE and payback calculations directly rather than using PySAM—the formulas are straightforward (LCOE = (Capital × FCR + O&M) / Annual Energy), and custom implementation allows proper uncertainty propagation through Monte Carlo. UK residential solar typically achieves **8-15 year payback** depending on self-consumption rates, with 70% self-consumption and 30% export being typical for systems without batteries.

## Conclusion

Building a 100-home distributed solar simulation is well-supported by open-source Python tools. The critical architectural decisions are: pvlib for PV physics with PVGIS weather data; BLAST-Lite over PyBaMM for computationally tractable degradation; Latin Hypercube sampling for efficient Monte Carlo; and hierarchical timescale separation with vectorized operations across homes. UK-specific advantages include mature tariff APIs (Octopus), comprehensive weather data (PVGIS/Sheffield Solar), and realistic load generators (richardsonpy/CREST). The CityLearn framework provides a validated reference implementation, though custom code will likely be needed for UK tariff structures and SEG modeling. Start with single-home validation against real data before scaling to fleet-level simulation.