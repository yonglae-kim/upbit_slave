# Profitability Redesign Design

## Goal

Improve profit-seeking behavior by removing sim/live decision drift first, then evaluating a new strategy under explicit out-of-sample and parity gates. The redesign keeps the current runtime shell and broker boundaries intact and focuses on a shared pure decision core used by both live trading and backtesting.

## Decision

Use a shared decision core plus thin adapters.

- Keep `main.py`, broker adapters, reconciliation, websocket plumbing, and notifications as the runtime shell.
- Extract entry, regime, sizing, and exit decisions into a shared pure core.
- Preserve `core/position_policy.py` as the common exit-policy boundary for the first migration slice.
- Extract the current `rsi_bb_reversal_long` behavior as the `baseline` strategy.
- Add `candidate_v1` as a simpler regime-aware pullback strategy.
- Promote a candidate only if a machine-readable experiment gate says `promote`.

## Why This Direction

The current codebase already has useful optimization and walk-forward tooling, but the most important trading decisions are still duplicated across live and backtest paths.

- `core/engine.py` mixes regime selection, entry evaluation, sizing, damping, order preflight, execution, and logging inside runtime orchestration.
- `testing/backtest_runner.py` reproduces much of the same entry, sizing, and trade accounting logic separately.
- This makes it hard to know whether apparent profitability comes from the strategy itself or from path-specific behavior.
- `core/position_policy.py` is already the most reusable shared boundary, so rewriting exits first is lower leverage than fixing entry/sizing parity.

## Scope

### In Scope

- Shared pure decision models and decision pipeline.
- Strategy registry with `baseline` and `candidate_v1`.
- Refactor live engine and backtest runner to use the same decision core.
- Experiment runner that emits `promote` or `reject`.
- Config updates required to select strategies and enforce promotion gates.
- Test and documentation updates.

### Out Of Scope

- Broker API rewrites.
- New external data sources.
- Exchange changes.
- Websocket/event-platform rewrite.
- Notification system redesign.
- Promise of higher profitability without evidence.

## Architecture

### 1. Shared Decision Models

Add shared domain models for the trading decision path.

Proposed new module boundary:

- `core/decision_models.py`
  - `MarketSnapshot`
  - `PositionSnapshot`
  - `PortfolioSnapshot`
  - `DecisionContext`
  - `DecisionIntent`
  - `StrategySignal`

These models must be pure data only. They must not call brokers, emit notifications, or perform persistence.

### 2. Shared Decision Pipeline

Add a pure orchestration layer that converts a snapshot into an intent.

Proposed module:

- `core/decision_core.py`
  - normalize market inputs
  - classify regime
  - select strategy
  - compute entry signal
  - compute sizing recommendation
  - compute exit decision via shared policy
  - return `DecisionIntent`

The decision core produces outcomes like:

- `hold`
- `enter`
- `exit_partial`
- `exit_full`
- `skip`

The core returns reasons and diagnostics so both live and backtest can log the same decision metadata.

The shared core must not own long-lived mutable runtime state. The adapters own persistence of trade state across cycles.

Required state boundary:

- adapters build `PositionSnapshot` and current persisted exit-state input
- shared core evaluates decisions against a copied state payload
- shared core returns `DecisionIntent` plus `next_position_state` payload
- adapters persist `next_position_state` after execution or simulation completes

For the first slice, `PositionOrderPolicy` remains the canonical exit engine, but it must be wrapped so the shared core treats it as a state-transform function instead of mutating adapter-owned state in place.

### 3. Thin Adapters

Refactor the existing shells so they call the decision core instead of embedding strategy logic.

- `core/engine.py`
  - gathers live snapshots
  - calls decision core
  - performs preflight and broker execution
  - updates reconciliation and notifications

- `testing/backtest_runner.py`
  - builds historical snapshots
  - calls the same decision core
  - simulates fills and PnL accounting
  - writes comparable diagnostics

The adapters may differ in execution mechanics, but they must not differ in trading decisions for the same snapshot and state.

More explicitly:

- live adapter owns broker-side identifiers, fills, reconciliation, and persisted exit-state storage
- backtest adapter owns simulated fills, cash ledger, and persisted exit-state storage
- both adapters must pass the same snapshot and the same logical position-state shape into the shared core
- both adapters must persist the returned `next_position_state` in their own storage layer

## Strategy Design

### Baseline Strategy

The current `rsi_bb_reversal_long` behavior becomes the explicit `baseline` strategy.

Purpose:

- preserve existing behavior behind the new strategy contract
- provide a control arm for every future experiment
- allow direct parity testing during migration

### Candidate Strategy: `candidate_v1`

`candidate_v1` is a regime-aware pullback continuation strategy built only on the data already available in the repo.

Core idea:

- Trade only when the higher-timeframe regime is `strong_trend` or `weak_trend`.
- Skip `sideways` regimes entirely.
- Use a simpler entry model than the current weighted reversal score.
- Enter on a 1m pullback-and-reclaim pattern aligned with 5m and 15m trend context.
- Size using explicit ATR-based risk sizing without the current score-bucket multiplier logic.
- Use the shared `PositionOrderPolicy` initially so the first strategy comparison isolates entry/sizing improvements more than exit changes.

Candidate entry outline:

- 15m regime must be trend-positive.
- 5m structure must confirm trend continuation rather than reversal.
- 1m must show pullback exhaustion followed by reclaim confirmation.
- stop placement must be ATR- or swing-based and explicit in diagnostics.

Candidate non-goals:

- do not add volume profile, order book, or external market data
- do not add adaptive ML scoring
- do not optimize with hidden future information

## Config And Selection Model

The current config surface mixes multiple strategy families into one large `StrategyParams` shape. The redesign should not fully solve that in the first slice, but it should stop hard-coding strategy branching deep inside the engine.

Required behavior:

- add explicit strategy selection through a strategy registry
- allow `baseline` and `candidate_v1` to be selected by name
- keep current environment/config loading flow intact
- reject running `candidate_v1` in paper/live unless a gate artifact approves it

## Experiment And Promotion Gate

Add a new experiment layer that compares strategies under fixed assumptions.

Proposed module:

- `testing/experiment_runner.py`

Responsibilities:

- run `baseline` and `candidate_v1` on the same backtest window
- record baseline metrics, candidate metrics, and deltas
- enforce OOS acceptance rules and parity checks
- emit a machine-readable decision artifact with value `promote` or `reject`

The decision artifact must include at minimum:

- strategy names
- run configuration
- return percentage
- max drawdown
- sharpe
- win rate
- expectancy
- trade count
- cost assumptions
- acceptance reasons
- final decision

### Required Artifacts

The redesign introduces two machine-readable artifacts.

1. OOS decision artifact
   - default path: `testing/artifacts/candidate_v1_decision.json`
   - producer: `testing/experiment_runner.py`
   - required fields:
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

2. Parity artifact
   - default path: `testing/artifacts/candidate_v1_parity.json`
   - producer: parity fixtures/tests plus a lightweight parity runner
   - required fields:
     - `strategy_name`
     - `snapshot_count`
     - `matched_intent_count`
     - `matched_reason_count`
     - `matched_size_count`
     - `mismatch_rows`
     - `pass`

### Promotion Rules

`decision` is `promote` only if all of the following are true.

- the OOS gate passes under fixed cost assumptions
- the parity artifact has `pass = true`
- the candidate meets or exceeds the baseline on the project-defined OOS objective contract
- no required artifact field is missing

Otherwise `decision` is `reject`.

For this slice, the parity gate is binary.

- expected pass rule: no mismatched decision intent, reason, or size across the approved parity fixture set
- any mismatch in those fields forces `pass = false`

## Migration Sequence

### Phase 1: Freeze Baseline And Gate Contract

- Define the exact artifact schema and promotion rules.
- Preserve the current strategy as `baseline`.
- Add tests proving baseline artifacts can be produced reproducibly.

### Phase 2: Extract Shared Decision Core

- Introduce shared decision models.
- Move strategy selection, regime logic, and sizing decisions out of `core/engine.py`.
- Make backtest runner consume the same core.

### Phase 3: Add `candidate_v1`

- Implement the candidate strategy behind the new contract.
- Compare it against `baseline` using fixed costs and OOS rules.
- Accept that the correct outcome may be `reject`.

### Phase 4: Gate Paper And Live Usage

- Prevent unapproved candidates from running in paper/live.
- Allow approved candidates through explicit decision artifacts only.

## File Plan

### New Files

- `docs/superpowers/specs/2026-03-16-profitability-redesign-design.md`
- `core/decision_models.py`
- `core/decision_core.py`
- `core/strategy_registry.py`
- `core/strategies/baseline.py`
- `core/strategies/candidate_v1.py`
- `testing/experiment_runner.py`
- `testing/test_strategy_registry.py`
- `testing/test_candidate_strategy_v1.py`
- `testing/test_experiment_runner.py`

### Modified Files

- `core/engine.py`
- `testing/backtest_runner.py`
- `core/config.py`
- `core/config_loader.py`
- `config.py`
- `docs/PROJECT_REFERENCE.md`

## Binary Acceptance Criteria

The redesign is done only when all of the following are true.

1. Live and backtest both call the same shared decision core for strategy evaluation and sizing decisions.
2. The current strategy still runs as `baseline` through the new registry.
3. `candidate_v1` runs through the same contract as `baseline`.
4. `python -m testing.experiment_runner --market KRW-BTC --lookback-days 90 --strategy baseline --candidate candidate_v1 --output testing/artifacts/candidate_v1_decision.json` completes.
5. `testing/artifacts/candidate_v1_decision.json` contains a final decision field with value `promote` or `reject`.
6. `testing/artifacts/candidate_v1_parity.json` is written and contains `pass = true` only when no approved parity fixture produces an intent, reason, or size mismatch.
7. A rejected candidate cannot be selected for paper/live execution.
8. `docs/PROJECT_REFERENCE.md` is updated with the new execution and verification flow.

## Verification Plan

### Tests

- `python -m unittest testing.test_backtest_runner`
- `python -m unittest testing.test_optimize_walkforward`
- `python -m unittest testing.test_strategy_registry`
- `python -m unittest testing.test_candidate_strategy_v1`
- `python -m unittest testing.test_experiment_runner`
- `python -m unittest testing.test_main_signals`

### Manual QA

- Run a baseline backtest and confirm artifacts are produced.
- Run the experiment runner and confirm the decision artifact is written.
- Run the parity runner or parity test entrypoint and confirm the parity artifact is written.
- Attempt to run an unapproved candidate in paper mode and verify it is rejected.

### Diagnostics

- Run `lsp_diagnostics` on all changed files.
- Zero new errors are allowed in changed files.

## Risks And Guardrails

- Do not relax fee or slippage assumptions to manufacture wins.
- Do not rewrite broker integration first.
- Do not rewrite exits first unless parity extraction forces it.
- Do not add new data sources in this slice.
- Do not force `candidate_v1` to ship if the artifact says `reject`.

## Expected Outcome

This redesign does not guarantee better profits. It creates a safer path to discover whether a simpler candidate strategy actually beats the current baseline under the repo's own OOS and parity standards.
