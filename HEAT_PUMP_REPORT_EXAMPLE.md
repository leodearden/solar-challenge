# Heat Pump Report Enhancement - Example Output

This document shows the expected output format after the heat pump report enhancement.

## Before (Old Format)
```markdown
## Heat Pump
| Metric | Value |
|--------|-------|
| Total Heat Pump Load | 4500.0 kWh |
| Peak Heat Pump Load | 6.50 kW |
| Heat Pump Load Ratio | 55.2% |
```

## After (Enhanced Format)
```markdown
## Heat Pump Impact
| Metric | Value |
|--------|-------|
| Total Heat Pump Load | 4500.0 kWh |
| Peak Heat Pump Load | 6.50 kW |
| Heat Pump % of Total Demand | 55.2% |

### Seasonal Heat Pump Analysis
**Winter (Dec-Feb) vs Summer (Jun-Aug)**

| Metric | Winter | Summer | Winter/Summer Ratio |
|--------|--------|--------|---------------------|
| Total Heat Pump Load | 2800.0 kWh | 450.0 kWh | 6.2x |
| Peak Heat Pump Load | 6.50 kW | 1.20 kW | 5.4x |
| HP % of Demand | 68.5% | 32.1% | - |
| Daily Average | 31.1 kWh/day | 5.0 kWh/day | 6.2x |

**Key Insights:**
- Heat pump demand is **6.2x higher** in winter than summer
- Heat pump accounts for **68.5%** of winter demand vs **32.1%** in summer
```

## Key Enhancements

1. **Clearer Section Title**: "Heat Pump Impact" instead of just "Heat Pump"
2. **Better Metric Names**: "Heat Pump % of Total Demand" instead of "Heat Pump Load Ratio"
3. **Seasonal Breakdown**: New subsection showing winter vs summer comparison
4. **Comparison Ratios**: Shows how much higher winter demand is compared to summer
5. **Daily Averages**: Shows average daily heat pump usage per season
6. **Key Insights**: Highlights the most important findings in plain language

## Code Changes

The enhancement:
- Calculates seasonal metrics (winter: Dec-Feb, summer: Jun-Aug)
- Filters time series data by month using pandas `.isin()` method
- Converts power (kW) to energy (kWh) accounting for 1-minute resolution
- Computes ratios and averages with proper divide-by-zero protection
- Formats output using markdown tables with clear column headers
- Adds bold emphasis to key numbers in the insights section

## Verification

To verify this works correctly:

1. Run a simulation with heat pump enabled
2. Generate a summary report
3. Check that:
   - Heat pump section title says "Heat Pump Impact"
   - Seasonal analysis subsection is present
   - Winter/Summer ratios are calculated
   - Key insights highlight the differences
   - All numbers format correctly (1 decimal for kWh, 2 for kW, percentages)
