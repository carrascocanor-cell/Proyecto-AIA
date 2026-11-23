"""Interfaz de línea de comandos para analizar un CSV de precios."""

import argparse

from investment_agent.analysis import analyze_prices, load_close_prices


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Analiza precios históricos de un CSV; no genera órdenes."
    )
    parser.add_argument("csv_path", help="Ruta a un CSV con columnas date y close")
    parser.add_argument(
        "--window",
        type=int,
        default=20,
        help="Número de observaciones para la media móvil (por defecto: 20)",
    )
    args = parser.parse_args()

    try:
        prices = load_close_prices(args.csv_path)
        result = analyze_prices(prices, args.window)
    except (OSError, ValueError) as error:
        parser.error(str(error))

    print(f"Observaciones: {result['observations']}")
    if result["period_return_pct"] is None:
        print("Cambio del periodo: no disponible (solo una observación)")
    else:
        print(f"Cambio del periodo: {result['period_return_pct']:.2f}%")

    if result["trend"] == "insufficient_data":
        print(
            f"Tendencia: abstención (se necesitan al menos "
            f"{result['window']} observaciones)"
        )
    else:
        print(f"Media móvil ({result['window']}): {result['moving_average']:.6g}")
        print(f"Último precio respecto a la media: {result['trend']}")

    print("Análisis descriptivo únicamente; no es una recomendación ni una orden.")


if __name__ == "__main__":
    main()
