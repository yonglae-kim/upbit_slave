# ICT Multi-Model Runtime Redesign Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the active runtime strategy with a deterministic `ict_v1` strategy that trades Turtle Soup, Unicorn, Silver Bullet, and OTE long setups with TP1 partial profit, breakeven stop promotion, and a TP2 runner.

**Architecture:** Keep the stable engine / broker / decision / backtest seams. Reuse `core/strategy.py` as the shared primitive library, add `core/strategies/ict_models.py` and `core/strategies/ict_sessions.py` for new deterministic ICT predicates, add `core/strategies/ict_v1.py` as the runtime strategy adapter, generalize staged exit handling in `core/position_policy.py`, and narrow the universe redesign to a better ranking model in `core/universe.py`.

**Tech Stack:** Python, unittest, existing decision seam, existing runtime/backtest adapters, New York-local session windows derived from UTC candle timestamps

---

## Task 1: Add failing pure-helper tests for ICT setup primitives

**Files:**
- Add/Test: `testing/test_ict_models.py`

**QA:** The pure helper layer can deterministically detect liquidity sweeps, dealing ranges, OTE pockets, breaker/FVG overlap, and Silver Bullet time windows, and it rejects malformed/no-trade cases.

- [ ] Add failing tests for bullish Turtle Soup sweep/reclaim detection and false positives.
- [ ] Add failing tests for bullish Unicorn overlap detection and invalid overlap cases.
- [ ] Add failing tests for OTE pocket detection from a valid dealing range and out-of-range rejection.
- [ ] Add failing tests for Silver Bullet New York-local window gating using UTC candle timestamps.
- [ ] Run: `python -m unittest testing.test_ict_models`

## Task 2: Implement the minimum pure ICT helper layer

**Files:**
- Add: `core/strategies/ict_models.py`
- Add: `core/strategies/ict_sessions.py`
- Modify: `core/strategy.py` (only if a tiny reusable primitive extraction is actually required)

**QA:** The new pure ICT helper modules compose the existing `core/strategy.py` primitives without entangling runtime state, and all new pure-helper tests pass.

- [ ] Implement helpers for timestamp parsing and New York-local session-window checks.
- [ ] Implement helpers for dealing-range selection, premium/discount, and OTE pocket calculation.
- [ ] Implement helpers for liquidity-pool detection and sweep/reclaim validation.
- [ ] Implement helpers for breaker block identification and unicorn overlap construction using the existing FVG/OB machinery where possible.
- [ ] Re-run: `python -m unittest testing.test_ict_models`

## Task 3: Add the new `ict_v1` strategy and wire it into config/registry

**Files:**
- Add: `core/strategies/ict_v1.py`
- Modify: `core/strategies/__init__.py`
- Modify: `core/strategy_registry.py`
- Modify: `core/config.py`
- Modify: `core/config_loader.py`
- Modify: `config.py`
- Test: `testing/test_strategy_registry.py`
- Test: `testing/test_config_loader.py`
- Add/Test: `testing/test_ict_strategy_v1.py`

**QA:** `ict_v1` is a selectable canonical strategy, becomes the default active strategy, and deterministically chooses the best valid setup among Turtle Soup, Unicorn, Silver Bullet, and OTE.

- [ ] Add failing registry/config tests for `ict_v1` selection and default wiring.
- [ ] Add failing strategy tests for accepted and rejected entries across the four setup families.
- [ ] Implement `core/strategies/ict_v1.py` with deterministic model scoring and diagnostics (`setup_model`, `entry_price`, `stop_price`, `r_value`, `tp1_r`, `tp2_r`) backed by `core/strategies/ict_models.py`.
- [ ] Wire `ict_v1` into strategy registration and config defaults.
- [ ] Re-run: `python -m unittest testing.test_strategy_registry testing.test_config_loader testing.test_ict_strategy_v1`

## Task 4: Generalize staged exit handling for TP1 -> breakeven -> TP2

**Files:**
- Modify: `core/position_policy.py`
- Modify: `core/decision_core.py` (only if state/diagnostic propagation needs a seam adjustment)
- Test: `testing/test_risk_and_policy.py`
- Test: `testing/test_decision_core.py`

**QA:** The new strategy can take a partial profit at TP1, arm breakeven immediately after that partial, and fully exit at TP2 without relying on `rsi_bb_reversal_long`-specific gating.

- [ ] Add failing tests showing `ict_v1` partial take-profit triggers at the configured R multiple.
- [ ] Add failing tests showing stop moves to entry after the partial.
- [ ] Add failing tests showing full exit at TP2 through the shared seam.
- [ ] Replace the hard-coded `rsi_bb_reversal_long` strategy-partial gate with generic behavior suitable for `ict_v1` while preserving existing coverage.
- [ ] Re-run: `python -m unittest testing.test_risk_and_policy testing.test_decision_core`

## Task 5: Upgrade universe ranking for intraday ICT conditions

**Files:**
- Modify: `core/universe.py`
- Modify: `core/engine.py` (only if the ranking path needs an explicit strategy-aware hook)
- Test: `testing/test_universe.py`
- Test: `testing/test_engine_universe_refresh.py`

**QA:** Universe selection still honors liquidity/spread/missing-data filters but now prefers markets with enough intraday movement to support ICT setups.

- [ ] Add failing tests for ICT-aware ranking using recent trade value plus volatility/spread quality.
- [ ] Implement the minimum ranking upgrade in `core/universe.py` without rewriting the engine loop.
- [ ] Re-run: `python -m unittest testing.test_universe testing.test_engine_universe_refresh`

## Task 6: Update docs and run full verification

**Files:**
- Modify: `docs/PROJECT_REFERENCE.md`

**QA:** Docs reflect the new active strategy and verification commands, targeted tests pass, full test discovery passes, runtime boots in safe modes, and the backtest completes successfully.

- [ ] Update `docs/PROJECT_REFERENCE.md` with the redesign summary, affected files, and verification commands.
- [ ] Run: `python -m unittest discover -s testing`
- [ ] Run changed-file diagnostics on all modified Python files.
- [ ] Run: `TRADING_MODE=paper python main.py`
- [ ] Run: `TRADING_MODE=dry_run python main.py`
- [ ] Run: `python -m testing.backtest_runner --market KRW-BTC --lookback-days 7`
- [ ] Record any pre-existing diagnostics/test issues separately from changes introduced in this cycle.

## Atomic Commit Strategy

1. `test: add failing ICT model predicate coverage`
2. `feat: add pure ict model and session helpers`
3. `feat: add ict_v1 strategy and config wiring`
4. `test: cover staged TP1 breakeven and TP2 exits`
5. `feat: generalize strategy partial-exit handling`
6. `feat: upgrade ict-aware universe ranking`
7. `docs: update project reference for ict_v1 runtime`
