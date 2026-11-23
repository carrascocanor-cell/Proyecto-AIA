"""Modelos de instrumentos y velas OHLCV normalizadas."""

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from enum import StrEnum
from typing import Sequence


_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_CURRENCY_PATTERN = re.compile(r"^[A-Z0-9][A-Z0-9.-]{1,15}$")
_INTRADAY_INTERVAL_DURATIONS = {
    "1m": timedelta(minutes=1),
    "1h": timedelta(hours=1),
}
_SUPPORTED_INTERVALS = frozenset((*_INTRADAY_INTERVAL_DURATIONS, "1d"))


class AssetClass(StrEnum):
    CRYPTOCURRENCY = "cryptocurrency"
    EQUITY = "equity"
    ETF = "etf"
    INDEX = "index"
    SOLANA_TOKEN = "solana_token"


class SessionCloseConvention(StrEnum):
    """How session dates and boundaries are interpreted.

    ``UTC_INTERVAL_BOUNDARY`` uses UTC interval boundaries; daily bars start at
    00:00 UTC and their session date is that UTC start date.
    ``LOCAL_EXCHANGE_CLOSE`` uses the exchange session date. A calendar is
    required to validate its relationship to UTC timestamps.
    """

    UTC_INTERVAL_BOUNDARY = "utc_interval_boundary"
    LOCAL_EXCHANGE_CLOSE = "local_exchange_close"


class BarStatus(StrEnum):
    CLOSED = "closed"
    INCOMPLETE = "incomplete"


class AdjustmentType(StrEnum):
    RAW = "raw"
    SPLIT_ADJUSTED = "split_adjusted"
    SPLIT_AND_DIVIDEND_ADJUSTED = "split_and_dividend_adjusted"
    TOTAL_RETURN_ADJUSTED = "total_return_adjusted"


def _require_text(value: str, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ValueError(f"{field_name} debe ser texto no vacío y normalizado.")


def _require_identifier(value: str, field_name: str) -> None:
    _require_text(value, field_name)
    if not _IDENTIFIER_PATTERN.fullmatch(value):
        raise ValueError(f"{field_name} tiene un formato no válido.")


def _require_utc_datetime(value: datetime, field_name: str) -> None:
    if not isinstance(value, datetime):
        raise ValueError(f"{field_name} debe ser una fecha y hora.")
    try:
        offset = value.utcoffset()
    except (OverflowError, ValueError) as error:
        raise ValueError(f"{field_name} debe tener una zona horaria UTC válida.") from error
    if value.tzinfo is None or offset != timedelta(0):
        raise ValueError(f"{field_name} debe incluir una zona horaria UTC explícita.")


def _require_positive_decimal(value: Decimal, field_name: str) -> None:
    if not isinstance(value, Decimal) or not value.is_finite() or value <= 0:
        raise ValueError(f"{field_name} debe ser un Decimal positivo y finito.")


@dataclass(frozen=True)
class Instrument:
    """Identidad estable y metadatos de un instrumento en una fuente.

    ``timezone`` se conserva como texto y no se usa para conversiones.
    """

    instrument_id: str
    asset_class: AssetClass
    market: str
    provider: str
    provider_symbol: str
    quote_currency: str
    trading_calendar: str
    timezone: str
    session_close_convention: SessionCloseConvention

    def __post_init__(self) -> None:
        _require_identifier(self.instrument_id, "instrument_id")
        if not isinstance(self.asset_class, AssetClass):
            raise ValueError("asset_class debe ser un valor de AssetClass.")
        for field_name in (
            "market",
            "provider",
            "provider_symbol",
            "trading_calendar",
            "timezone",
        ):
            _require_text(getattr(self, field_name), field_name)
        if not isinstance(self.quote_currency, str) or not _CURRENCY_PATTERN.fullmatch(
            self.quote_currency
        ):
            raise ValueError(
                "quote_currency debe ser un código en mayúsculas de 2 a 16 "
                "caracteres alfanuméricos."
            )
        if not isinstance(
            self.session_close_convention, SessionCloseConvention
        ):
            raise ValueError(
                "session_close_convention debe ser un valor de "
                "SessionCloseConvention."
            )


@dataclass(frozen=True)
class OHLCVBar:
    """Una vela con precios en la moneda de cotización del instrumento.

    Se admiten intervalos 1m, 1h y 1d. La duración de 1m y 1h es fija;
    1d representa una frontera UTC o una sesión bursátil según el instrumento.
    ``available_at_utc`` es cuándo se conoció esta versión exacta del dato.
    Si la fuente no permite conocerlo, se deja en ``None``; no se infiere de
    ``end_utc``.
    """

    instrument_id: str
    interval: str
    start_utc: datetime
    end_utc: datetime
    session_date: date | None
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal | None
    volume_unit: str | None
    status: BarStatus
    adjustment_type: AdjustmentType
    provider: str
    source: str
    available_at_utc: datetime | None = None

    def __post_init__(self) -> None:
        _require_identifier(self.instrument_id, "instrument_id")
        _require_text(self.interval, "interval")
        if self.interval not in _SUPPORTED_INTERVALS:
            raise ValueError(
                f"El intervalo {self.interval!r} no está admitido; "
                "usa 1m, 1h o 1d."
            )
        _require_utc_datetime(self.start_utc, "start_utc")
        _require_utc_datetime(self.end_utc, "end_utc")
        if self.start_utc >= self.end_utc:
            raise ValueError("start_utc debe ser anterior a end_utc.")
        expected_duration = _INTRADAY_INTERVAL_DURATIONS.get(self.interval)
        if (
            expected_duration is not None
            and self.end_utc - self.start_utc != expected_duration
        ):
            raise ValueError(
                f"La duración de {self.interval} debe ser exactamente "
                f"{expected_duration}."
            )
        if self.session_date is not None and (
            not isinstance(self.session_date, date)
            or isinstance(self.session_date, datetime)
        ):
            raise ValueError("session_date debe ser una fecha de calendario o None.")
        if self.interval == "1d" and self.session_date is None:
            raise ValueError("Una vela diaria requiere una fecha de sesión.")

        for field_name in ("open", "high", "low", "close"):
            _require_positive_decimal(getattr(self, field_name), field_name)
        if not (
            self.low <= self.open <= self.high
            and self.low <= self.close <= self.high
        ):
            raise ValueError("Los valores OHLC deben respetar el rango low-high.")

        if self.volume is not None:
            if (
                not isinstance(self.volume, Decimal)
                or not self.volume.is_finite()
                or self.volume < 0
            ):
                raise ValueError("volume debe ser un Decimal no negativo y finito.")
            _require_text(self.volume_unit, "volume_unit")
        elif self.volume_unit is not None:
            raise ValueError("volume_unit debe ser None cuando volume es None.")

        if not isinstance(self.status, BarStatus):
            raise ValueError("status debe ser un valor de BarStatus.")
        if not isinstance(self.adjustment_type, AdjustmentType):
            raise ValueError("adjustment_type debe ser un valor de AdjustmentType.")
        _require_text(self.provider, "provider")
        _require_text(self.source, "source")

        if self.available_at_utc is not None:
            _require_utc_datetime(self.available_at_utc, "available_at_utc")
            if (
                self.status is BarStatus.CLOSED
                and self.available_at_utc < self.end_utc
            ):
                raise ValueError(
                    "Una vela cerrada no puede estar disponible antes de end_utc."
                )


def validate_bar_sequence(
    instrument: Instrument,
    bars: Sequence[OHLCVBar],
) -> None:
    """Valida una serie homogénea sin exigir una vela por día natural."""
    previous_bar = None
    first_bar = bars[0] if bars else None
    for index, bar in enumerate(bars):
        if bar.instrument_id != instrument.instrument_id:
            raise ValueError("La vela no pertenece al instrumento indicado.")
        if first_bar is not None:
            if bar.provider != first_bar.provider:
                raise ValueError("La serie no puede mezclar proveedores.")
            if bar.source != first_bar.source:
                raise ValueError("La serie no puede mezclar fuentes.")
            if bar.adjustment_type is not first_bar.adjustment_type:
                raise ValueError("La serie no puede mezclar tipos de ajuste.")
            if bar.volume_unit != first_bar.volume_unit:
                raise ValueError("La serie no puede mezclar unidades de volumen.")
            if bar.interval != first_bar.interval:
                raise ValueError("La secuencia no puede mezclar intervalos.")
        if bar.provider != instrument.provider:
            raise ValueError(
                "El proveedor de la vela debe coincidir con el instrumento."
            )
        if (
            bar.status is BarStatus.INCOMPLETE
            and index != len(bars) - 1
        ):
            raise ValueError("Una vela incompleta solo puede ser la última.")
        if previous_bar is not None:
            if bar.start_utc < previous_bar.end_utc:
                raise ValueError("Las velas de la serie se solapan.")
            if (
                bar.session_date is not None
                and previous_bar.session_date is not None
                and bar.session_date < previous_bar.session_date
            ):
                raise ValueError("Las fechas de sesión deben mantener el orden.")
            if bar.interval == "1d":
                if bar.session_date <= previous_bar.session_date:
                    raise ValueError(
                        "Las fechas de sesión diarias deben estar en orden y sin duplicados."
                    )

        if (
            bar.interval == "1d"
            and instrument.session_close_convention
            is SessionCloseConvention.UTC_INTERVAL_BOUNDARY
        ):
            if (
                bar.start_utc.hour != 0
                or bar.start_utc.minute != 0
                or bar.start_utc.second != 0
                or bar.start_utc.microsecond != 0
            ):
                raise ValueError("Una vela diaria UTC debe iniciar a las 00:00 UTC.")
            if bar.end_utc - bar.start_utc != timedelta(days=1):
                raise ValueError("Una vela diaria UTC debe durar exactamente 24 horas.")
            if bar.session_date != bar.start_utc.date():
                raise ValueError(
                    "La fecha de sesión debe coincidir con la fecha UTC de inicio."
                )
        elif (
            instrument.session_close_convention
            is SessionCloseConvention.LOCAL_EXCHANGE_CLOSE
        ):
            if bar.end_utc - bar.start_utc > timedelta(days=1):
                raise ValueError(
                    "La duración de una sesión local no puede superar 24 horas."
                )
            if bar.session_date is not None:
                # Provisional until official venue calendars and timezone
                # conversion are available; this does not replace either.
                utc_start_date = bar.start_utc.date()
                lower_bound = date.fromordinal(
                    max(1, utc_start_date.toordinal() - 1)
                )
                if not lower_bound <= bar.session_date <= bar.end_utc.date():
                    raise ValueError(
                        "La fecha de sesión está fuera del rango temporal provisional."
                    )
        previous_bar = bar
