# ICT Multi-Model Runtime Redesign

## Goal

Replace the active runtime trading algorithm with a deterministic ICT-style strategy family that can identify and trade Turtle Soup, Unicorn, Silver Bullet, and OTE long setups while managing trades with TP1 partial profit, stop-to-breakeven after TP1, and a runner toward TP2.

## Why This Direction Is Correct For This Repo

The repo already has the stable execution seams we need:

- `core/decision_core.py` already separates pure signal evaluation from runtime execution.
- `core/position_policy.py` already manages partial exits, trailing, and breakeven state.
- `core/strategy.py` already provides reusable S/R, FVG, OB, zone, and 1m trigger helpers.
- `core/candle_buffer.py` preserves UTC candle times, so New York session windows are implementable without broker changes.
- `core/universe.py` already owns tradable-market ranking and can be upgraded without changing the engine loop.

Because of that, the safest redesign is not a broker/runtime rewrite. It is a strategy, policy, and universe redesign on top of the existing seams.

## Research Conclusions

### Turtle Soup

- Core behavior: liquidity sweep / false breakout of internal support or resistance, followed by reversal.
- Deterministic repo-friendly encoding: recent low/high sweep on `5m` or `15m`, close back inside range, then `1m` bullish MSS/reclaim confirmation.

### Unicorn

- Core behavior: breaker block overlapping a fair value gap after a structure shift.
- Deterministic repo-friendly encoding: bullish breaker candidate plus bullish FVG overlap, bullish structure shift, then retest into the overlap zone.

### Silver Bullet

- Core behavior: liquidity sweep + lower-timeframe MSS + PD-array entry inside strict New York-local one-hour windows.
- Deterministic repo-friendly encoding: only evaluate Silver Bullet entries inside configured NY-local windows; require sweep -> MSS -> PD-array tap in the active window.

### OTE

- Core behavior: trend continuation entry in the 62% to 79% retracement zone of a valid dealing range.
- Deterministic repo-friendly encoding: derive a recent `15m` dealing range from swings, compute the OTE pocket, require current price inside the pocket plus bullish lower-timeframe confirmation.

## Approved Direction

Add a new canonical strategy, `ict_v1`, and make it the active default strategy.

### Entry architecture

1. `15m` supplies dealing range, premium/discount, higher-timeframe liquidity pools, and directional context.
2. `5m` supplies sweep context, breaker/FVG/zone structures, and session-compatible setup zones.
3. `1m` supplies the final trigger and reclaim/MSS timing.
4. `ict_v1.evaluate_long_entry(...)` evaluates four deterministic models:
   - `turtle_soup`
   - `unicorn`
   - `silver_bullet`
   - `ote`
5. If multiple models are valid, the strategy picks the highest deterministic setup score and persists `setup_model` in diagnostics.

### Module boundaries

- `core/strategies/ict_v1.py`: strategy adapter that chooses the winning setup and emits the normalized signal.
- `core/strategies/ict_models.py`: pure setup predicates and scoring for Turtle Soup, Unicorn, Silver Bullet, and OTE.
- `core/strategies/ict_sessions.py`: explicit New York-local Silver Bullet window handling derived from UTC candles.
- `core/strategy.py`: reused as the shared primitive layer for SR/FVG/OB/trigger building blocks, not expanded into another large strategy body unless a tiny helper extraction is unavoidable.

### Exit architecture

- TP1 is strategy-managed and R-based.
- After TP1, stop moves to entry price through the existing breakeven state.
- TP2 is a full exit target derived from `take_profit_r`.
- The shared position policy remains the guardrail for stop handling and runner protection.
- No broker rewrite is required.

### Universe architecture

Keep the existing universe subsystem, but upgrade ranking for `ict_v1` so it prefers liquid, tradeable, moving markets rather than raw turnover only.

Planned ranking inputs:

- recent 10m trade value
- relative spread
- 1m ATR as a percent of price
- missing-candle quality

This is a narrow ranking upgrade, not a universe subsystem rewrite.

## Scope

### In Scope

- Add `ict_v1` strategy and register it in the runtime/backtest seam.
- Add the pure helpers required to detect liquidity sweeps, dealing ranges, OTE pockets, breaker/unicorn zones, and Silver Bullet session windows.
- Generalize TP1 -> breakeven -> TP2 handling so it works for the new strategy.
- Upgrade universe ranking for the active ICT strategy.
- Update runtime defaults, tests, and `docs/PROJECT_REFERENCE.md`.

### Out Of Scope

- Broker rewrites
- websocket/reconciliation redesign
- new data providers
- discretionary annotations or chart UI
- live deployment claims

## Success Criteria

1. `ict_v1` is selectable through config and becomes the default active strategy.
2. Pure helper tests cover the four setup families and their primary no-trade cases.
3. Strategy tests show deterministic acceptance/rejection with setup diagnostics.
4. TP1 partial exit arms breakeven and TP2 exits through automated tests.
5. Universe ranking still works but prefers liquid + volatile markets suitable for intraday ICT execution.
6. `paper` and `dry_run` boot successfully with `ict_v1` selected.
7. Backtest completes successfully with the new strategy.

## Verification Plan

- Unit tests for pure ICT helper modules and setup selection.
- Strategy seam tests for entry/exit behavior.
- Policy tests for TP1 partial, breakeven arming, and TP2 full exit.
- Universe tests for ranking/filter changes.
- Runtime/manual QA:
  - `python -m unittest discover -s testing`
  - `TRADING_MODE=paper python main.py`
  - `TRADING_MODE=dry_run python main.py`
  - `python -m testing.backtest_runner --market KRW-BTC --lookback-days 7`
