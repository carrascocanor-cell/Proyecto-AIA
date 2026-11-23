import csv
import io
import json
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from investment_agent.analysis import analyze_prices, load_close_prices
from investment_agent.market_data.kraken import (
    KrakenDataError,
    download_daily_csv,
    fetch_daily_closes,
    parse_ohlc_response,
)


def _timestamp(day: int) -> int:
    return int(datetime(2025, 1, day, tzinfo=timezone.utc).timestamp())


def _candle(day: int, close: str = "102.5") -> list[object]:
    return [
        _timestamp(day),
        "100.0",
        "105.0",
        "95.0",
        close,
        "101.0",
        "12.5",
        42,
    ]


def _payload(candles: list[list[object]]) -> dict[str, object]:
    return {
        "error": [],
        "result": {
            "XXBTZUSD": candles,
            "last": _timestamp(3),
        },
    }


class ParseOhlcResponseTests(unittest.TestCase):
    def test_discards_the_last_candle_and_keeps_closed_candles(self):
        result = parse_ohlc_response(
            _payload([_candle(1, "100.5"), _candle(2, "102.5"), _candle(3, "104.5")])
        )

        self.assertEqual(
            result,
            [(date(2025, 1, 1), 100.5), (date(2025, 1, 2), 102.5)],
        )

    def test_discards_last_candle_from_721_returned_candles(self):
        start_timestamp = _timestamp(1)
        candles = []
        for offset in range(721):
            close = "104.5" if offset == 720 else "104.0"
            candle = _candle(1, close)
            candle[0] = start_timestamp + offset * 24 * 60 * 60
            candles.append(candle)

        result = parse_ohlc_response(_payload(candles))

        self.assertEqual(len(result), 720)
        self.assertEqual(result[0], (date(2025, 1, 1), 104.0))
        self.assertEqual(result[-1], (date(2025, 1, 1) + timedelta(days=719), 104.0))
        self.assertNotIn((date(2025, 1, 1) + timedelta(days=720), 104.5), result)

    def test_rejects_response_with_only_the_open_candle(self):
        with self.assertRaisesRegex(KrakenDataError, "solo contiene la vela abierta"):
            parse_ohlc_response(_payload([_candle(1)]))

    def test_validates_the_open_candle_before_discarding_it(self):
        open_candle = _candle(2)
        open_candle[4] = "nan"

        with self.assertRaisesRegex(KrakenDataError, "cierre debe ser positivo"):
            parse_ohlc_response(_payload([_candle(1), open_candle]))

    def test_rejects_api_errors(self):
        payload = _payload([_candle(1), _candle(2)])
        payload["error"] = ["EGeneral:Invalid arguments"]

        with self.assertRaisesRegex(KrakenDataError, "Invalid arguments"):
            parse_ohlc_response(payload)

    def test_rejects_malformed_candle(self):
        with self.assertRaisesRegex(KrakenDataError, "exactamente 8 campos"):
            parse_ohlc_response(_payload([_candle(1)[:-1], _candle(2)]))

    def test_rejects_non_chronological_or_duplicate_dates(self):
        with self.assertRaisesRegex(KrakenDataError, "orden cronológico"):
            parse_ohlc_response(_payload([_candle(2), _candle(1)]))
        with self.assertRaisesRegex(KrakenDataError, "orden cronológico"):
            parse_ohlc_response(_payload([_candle(1), _candle(1)]))

    def test_rejects_invalid_prices_and_inconsistent_ohlc(self):
        invalid_price = _candle(1)
        invalid_price[4] = "nan"
        with self.assertRaisesRegex(KrakenDataError, "cierre debe ser positivo"):
            parse_ohlc_response(_payload([invalid_price, _candle(2)]))

        inconsistent = _candle(1)
        inconsistent[2] = "99.0"
        with self.assertRaisesRegex(KrakenDataError, "Rango OHLC incoherente"):
            parse_ohlc_response(_payload([inconsistent, _candle(2)]))

    def test_rejects_invalid_volume_and_trade_count(self):
        invalid_volume = _candle(1)
        invalid_volume[6] = "-1"
        with self.assertRaisesRegex(KrakenDataError, "volumen debe ser finito"):
            parse_ohlc_response(_payload([invalid_volume, _candle(2)]))

        invalid_count = _candle(1)
        invalid_count[7] = "42"
        with self.assertRaisesRegex(KrakenDataError, "número de operaciones"):
            parse_ohlc_response(_payload([invalid_count, _candle(2)]))

    def test_rejects_invalid_response_structure(self):
        with self.assertRaisesRegex(KrakenDataError, "objeto JSON"):
            parse_ohlc_response([])
        with self.assertRaisesRegex(KrakenDataError, "no contiene un resultado"):
            parse_ohlc_response({"error": [], "result": None})
        with self.assertRaisesRegex(KrakenDataError, "cursor válido"):
            parse_ohlc_response({"error": [], "result": {"XXBTZUSD": [_candle(1)]}})


class KrakenHttpTests(unittest.TestCase):
    def test_fetches_public_daily_market_data_without_credentials(self):
        body = json.dumps(_payload([_candle(1), _candle(2)])).encode("utf-8")
        with patch(
            "investment_agent.market_data.kraken.urlopen",
            return_value=io.BytesIO(body),
        ) as mocked_urlopen:
            result = fetch_daily_closes()

        self.assertEqual(result, [(date(2025, 1, 1), 102.5)])
        request = mocked_urlopen.call_args.args[0]
        self.assertIn("pair=XBTUSD&interval=1440", request.full_url)

    def test_reports_rate_limit_without_retries(self):
        error = HTTPError(
            "https://api.kraken.com/0/public/OHLC",
            429,
            "Too Many Requests",
            {},
            None,
        )
        with patch(
            "investment_agent.market_data.kraken.urlopen", side_effect=error
        ) as mocked_urlopen:
            with self.assertRaisesRegex(KrakenDataError, "HTTP 429"):
                fetch_daily_closes()

        mocked_urlopen.assert_called_once()

    def test_reports_connection_and_invalid_json_errors(self):
        with patch(
            "investment_agent.market_data.kraken.urlopen",
            side_effect=URLError("offline"),
        ):
            with self.assertRaisesRegex(KrakenDataError, "No se pudo conectar"):
                fetch_daily_closes()

        with patch(
            "investment_agent.market_data.kraken.urlopen",
            return_value=io.BytesIO(b"not-json"),
        ):
            with self.assertRaisesRegex(KrakenDataError, "JSON no válida"):
                fetch_daily_closes()


class DownloadCsvTests(unittest.TestCase):
    def test_writes_closed_candles_compatible_with_existing_analysis(self):
        body = json.dumps(
            _payload([_candle(1, "100.0"), _candle(2, "104.0"), _candle(3, "105.0")])
        ).encode("utf-8")
        with tempfile.TemporaryDirectory() as directory:
            output_path = Path(directory) / "btc.csv"
            with patch(
                "investment_agent.market_data.kraken.urlopen",
                return_value=io.BytesIO(body),
            ):
                count = download_daily_csv(output_path)

            self.assertEqual(count, 2)
            prices = load_close_prices(output_path)
            self.assertEqual(prices, [100.0, 104.0])
            self.assertEqual(analyze_prices(prices, window=2)["trend"], "above")

    def test_preserves_existing_csv_on_network_error(self):
        with tempfile.TemporaryDirectory() as directory:
            output_path = Path(directory) / "btc.csv"
            original = b"date,close\n2024-12-31,99\n"
            output_path.write_bytes(original)

            with patch(
                "investment_agent.market_data.kraken.urlopen",
                side_effect=URLError("offline"),
            ):
                with self.assertRaises(KrakenDataError):
                    download_daily_csv(output_path)

            self.assertEqual(output_path.read_bytes(), original)
            self.assertEqual(list(Path(directory).glob("*.tmp")), [])

    def test_preserves_existing_csv_on_validation_error(self):
        with tempfile.TemporaryDirectory() as directory:
            output_path = Path(directory) / "btc.csv"
            original = b"date,close\n2024-12-31,99\n"
            output_path.write_bytes(original)
            body = json.dumps(_payload([_candle(1), _candle(1)])).encode("utf-8")

            with patch(
                "investment_agent.market_data.kraken.urlopen",
                return_value=io.BytesIO(body),
            ):
                with self.assertRaises(KrakenDataError):
                    download_daily_csv(output_path)

            self.assertEqual(output_path.read_bytes(), original)
            self.assertEqual(list(Path(directory).glob("*.tmp")), [])

    def test_preserves_existing_csv_when_temporary_write_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            output_path = Path(directory) / "btc.csv"
            original = b"date,close\n2024-12-31,99\n"
            output_path.write_bytes(original)
            body = json.dumps(
                _payload([_candle(1), _candle(2), _candle(3)])
            ).encode("utf-8")
            real_csv_writer = csv.writer

            class FailingWriter:
                def __init__(self, file_object):
                    self._writer = real_csv_writer(file_object)
                    self._rows_written = 0

                def writerow(self, row):
                    self._rows_written += 1
                    if self._rows_written == 3:
                        raise OSError("disk full")
                    self._writer.writerow(row)

            with (
                patch(
                    "investment_agent.market_data.kraken.urlopen",
                    return_value=io.BytesIO(body),
                ),
                patch(
                    "investment_agent.market_data.kraken.csv.writer",
                    side_effect=lambda file_object: FailingWriter(file_object),
                ),
            ):
                with self.assertRaisesRegex(KrakenDataError, "No se pudo guardar"):
                    download_daily_csv(output_path)

            self.assertEqual(output_path.read_bytes(), original)
            self.assertEqual(list(Path(directory).glob("*.tmp")), [])

    def test_preserves_existing_csv_when_atomic_replace_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            output_path = Path(directory) / "btc.csv"
            original = b"date,close\n2024-12-31,99\n"
            output_path.write_bytes(original)
            body = json.dumps(_payload([_candle(1), _candle(2)])).encode("utf-8")

            with (
                patch(
                    "investment_agent.market_data.kraken.urlopen",
                    return_value=io.BytesIO(body),
                ),
                patch(
                    "investment_agent.market_data.kraken.os.replace",
                    side_effect=OSError("replace failed"),
                ),
            ):
                with self.assertRaisesRegex(KrakenDataError, "No se pudo guardar"):
                    download_daily_csv(output_path)

            self.assertEqual(output_path.read_bytes(), original)
            self.assertEqual(list(Path(directory).glob("*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
