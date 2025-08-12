# Fantasy Football Model Validation

## Quick Start

Just run this command from the project root:

```bash
python tests_and_validation/run_validation.py
```

That's it! The script will:
1. Download 2023 NFL data (cached after first run)
2. Run rolling holdout validation
3. Show you if the model is working well
4. Save detailed results for analysis

## What It Tests

### 1. **Holdout Validation** (Most Important)
- Trains on weeks 1-8, predicts week 9, compares to actual
- Rolls forward each week (train 1-9, predict 10, etc.)
- Mimics real-world usage perfectly

### 2. **Key Metrics**

#### Regression Metrics (Point Predictions)
- **MAE** (Mean Absolute Error): How many points off are we on average?
  - < 5 points = Excellent
  - 5-8 points = Good
  - > 8 points = Needs work

- **RMSE**: Like MAE but penalizes big misses more
- **R²**: How much variance we're explaining (higher is better)

#### Classification Metrics (Start/Sit Decisions)
- **Precision**: When we say "start", how often do they perform well?
  - > 70% = Excellent
  - 60-70% = Good
  - < 60% = Needs tuning

- **Recall**: Of all the breakout performances, how many did we catch?
- **F1 Score**: Balance between precision and recall

#### Decision Value
- **Points Added**: Do our starters score more than our bench?
  - > 5 pts/week = Great
  - 0-5 pts/week = Good
  - < 0 = Problem!

#### Lineup Efficiency
- What % of the optimal lineup score did we achieve?
  - > 85% = Excellent
  - 75-85% = Good
  - < 75% = Room for improvement

## Understanding Results

After running validation, you'll see something like:

```
✅ VALIDATION COMPLETE - KEY FINDINGS
===============================================

📈 Model Performance:
  ✅ Good: Off by 6.3 points on average
  ✅ Excellent: 72% of 'start' recommendations performed well
  ✅ Great value: Starters scored 7.2 pts more than bench
  ✅ Good: Achieved 82% of optimal lineup score

🎯 Overall Assessment:
  ✅ MODEL IS WORKING WELL!
  The statistical refinements are showing positive results.
```

## File Structure

```
tests_and_validation/
├── run_validation.py        # 👈 RUN THIS - Simple entry point
├── tests/                   # Unit tests
│   └── test_*.py           # All test files
├── validation/             # Validation modules
│   ├── advanced_validator.py    # Core validation logic
│   ├── historical_validator.py  # Original validator
│   └── backtest_runner.py      # Comprehensive runner
└── data/                   # Cached data (gitignored)
    ├── nfl_historical.parquet  # Cached NFL data
    └── *.json                  # Validation results
```

## Advanced Usage

### Run Full Multi-Season Validation
```bash
python tests_and_validation/run_validation.py --full
```

### Run Specific Validation Scripts
```bash
# Advanced validator with detailed metrics
python tests_and_validation/validation/advanced_validator.py

# Original comprehensive backtest
python tests_and_validation/validation/backtest_runner.py --season 2023
```

## Interpreting Model Performance

### Good Model Signs:
- MAE < 8 points
- Precision > 65%
- Positive decision value (starters > bench)
- Efficiency > 75%

### Red Flags:
- MAE > 10 points (predictions way off)
- Precision < 50% (bad start/sit calls)
- Negative decision value (bench outscoring starters)
- Efficiency < 70% (missing optimal lineups)

## What The Validation Proves

1. **Tier System Works**: Elite players consistently outscore lower tiers
2. **Matchup Predictions Valid**: Correlation between predicted and actual
3. **Adds Value**: Recommendations beat random selection by significant margin
4. **Real-World Ready**: Holdout validation mimics actual usage

## Troubleshooting

### "Module not found" Error
```bash
pip install nfl-data-py matplotlib seaborn
```

### Data Download Issues
- First run downloads ~100MB of NFL data
- Cached in `tests_and_validation/data/`
- Delete cache files to force fresh download

### Memory Issues
- Reduce roster size in `run_validation.py`
- Test fewer weeks with `min_train_weeks` parameter

## Next Steps

After validation shows the model works:
1. Fine-tune parameters based on results
2. Test with your actual Yahoo roster
3. Run during the season for real-time validation
4. Compare different strategies (balanced vs matchup_heavy)