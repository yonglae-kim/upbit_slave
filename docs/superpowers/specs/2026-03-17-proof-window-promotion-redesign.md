# Proof-Window Promotion Redesign

## Goal

Keep the improved trade count from the current `candidate_v1` redesign while improving expectancy by preventing weak trades from graduating into full stop or trailing losses.

## Why This Cycle Exists

The latest 5-symbol 7-day backtest shows that participation is no longer the main problem.

- Baseline reference: `trade_count=4`, `combined_return_pct=-0.0207`, `median_return_pct=0.0`
- Current candidate: `trade_count=38`, `combined_return_pct=-1.0556`, `median_return_pct=-0.1726`

The current candidate now finds trades, but too many filled trades mature into negative stop or trailing outcomes.

Observed failure pattern:

- `KRW-BTC`: 6 trades, negative expectancy, multiple early `initial_defense` stop losses
- `KRW-ADA`: 10 trades, the worst symbol by far, dominated by `initial_defense` stop losses
- `KRW-ETH`: positive return, meaning the system can work when the post-entry trade lifecycle fits the symbol and move quality

This means the next redesign should change what happens *after* entry is accepted, not broadly loosen or tighten entry again.

## Scope

### In Scope

- Strategy-subsystem redesign only
- Candidate post-entry lifecycle logic
- Candidate-specific symbol-conditioned promotion thresholds or cooldown logic
- Minimal shared seam changes only if required to persist the new lifecycle state cleanly

### Out Of Scope

- Broker or runtime architecture changes
- New external data sources
- Artifact schema redesign
- Baseline strategy redesign
- Broad rework of the full backtest engine

## Approved Direction

Use a symbol-conditioned two-stage trade lifecycle.

### Stage 1: Proof Window

Every newly filled candidate trade starts in a short proof window.

Purpose:

- determine whether the trade is behaving like a real continuation, not just a locally valid entry

Requirements:

- during the proof window, the trade should have a stricter expectation of early favorable excursion
- weak trades should be scratched quickly or held to a tighter invalidation model
- proof-window behavior must remain analyzable in the existing stop/trailing CSV outputs

### Stage 2: Promotion To Normal Hold Logic

Only trades that prove enough early favorable excursion graduate into the normal delayed-trailing regime.

Purpose:

- preserve the trade count increase without allowing every filled trade to consume the full risk budget of a trend trade

Requirements:

- promotion is earned by observed trade progress, not by elapsed bars alone
- once promoted, the trade can use the normal delayed-trailing logic already introduced in the previous redesign cycle
- promotion state must be visible in diagnostics and persisted position state

## Symbol-Conditioned Behavior

The same candidate signal should not be trusted equally across all symbols.

Approved bounded use of symbol conditioning:

- symbols with persistently weak recent expectancy, especially `KRW-ADA`, may require a stricter proof threshold
- symbols with repeated weak proof-window outcomes may enter a local cooldown instead of taking every valid entry
- this must remain inside the strategy subsystem and must not require separate runtime paths

## Root Cause This Is Addressing

The previous redesign fixed several structural issues, but the current loss pattern still shows:

1. entries are now frequent enough to matter
2. the early post-entry lifecycle still lets too many weak trades survive into meaningful losses
3. the same lifecycle is being applied too uniformly across symbols with very different short-horizon behavior

The proof-window redesign is meant to convert some of those losses into:

- cheap scratches
- no-promotion holds that exit earlier
- symbol-local throttling on persistently weak names

## Verification Plan

### Unit And Seam Tests

- add tests for proof-window state, promotion thresholds, and candidate-specific cooldown behavior
- verify that promotion is not bars-led
- verify that promoted trades still flow through the shared delayed-trailing path

### Manual Backtest Loop

Re-run the same 5-symbol 7-day set with:

- `KRW-BTC`
- `KRW-ETH`
- `KRW-XRP`
- `KRW-SOL`
- `KRW-ADA`

Success must be judged using:

- trade count
- combined return
- median return
- symbol-level returns
- stop/trailing reason mix
- whether weak-symbol damage, especially `KRW-ADA`, is reduced without collapsing overall participation

## Success Criteria

This redesign is only successful if all of the following are true.

1. Trade count stays materially above the 4-trade baseline reference.
2. Trade count does not collapse materially relative to the current candidate participation level (approximately 38 trades across the 5-symbol set).
3. Combined return improves relative to the current candidate result.
4. Median return improves relative to the current candidate result.
5. The worst-symbol damage, especially from `KRW-ADA`, is reduced materially.
6. Artifact and runtime gate workflows continue to pass without schema changes.

## What Not To Do Next

- Do not loosen entry further before fixing post-entry lifecycle quality.
- Do not widen stops blindly without using proof-window promotion logic.
- Do not reopen broker/runtime architecture in this cycle.
- Do not optimize one symbol only; symbol conditioning must still coexist with a shared candidate strategy.

## Expected Outcome

The next implementation cycle should keep the current candidate signal generator mostly intact but make newly filled trades prove themselves before they are allowed to behave like full trend trades.
