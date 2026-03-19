# ICT Multi-Symbol Performance Tuning Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Improve `ict_v1` performance on a real KRW multi-symbol basket by tightening over-loose entry acceptance while preserving the TP1 -> breakeven -> TP2 trade lifecycle.

**Architecture:** Keep the shared engine/backtest/exit seams intact. Tune `ict_v1` by adding short-horizon strategy defaults that fit the current 7-day/3m evaluation window and by requiring actual regime + trigger confirmation using existing `core.strategy` primitives. Validate on workbook-backed KRW symbols, not a shared default workbook path.

**Tech Stack:** Python, unittest, existing decision seam, `testing.backtest_runner`, existing ICT helper modules, workbook-backed KRW artifact set under `testing/artifacts/`

---

## Baseline And Acceptance Criteria

True baseline must use per-symbol workbook paths:

- `testing/artifacts/backdata_krw_btc_7d.xlsx`
- `testing/artifacts/backdata_krw_eth_7d.xlsx`
- `testing/artifacts/backdata_krw_xrp_7d.xlsx`
- `testing/artifacts/backdata_krw_sol_7d.xlsx`
- `testing/artifacts/backdata_krw_ada_7d.xlsx`
- `testing/artifacts/backdata_krw_ankr_7d.xlsx`

Current `ict_v1` basket baseline on those six files:

- `combined_compounded_pct = -31.1829`
- `median_compounded_pct = -5.7729`
- `combined_return_pct = -4.7791`
- `median_return_pct = -0.8431`

This tuning cycle is only successful if the same basket improves those baseline metrics after the code change.

## Task 1: Add failing tests for short-horizon `ict_v1` gating

**Files:**
- Modify: `testing/test_ict_strategy_v1.py`
- Modify: `testing/test_strategy_registry.py`

**QA:** `ict_v1` cannot accept loose setups without regime + trigger confirmation, and its default strategy params are explicitly short-horizon rather than inheriting the broader baseline profile.

- [ ] Add a failing test showing `ict_v1` rejects an otherwise valid setup when the bullish micro trigger is absent.
- [ ] Add a failing test showing `ict_v1` rejects entries when the 15m regime filter fails.
- [ ] Add a failing test proving default `ict_v1` params use the intended short-horizon override values.
- [ ] Run: `python3 -m unittest testing.test_ict_strategy_v1 testing.test_strategy_registry`

## Task 2: Implement the minimum `ict_v1` rule tightening

**Files:**
- Modify: `core/config.py`
- Modify: `core/strategies/ict_v1.py`
- Modify: `core/strategies/ict_models.py` (only if a setup-specific confirmation rule is necessary beyond shared trigger primitives)

**QA:** `ict_v1` uses short-horizon defaults that fit the 7-day/3m tuning window and only accepts entries that also satisfy shared bullish trigger semantics.

- [ ] Add `ict_v1` strategy default overrides in `core/config.py` for a realistic short-horizon regime/trigger profile.
- [ ] Reuse existing `core.strategy` primitives in `core/strategies/ict_v1.py` to require regime pass plus a 1m bullish trigger around the selected setup zone.
- [ ] Keep TP1 / breakeven / TP2 logic unchanged.
- [ ] Re-run: `python3 -m unittest testing.test_ict_strategy_v1 testing.test_strategy_registry`

## Task 3: Re-verify seam behavior after tuning

**Files:**
- Test: `testing/test_decision_core.py`
- Test: `testing/test_risk_and_policy.py`

**QA:** Tightened entries still propagate the same diagnostics contract and the staged exit lifecycle is unaffected.

- [ ] Run: `python3 -m unittest testing.test_decision_core testing.test_risk_and_policy`
- [ ] If any seam behavior changes, add a failing regression test first and fix only that break.

## Task 4: Run workbook-backed KRW basket comparison

**Files:**
- No required code changes in this task; artifact outputs may refresh under `/tmp/` or `testing/artifacts/`

**QA:** The same six-symbol workbook-backed basket shows improved combined and median return metrics versus the baseline numbers recorded above.

- [ ] Run the six-symbol basket with explicit `--path` per market.
- [ ] Record combined and median `compounded_return_pct` and `return_pct`.
- [ ] Confirm metrics improved over:
  - `combined_compounded_pct = -31.1829`
  - `median_compounded_pct = -5.7729`
  - `combined_return_pct = -4.7791`
  - `median_return_pct = -0.8431`

## Task 5: Update docs and final verification

**Files:**
- Modify: `docs/PROJECT_REFERENCE.md`

**QA:** Project reference explains the tuned `ict_v1` behavior, the true multi-symbol evaluation method, and the verification commands used for this cycle.

- [ ] Update `docs/PROJECT_REFERENCE.md` with tuning summary, affected files, and verification method.
- [ ] Run changed-file `lsp_diagnostics`.
- [ ] Run: `TRADING_MODE=paper timeout 20s python3 main.py`
- [ ] Run: `TRADING_MODE=dry_run timeout 20s python3 main.py`
- [ ] Run the targeted test suites used in this tuning cycle.
- [ ] Re-run `python3 -m unittest discover -s testing` and explicitly document any remaining pre-existing order-dependent failures.
