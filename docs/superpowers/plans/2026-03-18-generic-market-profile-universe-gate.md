# Generic Market-Profile Universe Gate Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a generic market-profile gate that improves broader KRW backtest quality without using coin-name-specific logic.

**Architecture:** Keep the current candidate signal engine, proof-window lifecycle, delayed-trailing exit policy, and artifact/gate workflow intact. Add a generic market-profile admission layer and, if needed, align runtime universe selection with the same inputs.

**Tech Stack:** Python, unittest, existing `UniverseBuilder`, existing `candidate_v1`, existing backtest loop

---

## Task 1: Add a generic market-profile admission contract

**Files:**
- Modify: `core/decision_core.py`
- Modify: `testing/test_decision_core.py`
- Optional: `core/strategies/candidate_v1.py`

- [ ] Write failing tests proving poor market profile blocks entry for candidate_v1 without using coin names.
- [ ] Run: `python3 -m unittest testing.test_decision_core`
- [ ] Implement the minimum generic market-profile admission logic.
- [ ] Re-run: `python3 -m unittest testing.test_decision_core testing.test_candidate_strategy_v1 testing.test_strategy_registry`

## Task 2: Align runtime universe selection if needed

**Files:**
- Modify: `core/universe.py`
- Modify: `core/engine.py`
- Optional tests: universe/runtime tests

- [ ] If the same generic market-profile inputs can improve production watchlist quality, add them to universe selection without using coin-name-specific rules.
- [ ] Run the affected test suite after changes.

## Task 3: Re-run broader fee-aware KRW backtests including ANKR

- [ ] Run the broad KRW fee-aware backtest loop including `KRW-ANKR`.
- [ ] Update `testing/artifacts/backtest_7d_candidate_summary.json`.
- [ ] Compare trade count, approximate win rate, combined return, median return, and per-symbol returns against the most recent 6-symbol negative result.

## Task 4: Final verification

- [ ] Run: `python3 -m unittest testing.test_experiment_runner testing.test_parity_runner testing.test_config_loader testing.test_engine_order_acceptance`
- [ ] Run the artifact commands for `candidate_v1`.
- [ ] Run changed-file diagnostics on modified Python files.
