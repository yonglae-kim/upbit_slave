from __future__ import annotations

from dataclasses import dataclass, field


ZONE_PROFILE_OVERRIDES: dict[str, dict[str, int | float]] = {
    "conservative": {
        "fvg_min_width_atr_mult": 0.28,
        "displacement_min_atr_mult": 1.45,
        "zone_expiry_bars_5m": 24,
    },
    "balanced": {},
    "aggressive": {
        "fvg_min_width_atr_mult": 0.16,
        "displacement_min_atr_mult": 1.0,
        "zone_expiry_bars_5m": 48,
    },
    "krw_eth_relaxed": {
        "fvg_min_width_atr_mult": 0.14,
        "displacement_min_atr_mult": 0.95,
        "zone_expiry_bars_5m": 60,
    },
}


REGIME_STRATEGY_PARAM_OVERRIDES: dict[str, dict[str, int | float]] = {
    "strong_trend": {
        "rsi_long_threshold": 27.0,
        "bb_std": 2.2,
        "required_trigger_count": 2,
        "entry_score_threshold": 3.1,
        "take_profit_r": 2.6,
    },
    "weak_trend": {
        "rsi_long_threshold": 30.0,
        "bb_std": 2.0,
        "required_trigger_count": 1,
        "entry_score_threshold": 2.8,
        "take_profit_r": 2.0,
    },
    "sideways": {
        "rsi_long_threshold": 34.0,
        "bb_std": 1.8,
        "required_trigger_count": 1,
        "entry_score_threshold": 2.7,
        "take_profit_r": 1.6,
    },
}


ENTRY_EXPERIMENT_PROFILE_OVERRIDES: dict[str, dict[str, bool | int | float]] = {
    "baseline": {},
    "neckline_confirmed": {
        "require_neckline_break": True,
    },
}


REENTRY_COOLDOWN_PROFILE_OVERRIDES: dict[str, dict[str, bool]] = {
    "legacy": {
        "cooldown_on_loss_exits_only": False,
    },
    "loss_exit_guarded": {
        "cooldown_on_loss_exits_only": True,
    },
}


WALKFORWARD_DEFAULT_UPDATE_CRITERIA: dict[str, float | int] = {
    "min_oos_trades": 8,
    "min_oos_win_rate": 38.0,
    "max_overfit_gap_pct": 40.0,
    "max_efficiency_gap": 1.2,
}


@dataclass
class TradingConfig:
    do_not_trading: list[str]
    mode: str = "live"
    paper_initial_krw: float = 1_000_000
    fee_rate: float = 0.0005
    min_order_krw: int = 5000
    max_holdings: int = 1
    buy_divisor: int = 5
    position_sizing_mode: str = "risk_first"
    max_order_krw_by_cash_management: int = 0
    # Dynamic cash buffer used for pre-entry short-circuit.
    # Effective threshold is max(min_order_krw, min_buyable_krw).
    min_buyable_krw: int = 0
    risk_per_trade_pct: float = 0.1
    max_daily_loss_pct: float = 0.05
    max_consecutive_losses: int = 3
    max_concurrent_positions: int = 1
    max_correlated_positions: int = 2
    correlation_groups: dict[str, str] = field(default_factory=dict)
    trailing_stop_pct: float = 0.01
    partial_take_profit_threshold: float = 1.02
    partial_take_profit_ratio: float = 0.5
    partial_stop_loss_ratio: float = 1.0
    trailing_requires_breakeven: bool = True
    trailing_activation_bars: int = 0
    exit_mode: str = "atr"
    atr_period: int = 14
    atr_stop_mult: float = 1.4
    atr_trailing_mult: float = 2.0
    swing_lookback: int = 5
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
    sell_requires_profit: bool = False
    stop_loss_threshold: float = 0.975
    ws_data_format: str = "SIMPLE"
    krw_markets: list[str] = field(default_factory=list)
    universe_top_n1: int = 30
    universe_watch_n2: int = 10
    low_spec_watch_cap_n2: int = 10
    max_relative_spread: float = 0.003
    max_candle_missing_rate: float = 0.1
    market_damping_enabled: bool = False
    market_damping_max_spread: float = 0.003
    market_damping_min_trade_value_24h: float = 10_000_000_000
    market_damping_atr_period: int = 14
    market_damping_max_atr_ratio: float = 0.03
    sr_pivot_left: int = 2
    sr_pivot_right: int = 2
    sr_cluster_band_pct: float = 0.0025
    sr_min_touches: int = 2
    sr_lookback_bars: int = 120
    sr_touch_weight: float = 0.5
    sr_recency_weight: float = 0.3
    sr_volume_weight: float = 0.2
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
    trigger_zone_lookback: int = 5
    trigger_confirm_lookback: int = 3
    trigger_mode: str = "adaptive"
    min_candles_1m: int = 80
    min_candles_5m: int = 30
    min_candles_15m: int = 40
    regime_filter_enabled: bool = True
    regime_ema_fast: int = 50
    regime_ema_slow: int = 200
    regime_adx_period: int = 14
    regime_adx_min: float = 18.0
    regime_slope_lookback: int = 3
    zone_profile: str = "aggressive"
    reentry_cooldown_profile: str = "loss_exit_guarded"
    reentry_cooldown_bars: int = 10
    reentry_cooldown_bars_by_regime: dict[str, int] = field(default_factory=lambda: {"sideways": 14})
    cooldown_on_loss_exits_only: bool = True
    reentry_dynamic_cooldown_enabled: bool = True
    reentry_dynamic_cooldown_lookback_bars: int = 20
    reentry_dynamic_cooldown_atr_period: int = 14
    reentry_dynamic_cooldown_base_atr_ratio: float = 0.008
    reentry_dynamic_cooldown_scale: float = 2.5
    reentry_dynamic_cooldown_max_extra_bars: int = 8
    strategy_name: str = "sr_ob_fvg"
    rsi_period: int = 14
    rsi_long_threshold: float = 30.0
    rsi_neutral_filter_enabled: bool = True
    rsi_neutral_low: float = 45.0
    rsi_neutral_high: float = 55.0
    bb_period: int = 20
    bb_std: float = 2.0
    bb_touch_mode: str = "touch_or_break"
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9
    macd_histogram_filter_enabled: bool = True
    engulfing_strict: bool = True
    engulfing_include_wick: bool = False
    consecutive_bearish_count: int = 3
    pivot_left: int = 3
    pivot_right: int = 3
    double_bottom_lookback_bars: int = 40
    double_bottom_tolerance_pct: float = 0.5
    require_band_reentry_on_second_bottom: bool = True
    require_neckline_break: bool = False
    divergence_signal_enabled: bool = True
    entry_score_threshold: float = 2.5
    rsi_oversold_weight: float = 1.0
    bb_touch_weight: float = 1.0
    divergence_weight: float = 0.8
    macd_cross_weight: float = 0.8
    engulfing_weight: float = 1.0
    band_deviation_weight: float = 0.8
    quality_score_low_threshold: float = 0.35
    quality_score_high_threshold: float = 0.7
    quality_multiplier_low: float = 0.7
    quality_multiplier_mid: float = 1.0
    quality_multiplier_high: float = 1.15
    quality_multiplier_min_bound: float = 0.7
    quality_multiplier_max_bound: float = 1.2
    entry_mode: str = "close"
    stop_mode_long: str = "swing_low"
    take_profit_r: float = 2.0
    partial_take_profit_enabled: bool = False
    partial_take_profit_r: float = 1.0
    partial_take_profit_size: float = 0.5
    move_stop_to_breakeven_after_partial: bool = True
    max_hold_bars: int = 0
    strategy_cooldown_bars: int = 0
    entry_experiment_profile: str = "baseline"

    def regime_strategy_overrides(self, regime: str) -> dict[str, int | float]:
        key = str(regime or "").strip().lower()
        return dict(REGIME_STRATEGY_PARAM_OVERRIDES.get(key, {}))

    def reentry_cooldown_profile_overrides(self) -> dict[str, bool]:
        key = str(self.reentry_cooldown_profile or "legacy").strip().lower()
        overrides = REENTRY_COOLDOWN_PROFILE_OVERRIDES.get(key)
        if overrides is None:
            valid_profiles = ", ".join(sorted(REENTRY_COOLDOWN_PROFILE_OVERRIDES))
            raise ValueError(f"unknown reentry_cooldown_profile '{key}'. valid: {valid_profiles}")
        return dict(overrides)

    @property
    def min_effective_buyable_krw(self) -> int:
        return max(int(self.min_order_krw), int(self.min_buyable_krw))

    def to_strategy_params(
        self,
        *,
        zone_profile: str | None = None,
        zone_overrides: dict[str, int | float] | None = None,
    ):
        from core.strategy import StrategyParams

        profile_name = (zone_profile or self.zone_profile or "balanced").strip().lower()
        profile_overrides = ZONE_PROFILE_OVERRIDES.get(profile_name)
        if profile_overrides is None:
            valid_profiles = ", ".join(sorted(ZONE_PROFILE_OVERRIDES))
            raise ValueError(f"unknown zone_profile '{profile_name}'. valid: {valid_profiles}")

        runtime_overrides = {k: v for k, v in (zone_overrides or {}).items() if v is not None}
        experiment_profile_name = (self.entry_experiment_profile or "baseline").strip().lower()
        experiment_profile_overrides = ENTRY_EXPERIMENT_PROFILE_OVERRIDES.get(experiment_profile_name)
        if experiment_profile_overrides is None:
            valid_profiles = ", ".join(sorted(ENTRY_EXPERIMENT_PROFILE_OVERRIDES))
            raise ValueError(f"unknown entry_experiment_profile '{experiment_profile_name}'. valid: {valid_profiles}")

        base_params = {

            "buy_rsi_threshold": self.buy_rsi_threshold,
            "strategy_name": self.strategy_name,
            "rsi_period": self.rsi_period,
            "rsi_long_threshold": self.rsi_long_threshold,
            "rsi_neutral_filter_enabled": self.rsi_neutral_filter_enabled,
            "rsi_neutral_low": self.rsi_neutral_low,
            "rsi_neutral_high": self.rsi_neutral_high,
            "bb_period": self.bb_period,
            "bb_std": self.bb_std,
            "bb_touch_mode": self.bb_touch_mode,
            "macd_fast": self.macd_fast,
            "macd_slow": self.macd_slow,
            "macd_signal": self.macd_signal,
            "macd_histogram_filter_enabled": self.macd_histogram_filter_enabled,
            "engulfing_strict": self.engulfing_strict,
            "engulfing_include_wick": self.engulfing_include_wick,
            "consecutive_bearish_count": self.consecutive_bearish_count,
            "pivot_left": self.pivot_left,
            "pivot_right": self.pivot_right,
            "double_bottom_lookback_bars": self.double_bottom_lookback_bars,
            "double_bottom_tolerance_pct": self.double_bottom_tolerance_pct,
            "require_band_reentry_on_second_bottom": self.require_band_reentry_on_second_bottom,
            "require_neckline_break": self.require_neckline_break,
            "divergence_signal_enabled": self.divergence_signal_enabled,
            "entry_score_threshold": self.entry_score_threshold,
            "rsi_oversold_weight": self.rsi_oversold_weight,
            "bb_touch_weight": self.bb_touch_weight,
            "divergence_weight": self.divergence_weight,
            "macd_cross_weight": self.macd_cross_weight,
            "engulfing_weight": self.engulfing_weight,
            "band_deviation_weight": self.band_deviation_weight,
            "quality_score_low_threshold": self.quality_score_low_threshold,
            "quality_score_high_threshold": self.quality_score_high_threshold,
            "quality_multiplier_low": self.quality_multiplier_low,
            "quality_multiplier_mid": self.quality_multiplier_mid,
            "quality_multiplier_high": self.quality_multiplier_high,
            "entry_mode": self.entry_mode,
            "stop_mode_long": self.stop_mode_long,
            "take_profit_r": self.take_profit_r,
            "partial_take_profit_enabled": self.partial_take_profit_enabled,
            "partial_take_profit_r": self.partial_take_profit_r,
            "partial_take_profit_size": self.partial_take_profit_size,
            "move_stop_to_breakeven_after_partial": self.move_stop_to_breakeven_after_partial,
            "max_hold_bars": self.max_hold_bars,
            "strategy_cooldown_bars": self.strategy_cooldown_bars,
            "macd_n_fast": self.macd_n_fast,
            "macd_n_slow": self.macd_n_slow,
            "macd_n_signal": self.macd_n_signal,
            "min_candle_extra": self.min_candle_extra,
            "sell_profit_threshold": self.sell_profit_threshold,
            "sell_requires_profit": self.sell_requires_profit,
            "stop_loss_threshold": self.stop_loss_threshold,
            "sr_pivot_left": self.sr_pivot_left,
            "sr_pivot_right": self.sr_pivot_right,
            "sr_cluster_band_pct": self.sr_cluster_band_pct,
            "sr_min_touches": self.sr_min_touches,
            "sr_lookback_bars": self.sr_lookback_bars,
            "sr_touch_weight": self.sr_touch_weight,
            "sr_recency_weight": self.sr_recency_weight,
            "sr_volume_weight": self.sr_volume_weight,
            "zone_priority_mode": self.zone_priority_mode,
            "fvg_atr_period": self.fvg_atr_period,
            "fvg_min_width_atr_mult": self.fvg_min_width_atr_mult,
            "fvg_min_width_ticks": self.fvg_min_width_ticks,
            "displacement_min_body_ratio": self.displacement_min_body_ratio,
            "displacement_min_atr_mult": self.displacement_min_atr_mult,
            "ob_lookback_bars": self.ob_lookback_bars,
            "ob_max_base_bars": self.ob_max_base_bars,
            "zone_expiry_bars_5m": self.zone_expiry_bars_5m,
            "zone_reentry_buffer_pct": self.zone_reentry_buffer_pct,
            "trigger_rejection_wick_ratio": self.trigger_rejection_wick_ratio,
            "trigger_breakout_lookback": self.trigger_breakout_lookback,
            "trigger_zone_lookback": self.trigger_zone_lookback,
            "trigger_confirm_lookback": self.trigger_confirm_lookback,
            "trigger_mode": self.trigger_mode,
            "min_candles_1m": self.min_candles_1m,
            "min_candles_5m": self.min_candles_5m,
            "min_candles_15m": self.min_candles_15m,
            "regime_filter_enabled": self.regime_filter_enabled,
            "regime_ema_fast": self.regime_ema_fast,
            "regime_ema_slow": self.regime_ema_slow,
            "regime_adx_period": self.regime_adx_period,
            "regime_adx_min": self.regime_adx_min,
            "regime_slope_lookback": self.regime_slope_lookback,

        }
        base_params.update(profile_overrides)
        base_params.update(experiment_profile_overrides)
        base_params.update(runtime_overrides)
        return StrategyParams(**base_params)
