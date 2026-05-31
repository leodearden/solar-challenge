# Solar Challenge Energy Flow Simulator

A Python-based energy flow simulator for the Solar Challenge community energy project in Bristol, UK. This tool models solar PV generation, battery storage, and household consumption to support the planning and analysis of distributed solar installations across 100 homes.

## Project Goals

1. **Demonstrate technical viability** of community-scale solar PV + battery systems
2. **Estimate energy flows** including generation, self-consumption, and grid export
3. **Provide foundation** for financial modelling and project planning
4. **Support open-source principles** - all code and methodologies are transparent

## Current Phase Scope

Version 0.1 focuses on:
- Self-consumption modelling for individual homes
- Smart Export Guarantee (SEG) export calculation
- Fleet-level aggregation for 100 homes

More sophisticated power-sharing schemes are planned for future phases.

## Technical Stack

- **pvlib-python**: PV generation modelling (BSD licensed)
- **pandas**: Time series handling
- **richardsonpy**: UK CREST-based stochastic load profiles (windowed per-day simulation)
- **PVGIS**: Solar irradiance data for Bristol (51.45°N, 2.58°W)

## Setup

### Prerequisites

- Python 3.10 or higher
- pip package manager

### Installation

1. Clone the repository:
   ```bash
   git clone <repository-url>
   cd my-solar-challenge
   ```

2. Run the setup script:
   ```bash
   chmod +x init.sh
   ./init.sh
   ```

   Or manually:
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```

3. Verify installation:
   ```bash
   python -c "import pvlib; import pandas; print('Setup OK')"
   ```

4. (Optional) The `[stochastic]` extra is retained as a backward-compatibility alias
   but is now empty — `richardsonpy` is installed automatically as a core dependency:
   ```bash
   pip install "solar-challenge"          # includes richardsonpy
   pip install "solar-challenge[stochastic]"  # same result; alias kept for compatibility
   ```
   Stochastic UK CREST-based household load profiles are enabled by default.
   Pass `use_stochastic=False` in `LoadConfig` to use the deterministic Elexon fallback.

## Running Tests

```bash
# Activate virtual environment
source venv/bin/activate

# Run all tests
pytest -v

# Run with coverage
pytest --cov=src/solar_challenge
```

## Project Structure

```
my-solar-challenge/
├── src/
│   └── solar_challenge/     # Main package
├── tests/
│   ├── unit/                # Unit tests
│   ├── integration/         # Integration tests
│   └── conftest.py          # Shared fixtures
├── long_running/
│   └── solar-simulator/     # Development harness
│       ├── feature_list.json
│       ├── progress.txt
│       └── init.sh
├── requirements.txt         # Python dependencies
├── pyproject.toml           # Project configuration
└── README.md
```

## Development

This project follows test-driven development (TDD). Features are tracked in `long_running/solar-simulator/feature_list.json` and progress is logged in `long_running/solar-simulator/progress.txt`.

### Feature Status

See `long_running/solar-simulator/feature_list.json` for the complete list of features and their implementation status.

## Data Sources

- **PVGIS** (EU JRC): Solar irradiance data via pvlib integration
- **Ofgem TDCV**: UK average household consumption benchmarks (3,400 kWh/year)
- **Elexon Profile Classes**: Load shape validation data

## License

This project is licensed under the **MIT License**. See [LICENSE](LICENSE) for details.

## Contributing

Contributions welcome. Please ensure all code:
- Includes type hints
- Has corresponding tests
- Passes mypy type checking
- Follows existing code style
