# Short-Horizon Candidate Strategy Redesign Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Redesign `candidate_v1` so the 5-symbol 7-day 3-minute backtest set produces more meaningful trade count and better combined or median return, while preserving the shared decision seam and the existing artifact/gate workflow.

**Architecture:** Keep the existing shared seam, registry, experiment/parity runners, and runtime promotion gate intact. Restrict changes to `candidate_v1`, the strategy-facing defaults it depends on, and the tests/manual backtest loop needed to verify profitability improvement against the current baseline behavior.

**Tech Stack:** Python, dataclasses, unittest, existing shared decision seam (`core/decision_core.py`), existing backtest runner (`testing/backtest_runner.py`), existing artifact/gate workflow

---

## File Map

### Modify

- `core/strategies/candidate_v1.py` — redesign the short-horizon regime, entry, and strategy-facing sizing/diagnostic behavior.
- `core/decision_core.py` — only if a minimal seam adjustment is required to support the approved candidate behavior cleanly.
- `core/config.py` — only strategy-facing defaults required for the approved redesign.
- `testing/test_candidate_strategy_v1.py` — TDD coverage for the redesigned strategy behavior.
- `testing/test_decision_core.py` — seam contract tests if the redesign changes strategy-facing seam expectations.
- `docs/PROJECT_REFERENCE.md` — update strategy behavior and verification commands if they change.

### Reuse Without Redesign

- `core/strategy_registry.py`
- `core/strategies/baseline.py`
- `core/engine.py`
- `testing/backtest_runner.py`
- `testing/experiment_runner.py`
- `testing/parity_runner.py`
- runtime gating in `core/config_loader.py`

## Chunk 1: Candidate Strategy Redesign

### Task 1: Redesign short-horizon regime and insufficient-data behavior

**Files:**
- Modify: `core/strategies/candidate_v1.py`
- Test: `testing/test_candidate_strategy_v1.py`
- Test: `testing/test_decision_core.py`

- [ ] **Step 1: Write failing tests for shorter-horizon regime handling**

Add or adjust tests proving:

- `candidate_v1` can evaluate on the intended 7-day 3-minute backtest horizon without being dominated by 15m warmup insufficiency
- insufficient-data reasons remain explicit and strategy-specific when they still occur
- regime labeling remains stable through `evaluate_market`

- [ ] **Step 2: Run the failing tests**

Run: `python3 -m unittest testing.test_candidate_strategy_v1 testing.test_decision_core`
Expected: FAIL on the newly added shorter-horizon regime expectations.

- [ ] **Step 3: Implement the minimum regime-horizon redesign**

Change only what is necessary in `candidate_v1` (and seam defaults only if required) so the candidate can operate on the approved short-horizon evaluation window.

- [ ] **Step 4: Re-run the tests**

Run: `python3 -m unittest testing.test_candidate_strategy_v1 testing.test_decision_core`
Expected: PASS

### Task 2: Simplify pullback/reclaim entry and candidate sizing behavior

**Files:**
- Modify: `core/strategies/candidate_v1.py`
- Test: `testing/test_candidate_strategy_v1.py`
- Test: `testing/test_decision_core.py`

- [ ] **Step 1: Write failing tests for the simplified entry contract**

Add or adjust tests proving:

- more permissive but still deterministic pullback/reclaim acceptance
- stable downstream diagnostics: `entry_price`, `stop_price`, `r_value`, `entry_score`, `quality_score`, `regime`
- candidate-specific sizing behavior still uses the shared risk path but does not fall back to the baseline quality-bucket multiplier path

- [ ] **Step 2: Run the failing tests**

Run: `python3 -m unittest testing.test_candidate_strategy_v1 testing.test_decision_core`
Expected: FAIL on the new entry/sizing expectations.

- [ ] **Step 3: Implement the minimum entry redesign**

Keep the strategy trend-following and deterministic. Do not add new data sources or multi-stage strategy exits.

- [ ] **Step 4: Re-run the tests**

Run: `python3 -m unittest testing.test_candidate_strategy_v1 testing.test_decision_core testing.test_strategy_registry`
Expected: PASS

### Task 3: Simplify candidate-facing exit behavior

**Files:**
- Modify: `core/strategies/candidate_v1.py`
- Optionally modify: `core/config.py` (only if a strategy-facing default is the cleanest way to express the approved stop/profit behavior)
- Test: `testing/test_candidate_strategy_v1.py`
- Test: `testing/test_decision_core.py`

- [ ] **Step 1: Write failing tests for simpler candidate exit-facing behavior**

Add or adjust tests proving:

- the candidate still relies on the shared `PositionOrderPolicy` path rather than adding a custom strategy exit signal
- the candidate-facing stop/profit behavior is less prone to immediate stop-out noise than the current short-horizon setup
- diagnostics remain explicit about stop basis and risk context

- [ ] **Step 2: Run the failing tests**

Run: `python3 -m unittest testing.test_candidate_strategy_v1 testing.test_decision_core`
Expected: FAIL on the new candidate exit-facing expectations.

- [ ] **Step 3: Implement the minimum exit-behavior redesign**

Use the smallest strategy-facing change that achieves the approved direction: one clear ATR/structure-based protection model and one clear profit-taking model, while preserving the shared policy boundary.

- [ ] **Step 4: Re-run the tests**

Run: `python3 -m unittest testing.test_candidate_strategy_v1 testing.test_decision_core testing.test_strategy_registry`
Expected: PASS

## Chunk 2: Repeated Backtest Verification Loop

### Task 4: Establish the 5-symbol backtest comparison loop

**Files:**
- Modify: `docs/PROJECT_REFERENCE.md`
- Optionally modify: `core/config.py` (only if the candidate redesign needs updated strategy-facing defaults)

- [ ] **Step 1: Run the current candidate unit suite after redesign**

Run: `python3 -m unittest testing.test_candidate_strategy_v1 testing.test_decision_core testing.test_strategy_registry`
Expected: PASS

- [ ] **Step 2: Run the 5-symbol 7-day backtests**

Run:

```bash
TRADING_MODE=dry_run TRADING_STRATEGY_NAME=candidate_v1 python3 -m testing.backtest_runner --market KRW-BTC --lookback-days 7 --path testing/artifacts/backdata_krw_btc_7d.xlsx --segment-report-path testing/artifacts/krw_btc_candidate_7d_segments.csv --stop-diagnostics-path testing/artifacts/krw_btc_candidate_7d_stop_loss.csv --stop-recovery-path testing/artifacts/krw_btc_candidate_7d_stop_recovery.csv > testing/artifacts/krw_btc_candidate_7d_run.log
TRADING_MODE=dry_run TRADING_STRATEGY_NAME=candidate_v1 python3 -m testing.backtest_runner --market KRW-ETH --lookback-days 7 --path testing/artifacts/backdata_krw_eth_7d.xlsx --segment-report-path testing/artifacts/krw_eth_candidate_7d_segments.csv --stop-diagnostics-path testing/artifacts/krw_eth_candidate_7d_stop_loss.csv --stop-recovery-path testing/artifacts/krw_eth_candidate_7d_stop_recovery.csv > testing/artifacts/krw_eth_candidate_7d_run.log
TRADING_MODE=dry_run TRADING_STRATEGY_NAME=candidate_v1 python3 -m testing.backtest_runner --market KRW-XRP --lookback-days 7 --path testing/artifacts/backdata_krw_xrp_7d.xlsx --segment-report-path testing/artifacts/krw_xrp_candidate_7d_segments.csv --stop-diagnostics-path testing/artifacts/krw_xrp_candidate_7d_stop_loss.csv --stop-recovery-path testing/artifacts/krw_xrp_candidate_7d_stop_recovery.csv > testing/artifacts/krw_xrp_candidate_7d_run.log
TRADING_MODE=dry_run TRADING_STRATEGY_NAME=candidate_v1 python3 -m testing.backtest_runner --market KRW-SOL --lookback-days 7 --path testing/artifacts/backdata_krw_sol_7d.xlsx --segment-report-path testing/artifacts/krw_sol_candidate_7d_segments.csv --stop-diagnostics-path testing/artifacts/krw_sol_candidate_7d_stop_loss.csv --stop-recovery-path testing/artifacts/krw_sol_candidate_7d_stop_recovery.csv > testing/artifacts/krw_sol_candidate_7d_run.log
TRADING_MODE=dry_run TRADING_STRATEGY_NAME=candidate_v1 python3 -m testing.backtest_runner --market KRW-ADA --lookback-days 7 --path testing/artifacts/backdata_krw_ada_7d.xlsx --segment-report-path testing/artifacts/krw_ada_candidate_7d_segments.csv --stop-diagnostics-path testing/artifacts/krw_ada_candidate_7d_stop_loss.csv --stop-recovery-path testing/artifacts/krw_ada_candidate_7d_stop_recovery.csv > testing/artifacts/krw_ada_candidate_7d_run.log
```

Expected: all commands exit 0 and write per-symbol outputs.

- [ ] **Step 3: Write candidate summary artifact after the 5-symbol run**

Run:

```bash
python3 - <<'PY'
import json
from pathlib import Path

symbols = ['krw_btc', 'krw_eth', 'krw_xrp', 'krw_sol', 'krw_ada']
rows = []
for slug in symbols:
    log_path = Path(f'testing/artifacts/{slug}_candidate_7d_run.log')
    text = log_path.read_text(encoding='utf-8')
    summary_line = [line for line in text.splitlines() if line.startswith('평균 성과:')][-1]
    payload = eval(summary_line.split('평균 성과:', 1)[1].strip(), {'__builtins__': {}}, {'nan': float('nan')})
    rows.append({'market': slug.upper().replace('_', '-'), 'summary': payload})

output = Path('testing/artifacts/backtest_7d_candidate_summary.json')
output.write_text(json.dumps(rows, ensure_ascii=False, indent=2, allow_nan=True), encoding='utf-8')
print(output)
PY
```

Expected: `testing/artifacts/backtest_7d_candidate_summary.json` is written successfully.

- [ ] **Step 4: Compare against the current 5-symbol reference results**

Compare:

- trade count across symbols
- combined return across all 5 symbols
- median return across all 5 symbols

Reference source:

- `testing/artifacts/backtest_7d_summary.json`

Run:

```bash
python3 - <<'PY'
import json
from statistics import median
from pathlib import Path

reference = json.loads(Path('testing/artifacts/backtest_7d_summary.json').read_text())
current = json.loads(Path('testing/artifacts/backtest_7d_candidate_summary.json').read_text())

def collect(rows):
    returns = [float(row['summary']['return_pct']) for row in rows]
    finals = [float(row['summary']['final_amount_krw']) for row in rows]
    trade_total = 0
    for row in rows:
        market = row['market'].lower().replace('-', '_')
        sample = rows[0] if rows else {}
        is_candidate = sample.get('source') == 'candidate'
        segment_path = (
            Path(f'testing/artifacts/{market}_candidate_7d_segments.csv')
            if is_candidate
            else Path(f'testing/artifacts/{market}_7d_segments.csv')
        )
        if not segment_path.exists():
            continue
        lines = segment_path.read_text(encoding='utf-8').splitlines()[1:]
        for line in lines:
            if not line.strip():
                continue
            trade_total += int(line.split(',')[5])
    return {
        'trade_count': trade_total,
        'combined_return_pct': sum(returns),
        'median_return_pct': median(returns),
        'final_amount_sum': sum(finals),
    }

for row in reference:
    row['source'] = 'reference'
for row in current:
    row['source'] = 'candidate'

print({'reference': collect(reference), 'candidate': collect(current)})
PY
```

Expected: improved trade count plus improved combined return or median return relative to the current baseline reference.

- [ ] **Step 5: If success criteria are not met, iterate once more within approved scope**

Make one bounded follow-up adjustment only if the previous run still under-trades or fails profitability criteria.

- [ ] **Step 6: Re-run the same test and backtest loop after the final adjustment**

Run the same unittest and 5-symbol backtest commands again.
Expected: final evidence set captured.

## Chunk 3: Final Validation And Artifact Compatibility

### Task 5: Confirm the redesigned candidate still fits the existing artifact/gate workflow

**Files:**
- Modify: `docs/PROJECT_REFERENCE.md` (if needed)

- [ ] **Step 1: Run the experiment/parity test suite**

Run: `python3 -m unittest testing.test_experiment_runner testing.test_parity_runner testing.test_config_loader testing.test_engine_order_acceptance`
Expected: PASS

- [ ] **Step 2: Run manual artifact commands with the redesigned candidate**

Run:

```bash
python3 -m testing.experiment_runner --market KRW-BTC --lookback-days 90 --strategy baseline --candidate candidate_v1 --output testing/artifacts/candidate_v1_decision.json
python3 -m testing.parity_runner --strategy candidate_v1 --output testing/artifacts/candidate_v1_parity.json
```

Expected: both commands exit 0 and write updated artifacts.

- [ ] **Step 3: Run changed-file diagnostics**

Run `lsp_diagnostics` on all touched Python files.
Expected: zero errors on modified files.

- [ ] **Step 4: Update docs**

Update `docs/PROJECT_REFERENCE.md` with the final candidate behavior and exact verification commands used.

## Success Conditions

This plan is complete only when all of the following are true.

1. `candidate_v1` still runs through the shared seam and registry.
2. Candidate strategy tests and seam tests pass.
3. The 5-symbol 7-day backtest set runs successfully with `TRADING_STRATEGY_NAME=candidate_v1`.
4. Trade count is meaningfully higher than the current mostly-empty-segment baseline.
5. Combined return or median return across the 5-symbol set improves relative to the current reference run.
6. Experiment/parity commands still work after the redesign.
7. Modified files have zero `lsp_diagnostics` errors.

## Notes For Execution

- Do not broaden scope into broker/runtime architecture.
- Do not optimize only one coin at the expense of the 5-symbol set.
- Do not add external data sources.
- If the final candidate still fails the profitability target after bounded iteration, stop and report the limit with evidence rather than quietly overfitting.

## Suggested Checkpoint Commits

Only create these commits if the user later asks for git commits.

- Task 1 complete: `candidate_v1 단기 레짐 horizon 재설계`
- Task 2 complete: `candidate_v1 진입 조건과 sizing 단순화`
- Task 3 complete: `candidate_v1 단기 exit 동작 정리`
- Task 4 complete: `5심볼 7일 백테스트 비교 루프 추가`
- Task 5 complete: `candidate_v1 artifact 호환성 검증 갱신`
