"""Backtest diario de una estrategia larga basada en una media móvil de 20 días."""

import argparse
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path

from investment_agent.price_history import (
    PriceBar,
    load_price_history_with_hash,
)


SMA_WINDOW = 20
BASIS_POINTS = Decimal("10000")
ZERO = Decimal("0")
ONE = Decimal("1")


@dataclass(frozen=True)
class BacktestConfig:
    initial_capital: Decimal
    commission_bps: Decimal
    slippage_bps: Decimal

    def __post_init__(self) -> None:
        values = (
            ("capital inicial", self.initial_capital),
            ("comisión", self.commission_bps),
            ("deslizamiento", self.slippage_bps),
        )
        for name, value in values:
            if not value.is_finite():
                raise ValueError(f"El valor de {name} debe ser finito.")
        if self.initial_capital <= ZERO:
            raise ValueError("El capital inicial debe ser positivo.")
        if not ZERO <= self.commission_bps < BASIS_POINTS:
            raise ValueError("La comisión debe estar entre 0 y 9999.9999 bps.")
        if not ZERO <= self.slippage_bps < BASIS_POINTS:
            raise ValueError("El deslizamiento debe estar entre 0 y 9999.9999 bps.")

    @property
    def commission_rate(self) -> Decimal:
        return self.commission_bps / BASIS_POINTS

    @property
    def slippage_rate(self) -> Decimal:
        return self.slippage_bps / BASIS_POINTS


@dataclass(frozen=True)
class EquityPoint:
    date: date
    cash: Decimal
    btc: Decimal
    close: Decimal
    equity: Decimal


@dataclass(frozen=True)
class Execution:
    side: str
    signal_date: date | None
    date: date
    reference_price: Decimal
    execution_price: Decimal
    btc_quantity: Decimal
    commission: Decimal
    slippage_cost: Decimal


@dataclass(frozen=True)
class PortfolioResult:
    start_date: date
    end_date: date
    initial_capital: Decimal
    final_market_value: Decimal
    final_liquidation_value: Decimal
    liquidation_commission: Decimal
    liquidation_slippage: Decimal
    return_pct: Decimal
    max_drawdown_pct: Decimal
    executions: tuple[Execution, ...]
    equity_curve: tuple[EquityPoint, ...]
    total_commission: Decimal
    total_slippage: Decimal
    final_cash: Decimal
    final_btc: Decimal

    @property
    def final_equity(self) -> Decimal:
        """Alias del valor de mercado al cierre para compatibilidad."""
        return self.final_market_value

    @property
    def liquidation_return_pct(self) -> Decimal:
        return (self.final_liquidation_value / self.initial_capital - ONE) * 100

    @property
    def completed_round_trips(self) -> int:
        return sum(execution.side == "sell" for execution in self.executions)

    @property
    def open_position(self) -> bool:
        return self.final_btc > ZERO


@dataclass(frozen=True)
class PeriodComparison:
    label: str
    strategy: PortfolioResult
    buy_and_hold: PortfolioResult


@dataclass(frozen=True)
class BacktestReport:
    full_period: PeriodComparison
    common_operational_period: PeriodComparison | None
    initial_date: date
    final_date: date
    observations: int
    csv_sha256: str | None


def _validate_bars(bars: list[PriceBar]) -> None:
    if not bars:
        raise ValueError("El historial no contiene precios.")

    previous_date = None
    for bar in bars:
        if not isinstance(bar.close, Decimal) or not bar.close.is_finite() or bar.close <= ZERO:
            raise ValueError("Todos los cierres deben ser decimales positivos y finitos.")
        if previous_date is not None:
            if bar.date != previous_date + timedelta(days=1):
                raise ValueError("El historial diario contiene fechas duplicadas o días ausentes.")
        previous_date = bar.date


def _build_signals(bars: list[PriceBar]) -> list[bool | None]:
    signals: list[bool | None] = [None] * len(bars)
    for index in range(SMA_WINDOW - 1, len(bars)):
        moving_average = sum(
            (bar.close for bar in bars[index - SMA_WINDOW + 1 : index + 1]),
            start=ZERO,
        ) / SMA_WINDOW
        signals[index] = bars[index].close > moving_average
    return signals


def _buy(
    cash: Decimal,
    reference_price: Decimal,
    config: BacktestConfig,
) -> tuple[Decimal, Decimal, Decimal, Decimal, Decimal]:
    execution_price = reference_price * (ONE + config.slippage_rate)
    unit_cost = execution_price * (ONE + config.commission_rate)
    quantity = cash / unit_cost

    while quantity > ZERO:
        notional = quantity * execution_price
        commission = notional * config.commission_rate
        total_cost = notional + commission
        if total_cost <= cash:
            break
        quantity = quantity.next_minus()

    if quantity <= ZERO:
        raise ArithmeticError("No se pudo calcular una compra dentro del efectivo disponible.")

    slippage_cost = (execution_price - reference_price) * quantity
    remaining_cash = cash - total_cost
    if remaining_cash < ZERO:
        raise ArithmeticError("La compra excedería el efectivo disponible.")

    return quantity, remaining_cash, execution_price, commission, slippage_cost


def _simulate(
    bars: list[PriceBar],
    signals: list[bool | None],
    config: BacktestConfig,
    start_index: int,
    buy_and_hold: bool,
) -> PortfolioResult:
    cash = config.initial_capital
    quantity = ZERO
    executions: list[Execution] = []
    equity_curve: list[EquityPoint] = []
    total_commission = ZERO
    total_slippage = ZERO
    peak_equity = config.initial_capital
    max_drawdown = ZERO

    for index in range(start_index, len(bars)):
        bar = bars[index]
        if buy_and_hold:
            target_long = index == start_index or quantity > ZERO
            signal_date = None
        elif index > 0 and signals[index - 1] is not None:
            target_long = signals[index - 1]
            signal_date = bars[index - 1].date
        else:
            target_long = None
            signal_date = None

        is_long = quantity > ZERO
        if target_long is not None and target_long != is_long:
            if target_long:
                quantity, cash, execution_price, commission, slippage_cost = _buy(
                    cash, bar.close, config
                )
                side = "buy"
                executed_quantity = quantity
            else:
                executed_quantity = quantity
                execution_price = bar.close * (ONE - config.slippage_rate)
                notional = quantity * execution_price
                commission = notional * config.commission_rate
                slippage_cost = (bar.close - execution_price) * quantity
                cash += notional - commission
                quantity = ZERO
                side = "sell"

            if cash < ZERO or quantity < ZERO:
                raise ArithmeticError("La simulación produjo un saldo negativo.")
            total_commission += commission
            total_slippage += slippage_cost
            executions.append(
                Execution(
                    side=side,
                    signal_date=signal_date,
                    date=bar.date,
                    reference_price=bar.close,
                    execution_price=execution_price,
                    btc_quantity=executed_quantity,
                    commission=commission,
                    slippage_cost=slippage_cost,
                )
            )

        equity = cash + quantity * bar.close
        if cash < ZERO or quantity < ZERO or not equity.is_finite() or equity < ZERO:
            raise ArithmeticError("La simulación produjo un saldo o capital no válido.")

        peak_equity = max(peak_equity, equity)
        drawdown = (peak_equity - equity) / peak_equity * 100
        max_drawdown = max(max_drawdown, drawdown)
        equity_curve.append(EquityPoint(bar.date, cash, quantity, bar.close, equity))

    final_market_value = equity_curve[-1].equity
    final_liquidation_value = final_market_value
    liquidation_commission = ZERO
    liquidation_slippage = ZERO
    if quantity > ZERO:
        liquidation_price = bars[-1].close * (ONE - config.slippage_rate)
        liquidation_notional = quantity * liquidation_price
        liquidation_commission = liquidation_notional * config.commission_rate
        liquidation_slippage = (bars[-1].close - liquidation_price) * quantity
        final_liquidation_value = cash + liquidation_notional - liquidation_commission

    return PortfolioResult(
        start_date=bars[start_index].date,
        end_date=bars[-1].date,
        initial_capital=config.initial_capital,
        final_market_value=final_market_value,
        final_liquidation_value=final_liquidation_value,
        liquidation_commission=liquidation_commission,
        liquidation_slippage=liquidation_slippage,
        return_pct=(final_market_value / config.initial_capital - ONE) * 100,
        max_drawdown_pct=max_drawdown,
        executions=tuple(executions),
        equity_curve=tuple(equity_curve),
        total_commission=total_commission,
        total_slippage=total_slippage,
        final_cash=cash,
        final_btc=quantity,
    )


def run_backtest(
    bars: list[PriceBar],
    config: BacktestConfig,
    csv_sha256: str | None = None,
) -> BacktestReport:
    """Compara SMA(20) con Buy & Hold en el periodo completo y el común."""
    _validate_bars(bars)
    if csv_sha256 is not None and (
        len(csv_sha256) != 64
        or any(character not in "0123456789abcdef" for character in csv_sha256.lower())
    ):
        raise ValueError("El hash SHA-256 del CSV debe contener 64 caracteres hexadecimales.")
    signals = _build_signals(bars)

    full_period = PeriodComparison(
        label="Periodo completo",
        strategy=_simulate(bars, signals, config, 0, buy_and_hold=False),
        buy_and_hold=_simulate(bars, signals, config, 0, buy_and_hold=True),
    )

    first_operational_index = next(
        (
            index
            for index in range(1, len(bars))
            if signals[index - 1] is not None
        ),
        None,
    )
    common_period = None
    if first_operational_index is not None:
        common_period = PeriodComparison(
            label="Periodo operativo común",
            strategy=_simulate(
                bars, signals, config, first_operational_index, buy_and_hold=False
            ),
            buy_and_hold=_simulate(
                bars, signals, config, first_operational_index, buy_and_hold=True
            ),
        )

    return BacktestReport(
        full_period=full_period,
        common_operational_period=common_period,
        initial_date=bars[0].date,
        final_date=bars[-1].date,
        observations=len(bars),
        csv_sha256=csv_sha256,
    )


def _parse_decimal(value: str) -> Decimal:
    try:
        return Decimal(value)
    except InvalidOperation as error:
        raise argparse.ArgumentTypeError("Introduce un número decimal válido.") from error


def _print_result(label: str, result: PortfolioResult) -> None:
    print(f"  {label}:")
    print(f"    Fechas: {result.start_date} a {result.end_date}")
    print(f"    Capital inicial: {result.initial_capital:.2f} USD")
    print(f"    Valor de mercado final: {result.final_market_value:.2f} USD")
    print(f"    Rentabilidad a valor de mercado: {result.return_pct:.2f}%")
    print(
        f"    Valor de liquidación hipotético: "
        f"{result.final_liquidation_value:.2f} USD"
    )
    print(f"    Rentabilidad liquidando al final: {result.liquidation_return_pct:.2f}%")
    print(f"    Drawdown máximo (valor de mercado): {result.max_drawdown_pct:.2f}%")
    print(f"    Ejecuciones: {len(result.executions)}")
    print(f"    Operaciones completas: {result.completed_round_trips}")
    print(f"    Posición abierta al final: {'sí' if result.open_position else 'no'}")
    print(f"    Comisiones: {result.total_commission:.8f} USD")
    print(f"    Deslizamiento estimado: {result.total_slippage:.8f} USD")
    print(
        f"    Costes totales: "
        f"{result.total_commission + result.total_slippage:.8f} USD"
    )
    if result.open_position:
        print(
            f"    Costes hipotéticos de liquidación: "
            f"comisión {result.liquidation_commission:.8f} USD; "
            f"deslizamiento {result.liquidation_slippage:.8f} USD"
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Backtest diario SMA(20), sin conexión a servicios de trading."
    )
    parser.add_argument("csv_path", type=Path, help="CSV con columnas date y close")
    parser.add_argument("--capital", required=True, type=_parse_decimal, help="Capital inicial en USD")
    parser.add_argument(
        "--commission-bps",
        required=True,
        type=_parse_decimal,
        help="Comisión por lado, en puntos básicos",
    )
    parser.add_argument(
        "--slippage-bps",
        required=True,
        type=_parse_decimal,
        help="Deslizamiento por lado, en puntos básicos",
    )
    args = parser.parse_args()

    try:
        bars, csv_sha256 = load_price_history_with_hash(args.csv_path)
        config = BacktestConfig(args.capital, args.commission_bps, args.slippage_bps)
        report = run_backtest(bars, config, csv_sha256=csv_sha256)
    except (OSError, ValueError, ArithmeticError) as error:
        parser.error(str(error))

    print(f"Estrategia: SMA({SMA_WINDOW}), señal al cierre y ejecución al cierre siguiente")
    print(
        f"CSV: {report.initial_date} a {report.final_date}; "
        f"{report.observations} observaciones"
    )
    print(f"SHA-256 del CSV: {report.csv_sha256}")
    print(
        f"Costes configurados: comisión {args.commission_bps} bps por lado; "
        f"deslizamiento {args.slippage_bps} bps por lado"
    )
    print("Escenario descriptivo; no es una recomendación ni una predicción.")
    _print_result("SMA(20), periodo completo", report.full_period.strategy)
    _print_result("Buy & Hold, periodo completo", report.full_period.buy_and_hold)
    if report.common_operational_period is None:
        print("Periodo operativo común: no disponible (historial insuficiente).")
    else:
        _print_result(
            "SMA(20), periodo operativo común",
            report.common_operational_period.strategy,
        )
        _print_result(
            "Buy & Hold, periodo operativo común",
            report.common_operational_period.buy_and_hold,
        )
    print(
        "La ejecución exactamente al cierre siguiente es una hipótesis simplificada; "
        "no garantiza un precio alcanzable en operaciones reales."
    )
    print(
        "El backtest no ejecuta órdenes y no modela liquidez, impuestos ni "
        "trayectoria intradía."
    )


if __name__ == "__main__":
    main()
