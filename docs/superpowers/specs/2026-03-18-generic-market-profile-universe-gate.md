# Generic Market-Profile Universe Gate

## Goal

Improve trade count, win rate, and return across a broader KRW market set by replacing residual coin-specific handling with a generic market-profile gate shared by production universe selection and broader backtest evaluation.

## Why This Cycle Exists

The current candidate can be positive on a narrower set, but becomes negative when the evaluation expands to a broader fee-aware KRW basket including `KRW-ANKR`.

- Recent 6-symbol fee-aware run: `trade_count=26`, `approx_win_rate_pct=3.85`, `combined_return_pct=-1.1433`, `median_return_pct=-0.2108`
- Negative symbols are not failing for coin-name reasons. They are failing because the current system still admits low-quality markets that share generic traits: weaker liquidity/participation quality, more fragile trend persistence, and poor post-entry proof.

## Scope

### In Scope

- Generic market-profile gate for candidate entry admission
- Generic universe-selection improvements based on market quality signals already available in runtime/backtest context
- Broad fee-aware KRW backtests including `KRW-ANKR`

### Out Of Scope

- Coin-specific heuristics
- External data sources
- Broker/runtime loop rewrites
- Artifact schema changes

## Approved Direction

Introduce a generic market-profile gate built from already-available signals.

Required inputs:

- liquidity and recent traded-value context
- spread context
- missing-data quality
- short-horizon trend persistence / setup quality

Required behavior:

- the same gate logic must apply to every KRW symbol
- weak markets may still be considered, but only if they clear the same generic quality bar
- the gate should be usable both in runtime universe selection and in broader backtest loops

## Success Criteria

1. No coin-name-specific candidate logic remains in the strategy path.
2. The broader fee-aware KRW set including `KRW-ANKR` can be backtested with the generic gate active.
3. Trade count remains meaningfully above the 4-trade baseline reference.
4. Approximate win rate improves relative to the last 6-symbol negative run.
5. Combined return and median return improve relative to the last 6-symbol negative run.

## Verification Plan

- candidate/seam tests for generic market-profile gating
- universe-selection tests if production watchlist logic changes
- broader fee-aware KRW backtests including `KRW-ANKR`
