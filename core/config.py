from dataclasses import dataclass, field


@dataclass
class TradingConfig:
    do_not_trading: list[str]
    mode: str = "live"
    paper_initial_krw: float = 1_000_000
    fee_rate: float = 0.0005
    min_order_krw: int = 5000
    max_holdings: int = 4
    buy_divisor: int = 5
    min_buyable_krw: int = 20000
    risk_per_trade_pct: float = 0.1
    max_daily_loss_pct: float = 0.05
    max_consecutive_losses: int = 3
    max_concurrent_positions: int = 4
    trailing_stop_pct: float = 0.01
    max_order_retries: int = 2
    partial_fill_timeout_scale: float = 0.5
    partial_fill_reduce_ratio: float = 0.5
    timeout_retry_cooldown_seconds: float = 5.0
    candle_interval: int = 3
    macd_n_fast: int = 12
    macd_n_slow: int = 26
    macd_n_signal: int = 9
    min_candle_extra: int = 3
    buy_rsi_threshold: int = 35
    sell_profit_threshold: float = 1.01
    stop_loss_threshold: float = 0.975
    ws_data_format: str = "SIMPLE"
    krw_markets: list[str] = field(default_factory=list)
    universe_top_n1: int = 30
    universe_watch_n2: int = 10
    max_relative_spread: float = 0.003
    max_candle_missing_rate: float = 0.1
    sr_pivot_left: int = 2
    sr_pivot_right: int = 2
    sr_cluster_band_pct: float = 0.0025
    sr_min_touches: int = 2
    sr_lookback_bars: int = 120
    zone_priority_mode: str = "intersection"
    fvg_atr_period: int = 14
    fvg_min_width_atr_mult: float = 0.2
    fvg_min_width_ticks: int = 2
    displacement_min_body_ratio: float = 0.6
    displacement_min_atr_mult: float = 1.2
    ob_lookback_bars: int = 80
    ob_max_base_bars: int = 6
    zone_expiry_bars_5m: int = 36
    zone_reentry_buffer_pct: float = 0.0005
    trigger_rejection_wick_ratio: float = 0.35
    trigger_breakout_lookback: int = 3
    min_candles_1m: int = 80
    min_candles_5m: int = 120
    min_candles_15m: int = 120

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
            sr_pivot_left=self.sr_pivot_left,
            sr_pivot_right=self.sr_pivot_right,
            sr_cluster_band_pct=self.sr_cluster_band_pct,
            sr_min_touches=self.sr_min_touches,
            sr_lookback_bars=self.sr_lookback_bars,
            zone_priority_mode=self.zone_priority_mode,
            fvg_atr_period=self.fvg_atr_period,
            fvg_min_width_atr_mult=self.fvg_min_width_atr_mult,
            fvg_min_width_ticks=self.fvg_min_width_ticks,
            displacement_min_body_ratio=self.displacement_min_body_ratio,
            displacement_min_atr_mult=self.displacement_min_atr_mult,
            ob_lookback_bars=self.ob_lookback_bars,
            ob_max_base_bars=self.ob_max_base_bars,
            zone_expiry_bars_5m=self.zone_expiry_bars_5m,
            zone_reentry_buffer_pct=self.zone_reentry_buffer_pct,
            trigger_rejection_wick_ratio=self.trigger_rejection_wick_ratio,
            trigger_breakout_lookback=self.trigger_breakout_lookback,
            min_candles_1m=self.min_candles_1m,
            min_candles_5m=self.min_candles_5m,
            min_candles_15m=self.min_candles_15m,
        )
