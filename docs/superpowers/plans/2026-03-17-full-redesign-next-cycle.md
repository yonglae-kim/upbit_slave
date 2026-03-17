# Full Redesign Next Cycle Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the current `candidate_v1` path with a redesigned short-horizon strategy subsystem that preserves improved trade participation while materially improving expectancy on the 5-symbol 7-day 3-minute backtest set.

**Architecture:** Keep the shared decision seam, backtest runner, experiment/parity artifacts, and runtime promotion gate intact. Redesign only the strategy subsystem into three layers: a compact short-horizon regime map, a unified multi-timeframe signal engine that emits entry plus invalidation plus hold intent in one pass, and a delayed-trailing exit controller expressed through the existing shared `PositionOrderPolicy` boundary.

**Tech Stack:** Python, dataclasses, unittest, existing shared seam (`core/decision_core.py`), existing backtest runner/artifact workflow

---

## File Map

### Modify

- `core/strategies/candidate_v1.py` — replace the current candidate logic with the redesigned regime map and unified multi-timeframe signal engine.
- `core/decision_core.py` — minimal seam adjustment only if required to carry the redesigned signal/invalidation/hold intent cleanly.
- `core/position_policy.py` — adjust delayed-trailing semantics needed by the redesigned exit controller while staying within the shared policy boundary.
- `core/config.py` — candidate-specific strategy-facing defaults for the new regime/signal/exit model.
- `testing/test_candidate_strategy_v1.py` — TDD coverage for the redesigned strategy subsystem.
- `testing/test_decision_core.py` — seam contract tests for the redesigned candidate behavior.
- `testing/test_backtest_runner.py` — only if runner/reporting contracts need minimal adjustments for the redesign.
- `docs/PROJECT_REFERENCE.md` — update behavior and exact verification commands.

### Reuse Without Redesign

- `core/strategy_registry.py`
- `core/strategies/baseline.py`
- `core/engine.py`
- `testing/backtest_runner.py`
- `testing/experiment_runner.py`
- `testing/parity_runner.py`
- runtime gating in `core/config_loader.py`

## Chunk 1: Replace Candidate Strategy Subsystem

### Task 1: Build the compact short-horizon regime map

**Files:**
- Modify: `core/strategies/candidate_v1.py`
- Modify: `core/config.py`
- Test: `testing/test_candidate_strategy_v1.py`
- Test: `testing/test_decision_core.py`

- [ ] **Step 1: Write failing tests for the new regime map contract**

Add tests that prove:

- the redesigned candidate uses a compact short-horizon regime map suitable for 7-day 3-minute evaluation
- regime labels remain explicit and coherent through `evaluate_market`
- insufficient-data behavior remains explicit when data is truly insufficient

- [ ] **Step 2: Run the failing tests**

Run: `python3 -m unittest testing.test_candidate_strategy_v1 testing.test_decision_core`
Expected: FAIL on the new regime-map expectations.

- [ ] **Step 3: Implement the minimum regime-map redesign**

Keep the regime map lightweight and deterministic. It should answer only whether continuation trades should be considered, not whether a trade should fire immediately.

- [ ] **Step 4: Re-run the tests**

Run: `python3 -m unittest testing.test_candidate_strategy_v1 testing.test_decision_core`
Expected: PASS

### Task 2: Replace split setup/trigger logic with one multi-timeframe signal engine

**Files:**
- Modify: `core/strategies/candidate_v1.py`
- Modify: `core/decision_core.py` (only if required)
- Test: `testing/test_candidate_strategy_v1.py`
- Test: `testing/test_decision_core.py`

- [ ] **Step 1: Write failing tests for the unified signal contract**

Add tests that prove the candidate now emits one coherent signal decision with:

- entry readiness
- entry price
- invalidation price
- expected hold type
- signal quality
- stable rejection reasons for no-trade cases

- [ ] **Step 2: Run the failing tests**

Run: `python3 -m unittest testing.test_candidate_strategy_v1 testing.test_decision_core`
Expected: FAIL on the new unified signal contract.

- [ ] **Step 3: Implement the minimum signal-engine redesign**

The signal engine must collapse the old setup-vs-trigger mismatch. Do not emit hundreds of vague candidate entries that rely on later downstream filtering.

- [ ] **Step 4: Re-run the tests**

Run: `python3 -m unittest testing.test_candidate_strategy_v1 testing.test_decision_core testing.test_strategy_registry`
Expected: PASS

## Chunk 2: Redesign Candidate Exit Semantics Through Shared Policy

### Task 3: Implement the delayed-trailing exit controller semantics

**Files:**
- Modify: `core/position_policy.py`
- Modify: `core/decision_core.py`
- Test: `testing/test_candidate_strategy_v1.py`
- Test: `testing/test_decision_core.py`
- Test: `testing/test_risk_and_policy.py`

- [ ] **Step 1: Write failing tests for the new exit controller behavior**

Add tests that prove:

- initial stop represents thesis invalidation rather than early noise
- trailing cannot activate before the trade has earned room
- later trailing still preserves diagnostics needed for stop/recovery analysis
- candidate still has no custom strategy exit signal and relies on the shared policy path

- [ ] **Step 2: Run the failing tests**

Run: `python3 -m unittest testing.test_candidate_strategy_v1 testing.test_decision_core testing.test_risk_and_policy`
Expected: FAIL on the new exit behavior expectations.

- [ ] **Step 3: Implement the minimum delayed-trailing redesign**

Use the shared `PositionOrderPolicy` boundary. Do not add a new candidate-only exit engine.

- [ ] **Step 4: Re-run the tests**

Run: `python3 -m unittest testing.test_candidate_strategy_v1 testing.test_decision_core testing.test_risk_and_policy`
Expected: PASS

## Chunk 3: Backtest Evidence Loop

### Task 4: Run the redesigned candidate on the 5-symbol 7-day set

**Files:**
- Modify: `docs/PROJECT_REFERENCE.md`
- Optional: `testing/test_backtest_runner.py` only if minimal runner/reporting fixes are required by the redesign

- [ ] **Step 1: Run the redesigned candidate unit/seam suite**

Run: `python3 -m unittest testing.test_candidate_strategy_v1 testing.test_decision_core testing.test_strategy_registry testing.test_risk_and_policy`
Expected: PASS

- [ ] **Step 2: Run the 5-symbol 7-day candidate backtests**

Run:

```bash
TRADING_MODE=dry_run TRADING_STRATEGY_NAME=candidate_v1 python3 -m testing.backtest_runner --market KRW-BTC --lookback-days 7 --path testing/artifacts/backdata_krw_btc_7d.xlsx --segment-report-path testing/artifacts/krw_btc_candidate_7d_segments.csv --stop-diagnostics-path testing/artifacts/krw_btc_candidate_7d_stop_loss.csv --stop-recovery-path testing/artifacts/krw_btc_candidate_7d_stop_recovery.csv > testing/artifacts/krw_btc_candidate_7d_run.log
TRADING_MODE=dry_run TRADING_STRATEGY_NAME=candidate_v1 python3 -m testing.backtest_runner --market KRW-ETH --lookback-days 7 --path testing/artifacts/backdata_krw_eth_7d.xlsx --segment-report-path testing/artifacts/krw_eth_candidate_7d_segments.csv --stop-diagnostics-path testing/artifacts/krw_eth_candidate_7d_stop_loss.csv --stop-recovery-path testing/artifacts/krw_eth_candidate_7d_stop_recovery.csv > testing/artifacts/krw_eth_candidate_7d_run.log
TRADING_MODE=dry_run TRADING_STRATEGY_NAME=candidate_v1 python3 -m testing.backtest_runner --market KRW-XRP --lookback-days 7 --path testing/artifacts/backdata_krw_xrp_7d.xlsx --segment-report-path testing/artifacts/krw_xrp_candidate_7d_segments.csv --stop-diagnostics-path testing/artifacts/krw_xrp_candidate_7d_stop_loss.csv --stop-recovery-path testing/artifacts/krw_xrp_candidate_7d_stop_recovery.csv > testing/artifacts/krw_xrp_candidate_7d_run.log
TRADING_MODE=dry_run TRADING_STRATEGY_NAME=candidate_v1 python3 -m testing.backtest_runner --market KRW-SOL --lookback-days 7 --path testing/artifacts/backdata_krw_sol_7d.xlsx --segment-report-path testing/artifacts/krw_sol_candidate_7d_segments.csv --stop-diagnostics-path testing/artifacts/krw_sol_candidate_7d_stop_loss.csv --stop-recovery-path testing/artifacts/krw_sol_candidate_7d_stop_recovery.csv > testing/artifacts/krw_sol_candidate_7d_run.log
TRADING_MODE=dry_run TRADING_STRATEGY_NAME=candidate_v1 python3 -m testing.backtest_runner --market KRW-ADA --lookback-days 7 --path testing/artifacts/backdata_krw_ada_7d.xlsx --segment-report-path testing/artifacts/krw_ada_candidate_7d_segments.csv --stop-diagnostics-path testing/artifacts/krw_ada_candidate_7d_stop_loss.csv --stop-recovery-path testing/artifacts/krw_ada_candidate_7d_stop_recovery.csv > testing/artifacts/krw_ada_candidate_7d_run.log
```

Expected: all commands exit 0 and write per-symbol outputs.

- [ ] **Step 3: Write candidate summary artifact**

Write `testing/artifacts/backtest_7d_candidate_summary.json` from the five run logs.

- [ ] **Step 4: Compare against the current reference baseline**

Compare `testing/artifacts/backtest_7d_candidate_summary.json` to `testing/artifacts/backtest_7d_summary.json` for:

- trade count
- combined return across 5 symbols
- median return across 5 symbols
- symbol-level returns
- stop/trailing reason mix

Expected: redesigned candidate preserves materially higher trade count while improving expectancy relative to the current candidate and, ideally, toward or above the current baseline reference.

## Chunk 4: Artifact/Gate Compatibility And Final Verification

### Task 5: Confirm the redesigned candidate still fits artifact and runtime-gate workflows

**Files:**
- Modify: `docs/PROJECT_REFERENCE.md`

- [ ] **Step 1: Run artifact and runtime-gate test suites**

Run: `python3 -m unittest testing.test_experiment_runner testing.test_parity_runner testing.test_config_loader testing.test_engine_order_acceptance`
Expected: PASS

- [ ] **Step 2: Run manual artifact commands**

Run:

```bash
python3 -m testing.experiment_runner --market KRW-BTC --lookback-days 90 --strategy baseline --candidate candidate_v1 --output testing/artifacts/candidate_v1_decision.json
python3 -m testing.parity_runner --strategy candidate_v1 --output testing/artifacts/candidate_v1_parity.json
```

Expected: both commands exit 0 and write updated artifacts.

- [ ] **Step 3: Run changed-file diagnostics**

Run `lsp_diagnostics` on all modified Python files.
Expected: zero errors on modified files.

- [ ] **Step 4: Update docs**

Update `docs/PROJECT_REFERENCE.md` with the final redesign behavior and exact verification commands used.

## Success Conditions

This plan is complete only when all of the following are true.

1. `candidate_v1` still runs through the shared seam and registry.
2. The redesigned strategy subsystem tests pass.
3. The 5-symbol 7-day candidate backtest set runs successfully.
4. Trade count stays materially above the baseline reference.
5. Combined return and/or median return materially improve relative to the current candidate result.
6. Artifact and runtime-gate workflows still pass.
7. Modified files have zero `lsp_diagnostics` errors.

## Notes For Execution

- Do not reopen broker/runtime architecture in this cycle.
- Do not optimize one symbol at the expense of the 5-symbol set.
- Do not add external data sources.
- If the redesigned subsystem still fails the profitability target, stop with evidence rather than widening scope mid-cycle.
