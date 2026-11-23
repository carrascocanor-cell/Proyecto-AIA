"""Descarga velas diarias cerradas de BTC/USD desde el endpoint público Kraken."""

import argparse
import csv
import json
import math
import os
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


KRAKEN_OHLC_URL = "https://api.kraken.com/0/public/OHLC"
PAIR = "XBTUSD"
INTERVAL_MINUTES = 1440
DEFAULT_OUTPUT = Path("data") / "crypto" / "kraken_xbtusd_1d.csv"
REQUEST_TIMEOUT_SECONDS = 10


class KrakenDataError(Exception):
    """Error de conexión, respuesta o escritura de datos de Kraken."""


def _positive_number(value: object, field: str, candle_number: int) -> float:
    if isinstance(value, bool):
        raise KrakenDataError(
            f"Valor no válido para {field} en la vela {candle_number}."
        )
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as error:
        raise KrakenDataError(
            f"Valor no válido para {field} en la vela {candle_number}."
        ) from error
    if not math.isfinite(number) or number <= 0:
        raise KrakenDataError(
            f"{field} debe ser positivo y finito en la vela {candle_number}."
        )
    return number


def parse_ohlc_response(payload: object) -> list[tuple[date, float]]:
    """Valida la respuesta y devuelve cierres diarios, excluyendo la última vela."""
    if not isinstance(payload, dict):
        raise KrakenDataError("La respuesta de Kraken debe ser un objeto JSON.")

    errors = payload.get("error")
    if not isinstance(errors, list):
        raise KrakenDataError("La respuesta de Kraken no contiene una lista de errores.")
    if errors:
        raise KrakenDataError(f"Kraken devolvió errores: {', '.join(map(str, errors))}")

    result = payload.get("result")
    if not isinstance(result, dict):
        raise KrakenDataError("La respuesta de Kraken no contiene un resultado válido.")
    last_cursor = result.get("last")
    if isinstance(last_cursor, bool) or not isinstance(last_cursor, int):
        raise KrakenDataError("La respuesta de Kraken no contiene un cursor válido.")

    candle_keys = [key for key in result if key != "last"]
    if len(candle_keys) != 1:
        raise KrakenDataError("La respuesta no contiene un único par de velas.")

    candles = result[candle_keys[0]]
    if not isinstance(candles, list) or not candles:
        raise KrakenDataError("Kraken no devolvió una lista de velas.")

    parsed_candles: list[tuple[date, float]] = []
    previous_timestamp = None
    previous_date = None

    for candle_number, candle in enumerate(candles, start=1):
        if not isinstance(candle, list) or len(candle) != 8:
            raise KrakenDataError(
                f"La vela {candle_number} debe contener exactamente 8 campos."
            )

        timestamp = candle[0]
        if isinstance(timestamp, bool) or not isinstance(timestamp, int):
            raise KrakenDataError(
                f"Fecha no válida en la vela {candle_number}: se esperaba Unix time."
            )
        if previous_timestamp is not None and timestamp <= previous_timestamp:
            raise KrakenDataError("Las velas deben estar en orden cronológico estricto.")
        previous_timestamp = timestamp

        try:
            candle_date = datetime.fromtimestamp(timestamp, timezone.utc).date()
        except (OverflowError, OSError, ValueError) as error:
            raise KrakenDataError(
                f"Fecha fuera de rango en la vela {candle_number}."
            ) from error
        if previous_date is not None and candle_date <= previous_date:
            raise KrakenDataError(
                "Las fechas diarias deben estar en orden ascendente y sin duplicados."
            )
        previous_date = candle_date

        open_price = _positive_number(candle[1], "apertura", candle_number)
        high_price = _positive_number(candle[2], "máximo", candle_number)
        low_price = _positive_number(candle[3], "mínimo", candle_number)
        close_price = _positive_number(candle[4], "cierre", candle_number)
        _positive_number(candle[5], "VWAP", candle_number)

        if low_price > high_price or not (
            low_price <= open_price <= high_price
            and low_price <= close_price <= high_price
        ):
            raise KrakenDataError(
                f"Rango OHLC incoherente en la vela {candle_number}."
            )

        volume = candle[6]
        if isinstance(volume, bool):
            raise KrakenDataError(
                f"Volumen no válido en la vela {candle_number}."
            )
        try:
            numeric_volume = float(volume)
        except (TypeError, ValueError, OverflowError) as error:
            raise KrakenDataError(
                f"Volumen no válido en la vela {candle_number}."
            ) from error
        if not math.isfinite(numeric_volume) or numeric_volume < 0:
            raise KrakenDataError(
                f"El volumen debe ser finito y no negativo en la vela {candle_number}."
            )

        trade_count = candle[7]
        if (
            isinstance(trade_count, bool)
            or not isinstance(trade_count, int)
            or trade_count < 0
        ):
            raise KrakenDataError(
                f"El número de operaciones no es válido en la vela {candle_number}."
            )

        parsed_candles.append((candle_date, close_price))

    closed_candles = parsed_candles[:-1]
    if not closed_candles:
        raise KrakenDataError(
            "La respuesta solo contiene la vela abierta; no hay velas cerradas."
        )
    return closed_candles


def fetch_daily_closes(
    timeout: int = REQUEST_TIMEOUT_SECONDS,
) -> list[tuple[date, float]]:
    """Solicita una vez las velas diarias públicas y valida la respuesta."""
    request = Request(
        f"{KRAKEN_OHLC_URL}?pair={PAIR}&interval={INTERVAL_MINUTES}",
        headers={"User-Agent": "AutonomousInvestmentAgent/0.2"},
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            response_body = response.read()
    except HTTPError as error:
        status_code = error.code
        error.close()
        if status_code == 429:
            raise KrakenDataError(
                "Kraken limitó la solicitud (HTTP 429); espera antes de intentarlo de nuevo."
            ) from error
        raise KrakenDataError(f"Kraken respondió con HTTP {status_code}.") from error
    except (URLError, TimeoutError, OSError) as error:
        raise KrakenDataError(f"No se pudo conectar con Kraken: {error}") from error

    try:
        payload = json.loads(response_body)
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise KrakenDataError("Kraken devolvió una respuesta JSON no válida.") from error

    return parse_ohlc_response(payload)


def _write_csv_atomically(
    output_path: str | Path,
    candles: list[tuple[date, float]],
) -> None:
    """Escribe en el mismo directorio y reemplaza el destino al terminar."""
    destination = Path(output_path)
    temporary_path = None

    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="",
            dir=destination.parent,
            prefix=f".{destination.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            writer = csv.writer(temporary_file)
            writer.writerow(("date", "close"))
            for candle_date, close_price in candles:
                writer.writerow((candle_date.isoformat(), repr(close_price)))
            temporary_file.flush()
            os.fsync(temporary_file.fileno())

        os.replace(temporary_path, destination)
        temporary_path = None
    except OSError as error:
        raise KrakenDataError(f"No se pudo guardar el CSV {destination}: {error}") from error
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink()
            except FileNotFoundError:
                pass


def download_daily_csv(
    output_path: str | Path = DEFAULT_OUTPUT,
    timeout: int = REQUEST_TIMEOUT_SECONDS,
) -> int:
    """Descarga, valida y guarda cierres diarios; devuelve el número de velas."""
    candles = fetch_daily_closes(timeout=timeout)
    _write_csv_atomically(output_path, candles)
    return len(candles)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Descarga velas cerradas públicas de BTC/USD desde Kraken."
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"CSV de destino (por defecto: {DEFAULT_OUTPUT})",
    )
    args = parser.parse_args()

    try:
        count = download_daily_csv(args.output)
    except KrakenDataError as error:
        parser.error(str(error))

    print(f"Guardadas {count} velas diarias cerradas en {args.output}.")
    print("Solo se descargaron datos públicos; no se enviaron operaciones.")


if __name__ == "__main__":
    main()
