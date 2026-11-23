import unittest
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from enum import StrEnum

from investment_agent.market_data.models import (
    AdjustmentType,
    AssetClass,
    BarStatus,
    Instrument,
    OHLCVBar,
    SessionCloseConvention,
    validate_bar_sequence,
)


UTC = timezone.utc


def _instrument(
    *,
    instrument_id="urn:aia:instrument:btc-usd-kraken",
    asset_class=AssetClass.CRYPTOCURRENCY,
    market="Kraken Spot",
    provider="Kraken",
    provider_symbol="XBTUSD",
    quote_currency="USD",
    trading_calendar="CRYPTO_24_7_UTC",
    timezone_name="UTC",
    session_close_convention=SessionCloseConvention.UTC_INTERVAL_BOUNDARY,
):
    return Instrument(
        instrument_id=instrument_id,
        asset_class=asset_class,
        market=market,
        provider=provider,
        provider_symbol=provider_symbol,
        quote_currency=quote_currency,
        trading_calendar=trading_calendar,
        timezone=timezone_name,
        session_close_convention=session_close_convention,
    )


def _bar(
    instrument_id,
    start_utc,
    end_utc,
    session_date,
    *,
    interval="1d",
    open_price=Decimal("100"),
    high=Decimal("105"),
    low=Decimal("95"),
    close=Decimal("102"),
    volume=Decimal("1"),
    volume_unit="BTC",
    status=BarStatus.CLOSED,
    adjustment_type=AdjustmentType.RAW,
    provider="Kraken",
    source="synthetic_ohlcv",
    available_at_utc=None,
):
    return OHLCVBar(
        instrument_id=instrument_id,
        interval=interval,
        start_utc=start_utc,
        end_utc=end_utc,
        session_date=session_date,
        open=open_price,
        high=high,
        low=low,
        close=close,
        volume=volume,
        volume_unit=volume_unit,
        status=status,
        adjustment_type=adjustment_type,
        provider=provider,
        source=source,
        available_at_utc=available_at_utc,
    )


class InstrumentTests(unittest.TestCase):
    def test_instrument_keeps_stable_id_and_source_market_metadata(self):
        instrument = _instrument()

        self.assertNotEqual(instrument.instrument_id, instrument.provider_symbol)
        self.assertEqual(instrument.quote_currency, "USD")
        self.assertEqual(instrument.trading_calendar, "CRYPTO_24_7_UTC")
        self.assertEqual(instrument.timezone, "UTC")

    def test_supports_equity_and_sol_token_asset_classes(self):
        equity = _instrument(
            instrument_id="urn:aia:instrument:fictional-equity",
            asset_class=AssetClass.EQUITY,
            market="SIM-US",
            provider_symbol="TEST",
            trading_calendar="SIM_US_WEEKDAYS",
            timezone_name="America/New_York",
            session_close_convention=SessionCloseConvention.LOCAL_EXCHANGE_CLOSE,
        )
        token = _instrument(
            instrument_id="urn:aia:instrument:solana-token-example",
            asset_class=AssetClass.SOLANA_TOKEN,
            market="Solana DEX",
            provider_symbol="TINY",
            quote_currency="USDC",
            trading_calendar="SOLANA_24_7_UTC",
        )

        self.assertEqual(equity.asset_class, AssetClass.EQUITY)
        self.assertEqual(equity.timezone, "America/New_York")
        self.assertEqual(token.asset_class, AssetClass.SOLANA_TOKEN)
        self.assertEqual(token.quote_currency, "USDC")

    def test_rejects_invalid_instrument_id_currency_and_timezone(self):
        with self.assertRaisesRegex(ValueError, "instrument_id"):
            _instrument(instrument_id="bad id")
        with self.assertRaisesRegex(ValueError, "quote_currency"):
            _instrument(quote_currency="usd")
        with self.assertRaisesRegex(ValueError, "timezone"):
            _instrument(timezone_name=" ")


class EnumTextTests(unittest.TestCase):
    def test_all_model_enums_are_str_enums_with_stable_text_values(self):
        values = (
            AssetClass.EQUITY,
            SessionCloseConvention.LOCAL_EXCHANGE_CLOSE,
            BarStatus.INCOMPLETE,
            AdjustmentType.SPLIT_AND_DIVIDEND_ADJUSTED,
        )

        for value in values:
            with self.subTest(value=value.value):
                self.assertIsInstance(value, StrEnum)
                self.assertEqual(str(value), value.value)
                self.assertEqual(f"{value}", value.value)


class OHLCVBarTests(unittest.TestCase):
    def test_accepts_bitcoin_daily_bars_on_weekend(self):
        instrument = _instrument()
        bars = [
            _bar(
                instrument.instrument_id,
                datetime(2025, 2, day, tzinfo=UTC),
                datetime(2025, 2, day + 1, tzinfo=UTC),
                date(2025, 2, day),
            )
            for day in (1, 2, 3)
        ]

        validate_bar_sequence(instrument, bars)

        self.assertEqual(
            [bar.session_date for bar in bars],
            [date(2025, 2, 1), date(2025, 2, 2), date(2025, 2, 3)],
        )

    def test_accepts_fictional_equity_with_weekend_session_gap(self):
        instrument = _instrument(
            instrument_id="urn:aia:instrument:fictional-equity",
            asset_class=AssetClass.EQUITY,
            market="SIM-US",
            provider="Fixture",
            provider_symbol="TEST",
            trading_calendar="SIM_US_WEEKDAYS",
            timezone_name="America/New_York",
            session_close_convention=SessionCloseConvention.LOCAL_EXCHANGE_CLOSE,
        )
        bars = [
            _bar(
                instrument.instrument_id,
                datetime(2025, 1, 3, 14, 30, tzinfo=UTC),
                datetime(2025, 1, 3, 21, 0, tzinfo=UTC),
                date(2025, 1, 3),
                provider="Fixture",
                volume=Decimal("1200"),
                volume_unit="shares",
            ),
            _bar(
                instrument.instrument_id,
                datetime(2025, 1, 6, 14, 30, tzinfo=UTC),
                datetime(2025, 1, 6, 21, 0, tzinfo=UTC),
                date(2025, 1, 6),
                provider="Fixture",
                volume=Decimal("900"),
                volume_unit="shares",
            ),
        ]

        validate_bar_sequence(instrument, bars)

        self.assertEqual(
            [bar.session_date for bar in bars],
            [date(2025, 1, 3), date(2025, 1, 6)],
        )
        self.assertEqual(instrument.trading_calendar, "SIM_US_WEEKDAYS")

    def test_stock_session_date_is_not_forced_to_utc_start_or_end_date(self):
        instrument = _instrument(
            instrument_id="urn:aia:instrument:fictional-equity",
            asset_class=AssetClass.EQUITY,
            market="SIM-US",
            provider="Fixture",
            provider_symbol="TEST",
            trading_calendar="SIM_DATE_LABELS",
            timezone_name="America/Los_Angeles",
            session_close_convention=SessionCloseConvention.LOCAL_EXCHANGE_CLOSE,
        )
        bar = _bar(
            instrument.instrument_id,
            datetime(2025, 1, 3, 0, 30, tzinfo=UTC),
            datetime(2025, 1, 3, 7, 0, tzinfo=UTC),
            date(2025, 1, 2),
            provider="Fixture",
        )

        validate_bar_sequence(instrument, [bar])

        self.assertNotEqual(bar.session_date, bar.start_utc.date())
        self.assertNotEqual(bar.session_date, bar.end_utc.date())

    def test_accepts_very_small_decimal_token_price_without_rounding(self):
        instrument = _instrument(
            instrument_id="urn:aia:instrument:solana-token-example",
            asset_class=AssetClass.SOLANA_TOKEN,
            market="Solana DEX",
            provider_symbol="TINY",
            quote_currency="USDC",
            trading_calendar="SOLANA_24_7_UTC",
        )
        tiny_price = Decimal("0.0000000000000000000000001234")

        bar = _bar(
            instrument.instrument_id,
            datetime(2025, 2, 1, tzinfo=UTC),
            datetime(2025, 2, 1, 0, 1, tzinfo=UTC),
            date(2025, 2, 1),
            interval="1m",
            open_price=tiny_price,
            high=tiny_price,
            low=tiny_price,
            close=tiny_price,
            volume=Decimal("123456789.123456789"),
            volume_unit="TINY",
        )

        self.assertEqual(bar.close, tiny_price)
        self.assertEqual(bar.volume, Decimal("123456789.123456789"))

    def test_interval_must_be_supported_and_intraday_duration_must_match(self):
        base = dict(
            instrument_id="urn:aia:instrument:btc-usd-kraken",
            start_utc=datetime(2025, 1, 1, tzinfo=UTC),
            session_date=date(2025, 1, 1),
        )
        with self.assertRaisesRegex(ValueError, "intervalo.*no está admitido"):
            _bar(
                **base,
                interval="2h",
                end_utc=datetime(2025, 1, 1, 2, tzinfo=UTC),
            )
        with self.assertRaisesRegex(ValueError, "duración de 1m"):
            _bar(
                **base,
                interval="1m",
                end_utc=datetime(2025, 1, 1, 0, 0, 59, tzinfo=UTC),
            )
        with self.assertRaisesRegex(ValueError, "duración de 1h"):
            _bar(
                **base,
                interval="1h",
                end_utc=datetime(2025, 1, 1, 1, 1, tzinfo=UTC),
            )

        one_minute = _bar(
            **base,
            interval="1m",
            end_utc=datetime(2025, 1, 1, 0, 1, tzinfo=UTC),
        )
        one_hour = _bar(
            **base,
            interval="1h",
            end_utc=datetime(2025, 1, 1, 1, tzinfo=UTC),
        )
        self.assertEqual(one_minute.end_utc - one_minute.start_utc, timedelta(minutes=1))
        self.assertEqual(one_hour.end_utc - one_hour.start_utc, timedelta(hours=1))

    def test_rejects_non_decimal_non_finite_or_non_positive_prices(self):
        valid = dict(
            instrument_id="urn:aia:instrument:btc-usd-kraken",
            start_utc=datetime(2025, 1, 1, tzinfo=UTC),
            end_utc=datetime(2025, 1, 2, tzinfo=UTC),
            session_date=date(2025, 1, 1),
        )
        for invalid in (100.0, Decimal("NaN"), Decimal("0"), Decimal("-1")):
            with self.subTest(invalid=invalid):
                with self.assertRaisesRegex(ValueError, "Decimal positivo y finito"):
                    _bar(**valid, open_price=invalid)
        with self.assertRaisesRegex(ValueError, "Decimal positivo y finito"):
            _bar(**valid, open_price=Decimal("Infinity"))

    def test_rejects_invalid_volume(self):
        base = dict(
            instrument_id="urn:aia:instrument:btc-usd-kraken",
            start_utc=datetime(2025, 1, 1, tzinfo=UTC),
            end_utc=datetime(2025, 1, 2, tzinfo=UTC),
            session_date=date(2025, 1, 1),
        )
        for invalid in (-1.0, Decimal("Infinity"), Decimal("-0.1")):
            with self.subTest(invalid=invalid):
                with self.assertRaisesRegex(ValueError, "volume debe ser"):
                    _bar(**base, volume=invalid)

    def test_validates_ohlc_range(self):
        with self.assertRaisesRegex(ValueError, "rango low-high"):
            _bar(
                "urn:aia:instrument:btc-usd-kraken",
                datetime(2025, 1, 1, tzinfo=UTC),
                datetime(2025, 1, 2, tzinfo=UTC),
                date(2025, 1, 1),
                high=Decimal("101"),
                close=Decimal("102"),
            )

    def test_requires_explicit_utc_instants_and_positive_interval(self):
        start = datetime(2025, 1, 1, tzinfo=UTC)
        end = datetime(2025, 1, 2, tzinfo=UTC)
        with self.assertRaisesRegex(ValueError, "UTC explícita"):
            _bar(
                "urn:aia:instrument:btc-usd-kraken",
                start.replace(tzinfo=None),
                end,
                date(2025, 1, 1),
            )
        with self.assertRaisesRegex(ValueError, "UTC explícita"):
            _bar(
                "urn:aia:instrument:btc-usd-kraken",
                start.replace(tzinfo=timezone(timedelta(hours=-5))),
                end,
                date(2025, 1, 1),
            )
        with self.assertRaisesRegex(ValueError, "anterior a end_utc"):
            _bar(
                "urn:aia:instrument:btc-usd-kraken",
                end,
                start,
                date(2025, 1, 1),
            )
        with self.assertRaisesRegex(ValueError, "UTC explícita"):
            _bar(
                "urn:aia:instrument:btc-usd-kraken",
                start,
                end,
                date(2025, 1, 1),
                available_at_utc=datetime(2025, 1, 2),
            )

    def test_tracks_closed_and_incomplete_status_and_temporal_availability(self):
        end = datetime(2025, 1, 2, tzinfo=UTC)
        closed = _bar(
            "urn:aia:instrument:btc-usd-kraken",
            datetime(2025, 1, 1, tzinfo=UTC),
            end,
            date(2025, 1, 1),
            available_at_utc=end + timedelta(minutes=2),
        )
        incomplete = _bar(
            "urn:aia:instrument:btc-usd-kraken",
            datetime(2025, 1, 1, tzinfo=UTC),
            end,
            date(2025, 1, 1),
            status=BarStatus.INCOMPLETE,
            available_at_utc=end - timedelta(minutes=1),
        )

        self.assertEqual(closed.status, BarStatus.CLOSED)
        self.assertEqual(incomplete.status, BarStatus.INCOMPLETE)
        self.assertEqual(closed.available_at_utc, end + timedelta(minutes=2))

    def test_closed_bar_cannot_be_available_before_its_end(self):
        end = datetime(2025, 1, 2, tzinfo=UTC)
        with self.assertRaisesRegex(ValueError, "disponible antes de end_utc"):
            _bar(
                "urn:aia:instrument:btc-usd-kraken",
                datetime(2025, 1, 1, tzinfo=UTC),
                end,
                date(2025, 1, 1),
                available_at_utc=end - timedelta(seconds=1),
            )

    def test_keeps_adjustment_and_data_provenance(self):
        bar = _bar(
            "urn:aia:instrument:fictional-equity",
            datetime(2025, 1, 3, 14, 30, tzinfo=UTC),
            datetime(2025, 1, 3, 21, 0, tzinfo=UTC),
            date(2025, 1, 3),
            adjustment_type=AdjustmentType.SPLIT_AND_DIVIDEND_ADJUSTED,
            provider="SyntheticProvider",
            source="daily_adjusted_endpoint",
        )

        self.assertEqual(
            bar.adjustment_type, AdjustmentType.SPLIT_AND_DIVIDEND_ADJUSTED
        )
        self.assertEqual(bar.provider, "SyntheticProvider")
        self.assertEqual(bar.source, "daily_adjusted_endpoint")

    def test_volume_and_unit_must_be_present_together(self):
        with self.assertRaisesRegex(ValueError, "volume_unit debe ser None"):
            _bar(
                "urn:aia:instrument:btc-usd-kraken",
                datetime(2025, 1, 1, tzinfo=UTC),
                datetime(2025, 1, 2, tzinfo=UTC),
                date(2025, 1, 1),
                volume=None,
                volume_unit="BTC",
            )
        with self.assertRaisesRegex(ValueError, "volume_unit"):
            _bar(
                "urn:aia:instrument:btc-usd-kraken",
                datetime(2025, 1, 1, tzinfo=UTC),
                datetime(2025, 1, 2, tzinfo=UTC),
                date(2025, 1, 1),
                volume=Decimal("1"),
                volume_unit=" ",
            )

    def test_sequence_rejects_other_instrument_and_non_increasing_times(self):
        instrument = _instrument()
        first = _bar(
            instrument.instrument_id,
            datetime(2025, 1, 1, tzinfo=UTC),
            datetime(2025, 1, 2, tzinfo=UTC),
            date(2025, 1, 1),
        )
        duplicate = _bar(
            instrument.instrument_id,
            datetime(2025, 1, 1, tzinfo=UTC),
            datetime(2025, 1, 2, tzinfo=UTC),
            date(2025, 1, 1),
        )
        other = _bar(
            "urn:aia:instrument:other",
            datetime(2025, 1, 2, tzinfo=UTC),
            datetime(2025, 1, 3, tzinfo=UTC),
            date(2025, 1, 2),
        )

        with self.assertRaisesRegex(ValueError, "se solapan"):
            validate_bar_sequence(instrument, [first, duplicate])
        with self.assertRaisesRegex(ValueError, "no pertenece"):
            validate_bar_sequence(instrument, [first, other])
        different_interval = _bar(
            instrument.instrument_id,
            datetime(2025, 1, 2, tzinfo=UTC),
            datetime(2025, 1, 2, 1, tzinfo=UTC),
            date(2025, 1, 2),
            interval="1h",
        )
        with self.assertRaisesRegex(ValueError, "mezclar intervalos"):
            validate_bar_sequence(instrument, [first, different_interval])

    def test_sequence_accepts_consistent_provider_adjustment_and_volume_unit(self):
        instrument = _instrument()
        first = _bar(
            instrument.instrument_id,
            datetime(2025, 1, 1, tzinfo=UTC),
            datetime(2025, 1, 2, tzinfo=UTC),
            date(2025, 1, 1),
        )
        second = _bar(
            instrument.instrument_id,
            datetime(2025, 1, 2, tzinfo=UTC),
            datetime(2025, 1, 3, tzinfo=UTC),
            date(2025, 1, 2),
        )

        validate_bar_sequence(instrument, [first, second])

    def test_sequence_rejects_mixed_provider_adjustment_or_volume_unit(self):
        instrument = _instrument()
        first = _bar(
            instrument.instrument_id,
            datetime(2025, 1, 1, tzinfo=UTC),
            datetime(2025, 1, 2, tzinfo=UTC),
            date(2025, 1, 1),
        )
        incompatible_bars = (
            (
                "provider",
                _bar(
                    instrument.instrument_id,
                    datetime(2025, 1, 2, tzinfo=UTC),
                    datetime(2025, 1, 3, tzinfo=UTC),
                    date(2025, 1, 2),
                    provider="OtherProvider",
                ),
                "proveedor",
            ),
            (
                "adjustment",
                _bar(
                    instrument.instrument_id,
                    datetime(2025, 1, 2, tzinfo=UTC),
                    datetime(2025, 1, 3, tzinfo=UTC),
                    date(2025, 1, 2),
                    adjustment_type=AdjustmentType.SPLIT_ADJUSTED,
                ),
                "ajuste",
            ),
            (
                "source",
                _bar(
                    instrument.instrument_id,
                    datetime(2025, 1, 2, tzinfo=UTC),
                    datetime(2025, 1, 3, tzinfo=UTC),
                    date(2025, 1, 2),
                    source="different_endpoint",
                ),
                "fuentes",
            ),
            (
                "volume_unit",
                _bar(
                    instrument.instrument_id,
                    datetime(2025, 1, 2, tzinfo=UTC),
                    datetime(2025, 1, 3, tzinfo=UTC),
                    date(2025, 1, 2),
                    volume_unit="ETH",
                ),
                "unidades de volumen",
            ),
        )

        for label, second, message in incompatible_bars:
            with self.subTest(label=label):
                with self.assertRaisesRegex(ValueError, message):
                    validate_bar_sequence(instrument, [first, second])

    def test_every_bar_provider_must_match_its_instrument(self):
        instrument = _instrument(provider="Kraken")
        bars = [
            _bar(
                instrument.instrument_id,
                datetime(2025, 1, day, tzinfo=UTC),
                datetime(2025, 1, day + 1, tzinfo=UTC),
                date(2025, 1, day),
                provider="OtherProvider",
            )
            for day in (1, 2)
        ]

        with self.assertRaisesRegex(ValueError, "coincidir con el instrumento"):
            validate_bar_sequence(instrument, bars)

    def test_sequence_accepts_missing_volume_when_consistent(self):
        instrument = _instrument()
        bars = [
            _bar(
                instrument.instrument_id,
                datetime(2025, 1, day, tzinfo=UTC),
                datetime(2025, 1, day + 1, tzinfo=UTC),
                date(2025, 1, day),
                volume=None,
                volume_unit=None,
            )
            for day in (1, 2)
        ]

        validate_bar_sequence(instrument, bars)

    def test_incomplete_bar_is_only_allowed_at_the_end(self):
        instrument = _instrument()
        first_incomplete = _bar(
            instrument.instrument_id,
            datetime(2025, 1, 1, tzinfo=UTC),
            datetime(2025, 1, 2, tzinfo=UTC),
            date(2025, 1, 1),
            status=BarStatus.INCOMPLETE,
        )
        closed_second = _bar(
            instrument.instrument_id,
            datetime(2025, 1, 2, tzinfo=UTC),
            datetime(2025, 1, 3, tzinfo=UTC),
            date(2025, 1, 2),
        )
        closed_first = _bar(
            instrument.instrument_id,
            datetime(2025, 1, 1, tzinfo=UTC),
            datetime(2025, 1, 2, tzinfo=UTC),
            date(2025, 1, 1),
        )
        incomplete_last = _bar(
            instrument.instrument_id,
            datetime(2025, 1, 2, tzinfo=UTC),
            datetime(2025, 1, 3, tzinfo=UTC),
            date(2025, 1, 2),
            status=BarStatus.INCOMPLETE,
        )

        with self.assertRaisesRegex(ValueError, "solo puede ser la última"):
            validate_bar_sequence(instrument, [first_incomplete, closed_second])
        validate_bar_sequence(instrument, [closed_first, incomplete_last])

    def test_daily_session_dates_must_increase_without_duplicates(self):
        instrument = _instrument(
            instrument_id="urn:aia:instrument:fictional-equity",
            asset_class=AssetClass.EQUITY,
            market="SIM-US",
            provider="Fixture",
            provider_symbol="TEST",
            trading_calendar="SIM_US_WEEKDAYS",
            timezone_name="America/New_York",
            session_close_convention=SessionCloseConvention.LOCAL_EXCHANGE_CLOSE,
        )
        first = _bar(
            instrument.instrument_id,
            datetime(2025, 1, 3, 14, 30, tzinfo=UTC),
            datetime(2025, 1, 3, 21, 0, tzinfo=UTC),
            date(2025, 1, 3),
            provider="Fixture",
        )
        duplicate_session = _bar(
            instrument.instrument_id,
            datetime(2025, 1, 6, 14, 30, tzinfo=UTC),
            datetime(2025, 1, 6, 21, 0, tzinfo=UTC),
            date(2025, 1, 3),
            provider="Fixture",
        )
        reversed_session = _bar(
            instrument.instrument_id,
            datetime(2025, 1, 6, 14, 30, tzinfo=UTC),
            datetime(2025, 1, 6, 21, 0, tzinfo=UTC),
            date(2025, 1, 2),
            provider="Fixture",
        )

        with self.assertRaisesRegex(ValueError, "sesión.*orden"):
            validate_bar_sequence(instrument, [first, duplicate_session])
        with self.assertRaisesRegex(ValueError, "sesión.*orden"):
            validate_bar_sequence(instrument, [first, reversed_session])

    def test_daily_crypto_session_date_matches_utc_start_date(self):
        instrument = _instrument()
        shifted_date = _bar(
            instrument.instrument_id,
            datetime(2025, 1, 1, tzinfo=UTC),
            datetime(2025, 1, 2, tzinfo=UTC),
            date(2025, 1, 2),
        )
        shifted_start = _bar(
            instrument.instrument_id,
            datetime(2025, 1, 1, 1, tzinfo=UTC),
            datetime(2025, 1, 2, 1, tzinfo=UTC),
            date(2025, 1, 1),
        )

        with self.assertRaisesRegex(ValueError, "00:00 UTC"):
            validate_bar_sequence(instrument, [shifted_start])
        with self.assertRaisesRegex(ValueError, "fecha UTC de inicio"):
            validate_bar_sequence(instrument, [shifted_date])

    def test_stock_daily_duration_is_session_length_not_24_hours(self):
        instrument = _instrument(
            instrument_id="urn:aia:instrument:fictional-equity",
            asset_class=AssetClass.EQUITY,
            market="SIM-US",
            provider="Fixture",
            provider_symbol="TEST",
            trading_calendar="SIM_US_WEEKDAYS",
            timezone_name="America/New_York",
            session_close_convention=SessionCloseConvention.LOCAL_EXCHANGE_CLOSE,
        )
        full_session = _bar(
            instrument.instrument_id,
            datetime(2025, 1, 3, 14, 30, tzinfo=UTC),
            datetime(2025, 1, 3, 21, 0, tzinfo=UTC),
            date(2025, 1, 3),
            provider="Fixture",
        )
        shortened_session = _bar(
            instrument.instrument_id,
            datetime(2025, 1, 6, 14, 30, tzinfo=UTC),
            datetime(2025, 1, 6, 18, 0, tzinfo=UTC),
            date(2025, 1, 6),
            provider="Fixture",
        )

        validate_bar_sequence(instrument, [full_session, shortened_session])

    def test_local_exchange_rejects_sessions_longer_than_24_hours(self):
        instrument = _instrument(
            instrument_id="urn:aia:instrument:fictional-equity",
            asset_class=AssetClass.EQUITY,
            market="SIM-US",
            provider="Fixture",
            provider_symbol="TEST",
            trading_calendar="SIM_US_WEEKDAYS",
            timezone_name="America/New_York",
            session_close_convention=SessionCloseConvention.LOCAL_EXCHANGE_CLOSE,
        )
        start = datetime(2025, 1, 3, 14, 30, tzinfo=UTC)

        for duration in (timedelta(hours=30), timedelta(days=5)):
            with self.subTest(duration=duration):
                bar = _bar(
                    instrument.instrument_id,
                    start,
                    start + duration,
                    date(2025, 1, 3),
                    provider="Fixture",
                )
                with self.assertRaisesRegex(ValueError, "no puede superar 24 horas"):
                    validate_bar_sequence(instrument, [bar])

    def test_local_exchange_accepts_regular_half_and_overnight_sessions(self):
        instrument = _instrument(
            instrument_id="urn:aia:instrument:fictional-equity",
            asset_class=AssetClass.EQUITY,
            market="SIM-US",
            provider="Fixture",
            provider_symbol="TEST",
            trading_calendar="SIM_US_WEEKDAYS",
            timezone_name="America/New_York",
            session_close_convention=SessionCloseConvention.LOCAL_EXCHANGE_CLOSE,
        )
        bars = [
            _bar(
                instrument.instrument_id,
                datetime(2025, 1, 3, 14, 30, tzinfo=UTC),
                datetime(2025, 1, 3, 21, 0, tzinfo=UTC),
                date(2025, 1, 3),
                provider="Fixture",
            ),
            _bar(
                instrument.instrument_id,
                datetime(2025, 1, 6, 14, 30, tzinfo=UTC),
                datetime(2025, 1, 6, 18, 0, tzinfo=UTC),
                date(2025, 1, 6),
                provider="Fixture",
            ),
            _bar(
                instrument.instrument_id,
                datetime(2025, 1, 7, 22, 0, tzinfo=UTC),
                datetime(2025, 1, 8, 3, 0, tzinfo=UTC),
                date(2025, 1, 7),
                provider="Fixture",
            ),
        ]

        validate_bar_sequence(instrument, bars)

    def test_local_exchange_rejects_clearly_displaced_session_date(self):
        instrument = _instrument(
            instrument_id="urn:aia:instrument:fictional-equity",
            asset_class=AssetClass.EQUITY,
            market="SIM-US",
            provider="Fixture",
            provider_symbol="TEST",
            trading_calendar="SIM_US_WEEKDAYS",
            timezone_name="America/Los_Angeles",
            session_close_convention=SessionCloseConvention.LOCAL_EXCHANGE_CLOSE,
        )
        displaced = _bar(
            instrument.instrument_id,
            datetime(2025, 1, 3, 0, 30, tzinfo=UTC),
            datetime(2025, 1, 3, 7, 0, tzinfo=UTC),
            date(2024, 12, 30),
            provider="Fixture",
        )

        with self.assertRaisesRegex(ValueError, "fuera del rango temporal provisional"):
            validate_bar_sequence(instrument, [displaced])

    def test_sequence_rejects_overlaps_but_accepts_touching_or_gapped_bars(self):
        instrument = _instrument(
            instrument_id="urn:aia:instrument:fictional-equity",
            asset_class=AssetClass.EQUITY,
            market="SIM-US",
            provider="Fixture",
            provider_symbol="TEST",
            trading_calendar="SIM_US_WEEKDAYS",
            timezone_name="America/New_York",
            session_close_convention=SessionCloseConvention.LOCAL_EXCHANGE_CLOSE,
        )
        first = _bar(
            instrument.instrument_id,
            datetime(2025, 1, 1, tzinfo=UTC),
            datetime(2025, 1, 1, 1, tzinfo=UTC),
            date(2025, 1, 1),
            interval="1h",
            provider="Fixture",
        )
        touching = _bar(
            instrument.instrument_id,
            datetime(2025, 1, 1, 1, tzinfo=UTC),
            datetime(2025, 1, 1, 2, tzinfo=UTC),
            date(2025, 1, 1),
            interval="1h",
            provider="Fixture",
        )
        gapped = _bar(
            instrument.instrument_id,
            datetime(2025, 1, 1, 3, tzinfo=UTC),
            datetime(2025, 1, 1, 4, tzinfo=UTC),
            date(2025, 1, 1),
            interval="1h",
            provider="Fixture",
        )
        overlapping = _bar(
            instrument.instrument_id,
            datetime(2025, 1, 1, 0, 30, tzinfo=UTC),
            datetime(2025, 1, 1, 1, 30, tzinfo=UTC),
            date(2025, 1, 1),
            interval="1h",
            provider="Fixture",
        )

        validate_bar_sequence(instrument, [first, touching])
        validate_bar_sequence(instrument, [first, gapped])
        with self.assertRaisesRegex(ValueError, "se solapan"):
            validate_bar_sequence(instrument, [first, overlapping])


if __name__ == "__main__":
    unittest.main()
