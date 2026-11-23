# Autonomous Investment Agent

Proyecto personal para aprender a investigar mercados y desarrollar un sistema
de análisis de inversiones por etapas. No promete rentabilidad.

## Análisis local

El analizador lee precios históricos de un archivo CSV. Sus resultados son
descriptivos, no recomendaciones de inversión.

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

## Descargar precios diarios de BTC desde Kraken

El adaptador consulta el endpoint público de datos OHLC de Kraken para
`XBTUSD`. Solo obtiene datos de mercado: no usa API keys, no accede a cuentas y
no puede enviar operaciones. Kraken documenta hasta 720 velas OHLC; durante
nuestra comprobación observamos 721 entradas, incluida la vela abierta. El
adaptador descarta siempre la última entrada, sin depender de un número fijo
de velas. Las fechas del CSV se expresan como fechas de calendario UTC.

Desde la carpeta del proyecto, descarga las velas cerradas a un CSV:

```powershell
python -m investment_agent.market_data.kraken --output data\crypto\kraken_xbtusd_1d.csv
```

Después, analiza ese CSV con el programa existente:

```powershell
python -m investment_agent data\crypto\kraken_xbtusd_1d.csv --window 20
```

El archivo de destino solo se reemplaza después de validar la respuesta y
escribir correctamente un archivo temporal en la misma carpeta. Si la descarga,
la validación o la escritura fallan, se conserva el CSV anterior. Los CSV
descargados en `data\crypto` no se incluyen en Git.

## Ejecutar las pruebas

No hace falta instalar pytest; se usa el módulo de pruebas incluido con Python:

```powershell
python -m unittest discover -s tests -v
```

## Límites y siguientes etapas

La consulta devuelve un historial diario reciente, no un historial completo
para backtests de varios años. El analizador actual tampoco comprueba si faltan
días entre observaciones.

Los siguientes pasos serán evaluar otros proveedores y mercados por separado,
investigar estrategias con costes y datos históricos adecuados y, más adelante,
añadir simulación y controles de riesgo. Esta versión no conecta a servicios de
trading ni ejecuta órdenes.
