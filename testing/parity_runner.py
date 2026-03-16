from __future__ import annotations

import argparse
import json
import math
from dataclasses import replace
from pathlib import Path
from typing import Mapping, Sequence, cast

from core.config import TradingConfig
from core.decision_core import evaluate_market
from core.decision_models import (
    DecisionContext,
    MarketSnapshot,
    PortfolioSnapshot,
    PositionSnapshot,
)
from core.position_policy import PositionOrderPolicy


DEFAULT_FIXTURE_PATH = "testing/fixtures/parity_baseline_cases.json"
DEFAULT_OUTPUT_PATH = "testing/artifacts/candidate_v1_parity.json"


def default_fixture_path_for_strategy(strategy_name: str) -> str:
    normalized = str(strategy_name or "").strip().lower()
    fixture_name = f"parity_{normalized}_cases.json"
    candidate_path = Path("testing/fixtures") / fixture_name
    if normalized and candidate_path.exists():
        return str(candidate_path)
    return DEFAULT_FIXTURE_PATH


class ParityRunner:
    strategy_name: str
    fixture_path: str
    output_path: str

    def __init__(
        self,
        *,
        strategy_name: str,
        fixture_path: str | None = None,
        output_path: str = DEFAULT_OUTPUT_PATH,
    ) -> None:
        self.strategy_name = str(strategy_name)
        self.fixture_path = fixture_path or default_fixture_path_for_strategy(
            self.strategy_name
        )
        self.output_path = output_path

    def run(self) -> dict[str, object]:
        cases = self._load_cases()
        mismatch_rows: list[dict[str, object]] = []
        matched_intent_count = 0
        matched_reason_count = 0
        matched_size_count = 0

        for index, case in enumerate(cases):
            actual = self._evaluate_case(case)
            expected = self._mapping_to_dict(case.get("expected"))

            intent_match = actual["action"] == self._as_str(expected.get("action"))
            reason_match = actual["reason"] == self._as_str(expected.get("reason"))
            size_match = math.isclose(
                self._as_float(actual["size"]),
                self._as_float(expected.get("size")),
                rel_tol=0.0,
                abs_tol=1e-9,
            )

            if intent_match:
                matched_intent_count += 1
            if reason_match:
                matched_reason_count += 1
            if size_match:
                matched_size_count += 1

            if intent_match and reason_match and size_match:
                continue

            mismatch_rows.append(
                {
                    "index": index,
                    "name": self._as_str(case.get("name")) or f"case_{index}",
                    "expected": expected,
                    "actual": actual,
                    "intent_match": intent_match,
                    "reason_match": reason_match,
                    "size_match": size_match,
                }
            )

        artifact: dict[str, object] = {
            "strategy_name": self.strategy_name,
            "snapshot_count": len(cases),
            "matched_intent_count": matched_intent_count,
            "matched_reason_count": matched_reason_count,
            "matched_size_count": matched_size_count,
            "mismatch_rows": mismatch_rows,
            "pass": len(cases) > 0 and len(mismatch_rows) == 0,
        }
        self._write_json(self.output_path, artifact)
        return artifact

    def _load_cases(self) -> list[dict[str, object]]:
        raw = json.loads(Path(self.fixture_path).read_text(encoding="utf-8"))
        if not isinstance(raw, list):
            return []
        return [self._mapping_to_dict(item) for item in raw]

    def _evaluate_case(self, case: dict[str, object]) -> dict[str, object]:
        config = TradingConfig(do_not_trading=[], strategy_name=self.strategy_name)
        params = replace(
            config.to_strategy_params(),
            **self._mapping_to_dict(case.get("strategy_params_overrides")),
        )
        order_policy = PositionOrderPolicy(
            stop_loss_threshold=config.stop_loss_threshold,
            trailing_stop_pct=config.trailing_stop_pct,
            partial_take_profit_threshold=config.partial_take_profit_threshold,
            partial_take_profit_ratio=config.partial_take_profit_ratio,
            partial_stop_loss_ratio=config.partial_stop_loss_ratio,
            exit_mode=config.exit_mode,
            atr_period=config.atr_period,
            atr_stop_mult=config.atr_stop_mult,
            atr_trailing_mult=config.atr_trailing_mult,
            swing_lookback=config.swing_lookback,
        )

        context = DecisionContext(
            strategy_name=self.strategy_name,
            market=self._market_snapshot(self._mapping_to_dict(case.get("market"))),
            position=self._position_snapshot(
                self._mapping_to_dict(case.get("position"))
            ),
            portfolio=self._portfolio_snapshot(
                self._mapping_to_dict(case.get("portfolio"))
            ),
            diagnostics=self._mapping_to_dict(case.get("context_diagnostics")),
        )
        intent = evaluate_market(
            context,
            strategy_params=params,
            order_policy=order_policy,
        )
        return {
            "action": intent.action,
            "reason": intent.reason,
            "size": self._extract_size(intent.action, intent.diagnostics),
        }

    def _market_snapshot(self, payload: dict[str, object]) -> MarketSnapshot:
        return MarketSnapshot(
            symbol=self._as_str(payload.get("symbol")),
            candles_by_timeframe=self._candles_by_timeframe(
                self._mapping_to_dict(payload.get("candles_by_timeframe"))
            ),
            price=self._as_float(payload.get("price")),
            diagnostics=self._mapping_to_dict(payload.get("diagnostics")),
        )

    def _position_snapshot(self, payload: dict[str, object]) -> PositionSnapshot:
        return PositionSnapshot(
            market=self._optional_str(payload.get("market")),
            quantity=self._as_float(payload.get("quantity")),
            entry_price=self._optional_float(payload.get("entry_price")),
            state=self._mapping_to_dict(payload.get("state")),
        )

    def _portfolio_snapshot(self, payload: dict[str, object]) -> PortfolioSnapshot:
        return PortfolioSnapshot(
            available_krw=self._as_float(payload.get("available_krw")),
            open_positions=self._as_int(payload.get("open_positions")),
            state=self._mapping_to_dict(payload.get("state")),
        )

    def _candles_by_timeframe(
        self, payload: dict[str, object]
    ) -> dict[str, list[dict[str, object]]]:
        resolved: dict[str, list[dict[str, object]]] = {}
        for timeframe, value in payload.items():
            key = self._as_str(timeframe)
            if isinstance(value, list):
                resolved[key] = [self._mapping_to_dict(row) for row in value]
                continue
            spec = self._mapping_to_dict(value)
            series_name = self._as_str(spec.get("series")).strip().lower()
            if series_name == "linear_ohlc":
                resolved[key] = self._linear_ohlc(spec)
            elif series_name == "step_path_ohlc":
                resolved[key] = self._step_path_ohlc(spec)
            else:
                resolved[key] = []
        return resolved

    def _linear_ohlc(self, spec: dict[str, object]) -> list[dict[str, object]]:
        count = max(0, self._as_int(spec.get("count")))
        candles_oldest: list[dict[str, object]] = []
        for index in range(count):
            candles_oldest.append(
                {
                    "opening_price": self._as_float(spec.get("open_start"))
                    + (index * self._as_float(spec.get("open_step"))),
                    "high_price": self._as_float(spec.get("high_start"))
                    + (index * self._as_float(spec.get("high_step"))),
                    "low_price": self._as_float(spec.get("low_start"))
                    + (index * self._as_float(spec.get("low_step"))),
                    "trade_price": self._as_float(spec.get("close_start"))
                    + (index * self._as_float(spec.get("close_step"))),
                }
            )
        candles_oldest.reverse()
        return candles_oldest

    def _step_path_ohlc(self, spec: dict[str, object]) -> list[dict[str, object]]:
        steps = [self._as_float(value) for value in self._sequence(spec.get("steps"))]
        repeat = max(0, self._as_int(spec.get("repeat")))
        price = self._as_float(spec.get("start_price"))
        candles_oldest: list[dict[str, object]] = []
        for step in steps * repeat:
            price += step
            candles_oldest.append(
                {
                    "opening_price": price + self._as_float(spec.get("open_offset")),
                    "high_price": price + self._as_float(spec.get("high_offset")),
                    "low_price": price + self._as_float(spec.get("low_offset")),
                    "trade_price": price,
                }
            )
        candles_oldest.reverse()
        return candles_oldest

    def _extract_size(self, action: str, diagnostics: dict[str, object]) -> float:
        if action == "enter":
            sizing = self._mapping_to_dict(diagnostics.get("sizing"))
            return self._as_float(sizing.get("final_order_krw"))
        return self._as_float(diagnostics.get("qty_ratio"))

    def _write_json(self, path: str, payload: Mapping[str, object]) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
        )

    def _mapping_to_dict(self, value: object) -> dict[str, object]:
        if not isinstance(value, Mapping):
            return {}
        return {
            self._as_str(key): item
            for key, item in cast(Mapping[object, object], value).items()
        }

    def _sequence(self, value: object) -> Sequence[object]:
        if isinstance(value, Sequence) and not isinstance(
            value, (str, bytes, bytearray)
        ):
            return cast(Sequence[object], value)
        return ()

    def _as_float(self, value: object) -> float:
        if isinstance(value, bool):
            return float(value)
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            try:
                return float(value)
            except ValueError:
                return 0.0
        return 0.0

    def _as_int(self, value: object) -> int:
        if isinstance(value, bool):
            return int(value)
        if isinstance(value, int):
            return value
        if isinstance(value, float):
            return int(value)
        if isinstance(value, str):
            try:
                return int(float(value))
            except ValueError:
                return 0
        return 0

    def _as_str(self, value: object) -> str:
        if value is None:
            return ""
        return str(value)

    def _optional_float(self, value: object) -> float | None:
        if value is None:
            return None
        return self._as_float(value)

    def _optional_str(self, value: object) -> str | None:
        if value is None:
            return None
        return self._as_str(value)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Replay approved parity fixtures")
    _ = parser.add_argument("--strategy", default="baseline")
    _ = parser.add_argument("--fixture", default=None)
    _ = parser.add_argument("--output", default=DEFAULT_OUTPUT_PATH)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    artifact = ParityRunner(
        strategy_name=str(args.strategy),
        fixture_path=None if args.fixture in (None, "") else str(args.fixture),
        output_path=str(args.output),
    ).run()
    print(f"saved parity artifact: {args.output} pass={artifact['pass']}")


if __name__ == "__main__":
    main()
