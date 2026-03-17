# Proof-Window Promotion Redesign Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a proof-window and symbol-conditioned promotion/cooldown lifecycle to `candidate_v1` so the strategy keeps materially higher trade count while improving expectancy on the 5-symbol 7-day 3-minute backtest set.

**Architecture:** Keep the current entry generator mostly intact. Add a post-entry proof window inside the strategy subsystem so each filled trade must earn early favorable excursion before graduating into the normal delayed-trailing regime, and allow weak symbols to require stricter proof or temporary cooldown without changing the surrounding runtime, artifact, or gate infrastructure.

**Tech Stack:** Python, dataclasses, unittest, existing shared decision seam (`core/decision_core.py`), existing shared exit policy (`core/position_policy.py`), existing backtest/artifact workflow

---

## File Map

### Modify

- `core/strategies/candidate_v1.py` — add proof-window and symbol-conditioned promotion/cooldown strategy state/diagnostics.
- `core/decision_core.py` — persist and propagate proof-window state through the shared seam.
- `core/position_policy.py` — honor proof-window state before allowing normal delayed-trailing progression.
- `core/config.py` — candidate-specific defaults for proof-window thresholds and any bounded symbol-conditioned settings.
- `testing/test_candidate_strategy_v1.py` — TDD coverage for proof-window, promotion, and cooldown behavior.
- `testing/test_decision_core.py` — seam contract tests for proof-window state propagation and promotion semantics.
- `testing/test_risk_and_policy.py` — shared exit policy tests for proof-window-aware candidate exits.
- `docs/PROJECT_REFERENCE.md` — update behavior and exact verification commands.

### Reuse Without Redesign

- `core/strategy_registry.py`
- `core/strategies/baseline.py`
- `core/engine.py`
- `testing/backtest_runner.py`
- `testing/experiment_runner.py`
- `testing/parity_runner.py`
- runtime gating in `core/config_loader.py`

## Chunk 1: Add Proof-Window Lifecycle State

### Task 1: Persist proof-window state through the shared seam

**Files:**
- Modify: `core/strategies/candidate_v1.py`
- Modify: `core/decision_core.py`
- Test: `testing/test_candidate_strategy_v1.py`
- Test: `testing/test_decision_core.py`

- [ ] **Step 1: Write failing tests for proof-window state creation**

Add tests that prove a newly accepted `candidate_v1` entry initializes proof-window state, including:

- proof-window activation flag
- proof start bars / early favorable excursion tracking
- promotion threshold target in diagnostics or persisted state
- coherent symbol-aware defaults in diagnostics or state
- bars advancing without enough early favorable excursion is not sufficient for promotion

- [ ] **Step 2: Run the failing tests**

Run: `python3 -m unittest testing.test_candidate_strategy_v1 testing.test_decision_core`
Expected: FAIL on the new proof-window state expectations.

- [ ] **Step 3: Implement the minimum proof-window state propagation**

Keep the existing entry generator intact. Only add the state and diagnostics needed so later exit logic can tell whether a trade has earned promotion.

- [ ] **Step 4: Re-run the tests**

Run: `python3 -m unittest testing.test_candidate_strategy_v1 testing.test_decision_core`
Expected: PASS

### Task 2: Add symbol-conditioned promotion/cooldown inputs

**Files:**
- Modify: `core/config.py`
- Modify: `core/strategies/candidate_v1.py`
- Test: `testing/test_candidate_strategy_v1.py`
- Test: `testing/test_decision_core.py`

- [ ] **Step 1: Write failing tests for symbol-conditioned candidate behavior**

Add tests that prove:

- weak symbols can require a stricter proof threshold than neutral/strong symbols
- symbol-conditioned behavior stays inside the strategy subsystem
- symbol-conditioned defaults do not affect baseline behavior

- [ ] **Step 2: Run the failing tests**

Run: `python3 -m unittest testing.test_candidate_strategy_v1 testing.test_decision_core`
Expected: FAIL on the new symbol-conditioned expectations.

- [ ] **Step 3: Implement the minimum candidate-only symbol conditioning**

Use only bounded symbol-conditioned thresholds or cooldown hints. Do not add new runtime paths.

- [ ] **Step 4: Re-run the tests**

Run: `python3 -m unittest testing.test_candidate_strategy_v1 testing.test_decision_core testing.test_strategy_registry`
Expected: PASS

## Chunk 2: Gate Exit Progression On Proof

### Task 3: Prevent non-proven trades from reaching full trailing behavior

**Files:**
- Modify: `core/position_policy.py`
- Modify: `core/decision_core.py`
- Test: `testing/test_risk_and_policy.py`
- Test: `testing/test_decision_core.py`

- [ ] **Step 1: Write failing tests for proof-gated exit progression**

Add tests that prove:

- non-promoted candidate trades do not graduate into the normal delayed-trailing regime
- proof-window failures scratch or exit under the tighter proof-window policy rather than behaving like full trend trades
- promoted trades still use the current delayed-trailing semantics
- bars advancing without proof is still not sufficient for promotion at the policy/seam layer

- [ ] **Step 2: Run the failing tests**

Run: `python3 -m unittest testing.test_risk_and_policy testing.test_decision_core`
Expected: FAIL on the new proof-gated exit expectations.

- [ ] **Step 3: Implement the minimum proof-gated exit redesign**

Keep the shared `PositionOrderPolicy` boundary. Do not add a candidate-only exit engine.

- [ ] **Step 4: Re-run the tests**

Run: `python3 -m unittest testing.test_risk_and_policy testing.test_decision_core testing.test_candidate_strategy_v1`
Expected: PASS

## Chunk 3: Backtest Evidence Loop

### Task 4: Run the proof-window candidate on the 5-symbol 7-day set

**Files:**
- Modify: `docs/PROJECT_REFERENCE.md`

- [ ] **Step 1: Run the redesigned candidate test suite**

Run: `python3 -m unittest testing.test_candidate_strategy_v1 testing.test_decision_core testing.test_risk_and_policy testing.test_strategy_registry`
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

Run:

```bash
python3 - <<'PY'
import json
from pathlib import Path

symbols = ["KRW-BTC", "KRW-ETH", "KRW-XRP", "KRW-SOL", "KRW-ADA"]
rows = []
for symbol in symbols:
    slug = symbol.lower().replace('-', '_')
    text = Path(f'testing/artifacts/{slug}_candidate_7d_run.log').read_text(encoding='utf-8')
    summary_line = [line for line in text.splitlines() if line.startswith('평균 성과:')][-1]
    payload = eval(summary_line.split('평균 성과:', 1)[1].strip(), {'__builtins__': {}}, {'nan': float('nan')})
    rows.append({'market': symbol, 'source': 'candidate', 'summary': payload})

output = Path('testing/artifacts/backtest_7d_candidate_summary.json')
output.write_text(json.dumps(rows, ensure_ascii=False, indent=2, allow_nan=True), encoding='utf-8')
print(output)
PY
```

Expected: `testing/artifacts/backtest_7d_candidate_summary.json` exists and contains 5 rows with `market`, `source`, and `summary`.

- [ ] **Step 4: Compare against the current baseline and current-candidate reference**

Compare:

- trade count vs baseline 4 and vs current-candidate ~38
- combined return vs current-candidate `-1.0556`
- median return vs current-candidate `-0.1726`
- worst-symbol damage, especially `KRW-ADA`

Run:

```bash
python3 - <<'PY'
import csv, json
from pathlib import Path
from statistics import median

reference = json.loads(Path('testing/artifacts/backtest_7d_summary.json').read_text())
candidate = json.loads(Path('testing/artifacts/backtest_7d_candidate_summary.json').read_text())

def collect(rows, candidate_mode):
    returns = [float(row['summary']['return_pct']) for row in rows]
    trade_total = 0
    stop_reason_counts = {'stop_loss': 0, 'trailing_stop': 0}
    for row in rows:
        market = row['market'].lower().replace('-', '_')
        seg = Path(f'testing/artifacts/{market}_candidate_7d_segments.csv' if candidate_mode else f'testing/artifacts/{market}_7d_segments.csv')
        for line in seg.read_text(encoding='utf-8').splitlines()[1:]:
            if line.strip():
                trade_total += int(line.split(',')[5])
        stop_csv = Path(f'testing/artifacts/{market}_candidate_7d_stop_loss.csv' if candidate_mode else f'testing/artifacts/{market}_7d_stop_loss.csv')
        if stop_csv.exists():
            for stop_row in csv.DictReader(stop_csv.open()):
                reason = stop_row['reason']
                if reason in stop_reason_counts:
                    stop_reason_counts[reason] += 1
    return {
        'trade_count': trade_total,
        'combined_return_pct': round(sum(returns), 4),
        'median_return_pct': round(median(returns), 4),
        'per_symbol_returns': {row['market']: float(row['summary']['return_pct']) for row in rows},
        'stop_reason_mix': stop_reason_counts,
    }

print(json.dumps({'reference': collect(reference, False), 'candidate': collect(candidate, True)}, ensure_ascii=False, indent=2))
PY
```

Expected: output includes `trade_count`, `combined_return_pct`, `median_return_pct`, `per_symbol_returns`, and `stop_reason_mix` for both reference and candidate.

Expected: proof-window redesign preserves materially higher trade count while improving combined and median return relative to the current candidate result.

## Chunk 4: Artifact/Gate Compatibility And Final Verification

### Task 5: Confirm the proof-window redesign still fits artifact and runtime-gate workflows

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

Update `docs/PROJECT_REFERENCE.md` with the final proof-window behavior and exact verification commands used.

## Success Conditions

This plan is complete only when all of the following are true.

1. `candidate_v1` still runs through the shared seam and registry.
2. The proof-window and promotion/cooldown tests pass.
3. The 5-symbol 7-day candidate backtest set runs successfully.
4. Trade count stays materially above the 4-trade baseline and does not collapse materially relative to the current candidate participation level.
5. Combined return and median return improve relative to the current candidate result.
6. The worst-symbol damage, especially from `KRW-ADA`, is reduced materially.
7. Artifact and runtime-gate workflows still pass.
8. Modified files have zero `lsp_diagnostics` errors.

## Notes For Execution

- Do not reopen broker/runtime architecture in this cycle.
- Do not loosen entry again before changing post-entry lifecycle quality.
- Do not optimize one symbol only; symbol conditioning must remain bounded and candidate-only.
- If this proof-window redesign still fails the profitability target, stop with evidence rather than widening scope mid-cycle.
