# Profitability Redesign Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a shared decision core for live trading and backtesting, preserve the current strategy as `baseline`, add a gated `candidate_v1`, and produce machine-readable `promote` or `reject` artifacts.

**Architecture:** Keep the runtime shell (`main.py`, brokers, reconciliation, notifications) intact and move trading decisions into a shared pure core. Both `core/engine.py` and `testing/backtest_runner.py` must call the same decision pipeline and persist adapter-owned state separately. Promotion into paper/live must depend on explicit OOS and parity artifacts.

**Tech Stack:** Python, dataclasses, unittest, existing `core/position_policy.py`, existing walk-forward tooling in `testing/optimize_walkforward.py`

---

## File Map

### Create

- `core/decision_models.py` — shared immutable-ish data models for snapshots, state payloads, and intents.
- `core/decision_core.py` — pure orchestration of regime, strategy selection, sizing, and exit evaluation.
- `core/strategy_registry.py` — maps strategy names to strategy implementations.
- `core/strategies/__init__.py` — package marker and exports.
- `core/strategies/baseline.py` — wraps current `rsi_bb_reversal_long` as the `baseline` strategy contract.
- `core/strategies/candidate_v1.py` — new regime-aware pullback strategy.
- `testing/experiment_runner.py` — baseline vs candidate experiment gate.
- `testing/parity_runner.py` — emits parity artifact from approved fixtures.
- `testing/fixtures/parity_baseline_cases.json` — approved parity snapshots and expected results.
- `testing/fixtures/rejected_candidate_v1_decision.json` — explicit reject artifact used for gate QA.
- `testing/test_decision_core.py` — unit tests for the pure core.
- `testing/test_strategy_registry.py` — strategy lookup and selection tests.
- `testing/test_candidate_strategy_v1.py` — candidate strategy behavior tests.
- `testing/test_experiment_runner.py` — `promote`/`reject` artifact tests.
- `testing/test_parity_runner.py` — parity artifact tests.

### Modify

- `core/engine.py` — replace embedded decision logic with adapter calls into the shared core.
- `testing/backtest_runner.py` — replace duplicated decision logic with shared-core calls.
- `core/config.py` — add strategy/gating config surface and any helper conversion needed by the registry/core.
- `core/config_loader.py` — validate new strategy names and gate-related config.
- `config.py` — default strategy/gate configuration.
- `docs/PROJECT_REFERENCE.md` — document new structure, commands, and verification steps.
- `testing/test_backtest_runner.py` — adapt expectations to shared-core flow.
- `testing/test_main_signals.py` — preserve regime classification expectations if touched.
- `testing/test_engine_order_acceptance.py` — verify engine adapter behavior after refactor.
- `testing/test_config_loader.py` — validate new config loading behavior.

### Reuse Without Immediate Rewrite

- `core/position_policy.py` — stays the canonical exit policy in slice one.
- `core/rsi_bb_reversal_long.py` — remains the source of baseline entry logic, wrapped instead of rewritten initially.
- `testing/optimize_walkforward.py` — remains the OOS optimization reference and threshold source.

## Chunk 1: Strategy Contract And Shared Models

### Task 1: Add the shared strategy contract and registry

**Files:**
- Create: `core/strategy_registry.py`
- Create: `core/strategies/__init__.py`
- Create: `core/strategies/baseline.py`
- Test: `testing/test_strategy_registry.py`
- Modify: `core/config_loader.py`
- Modify: `core/config.py`

- [ ] **Step 1: Write failing registry tests**

Add tests in `testing/test_strategy_registry.py` for:

- lookup of `baseline`
- rejection of unknown strategy names

- [ ] **Step 2: Run the failing registry tests**

Run: `python -m unittest testing.test_strategy_registry`
Expected: FAIL with import errors or missing registry symbols.

- [ ] **Step 3: Implement the registry and baseline wrapper**

Create a simple registry API, for example:

```python
from dataclasses import dataclass


@dataclass(frozen=True)
class RegisteredStrategy:
    name: str
    entry_evaluator: object
    metadata: dict[str, str]


def get_strategy(name: str) -> RegisteredStrategy:
    ...
```

In `core/strategies/baseline.py`, wrap existing `evaluate_long_entry` logic from `core/rsi_bb_reversal_long.py` instead of copying it.

- [ ] **Step 4: Extend config validation for registry-friendly names**

Update `core/config_loader.py` and `core/config.py` so strategy selection does not rely on hard-coded branches inside `core/engine.py`.

- [ ] **Step 5: Re-run registry/config tests**

Run: `python -m unittest testing.test_strategy_registry testing.test_config_loader`
Expected: PASS

- [ ] **Step 6: Checkpoint review**

Confirm that baseline lookup works through the registry without adding any new runtime-only branching.

### Task 2: Add shared decision models

**Files:**
- Create: `core/decision_models.py`
- Test: `testing/test_decision_core.py`
- Modify: `core/strategy_registry.py`

- [ ] **Step 1: Write failing decision-model tests**

Add tests for the shape and defaults of:

- `MarketSnapshot`
- `PositionSnapshot`
- `PortfolioSnapshot`
- `DecisionContext`
- `DecisionIntent`

Include at least one test proving that intent payloads carry `action`, `reason`, `diagnostics`, and `next_position_state`.

- [ ] **Step 2: Run the failing model tests**

Run: `python -m unittest testing.test_decision_core`
Expected: FAIL with missing module or missing class errors.

- [ ] **Step 3: Implement the models**

Use dataclasses and plain Python types. Do not place broker objects or notifier objects in these models.

- [ ] **Step 4: Re-run the model tests**

Run: `python -m unittest testing.test_decision_core`
Expected: partial PASS or new failures only in unimplemented decision-core logic.

## Chunk 2: Shared Decision Core And Adapter Refactor

### Task 3: Build the pure decision core around shared state handoff

**Files:**
- Create: `core/decision_core.py`
- Modify: `core/position_policy.py`
- Modify: `core/strategy_registry.py`
- Test: `testing/test_decision_core.py`

- [ ] **Step 1: Write failing decision-core tests**

Add tests covering:

- `hold` when no strategy entry passes
- `enter` intent with baseline strategy diagnostics
- `exit_full` or `exit_partial` intent using `PositionOrderPolicy`
- returned `next_position_state` payload instead of adapter mutation

- [ ] **Step 2: Run the failing decision-core tests**

Run: `python -m unittest testing.test_decision_core`
Expected: FAIL with missing core functions or wrong return shape.

- [ ] **Step 3: Implement minimal decision-core flow**

Recommended structure:

```python
def evaluate_market(context: DecisionContext) -> DecisionIntent:
    strategy = get_strategy(context.strategy_name)
    entry_signal = strategy.evaluate_entry(context)
    if should_exit_position(context):
        return build_exit_intent(...)
    if should_enter_position(context, entry_signal):
        return build_enter_intent(...)
    return build_hold_intent(...)
```

Wrap `PositionOrderPolicy` so the core can pass in state and receive a new state payload plus decision, rather than relying on adapters to share mutable internals.

- [ ] **Step 4: Re-run the decision-core tests**

Run: `python -m unittest testing.test_decision_core`
Expected: PASS

- [ ] **Step 5: Run adjacent regression tests**

Run: `python -m unittest testing.test_risk_and_policy testing.test_main_signals`
Expected: PASS

### Task 4: Refactor the live engine into a thin adapter

**Files:**
- Modify: `core/engine.py`
- Modify: `core/config.py`
- Test: `testing/test_engine_order_acceptance.py`
- Test: `testing/test_engine_ws_hooks.py`
- Test: `testing/test_engine_candle_trigger.py`
- Test: `testing/test_main_signals.py`

- [ ] **Step 1: Write failing engine-adapter tests**

Extend engine tests to assert:

- engine builds a decision context
- engine routes `enter` intents to broker preflight/execution
- engine routes `exit` intents to sell paths
- engine persists `next_position_state`

- [ ] **Step 2: Run the failing engine tests**

Run: `python -m unittest testing.test_engine_order_acceptance testing.test_engine_ws_hooks testing.test_engine_candle_trigger testing.test_main_signals`
Expected: FAIL where embedded decision logic is still assumed.

- [ ] **Step 3: Replace `_try_buy` branching with shared-core calls**

Keep runtime-only responsibilities in `core/engine.py`:

- market refresh
- data fetch and snapshot assembly
- broker preflight
- broker execution
- notifications
- reconciliation hooks

Remove runtime-owned strategy branching where possible and replace it with strategy registry + shared-core evaluation.

- [ ] **Step 4: Re-run engine tests**

Run: `python -m unittest testing.test_engine_order_acceptance testing.test_engine_ws_hooks testing.test_engine_candle_trigger testing.test_main_signals`
Expected: PASS

- [ ] **Step 5: Checkpoint review**

Confirm that runtime code no longer depends on the old `strategy_name == ...` branch for baseline strategy selection.

- [ ] **Step 6: Run focused diagnostics**

Run `lsp_diagnostics` on `core/engine.py`, `core/decision_core.py`, and `core/decision_models.py`.
Expected: Zero new errors in the changed files.

### Task 5: Refactor the backtest runner into a thin adapter

**Files:**
- Modify: `testing/backtest_runner.py`
- Modify: `testing/test_backtest_runner.py`
- Test: `testing/test_decision_core.py`

- [ ] **Step 1: Write failing backtest-adapter tests**

Add tests that prove backtest uses the shared decision core for:

- entry decision
- sizing intent
- exit-policy evaluation
- next-position-state persistence

- [ ] **Step 2: Run the failing backtest tests**

Run: `python -m unittest testing.test_backtest_runner`
Expected: FAIL due to old duplicated entry/sizing path.

- [ ] **Step 3: Refactor `_run_segment` to call the shared core**

Do not change fill simulation, slippage accounting, or ledger writing semantics in this task unless necessary for parity with the new intent format.

- [ ] **Step 4: Re-run backtest tests**

Run: `python -m unittest testing.test_backtest_runner`
Expected: PASS

- [ ] **Step 5: Run baseline manual QA**

Run: `python -m testing.backtest_runner --market KRW-BTC --lookback-days 30`
Expected: command exits 0 and prints/writes baseline diagnostics without crashing.

## Chunk 3: Candidate Strategy, Experiment Gate, And Promotion Safety

### Task 6: Implement `candidate_v1`

**Files:**
- Create: `core/strategies/candidate_v1.py`
- Modify: `core/strategy_registry.py`
- Test: `testing/test_candidate_strategy_v1.py`
- Test: `testing/test_decision_core.py`

- [ ] **Step 1: Write failing candidate tests**

Add tests for:

- skip in `sideways`
- entry in `strong_trend` after pullback-and-reclaim fixture
- no entry when reclaim confirmation is missing
- stable diagnostics including stop basis and regime

- [ ] **Step 2: Run the failing candidate tests**

Run: `python -m unittest testing.test_candidate_strategy_v1`
Expected: FAIL with missing strategy module or missing evaluator.

- [ ] **Step 3: Implement the candidate strategy minimally**

Use only existing repo data. Keep the implementation simpler than `rsi_bb_reversal_long`.

- [ ] **Step 4: Re-run candidate tests**

Run: `python -m unittest testing.test_candidate_strategy_v1 testing.test_decision_core`
Expected: PASS

### Task 7: Add experiment and parity runners

**Files:**
- Create: `testing/experiment_runner.py`
- Create: `testing/parity_runner.py`
- Create: `testing/fixtures/parity_baseline_cases.json`
- Create: `testing/test_experiment_runner.py`
- Create: `testing/test_parity_runner.py`
- Modify: `testing/optimize_walkforward.py`
- Modify: `core/config.py`

- [ ] **Step 1: Write failing experiment and parity tests**

Add tests for:

- decision artifact schema
- parity artifact schema
- `promote` on synthetic better candidate fixture
- `reject` on synthetic worse candidate fixture
- `reject` when parity mismatches exist

The decision artifact schema tests must require:

- `baseline_strategy`
- `candidate_strategy`
- `run_config`
- `cost_model`
- `baseline_metrics`
- `candidate_metrics`
- `delta_metrics`
- `oos_gate`
- `parity_gate`
- `decision`
- `reasons`

- [ ] **Step 2: Run the failing tests**

Run: `python -m unittest testing.test_experiment_runner testing.test_parity_runner`
Expected: FAIL with missing runner modules or missing artifact fields.

- [ ] **Step 3: Implement `testing/experiment_runner.py`**

The runner must write `testing/artifacts/candidate_v1_decision.json` with:

- baseline strategy name
- candidate strategy name
- run configuration
- cost model
- baseline metrics
- candidate metrics
- delta metrics
- OOS gate result
- parity gate result
- final `promote` or `reject`
- reasons

The runner must reuse the project thresholds already represented in `testing/optimize_walkforward.py` and `core/config.py` rather than inventing a new objective contract.

- [ ] **Step 4: Implement `testing/parity_runner.py`**

The runner must write `testing/artifacts/candidate_v1_parity.json` and set `pass` to `false` on any mismatch of intent, reason, or size across the approved parity fixtures.

Store the approved parity fixture set in `testing/fixtures/parity_baseline_cases.json` so the parity runner and parity tests share one source of truth.

- [ ] **Step 5: Re-run the tests**

Run: `python -m unittest testing.test_experiment_runner testing.test_parity_runner testing.test_optimize_walkforward`
Expected: PASS

- [ ] **Step 6: Manual QA the artifacts**

Run: `python -m testing.experiment_runner --market KRW-BTC --lookback-days 90 --strategy baseline --candidate candidate_v1 --output testing/artifacts/candidate_v1_decision.json`
Expected: exit 0 and `testing/artifacts/candidate_v1_decision.json` exists with `decision` set to `promote` or `reject`.

Run: `python -m testing.parity_runner --strategy baseline --output testing/artifacts/candidate_v1_parity.json`
Expected: exit 0 and `testing/artifacts/candidate_v1_parity.json` exists with `pass` present.

### Task 8: Enforce promotion gates in runtime selection

**Files:**
- Modify: `core/config_loader.py`
- Modify: `core/config.py`
- Modify: `config.py`
- Modify: `core/engine.py`
- Create: `testing/fixtures/rejected_candidate_v1_decision.json`
- Test: `testing/test_config_loader.py`
- Test: `testing/test_engine_order_acceptance.py`

- [ ] **Step 1: Write failing gate-enforcement tests**

Add tests proving:

- baseline can run without a decision artifact
- candidate strategies require an approved decision artifact in paper/live
- rejected candidates are blocked
- dry-run behavior follows the chosen policy consistently

- [ ] **Step 2: Run the failing gate tests**

Run: `python -m unittest testing.test_config_loader testing.test_engine_order_acceptance`
Expected: FAIL with missing gating behavior.

- [ ] **Step 3: Implement the gate checks**

Keep the checks close to configuration/runtime selection, not inside the pure strategy logic.

- [ ] **Step 4: Re-run the gate tests**

Run: `python -m unittest testing.test_config_loader testing.test_engine_order_acceptance`
Expected: PASS

- [ ] **Step 5: Manual QA rejection path**

Run: `TRADING_MODE=paper TRADING_STRATEGY_NAME=candidate_v1 TRADING_STRATEGY_DECISION_PATH=testing/fixtures/rejected_candidate_v1_decision.json python main.py`
Expected: non-zero exit or explicit validation error before the polling loop starts.

### Task 9: Update docs and run full verification

**Files:**
- Modify: `docs/PROJECT_REFERENCE.md`
- Modify: `docs/superpowers/plans/2026-03-16-profitability-redesign.md`

- [ ] **Step 1: Update project documentation**

Add:

- new architecture summary
- new files and responsibilities
- baseline/candidate experiment commands
- parity/gating commands
- changed verification flow

- [ ] **Step 2: Run the full targeted test set**

Run: `python -m unittest testing.test_strategy_registry testing.test_decision_core testing.test_candidate_strategy_v1 testing.test_experiment_runner testing.test_parity_runner testing.test_backtest_runner testing.test_config_loader testing.test_engine_order_acceptance testing.test_engine_ws_hooks testing.test_engine_candle_trigger testing.test_main_signals testing.test_optimize_walkforward`
Expected: PASS

- [ ] **Step 3: Run end-to-end manual QA commands**

Run:

- `python -m testing.backtest_runner --market KRW-BTC --lookback-days 30`
- `python -m testing.experiment_runner --market KRW-BTC --lookback-days 90 --strategy baseline --candidate candidate_v1 --output testing/artifacts/candidate_v1_decision.json`
- `python -m testing.parity_runner --strategy baseline --output testing/artifacts/candidate_v1_parity.json`

Expected:

- each command exits 0
- both artifact files exist
- decision artifact contains `promote` or `reject`
- parity artifact contains `pass`

- [ ] **Step 4: Run diagnostics on changed files**

Run `lsp_diagnostics` on all modified and created Python files.
Expected: zero new errors in files changed by this work.

- [ ] **Step 5: Final checkpoint**

Confirm that:

- live and backtest both call the same decision core
- `baseline` still behaves as the control strategy
- `candidate_v1` is gated by artifacts
- `docs/PROJECT_REFERENCE.md` reflects the new flow

## Notes For Execution

- Do not rewrite brokers, websockets, or reconciliation first.
- Do not relax fees or slippage to manufacture wins.
- Do not promote `candidate_v1` unless the artifact explicitly says `promote`.
- If the artifact says `reject`, that is still a successful implementation outcome.

## Suggested Checkpoint Commits

Only create these commits if the user later asks for git commits.

- Chunk 1 complete: `refactor: add strategy registry and decision models`
- Chunk 2 complete: `refactor: share decision core across engine and backtest`
- Chunk 3 complete: `feat: add candidate experiment and promotion gates`
