# Candidate Zone Confluence Redesign Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add FVG, Order Block, and S/R Flip-aware entry logic to `candidate_v1` without reviving the legacy `sr_ob_fvg` runtime path.

**Architecture:** Preserve the current `candidate_v1` regime/reset/reclaim structure and insert a bounded zone-confluence helper between the existing `5m` setup and `1m` trigger. Reuse pure SR/FVG/OB helper functions from `core/strategy.py`, but keep runtime/backtest strategy selection unchanged.

**Tech Stack:** Python, unittest, existing `candidate_v1`, shared decision seam, existing backtest runner

---

## Task 1: Add candidate zone-confluence setup logic

**Files:**
- Modify: `core/strategies/candidate_v1.py`
- Test: `testing/test_candidate_strategy_v1.py`

**QA:** `candidate_v1.evaluate_long_entry(...)` accepts only when trend/reset/reclaim shape also has valid bullish zone confluence; a reclaim-only setup without valid zone confluence fails explicitly.

- [ ] Write failing tests in `testing/test_candidate_strategy_v1.py` for:
  - acceptance when bullish FVG/OB + scored support context exists
  - rejection when existing reset/reclaim shape has no valid selected zone
  - diagnostics exposing selected zone metadata / SR-flip readiness
- [ ] Run: `python3 -m unittest testing.test_candidate_strategy_v1`
- [ ] Implement the minimum candidate helper logic in `core/strategies/candidate_v1.py` by reusing pure helpers from `core/strategy.py`
- [ ] Re-run: `python3 -m unittest testing.test_candidate_strategy_v1`

## Task 2: Verify the shared seam still reflects the active candidate path

**Files:**
- Modify: `testing/test_decision_core.py`
- Optional modify: `core/decision_core.py`

**QA:** `evaluate_market(...)` still routes through `candidate_v1`, and the shared seam preserves the intended candidate reason/diagnostic shape after the new zone-confluence gate is added.

- [ ] Write failing seam tests for the new candidate diagnostics / rejection reason if the current seam coverage does not already pin them.
- [ ] Run: `python3 -m unittest testing.test_decision_core`
- [ ] Make only the minimum seam changes needed to keep diagnostics and reasons stable.
- [ ] Re-run: `python3 -m unittest testing.test_decision_core testing.test_strategy_registry`

## Task 3: Update project docs for the new active strategy behavior

**Files:**
- Modify: `docs/PROJECT_REFERENCE.md`

**QA:** The project reference states that the active candidate path now includes FVG / Order Block / S/R Flip-aware zone confluence, and it lists the affected files and verification commands.

- [ ] Update `docs/PROJECT_REFERENCE.md` with the design summary, affected files, and verification commands.

## Task 4: Full verification and real backtest run

**Files:**
- Refresh: `testing/artifacts/backtest_7d_candidate_summary.json`
- Refresh as produced: `testing/artifacts/*candidate_7d_*.csv`

**QA:** Diagnostics are clean, the full candidate verification suite passes, and the actual 6-symbol fee-aware backtest executes with the new strategy logic.

- [ ] Run: `python3 -m unittest testing.test_candidate_strategy_v1 testing.test_decision_core testing.test_strategy_registry`
- [ ] Run: `python3 -m unittest testing.test_backtest_runner testing.test_config_loader testing.test_engine_order_acceptance testing.test_experiment_runner testing.test_parity_runner`
- [ ] Run changed-file diagnostics on modified Python files.
- [ ] Run the fee-aware 6-symbol candidate backtest loop and refresh `testing/artifacts/backtest_7d_candidate_summary.json`.
- [ ] Compare trade count, approximate win rate, combined return, and median return against the current candidate checkpoint before deciding whether to commit/push.
