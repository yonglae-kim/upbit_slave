# Weak-Symbol Probation Lane Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a candidate-only probation lane for weak symbols so trade count remains high while win rate and combined profitability improve.

**Architecture:** Keep the current candidate signal engine, proof-window lifecycle, delayed-trailing exit policy, and artifact/gate workflow intact. Restrict this cycle to stricter entry admission for weak symbols only.

**Tech Stack:** Python, unittest, existing shared candidate seam, existing 5-symbol 7-day backtest workflow

---

## File Map

### Modify
- `core/candidate_strategy_defaults.py`
- `core/strategies/candidate_v1.py`
- `testing/test_candidate_strategy_v1.py`
- `testing/test_decision_core.py`
- `docs/PROJECT_REFERENCE.md`

## Task 1: Add the probation-lane contract

**Files:**
- Modify: `core/candidate_strategy_defaults.py`
- Modify: `core/strategies/candidate_v1.py`
- Test: `testing/test_candidate_strategy_v1.py`
- Test: `testing/test_decision_core.py`

- [ ] **Step 1: Write failing tests**

Add tests that prove weak symbols require a stricter high-conviction lane than normal symbols, while normal symbols still use the current candidate entry path.

- [ ] **Step 2: Run the failing tests**

Run: `python3 -m unittest testing.test_candidate_strategy_v1 testing.test_decision_core`
Expected: FAIL on the new probation-lane expectations.

- [ ] **Step 3: Implement the minimum candidate-only probation logic**

Add symbol-conditioned stricter entry admission for weak symbols only. Do not touch exit logic in this cycle.

- [ ] **Step 4: Re-run the tests**

Run: `python3 -m unittest testing.test_candidate_strategy_v1 testing.test_decision_core testing.test_strategy_registry`
Expected: PASS

## Task 2: Re-run the 5-symbol backtest comparison

**Files:**
- Modify: `docs/PROJECT_REFERENCE.md`

- [ ] **Step 1: Run the candidate test suite**

Run: `python3 -m unittest testing.test_candidate_strategy_v1 testing.test_decision_core testing.test_strategy_registry`
Expected: PASS

- [ ] **Step 2: Run the 5-symbol 7-day candidate backtests**

Run the same `TRADING_MODE=dry_run TRADING_STRATEGY_NAME=candidate_v1 python3 -m testing.backtest_runner ...` loop used in the previous cycle for BTC/ETH/XRP/SOL/ADA.

- [ ] **Step 3: Write and compare summary artifacts**

Update `testing/artifacts/backtest_7d_candidate_summary.json` and compare:

- trade count vs current candidate `35`
- approximate win rate vs current candidate `8.57%`
- combined return vs current candidate `+0.4016`
- median return vs current candidate `+0.0644`
- per-symbol returns, especially XRP and ADA

## Task 3: Final verification

- [ ] **Step 1: Re-run artifact/gate tests**

Run: `python3 -m unittest testing.test_experiment_runner testing.test_parity_runner testing.test_config_loader testing.test_engine_order_acceptance`
Expected: PASS

- [ ] **Step 2: Run manual artifact commands**

Run:

```bash
python3 -m testing.experiment_runner --market KRW-BTC --lookback-days 90 --strategy baseline --candidate candidate_v1 --output testing/artifacts/candidate_v1_decision.json
python3 -m testing.parity_runner --strategy candidate_v1 --output testing/artifacts/candidate_v1_parity.json
```

Expected: PASS

- [ ] **Step 3: Run changed-file diagnostics**

Run `lsp_diagnostics` on modified Python files.
Expected: zero errors.
