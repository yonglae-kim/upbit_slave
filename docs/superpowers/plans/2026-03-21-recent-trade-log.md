# Recent Trade Log Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist the most recent 10 completed runtime trades to a text file with enough entry, exit, and candle context to explain why each trade happened.

**Architecture:** Extend the existing runtime engine diagnostics seam instead of creating a parallel reporting subsystem. Keep entry context in the in-memory trade tracking payload, capture every exit event as it happens, and rewrite a single rolling text file whenever a trade fully closes.

**Tech Stack:** Python, `core/engine.py`, `TradingConfig`, unittest

---

## Chunk 1: Config Surface

### Task 1: Add a runtime path for the recent trade log

**Files:**
- Modify: `config.py`
- Modify: `core/config.py`
- Modify: `core/config_loader.py`
- Test: `testing/test_config_loader.py`

- [ ] **Step 1: Write the failing config test**

Add a unittest that sets `TRADING_RECENT_TRADE_LOG_PATH` and expects `load_trading_config()` to expose the value.

- [ ] **Step 2: Run the config test to verify it fails**

Run: `python3 -m unittest testing.test_config_loader.ConfigLoaderTest.test_recent_trade_log_path_can_be_overridden_from_env`
Expected: FAIL because the config surface does not expose the field yet.

- [ ] **Step 3: Add the minimal config support**

Add `recent_trade_log_path` to runtime defaults and config loading so the engine has a single text-file target.

- [ ] **Step 4: Run the config test to verify it passes**

Run: `python3 -m unittest testing.test_config_loader.ConfigLoaderTest.test_recent_trade_log_path_can_be_overridden_from_env`
Expected: PASS.

## Chunk 2: Runtime Recent-Trade Log

### Task 2: Capture entry and exit context and persist the last 10 completed trades

**Files:**
- Modify: `core/engine.py`
- Test: `testing/test_engine_order_acceptance.py`

- [ ] **Step 1: Write the failing runtime tests**

Add tests for:
1. A full trade writes a text file containing the entry reason, exit reason, and candle context.
2. The file keeps only the most recent 10 completed trades.

- [ ] **Step 2: Run the runtime tests to verify they fail**

Run: `python3 -m unittest testing.test_engine_order_acceptance.TradingEngineOrderAcceptanceTest.test_full_exit_writes_recent_trade_log_with_reasons_and_candles testing.test_engine_order_acceptance.TradingEngineOrderAcceptanceTest.test_recent_trade_log_keeps_only_latest_ten_completed_trades`
Expected: FAIL because the engine does not persist the log yet.

- [ ] **Step 3: Add the minimal engine implementation**

Store richer entry metadata at buy time, append every exit event, finalize a completed trade on `exit_full`, and rewrite a rolling text file that keeps the latest 10 completed trades.

- [ ] **Step 4: Run the runtime tests to verify they pass**

Run: `python3 -m unittest testing.test_engine_order_acceptance.TradingEngineOrderAcceptanceTest.test_full_exit_writes_recent_trade_log_with_reasons_and_candles testing.test_engine_order_acceptance.TradingEngineOrderAcceptanceTest.test_recent_trade_log_keeps_only_latest_ten_completed_trades`
Expected: PASS.

## Chunk 3: Verification

### Task 3: Verify the feature with real output

**Files:**
- Verify only: `core/engine.py`
- Verify only: `testing/test_config_loader.py`
- Verify only: `testing/test_engine_order_acceptance.py`

- [ ] **Step 1: Run the focused unittest coverage**

Run: `python3 -m unittest testing.test_config_loader testing.test_engine_order_acceptance`
Expected: PASS.

- [ ] **Step 2: Run Python diagnostics for changed files**

Run the available diagnostics/type checks for the modified Python files and confirm zero new issues.

- [ ] **Step 3: Run a manual runtime-style scenario**

Execute a small Python scenario that enters and exits a position, then print the generated `recent_trades.txt` content.
Expected: The file exists and shows a readable trade summary plus structured payload for later analysis.
