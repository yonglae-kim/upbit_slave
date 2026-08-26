#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.8"
# dependencies = ["openpyxl"]
# ///

# ─── How to run ───
# py -3.8 -B -m testing.cross_sectional_contrarian_runner --help
# ──────────────────

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from math import isfinite
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple, TypedDict, Union
from zipfile import BadZipFile

from openpyxl.utils.exceptions import InvalidFileException

from testing.cross_sectional_contrarian_evaluation import (
    CANDIDATE,
    MARKETS,
    AlignedMarketData,
    BacktestResult,
    Candle,
    ContrarianConfig,
    EvaluationInputError,
    EvaluationWindow,
    TradeRecord,
    align_series,
    validate_manifest,
    run_portfolio,
)
from testing.cross_sectional_momentum_runner import _load_market


class MarketMetric(TypedDict):
    trades: int
    winning_trades: int
    total_return_pct: float
    average_portfolio_return_pct: float
    win_rate_pct: float


def _parse_utc(raw: str) -> datetime:
    """Parse a CLI timestamp and normalize it to UTC."""
    try:
        value = raw.strip().replace("Z", "+00:00")
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError) as error:
        raise EvaluationInputError("invalid UTC timestamp: " + raw) from error
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _validate_loaded_candles(market: str, candles: Tuple[Candle, ...]) -> Tuple[str, Tuple[Candle, ...]]:
    """Accept only finite, positive candles whose low does not exceed close."""
    for candle in candles:
        if (
            not isfinite(candle.close)
            or not isfinite(candle.low)
            or candle.close <= 0.0
            or candle.low <= 0.0
            or candle.low > candle.close
        ):
            raise EvaluationInputError("invalid candle values: " + market)
    return market, candles


def _load_data(manifest: Path) -> AlignedMarketData:
    """Validate the manifest, load real candles, and intersect timestamps."""
    entries = validate_manifest(manifest)
    loaded: List[Tuple[str, Tuple[Candle, ...]]] = []
    for market, source in entries:
        try:
            loaded.append(_validate_loaded_candles(*_load_market(market, source)))
        except EvaluationInputError:
            raise
        except (OSError, BadZipFile, InvalidFileException, KeyError, TypeError, ValueError) as error:
            raise EvaluationInputError("invalid workbook: " + market) from error
    return align_series(tuple(loaded))


def _iso(value: datetime) -> str:
    """Serialize an aware timestamp as a UTC ISO value."""
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha256(path: Path) -> str:
    """Hash the exact manifest bytes used for this evaluation."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _market_metrics(result: BacktestResult) -> Dict[str, MarketMetric]:
    """Build independent per-market metrics from the complete trade stream."""
    metrics: Dict[str, MarketMetric] = {}
    for market in MARKETS:
        records = tuple(record for record in result.trade_records if record.market == market)
        equity = 1.0
        for record in records:
            equity *= 1.0 + record.portfolio_return
        winning = sum(record.net_return > 0.0 for record in records)
        metrics[market] = {
            "trades": len(records),
            "winning_trades": winning,
            "total_return_pct": (equity - 1.0) * 100.0,
            "average_portfolio_return_pct": (
                sum(record.portfolio_return for record in records) / len(records) * 100.0
                if records
                else 0.0
            ),
            "win_rate_pct": winning / len(records) * 100.0 if records else 0.0,
        }
    return metrics


def _trade_payload(trade: TradeRecord) -> Dict[str, Union[str, float, int]]:
    """Serialize every decision, execution, and return field in one trade."""
    return {
        "market": trade.market,
        "entry_time": _iso(trade.entry_time),
        "exit_time": _iso(trade.exit_time),
        "entry_price": trade.entry_price,
        "exit_price": trade.exit_price,
        "exit_reason": trade.exit_reason,
        "selected_return": trade.selected_return,
        "btc_return": trade.btc_return,
        "breadth_positive": trade.breadth_positive,
        "gross_return_pct": trade.gross_return * 100.0,
        "net_return_pct": trade.net_return * 100.0,
        "portfolio_return_pct": trade.portfolio_return * 100.0,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Evaluation-only contrarian bounce backtest")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--window-start", required=True)
    parser.add_argument("--window-end", required=True)
    parser.add_argument("--momentum-lookback", type=int, default=36)
    parser.add_argument("--hold-bars", type=int, default=48)
    parser.add_argument("--btc-gate-lookback", type=int, default=72)
    parser.add_argument("--btc-gate-threshold", type=float, default=0.0)
    parser.add_argument("--breadth-min", type=int, default=5)
    parser.add_argument("--selected-return-max", type=float, default=-0.005)
    parser.add_argument("--stop-loss-pct", type=float, default=0.03)
    parser.add_argument("--exposure", type=float, default=0.50)
    parser.add_argument("--fee", type=float, default=0.0005)
    parser.add_argument("--spread", type=float, default=0.0003)
    parser.add_argument("--slippage", type=float, default=0.0002)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Run the candidate offline and write a machine-readable evaluation JSON."""
    args = _parser().parse_args(argv)
    manifest = args.manifest.resolve()
    window = EvaluationWindow(_parse_utc(args.window_start), _parse_utc(args.window_end))
    config = ContrarianConfig(
        momentum_lookback=args.momentum_lookback,
        hold_bars=args.hold_bars,
        btc_gate_lookback=args.btc_gate_lookback,
        btc_gate_threshold=args.btc_gate_threshold,
        breadth_min=args.breadth_min,
        selected_return_max=args.selected_return_max,
        stop_loss_pct=args.stop_loss_pct,
        exposure=args.exposure,
        fee=args.fee,
        spread=args.spread,
        slippage=args.slippage,
    )
    data = _load_data(manifest)
    result = run_portfolio(data, config, window)
    payload = {
        "candidate": CANDIDATE,
        "evaluation_only": True,
        "windows": {
            "convention": "half_open_utc",
            "start": _iso(window.start),
            "end": _iso(window.end),
        },
        "parameters": {
            "momentum_lookback": config.momentum_lookback,
            "hold_bars": config.hold_bars,
            "btc_gate_lookback": config.btc_gate_lookback,
            "btc_gate_threshold": config.btc_gate_threshold,
            "breadth_min": config.breadth_min,
            "selected_return_max": config.selected_return_max,
            "stop_loss_pct": config.stop_loss_pct,
            "exposure": config.exposure,
        },
        "cost_model": {
            "fee": config.fee,
            "spread": config.spread,
            "slippage": config.slippage,
            "one_side_cost": config.one_side_cost,
            "two_sided_flat_cost": 1.0 - (1.0 - config.one_side_cost) / (1.0 + config.one_side_cost),
        },
        "manifest_sha256": _sha256(manifest),
        "integrity": {
            "fixed_universe": data.markets == MARKETS,
            "markets": list(data.markets),
            "common_timestamp_rows": len(data.timestamps),
            "synthetic_rows": 0,
            "forward_fill": False,
            "real_ohlc_low_stop": True,
        },
        "aggregate": {
            "total_return_pct": result.total_return * 100.0,
            "max_drawdown_pct": result.max_drawdown * 100.0,
            "trades": result.trades,
            "winning_trades": result.winning_trades,
            "win_rate_pct": result.winning_trades / result.trades * 100.0 if result.trades else 0.0,
        },
        "per_market": _market_metrics(result),
        "trades": [_trade_payload(trade) for trade in result.trade_records],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except EvaluationInputError as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1)
