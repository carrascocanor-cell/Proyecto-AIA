"""Lectura y análisis descriptivo de precios históricos."""

import csv
import math
from datetime import date
from pathlib import Path


def load_close_prices(csv_path: str | Path) -> list[float]:
    """Carga precios de cierre diarios y valida fechas y valores."""
    prices = []
    previous_date = None

    with Path(csv_path).open(encoding="utf-8-sig", newline="") as csv_file:
        reader = csv.DictReader(csv_file)
        required_columns = {"date", "close"}
        if reader.fieldnames is None or not required_columns.issubset(reader.fieldnames):
            raise ValueError("El CSV debe incluir las columnas 'date' y 'close'.")

        for row in reader:
            row_number = reader.line_num
            try:
                row_date = date.fromisoformat(row["date"])
            except (TypeError, ValueError) as error:
                raise ValueError(
                    f"Fecha no válida en la fila {row_number}; usa YYYY-MM-DD."
                ) from error

            if previous_date is not None and row_date <= previous_date:
                raise ValueError(
                    f"Las fechas deben estar en orden ascendente y sin duplicados "
                    f"(fila {row_number})."
                )
            previous_date = row_date

            try:
                close = float(row["close"])
            except (TypeError, ValueError) as error:
                raise ValueError(
                    f"Precio de cierre no válido en la fila {row_number}."
                ) from error

            if not math.isfinite(close) or close <= 0:
                raise ValueError(
                    f"El precio de cierre debe ser un número positivo y finito "
                    f"(fila {row_number})."
                )
            prices.append(close)

    if not prices:
        raise ValueError("El CSV no contiene observaciones de precios.")

    return prices


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
