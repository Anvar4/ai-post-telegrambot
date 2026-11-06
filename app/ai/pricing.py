"""Model narxlari (1M token uchun USD; rasm — bitta rasm uchun). `MODEL_PRICES_JSON` bilan almashtiriladi."""

from __future__ import annotations

from collections.abc import Mapping

Prices = Mapping[str, Mapping[str, float]]

DEFAULT_PRICES: dict[str, dict[str, float]] = {
    # OpenAI (2026-09-22 dan, rasmiy narxlar)
    "gpt-6-sol": {"in": 2.0, "out": 10.0, "cached": 0.20},
    "gpt-6-luna": {"in": 0.10, "out": 0.50, "cached": 0.01},
    "gpt-6-astra": {"in": 10.0, "out": 50.0, "cached": 1.0},
    # Taxminiy qiymatlar — aniq narxni MODEL_PRICES_JSON bilan bering
    "claude-": {"in": 3.0, "out": 15.0, "cached": 0.30},
    "gemini-": {"in": 1.25, "out": 10.0, "cached": 0.125, "image": 0.04},
    "deepseek": {"in": 0.30, "out": 1.20, "cached": 0.03},
    "gpt-image": {"in": 5.0, "out": 40.0, "image": 0.05},
    "imagen": {"image": 0.04},
    "flux": {"image": 0.01},
    "core": {"image": 0.03},
    "_default": {"in": 3.0, "out": 15.0, "cached": 0.30, "image": 0.05},
}


def _lookup(model: str, prices: Prices | None) -> Mapping[str, float]:
    table: dict[str, Mapping[str, float]] = {**DEFAULT_PRICES, **(prices or {})}
    if model in table:
        return table[model]
    keys = sorted((k for k in table if k != "_default"), key=len, reverse=True)
    for key in keys:
        if model.startswith(key):
            return table[key]
    for key in keys:
        if len(key) >= 4 and key in model:
            return table[key]
    return table["_default"]


def cost_usd(
    model: str, input_tokens: int, output_tokens: int, cached_tokens: int = 0, prices: Prices | None = None
) -> float:
    p = _lookup(model, prices)
    price_in = p.get("in", DEFAULT_PRICES["_default"]["in"])
    price_cached = p.get("cached", price_in)
    price_out = p.get("out", DEFAULT_PRICES["_default"]["out"])
    uncached = max(input_tokens - cached_tokens, 0)
    return (uncached * price_in + cached_tokens * price_cached + output_tokens * price_out) / 1_000_000


def image_cost(model: str, prices: Prices | None = None) -> float:
    return _lookup(model, prices).get("image", DEFAULT_PRICES["_default"]["image"])
