# Short-Horizon Candidate Strategy Redesign

## Goal

Improve the 5-symbol 7-day backtest so it produces meaningful trade count and better combined profitability by redesigning `candidate_v1` for short-horizon 3-minute data.

## Problem Statement

The current short-horizon backtest is not yet a reliable profitability signal.

- Recent 7-day backtests across `KRW-BTC`, `KRW-ETH`, `KRW-XRP`, `KRW-SOL`, and `KRW-ADA` produce very low trade counts.
- Many segment rows are dominated by `regime_filter_fail:insufficient_15m_candles`.
- The current positive result on `KRW-ETH` is effectively driven by a single successful trade, while multiple symbols remain flat or negative.
- This means the present system is under-trading rather than expressing a strong directional edge.

## Approved Direction

Redesign `candidate_v1` for short-horizon 3-minute backtests.

- Keep the shared decision seam, registry, experiment runner, parity runner, and runtime promotion gate intact.
- Do not redesign brokers, engine architecture, or artifact schemas.
- Do not introduce external data sources.
- Target only strategy behavior and the strategy-facing parameter defaults required to make the strategy meaningful on the requested 7-day multi-symbol backtests.

## Strategy Redesign

### 1. Shorter Regime Horizon

The current regime path is too heavy for the requested 7-day evaluation horizon.

Required changes:

- Reduce the effective regime horizon used by `candidate_v1` so it can evaluate reliably on 7 days of 3-minute candles.
- Preserve regime classification as a real filter, but avoid 15-minute warmup rules that cause most segments to become non-trading.
- Keep regime labels explicit in diagnostics and consistent through the shared seam.

Intended effect:

- more segments with actual trading opportunities
- fewer strategy rejections caused purely by oversized warmup requirements

### 2. Simpler Entry Logic

`candidate_v1` should remain a trend-following pullback strategy, but with fewer hard gates.

Required changes:

- Keep the high-level shape: trade only in allowed trend regimes, not sideways.
- Simplify the pullback-and-reclaim test so it accepts more valid short-horizon continuation setups.
- Prefer deterministic, explainable conditions over score-heavy composition.
- Keep diagnostics stable: regime, entry price, stop price, stop basis, risk/R, and sizing-related fields must remain available.

Intended effect:

- higher candidate trade count
- fewer false negatives from brittle reclaim confirmation

### 3. Simpler Exit Behavior

For this iteration, the exit path should favor consistency and faster feedback over complexity.

Required changes:

- Keep `PositionOrderPolicy` as the shared execution boundary.
- Adjust candidate-facing stop and profit behavior so it is less likely to stop out immediately after entry.
- Avoid adding custom multi-stage candidate exits unless they are strictly necessary.
- Prefer one clear ATR/structure-based protection model and one clear profit-taking model.

Intended effect:

- less noise from overly tight stop behavior
- more interpretable trade outcomes in repeated backtests

## Iteration Policy

The implementation is allowed to iterate through multiple strategy revisions, but only within the approved direction above.

Each iteration must:

- keep the shared seam contract intact
- run the relevant test suite
- run the 5-symbol 7-day backtests
- compare both trade count and profitability against the previous iteration

## Success Criteria

The redesign is considered successful only if all of the following are true.

1. `candidate_v1` still runs through the shared registry and decision seam.
2. The candidate strategy tests and seam tests pass.
3. The 5-symbol 7-day backtest set executes successfully for `KRW-BTC`, `KRW-ETH`, `KRW-XRP`, `KRW-SOL`, and `KRW-ADA`.
4. The redesign increases the number of actual trades enough that the backtest is more meaningful than the current mostly-empty-segment baseline.
5. The redesign improves either combined return across the 5-symbol set or median return across the 5-symbol set, without collapsing trade count back toward zero.
6. Diagnostics, experiments, parity artifacts, and runtime gating remain valid after the strategy change.

## Verification Plan

### Tests

- `python3 -m unittest testing.test_candidate_strategy_v1 testing.test_decision_core testing.test_strategy_registry`
- any additional touched engine/backtest/config tests if the strategy-facing defaults require them

### Manual Backtest QA

Run all of the following after each meaningful strategy iteration:

- `python3 -m testing.backtest_runner --market KRW-BTC --lookback-days 7 --path testing/artifacts/backdata_krw_btc_7d.xlsx --segment-report-path testing/artifacts/krw_btc_7d_segments.csv --stop-diagnostics-path testing/artifacts/krw_btc_7d_stop_loss.csv --stop-recovery-path testing/artifacts/krw_btc_7d_stop_recovery.csv`
- `python3 -m testing.backtest_runner --market KRW-ETH --lookback-days 7 --path testing/artifacts/backdata_krw_eth_7d.xlsx --segment-report-path testing/artifacts/krw_eth_7d_segments.csv --stop-diagnostics-path testing/artifacts/krw_eth_7d_stop_loss.csv --stop-recovery-path testing/artifacts/krw_eth_7d_stop_recovery.csv`
- `python3 -m testing.backtest_runner --market KRW-XRP --lookback-days 7 --path testing/artifacts/backdata_krw_xrp_7d.xlsx --segment-report-path testing/artifacts/krw_xrp_7d_segments.csv --stop-diagnostics-path testing/artifacts/krw_xrp_7d_stop_loss.csv --stop-recovery-path testing/artifacts/krw_xrp_7d_stop_recovery.csv`
- `python3 -m testing.backtest_runner --market KRW-SOL --lookback-days 7 --path testing/artifacts/backdata_krw_sol_7d.xlsx --segment-report-path testing/artifacts/krw_sol_7d_segments.csv --stop-diagnostics-path testing/artifacts/krw_sol_7d_stop_loss.csv --stop-recovery-path testing/artifacts/krw_sol_7d_stop_recovery.csv`
- `python3 -m testing.backtest_runner --market KRW-ADA --lookback-days 7 --path testing/artifacts/backdata_krw_ada_7d.xlsx --segment-report-path testing/artifacts/krw_ada_7d_segments.csv --stop-diagnostics-path testing/artifacts/krw_ada_7d_stop_loss.csv --stop-recovery-path testing/artifacts/krw_ada_7d_stop_recovery.csv`

### Guardrails

- Do not claim success from a single-symbol win.
- Do not reduce filtering so far that the system trades constantly without edge.
- Do not silently change artifact schemas or runtime gate semantics.
- Do not optimize only for one coin.

## Expected Output

At the end of implementation, the user should be able to see:

- what changed in `candidate_v1`
- how trade count changed across the 5-symbol set
- whether aggregate and median returns improved
- whether the redesign still passes tests and keeps the promotion/gating workflow intact
