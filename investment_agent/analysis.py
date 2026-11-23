"""Lectura y análisis descriptivo de precios históricos."""

import math
from pathlib import Path

from investment_agent.price_history import load_price_history


def load_close_prices(csv_path: str | Path) -> list[float]:
    """Carga precios de cierre diarios y valida fechas y valores."""
    return [float(bar.close) for bar in load_price_history(csv_path)]


def analyze_prices(prices: list[float], window: int = 20) -> dict[str, float | int | str | None]:
    """Calcula el cambio del periodo y compara el último precio con su media móvil."""
    if window < 1:
        raise ValueError("La ventana debe ser un entero positivo.")
    if not prices:
        raise ValueError("Se necesita al menos un precio para realizar el análisis.")
    if any(not math.isfinite(price) or price <= 0 for price in prices):
        raise ValueError("Todos los precios deben ser números positivos y finitos.")

    period_return_pct = None
    if len(prices) > 1:
        period_return_pct = (prices[-1] / prices[0] - 1) * 100

    if len(prices) < window:
        moving_average = None
        trend = "insufficient_data"
    else:
        moving_average = sum(prices[-window:]) / window
        if prices[-1] > moving_average:
            trend = "above"
        elif prices[-1] < moving_average:
            trend = "below"
        else:
            trend = "at"

    return {
        "observations": len(prices),
        "period_return_pct": period_return_pct,
        "moving_average": moving_average,
        "window": window,
        "trend": trend,
    }
