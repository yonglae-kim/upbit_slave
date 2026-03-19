# Candidate Zone Confluence Redesign

## Goal

Apply Fair Value Gap, Order Block, and S/R Flip concepts to the active `candidate_v1` strategy path without reviving the legacy `sr_ob_fvg` runtime surface.

## Why This Cycle Exists

The active broad backtest path currently runs `candidate_v1`, but that strategy does not use the repo's dormant FVG / Order Block / S/R zone logic.

- Active runtime/backtest selection allows `baseline`, `candidate_v1`, and `rsi_bb_reversal_long`; `sr_ob_fvg` is explicitly rejected as a runtime/backtest strategy.
- `core/config.py` and `core/strategy.py` still contain reusable zone parameters and pure helper functions for SR pivots, SR scoring, FVG detection, OB detection, and zone ranking.
- `core/strategies/candidate_v1.py` currently uses only `15m` regime + `5m` reset context + `1m` reclaim trigger.

## Scope

### In Scope

- Add FVG / Order Block / S/R Flip-aware setup logic to `candidate_v1`
- Reuse pure helper functions already present in `core/strategy.py`
- Keep the existing shared runtime/backtest seam centered on `candidate_v1`
- Add or update tests that pin the new entry behavior and seam diagnostics

### Out Of Scope

- Re-enabling `sr_ob_fvg` as a selectable runtime/backtest strategy
- Exit-policy redesign in this cycle
- Universe-selection redesign in this cycle
- External indicators, external data, or coin-specific heuristics

## Approved Direction

Keep `candidate_v1` as the only active strategy surface and extend its existing entry evaluation with a bounded zone-confluence layer.

The new entry stack is:

1. `15m` regime still decides whether the market is tradeable.
2. `5m` still provides the candidate's existing trend-reset setup.
3. Reusable legacy helpers compute:
   - scored SR levels from `15m`
   - bullish FVG / bullish OB setup zones from `5m`
   - active zones near the current `5m` price
4. `candidate_v1` selects a bullish zone only when it has valid SR-confluence for the buy side. In this cycle, S/R Flip is represented as a reclaimable support context: a bullish active FVG/OB zone must intersect a scored support band before it is allowed to feed the entry path.
5. The existing `1m` reclaim trigger remains the final confirmation layer.

This keeps the candidate architecture intact while making FVG, Order Block, and S/R Flip first-class parts of the live strategy path.

## Design Notes

- Reuse, do not revive: the reusable part of the old surface is the pure zone math in `core/strategy.py`, not the legacy top-level strategy wiring.
- Keep reasons and diagnostics machine-friendly: if zone confluence is missing, candidate should fail explicitly instead of silently degrading into the old reclaim-only path.
- Prefer diagnostics over hidden magic: selected zone type, zone bounds, zone counts, and SR-flip readiness should be visible in candidate diagnostics so the backtest/debug seam can explain why entries did or did not happen.

## Success Criteria

1. `candidate_v1` entry evaluation uses FVG / Order Block / S/R-confluence before accepting an entry.
2. A candidate setup with valid trend/reset/reclaim shape but no valid zone confluence is explicitly rejected.
3. The shared seam still enters `candidate_v1` through `evaluate_market(...)` without reviving `sr_ob_fvg` selection.
4. Existing backtest/runtime paths continue to use `candidate_v1` as the active strategy name.
5. The 6-symbol fee-aware candidate backtest runs successfully after the change.

## Verification Plan

- `testing/test_main_signals.py` remains the reference for legacy helper semantics
- `testing/test_candidate_strategy_v1.py` gains focused tests for candidate zone-confluence acceptance and rejection
- `testing/test_decision_core.py` verifies the shared seam still exposes the intended candidate diagnostics/reasons
- `python3 -m unittest testing.test_candidate_strategy_v1 testing.test_decision_core testing.test_strategy_registry`
- `python3 -m unittest testing.test_backtest_runner testing.test_config_loader testing.test_engine_order_acceptance testing.test_experiment_runner testing.test_parity_runner`
- Fee-aware 6-symbol candidate rerun on `KRW-BTC`, `KRW-ETH`, `KRW-XRP`, `KRW-SOL`, `KRW-ADA`, `KRW-ANKR`
