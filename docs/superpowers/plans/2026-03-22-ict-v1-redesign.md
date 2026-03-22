# ICT v1 Broader Runtime Redesign Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the approved broader `ict_v1` redesign so setup selection remains deterministic while execution quality, zone-aware entry pricing, derived higher-timeframe bias, and intraday stale-trade exits become real runtime behavior.

**Architecture:** Keep the existing decision/runtime/backtest seams. Extend `ict_v1` and `ict_models` for two-stage gating, shared-trigger-backed execution checks, deterministic `zone_limit` pricing, and derived `1h` bias from `15m` candles; extend config/strategy params only where required; and tighten `core/position_policy.py` so `ict_v1` can time out stale trades without regressing candidate proof-window behavior.

**Tech Stack:** Python, unittest, existing `core/decision_core.py` seam, existing `core/position_policy.py`, existing `TradingConfig` / `StrategyParams` config surface

---

## Chunk 1: Config Surface and Parameter Plumbing

### Task 1: Add fail-first config coverage for the new `ict_v1` controls

**Files:**
- Modify/Test: `testing/test_config_loader.py`
- Modify/Test: `testing/test_strategy_registry.py` (only if canonical defaults or strategy-specific overrides need explicit assertions)

**QA:** Config loading exposes the new redesign controls, validates them, and keeps existing strategies working with their current entry modes.

- [ ] **Step 1: Write the failing config tests**

Add tests for:
- `TRADING_ENTRY_MODE=zone_limit` is accepted when loading config for `ict_v1`
- new stale-trade fields load from env/config and stay numeric
- new derived-`1h` regime fields load from env/config and stay numeric
- invalid values fail closed with clear validation errors

- [ ] **Step 2: Run the config tests to verify they fail**

Run: `python3 -m unittest testing.test_config_loader`
Expected: FAIL because the new config surface and validation do not exist yet.

- [ ] **Step 3: Add the minimal config surface**

Modify `config.py`, `core/config.py`, `core/config_loader.py`, and `core/strategy.py` so the repo exposes exactly the new redesign controls:
- `entry_mode="zone_limit"` support
- `trailing_activation_r`
- `stale_trade_max_bars`
- `stale_trade_min_progress_r`
- derived-`1h` regime parameters (`min_candles_1h`, `regime_1h_ema_fast`, `regime_1h_ema_slow`, `regime_1h_adx_period`, `regime_1h_adx_min`, and any single enable flag if needed)
- strategy-specific `ict_v1` defaults for non-zero intraday timeouts

- [ ] **Step 4: Run the config tests to verify they pass**

Run: `python3 -m unittest testing.test_config_loader`
Expected: PASS.

## Chunk 2: Two-Stage Entry Gating and Low-Quality Skip

### Task 2: Add fail-first strategy coverage for setup-pass / execution-fail behavior

**Files:**
- Modify/Test: `testing/test_ict_strategy_v1.py`
- Modify/Test: `testing/test_ict_models.py` (only if the new entry-window contract is easier to lock at the pure-helper level)

**QA:** `ict_v1` can now distinguish "setup is valid" from "trade is executable," and low-quality setups are skipped before they reach shared sizing.

- [ ] **Step 1: Write the failing strategy tests**

Add tests for:
- a setup that passes the model layer but fails the shared-style trigger count contract
- a setup that passes the model layer but is rejected by the low-quality gate
- diagnostics clearly separating setup selection from execution rejection

- [ ] **Step 2: Run the strategy tests to verify they fail**

Run: `python3 -m unittest testing.test_ict_strategy_v1`
Expected: FAIL because `ict_v1` still uses the bespoke bullish micro-breakout helper and does not hard-skip low quality.

- [ ] **Step 3: Extend pure setup outputs only as needed**

Modify `core/strategies/ict_models.py` so zone-capable setups expose a normalized entry-window payload suitable for both trigger evaluation and `zone_limit` pricing. Keep the model layer pure and deterministic.

- [ ] **Step 4: Implement the minimal two-stage gating flow**

Modify `core/strategies/ict_v1.py` so it:
- keeps deterministic setup selection exactly once
- derives a concrete trigger zone from the winning setup
- uses shared trigger semantics that actually enforce `required_trigger_count`
- computes the `ict_v1` quality bucket before returning an accepted signal
- rejects low-quality entries with an explicit quality-gate reason instead of relying on shared size reduction

- [ ] **Step 5: Re-run the strategy tests to verify they pass**

Run: `python3 -m unittest testing.test_ict_strategy_v1`
Expected: PASS.

## Chunk 3: Deterministic `zone_limit` Entry Pricing and Derived `1h` Bias

### Task 3: Add fail-first coverage for `zone_limit` pricing

**Files:**
- Modify/Test: `testing/test_ict_strategy_v1.py`

**QA:** `zone_limit` uses exactly one preferred limit price per supported setup family and rejects rather than chases when the latest trigger candle did not touch that price.

- [ ] **Step 1: Write the failing `zone_limit` tests**

Add tests for:
- Unicorn accepted in `zone_limit` mode when the latest trigger candle touched the overlap midpoint
- Silver Bullet accepted in `zone_limit` mode when the latest trigger candle touched the FVG midpoint
- OTE accepted in `zone_limit` mode when the latest trigger candle touched the pocket midpoint
- otherwise valid zone-capable setups rejected with a limit-entry reason when the midpoint was not touched
- Turtle Soup rejected in `zone_limit` mode because this redesign keeps it `close`-only

- [ ] **Step 2: Run the strategy tests to verify they fail**

Run: `python3 -m unittest testing.test_ict_strategy_v1`
Expected: FAIL because `ict_v1` does not yet resolve deterministic midpoint-based zone-limit entries.

- [ ] **Step 3: Implement the minimal `zone_limit` resolver**

Modify `core/strategies/ict_v1.py` so `entry_mode="zone_limit"`:
- picks the exact midpoint price defined in the approved spec
- checks fillability against the latest closed trigger candle high/low range
- emits the chosen preferred limit price and explicit rejection reasons in diagnostics

- [ ] **Step 4: Re-run the strategy tests to verify they pass**

Run: `python3 -m unittest testing.test_ict_strategy_v1`
Expected: PASS.

### Task 4: Add fail-first coverage for derived-`1h` regime confirmation

**Files:**
- Modify/Test: `testing/test_ict_strategy_v1.py`

**QA:** `ict_v1` requires both `15m` execution regime alignment and derived `1h` bias alignment, and fails closed when there is not enough `15m` history to derive the required `1h` window.

- [ ] **Step 1: Write the failing `1h` regime tests**

Add tests for:
- accepted entry when both `15m` and derived `1h` pass
- rejection when `15m` passes but derived `1h` fails
- rejection when there are not enough `15m` candles to derive the required `1h` series

- [ ] **Step 2: Run the strategy tests to verify they fail**

Run: `python3 -m unittest testing.test_ict_strategy_v1`
Expected: FAIL because `ict_v1` currently has no derived `1h` regime path.

- [ ] **Step 3: Implement the derived-`1h` bias layer**

Modify `core/strategies/ict_v1.py` to aggregate closed `15m` candles in groups of four, derive a synthetic `1h` candle stream, and apply the new `1h` regime parameters without changing broker/data-provider scope.

- [ ] **Step 4: Re-run the strategy tests to verify they pass**

Run: `python3 -m unittest testing.test_ict_strategy_v1`
Expected: PASS.

## Chunk 4: Intraday Exit Tightening and Shared Policy Wiring

### Task 5: Add fail-first policy/seam coverage for stale-trade exits

**Files:**
- Modify/Test: `testing/test_risk_and_policy.py`
- Modify/Test: `testing/test_decision_core.py`

**QA:** `ict_v1` exits stale, low-progress trades through a deterministic time-based rule, while hard stops still take precedence and candidate proof-window behavior does not regress.

- [ ] **Step 1: Write the failing exit-policy tests**

Add tests for:
- stale-trade full exit when `bars_held >= stale_trade_max_bars`, `highest_r < stale_trade_min_progress_r`, and protection is not secured
- no stale-trade exit once protection is secured
- hard-stop precedence over stale-trade exit when price is already through the stop
- `max_hold_bars` still acting as the final absolute timeout
- candidate proof-window positions not accidentally inheriting the new non-candidate stale-trade branch

- [ ] **Step 2: Run the policy/seam tests to verify they fail**

Run: `python3 -m unittest testing.test_risk_and_policy testing.test_decision_core`
Expected: FAIL because the stale-trade rule and new parameter plumbing do not exist yet.

- [ ] **Step 3: Implement the minimal shared-exit changes**

Modify `core/position_policy.py` so the non-candidate `ict_v1` path:
- uses the configured `trailing_activation_r`
- checks the stale-trade rule after hard-stop / partial-stop handling but before trailing and strategy-signal exits
- emits a distinct time-based exit reason and diagnostics

- [ ] **Step 4: Wire the new order-policy parameters everywhere they are constructed**

Modify:
- `core/engine.py`
- `testing/backtest_runner.py`
- `testing/parity_runner.py`
- `testing/test_decision_core.py`

Pass `trailing_activation_r`, `stale_trade_max_bars`, and `stale_trade_min_progress_r` into `PositionOrderPolicy` so runtime, backtest, parity, and seam tests stay aligned.

- [ ] **Step 5: Re-run the policy/seam tests to verify they pass**

Run: `python3 -m unittest testing.test_risk_and_policy testing.test_decision_core`
Expected: PASS.

## Chunk 5: Docs and Full Verification

### Task 6: Update docs and run end-to-end verification

**Files:**
- Modify: `docs/PROJECT_REFERENCE.md`
- Verify only: all files changed in prior chunks

**QA:** The docs match the implemented redesign, targeted tests pass, safe-mode boots succeed, and workbook-backed backtest output reflects the new behavior without breaking the shared seams.

- [ ] **Step 1: Update the project reference document**

Document the broader `ict_v1` redesign in `docs/PROJECT_REFERENCE.md`, including the new two-stage gating, `zone_limit`, derived `1h` bias, stale-trade exit, affected files, and verification commands.

- [ ] **Step 2: Run the focused redesign regression suite**

Run: `python3 -m unittest testing.test_ict_strategy_v1 testing.test_risk_and_policy testing.test_decision_core testing.test_config_loader`
Expected: PASS.

- [ ] **Step 3: Run broader shared-seam regression coverage**

Run: `python3 -m unittest testing.test_strategy_registry testing.test_engine_order_acceptance testing.test_backtest_runner testing.test_parity_runner`
Expected: PASS. Any failure in this targeted regression set is a blocker for completing the redesign and must be investigated before sign-off.

- [ ] **Step 4: Run changed-file diagnostics**

Run `lsp_diagnostics` on every modified Python file.
Expected: zero errors on each changed file before sign-off.

- [ ] **Step 5: Run manual QA in safe runtime modes**

Run:
- `TRADING_MODE=paper timeout 20s python3 main.py`
- `TRADING_MODE=dry_run timeout 20s python3 main.py`

Expected: boot succeeds without strategy/config errors, and `ict_v1` remains selectable under the new config surface.

- [ ] **Step 6: Run a workbook-backed backtest smoke check**

Run: `python3 -m testing.backtest_runner --market KRW-BTC --path testing/artifacts/backdata_krw_btc_7d.xlsx --lookback-days 7`
Expected: completes successfully and produces diagnostics/artifacts without crashing on the redesigned `ict_v1` path.

## Atomic Commit Strategy

1. `test: add failing ict_v1 redesign config coverage`
2. `feat: add ict_v1 redesign config surface`
3. `test: cover two-stage ict_v1 gating and low-quality skips`
4. `feat: enforce ict_v1 trigger-count gate and quality veto`
5. `test: cover ict_v1 zone-limit pricing and derived 1h bias`
6. `feat: add deterministic zone-limit pricing and derived 1h regime`
7. `test: cover ict_v1 stale-trade exits through shared seam`
8. `feat: tighten ict_v1 intraday exit timing and policy wiring`
9. `docs: update project reference for broader ict_v1 redesign`
