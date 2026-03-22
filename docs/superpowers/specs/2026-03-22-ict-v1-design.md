# ICT v1 Broader Runtime Redesign

## Goal

Redesign `ict_v1` so the runtime behavior matches the recent trade-log review more closely: setup validity stays distinct from execution quality, low-quality trades are suppressed more aggressively, close-chasing is reduced with zone-aware entry pricing, trailing and time exits behave like an intraday system instead of a passive holder, and regime filtering is stabilized on a higher timeframe.

## Why This Direction Is Correct For This Repo

The repo already has the seams needed for a bounded redesign instead of a strategy-engine rewrite:

- `core/strategies/ict_v1.py` already owns setup selection and entry diagnostics.
- `core/strategies/ict_models.py` already emits deterministic setup-specific price zones and scores.
- `core/decision_core.py` already separates entry acceptance from sizing and state propagation.
- `core/position_policy.py` already owns stop, trailing, partial, breakeven, and `time_stop` behavior.
- `core/config.py` and `core/config_loader.py` already expose most of the tuning surface needed for gating, entry mode, and exit timing.

Because of that, the redesign should stay inside strategy/config/policy seams and avoid broker, reconciliation, or portfolio rewrites.

## Current Validated Baseline

These parts already exist in the current codebase and must not be re-implemented as if they were missing:

- `ict_v1` already records non-zero `entry_score` and normalized `quality_score`, and rejects `score_below_threshold` when the chosen setup score is below `entry_score_threshold`.
- `ict_v1` already keeps setup selection deterministic by choosing the highest-score passing model among Turtle Soup, Unicorn, Silver Bullet, and OTE.
- shared sizing already converts `quality_score` into `quality_bucket` and quality multipliers.
- shared exit policy already has fee-aware breakeven protection and an MFE-based trailing activation floor.
- shared exit policy already supports `max_hold_bars -> time_stop`, but `ict_v1` currently leaves that path effectively disabled because the default remains `0`.

The redesign must build on those facts instead of duplicating them.

## Current Gaps Confirmed In Code

1. `required_trigger_count` is normalized for `ict_v1`, but the current entry path does not actually use the shared trigger-count contract; it only checks a bespoke bullish micro-breakout helper.
2. low quality currently reduces size through the shared sizing seam, but does not veto the trade.
3. `entry_mode` exists globally, but `ict_v1` does not currently use it, so there is no limit-style entry behavior for ICT zones.
4. `max_hold_bars` exists globally, but `ict_v1` does not currently ship with an intraday default that reflects the review.
5. regime stabilization remains entirely `15m`-driven; there is no `1h` confirmation path in production code today.

## Approved Direction

The approved scope is the broader redesign, but it still needs to stay surgical and deterministic. The redesign should preserve the current setup family and shared trading seams while changing how `ict_v1` decides that a valid setup is good enough to execute.

### 1. Entry Gating Redesign

Split entry acceptance into two explicit stages:

1. **Setup stage**
   - A trade is eligible only if one ICT setup passes and the higher-timeframe regime filter passes.
   - This stage picks the winning setup exactly once and persists the same deterministic diagnostics as today.

2. **Execution-quality stage**
   - After setup selection, `ict_v1` must evaluate execution quality separately from setup existence.
   - The execution-quality decision uses:
     - actual lower-timeframe trigger evidence wired to `required_trigger_count`
     - setup-derived `quality_score`
     - any setup-specific chase guard already emitted by the pure model layer
   - `quality_bucket=low` becomes a hard skip for `ict_v1`; it is no longer merely a smaller order.
   - `mid` and `high` quality remain tradable and continue to flow into the shared sizing seam.

This preserves the current strategy philosophy while making the runtime "setup found" and "trade allowed" decisions observably distinct.

### 2. Trigger Contract Redesign

`ict_v1` should stop using a strategy-local breakout-only helper as its sole execution check. Instead, it should consume the same shared lower-timeframe trigger semantics used elsewhere in the repo, so `required_trigger_count` becomes a real contract instead of a normalized-but-unused parameter.

Design rules:

- each accepted ICT setup must expose or derive a concrete trigger zone for the shared trigger evaluator
- `required_trigger_count` must be enforced by code, not only surfaced in config
- a setup may remain valid at the model layer while still being rejected at the execution-quality stage because the trigger contract is not met
- rejection diagnostics must make that distinction explicit

This is the smallest way to make the review's "setup pass vs execution gate" recommendation real without replacing the entire model family.

### 3. Entry Pricing Redesign

Add an explicit zone-aware limit-entry mode for `ict_v1` instead of treating all accepted setups as close-chasing entries.

Approved behavior:

- `entry_mode="close"` remains supported and preserves the current behavior.
- add a new `ict_v1`-specific mode, `entry_mode="zone_limit"`.
- in `zone_limit` mode, the selected setup must expose a deterministic entry window and a single deterministic preferred entry price.
- the preferred entry price is fixed by setup family in this redesign:
  - Unicorn: overlap midpoint
  - Silver Bullet: bullish FVG midpoint
  - OTE: OTE pocket midpoint
  - Turtle Soup: unsupported in `zone_limit`; Turtle Soup remains `close`-only in this redesign
- a `zone_limit` entry is considered fillable only if the latest closed trigger candle's low/high range contains the preferred limit price.
- if the setup is otherwise valid but that price was not touched by the latest trigger candle, the strategy must reject with an explicit limit-entry reason rather than silently chase at close.

This keeps the feature narrow: deterministic zone-aware pricing, not a new order management subsystem.

### 4. Exit Management Redesign

Preserve the recently added fee-aware breakeven logic, but make the broader intraday exit policy explicit.

Approved behavior:

- keep the current fee-aware breakeven floor and trailing floor clamp as the invariant floor once protection is secured
- keep MFE-based trailing activation; do not allow trailing activation before the configured `trailing_activation_r`
- for `ict_v1`, make ATR-based trailing the intended trailing style rather than a latent generic option
- add an `ict_v1`-appropriate non-zero `max_hold_bars` default so the existing `time_stop` seam becomes an absolute timeout
- add one additional intraday stale-trade rule inside the shared exit seam for `ict_v1`/non-candidate paths:
  - new parameters: `stale_trade_max_bars` and `stale_trade_min_progress_r`
  - rule condition: if `bars_held >= stale_trade_max_bars` and `highest_r < stale_trade_min_progress_r` and protective room is still not secured, exit full with a distinct time-based reason
  - unit of progress is `highest_r` in R-multiples, not raw price or ATR
  - precedence: existing hard-stop / partial-stop logic stays first, then stale-trade time exit, then trailing, then strategy-signal exit
- `max_hold_bars` remains the final absolute timeout even if the stale-trade rule did not trigger earlier

The goal is not to invent a new discretionary exit engine. The goal is to tighten the existing policy so short-horizon positions that never prove themselves do not linger and then die as low-quality trailing or stop exits.

### 5. Regime Stabilization Redesign

Add a higher-timeframe bias layer so the current `15m` regime pass is no longer the only directional context.

Approved behavior:

- retain `15m` as the execution regime used for detailed context and diagnostics
- add `1h` as a coarser bias filter for `ict_v1`
- derive `1h` candles inside the strategy layer by aggregating closed `15m` candles in groups of four; do not expand broker/data-provider scope for this redesign
- setup acceptance now requires both:
  - `15m` execution regime pass
  - `1h` higher-timeframe bias agreement
- if there are not enough closed `15m` candles to derive the required `1h` window, the strategy should fail closed for `ict_v1` rather than silently bypass the higher-timeframe bias once this redesign is enabled

This is intentionally a stability filter, not a new multi-timeframe scoring framework.

## Module Boundaries

- `core/strategies/ict_models.py`
  - extend pure setup outputs so zone-capable models expose a normalized entry window contract usable by both trigger evaluation and `zone_limit` pricing
  - keep the models pure and deterministic

- `core/strategies/ict_v1.py`
  - replace the bespoke breakout-only execution check with a true two-stage flow
  - keep model selection and score ordering deterministic
  - add `zone_limit` entry resolution
  - add derived-`1h` regime confirmation from existing `15m` candles

- `core/decision_core.py`
  - keep shared sizing logic intact
  - ensure `ict_v1` rejection/acceptance diagnostics preserve the distinction between setup pass, quality gate fail, trigger-count fail, and limit-entry infeasibility

- `core/position_policy.py`
  - preserve fee-aware breakeven and trailing invariants
  - add the stale-trade time-based exit rule in the shared seam, bounded so it does not affect candidate proof-window semantics

- `core/config.py` and `core/config_loader.py`
  - add the new parameters required for `zone_limit`, stale-trade timing, and derived-`1h` regime confirmation
  - give `ict_v1` explicit strategy defaults instead of relying on generic zeros

- `testing/*`
  - strategy tests must cover two-stage gating and `zone_limit`
  - policy/seam tests must cover stale-trade exits and preserved fee-aware floors
  - config tests must cover new options and validation

## Scope

### In Scope

- enforce `required_trigger_count` for `ict_v1` through a shared-style trigger contract
- make low-quality `ict_v1` entries skip instead of merely shrinking size
- add `zone_limit` entry mode for zone-capable ICT setups
- activate explicit intraday `max_hold_bars` behavior for `ict_v1`
- add a stale-trade time exit for no-progress intraday positions
- stabilize regime filtering with `1h` confirmation
- update tests, docs, and config validation around those changes

### Out Of Scope

- short-side ICT trading
- broker/order-router rewrites
- new market data providers beyond the repo's candle pipeline
- discretionary chart logic or manual annotations
- changing candidate proof-window behavior except where the shared seam must explicitly avoid regressing it
- replacing the current setup family or scoring hierarchy

## Success Criteria

1. `ict_v1` can reject a trade after setup selection because the execution-quality gate failed, and diagnostics clearly show why.
2. `required_trigger_count` affects live strategy acceptance for `ict_v1` through executable tests.
3. `quality_bucket=low` results in a skipped `ict_v1` trade instead of a reduced-size trade.
4. `entry_mode="zone_limit"` uses one deterministic preferred price per supported setup family and rejects rather than chases when that price was not touched by the latest trigger candle.
5. `ict_v1` exits stale, low-progress trades through deterministic time-based behavior defined by `stale_trade_max_bars` and `stale_trade_min_progress_r` instead of only through passive trailing/stop logic.
6. fee-aware breakeven and trailing floor invariants remain intact after the broader redesign.
7. `ict_v1` requires both `15m` and `1h` regime alignment once the redesign is active.

## Verification Plan

- Strategy tests:
  - two-stage setup-pass / execution-fail coverage
  - `required_trigger_count` acceptance and rejection coverage
  - `zone_limit` acceptance/rejection coverage per supported setup family
  - `1h` regime alignment acceptance/rejection coverage
- Policy tests:
  - stale-trade time exit coverage
  - preserved fee-aware breakeven floor coverage
  - preserved trailing activation floor coverage
  - non-regression coverage for candidate proof-window semantics
- Shared seam tests:
  - `evaluate_market(...)` propagates the new diagnostics and exit reasons correctly
- Runtime/manual QA after implementation:
  - `python3 -m unittest testing.test_ict_strategy_v1 testing.test_risk_and_policy testing.test_decision_core testing.test_config_loader`
  - `TRADING_MODE=paper timeout 20s python3 main.py`
  - `TRADING_MODE=dry_run timeout 20s python3 main.py`
  - `python3 -m testing.backtest_runner --market KRW-BTC --path testing/artifacts/backdata_krw_btc_7d.xlsx --lookback-days 7`
