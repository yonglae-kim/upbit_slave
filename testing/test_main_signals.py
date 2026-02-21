import importlib
import sys
import types
import unittest
from unittest.mock import patch


class FakeWindow:
    def __init__(self, values):
        self._values = list(values)

    def isna(self):
        return FakeBoolWindow([value != value for value in self._values])

    @property
    def iloc(self):
        return self

    def __getitem__(self, index):
        return self._values[index]


class FakeBoolWindow:
    def __init__(self, values):
        self._values = values

    def any(self):
        return any(self._values)


class FakeSeries:
    def __init__(self, values):
        self._values = list(values)

    def __len__(self):
        return len(self._values)

    @property
    def iloc(self):
        return self

    def __getitem__(self, key):
        if isinstance(key, slice):
            return FakeWindow(self._values[key])
        return self._values[key]


class FakeMacdFrame:
    def __init__(self, macd_values, macd_diff_values):
        self._map = {
            "MACD": FakeSeries(macd_values),
            "MACDDiff": FakeSeries(macd_diff_values),
        }

    def __getitem__(self, key):
        return self._map[key]


class MainSignalValidationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fake_strategy_pkg = types.ModuleType("strategy")
        fake_strategy_module = types.SimpleNamespace(rsi=lambda _data: 20, macd=lambda _data, **_kwargs: None)
        fake_strategy_pkg.strategy = fake_strategy_module

        fake_message_pkg = types.ModuleType("message")
        fake_tele_module = types.SimpleNamespace(sendMessage=lambda *_args, **_kwargs: None)
        fake_message_pkg.tele = fake_tele_module

        sys.modules["apis"] = types.SimpleNamespace()
        sys.modules["message"] = fake_message_pkg
        sys.modules["message.tele"] = fake_tele_module
        sys.modules["slave_constants"] = types.SimpleNamespace(DO_NOT_TRADING=[])
        sys.modules["strategy"] = fake_strategy_pkg
        sys.modules["strategy.strategy"] = fake_strategy_module

        cls.main = importlib.import_module("main")

    @classmethod
    def tearDownClass(cls):
        for module_name in [
            "main",
            "apis",
            "message",
            "message.tele",
            "slave_constants",
            "strategy",
            "strategy.strategy",
        ]:
            sys.modules.pop(module_name, None)

    @staticmethod
    def _build_candles(length, trade_price=100.0):
        return [{"trade_price": float(trade_price)} for _ in range(length)]

    def test_check_buy_returns_false_for_boundary_lengths(self):
        for length in [0, 1, 2]:
            with self.subTest(length=length):
                self.assertFalse(self.main.check_buy(self._build_candles(length)))

    def test_check_sell_returns_false_for_boundary_lengths(self):
        for length in [0, 1, 2]:
            with self.subTest(length=length):
                self.assertFalse(self.main.check_sell(self._build_candles(length), avg_buy_price=100.0))

    def test_check_buy_returns_false_when_latest_macd_or_macd_diff_is_nan(self):
        candles = self._build_candles(40, trade_price=100.0)
        macd_with_nan = FakeMacdFrame(
            macd_values=[0.1] * 37 + [0.2, 0.3, float("nan")],
            macd_diff_values=[0.1] * 39 + [0.2],
        )

        with patch.object(self.main.st, "rsi", return_value=20), patch.object(
            self.main.st, "macd", return_value=macd_with_nan
        ):
            self.assertFalse(self.main.check_buy(candles))

    def test_check_sell_returns_false_when_latest_macd_diff_is_nan(self):
        candles = self._build_candles(40, trade_price=102.0)
        macd_with_nan = FakeMacdFrame(
            macd_values=[0.1] * 40,
            macd_diff_values=[0.2] * 37 + [0.1, 0.05, float("nan")],
        )

        with patch.object(self.main.st, "macd", return_value=macd_with_nan):
            self.assertFalse(self.main.check_sell(candles, avg_buy_price=100.0))


if __name__ == "__main__":
    unittest.main()
