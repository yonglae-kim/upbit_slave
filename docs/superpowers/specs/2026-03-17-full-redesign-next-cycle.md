# Full Redesign Next Cycle

## Goal

Redesign the strategy subsystem so the 5-symbol 7-day backtest keeps the improved trade count but stops destroying expectancy through weak signal quality and stop/trailing behavior.

## Why A Full Strategy Redesign Is Justified

The current candidate path improved participation but not outcome quality.

- Baseline 5-symbol 7-day reference: `trade_count=4`, `combined_return_pct=-0.0207`, `median_return_pct=0.0`.
- Current redesigned candidate: `trade_count=38`, `combined_return_pct=-1.1623`, `median_return_pct=-0.289`.
- Candidate trade generation is highly imbalanced: many symbol runs create hundreds of candidate entries but only a handful of triggered trades.
- Realized losses are dominated by `stop_loss` and `trailing_stop` behavior, while stop-recovery evidence shows a meaningful share of stopped trades would have recovered later.

This means the system is not primarily suffering from lack of opportunity anymore. It is suffering from a mismatch between signal generation, trigger selection, and exit management.

## Scope

### In Scope

- Full redesign of the strategy subsystem only.
- Replace the current `candidate_v1` logic with a new multi-layer strategy flow.
- Keep the shared decision seam, backtest runner, experiment runner, parity runner, and runtime promotion gate intact unless a minimal seam extension is strictly required.
- Reuse existing data sources only.

### Out Of Scope

- Broker rewrites.
- Runtime loop redesign.
- New external market data.
- New artifact schemas.
- Exchange-specific infrastructure changes.

## Root Cause Summary

### 1. Signal/Trigger Mismatch

The current candidate path produces too many upstream candidate setups relative to actual executed trades.

- Candidate entries are counted in the hundreds across symbols, while realized trades stay in single digits.
- This implies the strategy layer and the later trigger layer are not aligned in what qualifies as a good trade.
- The current design lets the strategy say “maybe” too often, then relies on downstream trigger logic to decide which few trades actually fire.

### 2. Exit Expectancy Damage

Losses are concentrated in stop and trailing exit behavior.

- Multiple symbols show stop/trailing exits dominating negative expectancy.
- Some trades reach meaningful MFE before trailing exits or stop exits still leave weak or negative realized R.
- This suggests the system is not distinguishing well between thesis invalidation and short-horizon noise.

### 3. Design Fragmentation

The current subsystem splits responsibility across too many partially independent judgments.

- Regime says one thing.
- Candidate entry says another.
- Adaptive trigger adds another gate.
- Shared exit policy reacts later with only partial knowledge of the original setup intent.

The next cycle should reduce those seams inside the strategy subsystem rather than adding more point fixes.

## Approved Redesign Direction

Replace the current candidate path with three strategy-subsystem layers.

### Layer 1: Compact Short-Horizon Regime Map

Purpose:

- Decide whether the market is in a state where continuation trades should even be considered.

Requirements:

- Use short-horizon parameters appropriate to 7-day 3-minute evaluation.
- Preserve explicit regime labels and diagnostics.
- Keep the regime map lightweight and deterministic.
- The regime map should only answer “what kind of state is the market in?” not “should we enter now?”

### Layer 2: Multi-Timeframe Signal Engine

Purpose:

- Replace the current split between setup builder and later trigger gate.
- Produce a single coherent trade intent candidate in one pass.

Inputs:

- 15m and 5m context for trend state and structure.
- 1m local action for execution timing.

Outputs:

- `entry_ready`
- `entry_price`
- `invalidation_price`
- `expected_hold_type`
- `signal_quality`
- structured diagnostics explaining why a trade is or is not ready

Requirements:

- Do not emit hundreds of vague candidate setups that rely on downstream trigger filtering.
- A signal that reaches the shared seam should already represent a coherent entry thesis.
- Invalidation must be defined as thesis failure, not just local pullback noise.

### Layer 3: Delayed-Trailing Exit Controller

Purpose:

- Keep shared exit architecture but redesign the semantics used for the strategy subsystem.

Requirements:

- Initial stop must represent thesis invalidation.
- Trailing must not activate until the trade has earned room.
- Breakeven or trailing promotion must be tied to actual trade progress, not just early bar noise.
- The controller must preserve strong diagnostics so stop/trailing outcomes remain analyzable in CSV outputs.

## Design Principles

### Keep Runtime Stable

The runtime, brokers, artifact generation, and gate validation are not the current bottleneck. They should stay in place unless a narrow seam change is strictly necessary.

### Make One Layer Own The Trade Thesis

The signal engine should own the full entry thesis, including invalidation and hold intent, so later layers are executing a coherent plan instead of trying to reconstruct one.

### Optimize For Cross-Symbol Robustness

The redesign should not chase one winning coin. It should improve combined and median return across the 5-symbol set while keeping trade count materially above the current baseline reference.

## Verification Plan

### Unit And Seam Tests

- Candidate strategy tests for regime map, signal engine, invalidation logic, and no-trade cases.
- Shared seam tests for propagation of regime, invalidation, sizing, and exit state.
- Backtest runner tests if any reporting or state contract changes are necessary.

### Manual Backtest Loop

Every implementation cycle must rerun the same 5-symbol 7-day set using `TRADING_MODE=dry_run TRADING_STRATEGY_NAME=candidate_v1`.

Required comparison outputs:

- total trade count
- combined return across 5 symbols
- median return across 5 symbols
- symbol-level returns
- stop/trailing reason mix

### Success Criteria

The redesign is only considered successful if:

1. Trade count remains materially above the baseline reference.
2. Combined return improves relative to the current candidate result and ideally exceeds the current baseline reference.
3. Median return improves relative to the current candidate result and moves toward or above zero.
4. Stop/trailing exits no longer dominate negative expectancy in the same way.
5. Artifact and runtime gate workflows still work without schema drift.

## What Not To Do Next

- Do not add more entry looseness before redesigning the strategy thesis.
- Do not widen stops blindly without redefining invalidation logic.
- Do not reopen broker/runtime architecture unless the next cycle proves the strategy subsystem is still not enough.

## Expected Outcome

The next implementation cycle should stop treating `candidate_v1` as a patched version of the current candidate path and instead replace it with a coherent short-horizon strategy subsystem whose entry, trigger timing, invalidation, and trailing rules are designed together.
