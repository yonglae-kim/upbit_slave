# OB/FVG/SR Flip Runtime Redesign Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the weak current `candidate_v1` OB/FVG/SR attempt with a real OB/FVG/SR-Flip strategy that can improve win rate and return in the active runtime/backtest path.

**Architecture:** Keep the stable registry/decision/backtest seams, but replace `candidate_v1` internals with an adapter over the mature `core.strategy` OB/FVG/SR engine. Extend that engine with explicit S/R Flip evaluation and wire candidate exits to the strategy-side sell signal so the shared position policy can realize profits through `strategy_signal`.

**Tech Stack:** Python, unittest, shared decision seam, `core.strategy` helper engine, candidate adapter, fee-aware backtest runner

---

## Task 1: Add explicit S/R Flip evaluation to the mature OB/FVG/SR engine

**Files:**
- Modify: `core/strategy.py`
- Test: `testing/test_main_signals.py`

**QA:** The pure helper layer can detect a valid bullish S/R Flip as break -> retest -> hold, and existing zone/trigger semantics remain intact.

- [ ] Write failing tests in `testing/test_main_signals.py` for bullish S/R Flip pass/fail cases.
- [ ] Run: `python3 -m unittest testing.test_main_signals.MainSignalValidationTest.test_<new_flip_tests>`
- [ ] Implement the minimum S/R Flip helper(s) and diagnostics in `core/strategy.py`.
- [ ] Re-run the targeted S/R Flip tests.

## Task 2: Replace candidate entry with an adapter over the mature OB/FVG/SR engine

**Files:**
- Modify: `core/strategies/candidate_v1.py`
- Test: `testing/test_candidate_strategy_v1.py`

**QA:** `candidate_v1.evaluate_long_entry(...)` no longer depends on the current pullback/reclaim internals and instead reflects OB/FVG/SR-Flip diagnostics from the shared helper engine.

- [ ] Write failing candidate tests for accepted entry, rejected no-flip/no-zone entry, and expected diagnostics.
- [ ] Run: `python3 -m unittest testing.test_candidate_strategy_v1`
- [ ] Implement the candidate adapter rewrite in `core/strategies/candidate_v1.py`.
- [ ] Re-run: `python3 -m unittest testing.test_candidate_strategy_v1`

## Task 3: Enable strategy-side candidate exits

**Files:**
- Modify: `core/strategies/candidate_v1.py`
- Test: `testing/test_decision_core.py`
- Test: `testing/test_parity_runner.py`
- Test: `testing/test_experiment_runner.py`

**QA:** Candidate exits can emit `strategy_signal` through the live seam, and parity/experiment fixtures remain stable under the rewritten candidate strategy.

- [ ] Write failing seam/harness tests for candidate exit identity and any updated fixture expectations.
- [ ] Run: `python3 -m unittest testing.test_decision_core testing.test_parity_runner testing.test_experiment_runner`
- [ ] Implement the minimum sell-side adapter behavior.
- [ ] Re-run: `python3 -m unittest testing.test_decision_core testing.test_parity_runner testing.test_experiment_runner testing.test_strategy_registry`

## Task 4: Update docs and run full verification

**Files:**
- Modify: `docs/PROJECT_REFERENCE.md`
- Refresh as produced: `testing/artifacts/backtest_7d_candidate_summary.json`
- Refresh as produced: `testing/artifacts/*candidate_7d_*.csv`

**QA:** Docs describe the rewritten active strategy, all affected suites pass, diagnostics are clean, and the actual 6-symbol fee-aware backtest shows whether the redesign beat the current dirty checkpoint.

- [ ] Update `docs/PROJECT_REFERENCE.md` with the redesign summary, affected files, and verification commands.
- [ ] Run: `python3 -m unittest testing.test_main_signals testing.test_candidate_strategy_v1 testing.test_decision_core testing.test_strategy_registry`
- [ ] Run: `python3 -m unittest testing.test_backtest_runner testing.test_config_loader testing.test_engine_order_acceptance testing.test_experiment_runner testing.test_parity_runner`
- [ ] Run changed-file diagnostics on modified Python files.
- [ ] Run the fee-aware 6-symbol candidate backtest loop and refresh summary artifacts.
- [ ] Compare metrics against the current dirty checkpoint `trade_count=27`, `approx_win_rate_pct=22.22`, `combined_return_pct=+0.3076`, `median_return_pct=+0.0322` before deciding whether to commit/push.
