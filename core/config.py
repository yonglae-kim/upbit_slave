from dataclasses import dataclass, field


@dataclass
class TradingConfig:
    do_not_trading: list[str]
    fee_rate: float = 0.0005
    min_order_krw: int = 5000
    max_holdings: int = 4
    buy_divisor: int = 5
    min_buyable_krw: int = 20000
    candle_interval: int = 3
    macd_n_fast: int = 12
    macd_n_slow: int = 26
    macd_n_signal: int = 9
    min_candle_extra: int = 3
    buy_rsi_threshold: int = 35
    sell_profit_threshold: float = 1.01
    stop_loss_threshold: float = 0.975
    krw_markets: list[str] = field(default_factory=list)

    def to_strategy_params(self):
        from core.strategy import StrategyParams

        return StrategyParams(
            buy_rsi_threshold=self.buy_rsi_threshold,
            macd_n_fast=self.macd_n_fast,
            macd_n_slow=self.macd_n_slow,
            macd_n_signal=self.macd_n_signal,
            min_candle_extra=self.min_candle_extra,
            sell_profit_threshold=self.sell_profit_threshold,
            stop_loss_threshold=self.stop_loss_threshold,
        )
