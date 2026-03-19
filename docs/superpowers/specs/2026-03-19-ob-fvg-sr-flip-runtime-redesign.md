# OB/FVG/SR Flip Runtime Redesign

## Goal

Implement a real Order Block / Fair Value Gap / Support-Resistance Flip strategy in the active runtime/backtest path, with win rate and return as the first optimization goals.

## Why The Previous Attempt Failed

The current dirty `candidate_v1` rewrite only added a static zone-confluence gate on top of the short-horizon pullback/reclaim strategy. It reused FVG/OB/SR helper functions, but it did not implement a true S/R Flip workflow.

- It treated S/R Flip as a simple support-band intersection instead of break -> retest -> hold.
- It kept the old `candidate_v1` pullback/reclaim trigger stack as the main strategy body.
- It still left `candidate_v1.should_exit_long(...)` as `False`, so profit realization remained dependent on generic policy exits.
- The resulting 6-symbol fee-aware checkpoint weakened from `trade_count=30`, `approx_win_rate_pct=26.67`, `combined_return_pct=+0.6409`, `median_return_pct=+0.0322` to `27 / 22.22 / +0.3076 / +0.0322`.

## Research Conclusions

The repo already contains most of the reusable pieces for a complete OB/FVG/SR strategy:

- `core/strategy.py` already implements:
  - SR pivot detection and clustering
  - SR scoring
  - FVG detection with displacement filters
  - OB detection with displacement filters
  - active-zone filtering
  - 1m trigger evaluation with strict / balanced / adaptive modes
- The runtime/backtest seam already supports strategy-driven exits through `strategy.exit_evaluator(...)` and `strategy_signal` in `core/decision_core.py` and `core/position_policy.py`.
- The registry seam is stable and only needs `candidate_v1` to keep exposing the same canonical strategy name.

External research confirms the missing conceptual piece: S/R Flip must be modeled as break -> retest -> hold, not just static overlap.

## Approved Direction

Replace the current `candidate_v1` internals with an adapter over the mature OB/FVG/SR engine in `core.strategy`, and extend that engine with an explicit S/R Flip state check.

### Entry model

1. `15m` still supplies regime and higher-timeframe S/R structure.
2. `5m` supplies setup zones:
   - bullish FVG
   - bullish OB
3. A valid bullish S/R Flip requires:
   - recent close-through of a scored resistance band,
   - subsequent retest into that band within tolerance,
   - hold / reclaim back above that band.
4. Candidate long entry requires:
   - regime filter pass,
   - active bullish OB or bullish FVG,
   - valid bullish S/R Flip context,
   - existing 1m trigger confirmation from the legacy trigger engine.

### Exit model

`candidate_v1.should_exit_long(...)` stops returning `False` and instead uses the strategy-side sell engine so bearish OB/FVG/SR conditions can emit `strategy_signal`. The shared position policy remains the execution guardrail and still enforces the required-R rule before allowing that signal to close the trade.

This keeps the stable runtime/backtest seam intact while replacing the weak candidate internals with a real OB/FVG/SR-Flip strategy.

## Scope

### In Scope

- Rewrite `candidate_v1` to use the mature OB/FVG/SR engine instead of the current pullback/reclaim body
- Add explicit S/R Flip evaluation to `core/strategy.py`
- Use strategy-side exits for candidate through the existing seam
- Update tests, parity fixtures, experiment harness coverage, and project docs

### Out Of Scope

- Re-enabling `sr_ob_fvg` as a separate runtime/backtest selectable strategy
- Universe-selection redesign in this cycle
- External data sources or coin-specific heuristics

## Success Criteria

1. `candidate_v1` entry is driven by OB/FVG/SR-Flip logic rather than the current pullback/reclaim stack.
2. S/R Flip is implemented as break -> retest -> hold and is visible in diagnostics.
3. `candidate_v1.should_exit_long(...)` can produce real strategy-side exits through the shared seam.
4. Candidate/parity/experiment harnesses still pass without reviving `sr_ob_fvg` selection.
5. The fresh 6-symbol fee-aware candidate backtest improves win rate and return over the current dirty checkpoint `27 / 22.22 / +0.3076 / +0.0322`.

## Verification Plan

- `testing/test_main_signals.py` covers the pure OB/FVG/SR/trigger helpers and will gain focused S/R Flip tests.
- `testing/test_candidate_strategy_v1.py` will be rewritten to reflect the new candidate adapter semantics.
- `testing/test_decision_core.py`, `testing/test_experiment_runner.py`, and `testing/test_parity_runner.py` will keep the shared seam and promotion/parity surfaces stable.
- Run:
  - `python3 -m unittest testing.test_main_signals testing.test_candidate_strategy_v1 testing.test_decision_core testing.test_strategy_registry`
  - `python3 -m unittest testing.test_backtest_runner testing.test_config_loader testing.test_engine_order_acceptance testing.test_experiment_runner testing.test_parity_runner`
- Run changed-file diagnostics on all modified Python files.
- Re-run the fee-aware 6-symbol candidate backtest on `KRW-BTC`, `KRW-ETH`, `KRW-XRP`, `KRW-SOL`, `KRW-ADA`, `KRW-ANKR` and compare against the current dirty checkpoint.
