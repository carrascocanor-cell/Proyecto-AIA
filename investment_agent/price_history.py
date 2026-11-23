"""Lectura validada de historiales CSV de fecha y cierre."""

import csv
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
import hashlib
import io
from pathlib import Path


@dataclass(frozen=True)
class PriceBar:
    """Un cierre diario con su fecha de calendario."""

    date: date
    close: Decimal


def _parse_price_history(text: str) -> list[PriceBar]:
    bars = []
    previous_date = None

    reader = csv.DictReader(io.StringIO(text, newline=""))
    required_columns = {"date", "close"}
    if reader.fieldnames is None or not required_columns.issubset(reader.fieldnames):
        raise ValueError("El CSV debe incluir las columnas 'date' y 'close'.")

    for row in reader:
        row_number = reader.line_num
        try:
            bar_date = date.fromisoformat(row["date"])
        except (TypeError, ValueError) as error:
            raise ValueError(
                f"Fecha no válida en la fila {row_number}; usa YYYY-MM-DD."
            ) from error

        if previous_date is not None and bar_date <= previous_date:
            raise ValueError(
                f"Las fechas deben estar en orden ascendente y sin duplicados "
                f"(fila {row_number})."
            )
        previous_date = bar_date

        try:
            close = Decimal(row["close"])
        except (InvalidOperation, TypeError, ValueError) as error:
            raise ValueError(
                f"Precio de cierre no válido en la fila {row_number}."
            ) from error

        if not close.is_finite() or close <= 0:
            raise ValueError(
                f"El precio de cierre debe ser un número positivo y finito "
                f"(fila {row_number})."
            )
        bars.append(PriceBar(bar_date, close))

    if not bars:
        raise ValueError("El CSV no contiene observaciones de precios.")

    return bars


def load_price_history(csv_path: str | Path) -> list[PriceBar]:
    """Carga cierres positivos y fechas ascendentes desde un CSV."""
    text = Path(csv_path).read_bytes().decode("utf-8-sig")
    return _parse_price_history(text)


def load_price_history_with_hash(
    csv_path: str | Path,
) -> tuple[list[PriceBar], str]:
    """Carga el historial y su SHA-256 desde los mismos bytes leídos."""
    content = Path(csv_path).read_bytes()
    digest = hashlib.sha256(content).hexdigest()
    text = content.decode("utf-8-sig")
    return _parse_price_history(text), digest
