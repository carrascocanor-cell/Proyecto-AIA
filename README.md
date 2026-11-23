# Autonomous Investment Agent

Proyecto personal para aprender a investigar mercados y desarrollar un sistema
de análisis de inversiones por etapas. No promete rentabilidad.

## Primera versión

Esta versión analiza precios históricos que proporciones en un archivo CSV.
No se conecta a exchanges o brókeres, no utiliza modelos de IA y no envía
órdenes. Sus resultados son descriptivos, no recomendaciones de inversión.

El CSV debe tener las columnas `date` y `close`, con fechas diarias en formato
`YYYY-MM-DD`, ordenadas de más antigua a más reciente. El formato de cabecera
es:

```csv
date,close
```

El proyecto no incluye precios de muestra ni datos de mercado.

## Ejecutar el análisis

Desde la carpeta del proyecto:

```powershell
python -m investment_agent ruta\a\precios.csv
```

El análisis usa una media móvil de 20 observaciones por defecto. Puedes elegir
otra ventana con `--window`:

```powershell
python -m investment_agent ruta\a\precios.csv --window 5
```

Si no hay suficientes observaciones para calcular la media móvil, el programa
indicará que se abstiene de evaluar la tendencia.

## Ejecutar las pruebas

No hace falta instalar pytest; se usa el módulo de pruebas incluido con Python:

```powershell
python -m unittest discover -s tests -v
```

## Siguientes etapas

1. Validar este análisis local y comprender sus cálculos y límites.
2. Elegir proveedores de datos por mercado y añadir adaptadores independientes.
3. Investigar estrategias y probarlas con costes y datos históricos adecuados.
4. Añadir simulación y controles de riesgo antes de considerar cualquier ejecución.
