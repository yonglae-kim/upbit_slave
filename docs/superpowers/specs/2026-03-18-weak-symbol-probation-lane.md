# Weak-Symbol Probation Lane

## Goal

Improve win rate and preserve positive combined return without materially collapsing trade count by sending weak symbols through a stricter high-conviction entry lane.

## Why This Cycle Exists

The current candidate is already net positive across the 5-symbol 7-day set.

- `trade_count=35`
- `combined_return_pct=+0.4016`
- `median_return_pct=+0.0644`

The remaining drag is concentrated in weaker symbols, especially `KRW-XRP` and `KRW-ADA`.

This means the next bounded redesign should not retune the whole engine. It should reduce low-quality participation only where expectancy is still suspect.

## Scope

### In Scope

- Candidate-only symbol-conditioned entry handling
- Stricter high-conviction entry requirements for weak symbols
- Minimal candidate-only diagnostics needed to verify the probation lane

### Out Of Scope

- Broker/runtime changes
- Backtest engine redesign
- Artifact schema changes
- Baseline strategy changes
- New data sources

## Approved Direction

Introduce a probation lane for weak symbols.

- Normal symbols keep the current candidate entry logic.
- Weak symbols must satisfy a stricter proof of entry quality before they are allowed to enter.
- Exit semantics stay unchanged in this cycle.

## Design

### 1. Weak-Symbol Probation Lane

Weak symbols are not excluded entirely. They are put into a stricter high-conviction lane.

Required behavior:

- apply a higher entry threshold for weak symbols
- require stronger signal quality and/or cleaner multi-timeframe confirmation for weak symbols
- keep diagnostics explicit so a backtest can show whether a trade passed through the probation lane or not

### 2. Keep The Rest Stable

Do not retune the whole candidate engine in this cycle.

- keep the current proof-window lifecycle
- keep current delayed-trailing behavior
- keep current runtime/artifact/gate path intact

## Success Criteria

1. Trade count stays materially above the 4-trade baseline reference.
2. Trade count does not collapse materially relative to the current candidate participation level of 35 trades.
3. Win rate improves relative to the current candidate result.
4. Combined return remains positive and improves if possible.
5. Median return remains positive and improves if possible.
6. Weak-symbol damage, especially from `KRW-XRP` and `KRW-ADA`, is reduced.

## Verification Plan

- candidate strategy/seam tests for weak-symbol probation behavior
- rerun the same 5-symbol 7-day backtest set
- compare trade count, approximate win rate, combined return, median return, and symbol-level returns against the current candidate artifact
