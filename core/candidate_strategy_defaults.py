from __future__ import annotations

CANDIDATE_V1_PROOF_WINDOW_DEFAULTS: dict[str, int | float | str] = {
    "proof_window_max_bars": 3,
    "proof_window_promotion_threshold_r": 0.35,
    "proof_window_cooldown_hint_bars": 0,
    "proof_window_symbol_profile": "default",
}

CANDIDATE_V1_SYMBOL_PROOF_WINDOW_DEFAULTS: dict[str, dict[str, int | float | str]] = {
    "KRW-XRP": {
        "proof_window_promotion_threshold_r": 0.45,
        "proof_window_cooldown_hint_bars": 1,
        "proof_window_symbol_profile": "guarded",
    },
    "KRW-ADA": {
        "proof_window_max_bars": 2,
        "proof_window_promotion_threshold_r": 0.65,
        "proof_window_cooldown_hint_bars": 3,
        "proof_window_symbol_profile": "weak",
    },
}


def candidate_v1_proof_window_defaults(symbol: str) -> dict[str, int | float | str]:
    resolved_symbol = str(symbol or "").strip().upper()
    defaults = dict(CANDIDATE_V1_PROOF_WINDOW_DEFAULTS)
    symbol_defaults = CANDIDATE_V1_SYMBOL_PROOF_WINDOW_DEFAULTS.get(resolved_symbol)
    if symbol_defaults:
        defaults.update(symbol_defaults)
    return defaults
