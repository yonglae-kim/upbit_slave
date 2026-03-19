from __future__ import annotations

CANDIDATE_V1_PROOF_WINDOW_DEFAULTS: dict[str, int | float | str] = {
    "proof_window_max_bars": 3,
    "proof_window_promotion_threshold_r": 0.35,
    "proof_window_cooldown_hint_bars": 0,
    "proof_window_symbol_profile": "default",
}


def candidate_v1_proof_window_defaults(symbol: str) -> dict[str, int | float | str]:
    _ = symbol
    return dict(CANDIDATE_V1_PROOF_WINDOW_DEFAULTS)
