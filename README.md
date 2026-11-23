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

## Backtest SMA(20)

El motor independiente compara una estrategia larga o en efectivo basada en
SMA(20) con Buy & Hold. La señal se calcula al cierre del día y se simula su
ejecución al cierre del día siguiente. Esa ejecución exactamente al cierre
siguiente es una hipótesis simplificada y no garantiza un precio alcanzable en
operaciones reales.

La estrategia comienza en efectivo, no usa apalancamiento ni posiciones cortas,
y no ejecuta la última señal si no existe un cierre posterior. Se comparan el
periodo completo y un periodo operativo común que comienza en la primera fecha
en que la estrategia puede ejecutar una señal; ambas carteras de cada
comparación usan fechas y capital inicial equivalentes. Las fechas diarias
ausentes se rechazan.

Las posiciones al final del periodo se valoran al último cierre, sin una venta
forzada. El informe separa el valor de mercado (efectivo más BTC al último
cierre) del valor hipotético de liquidación, que estima el efectivo neto si la
posición abierta se vendiera a ese cierre descontando deslizamiento y comisión.
La liquidación es solo una métrica: no añade una ejecución a la simulación.
El drawdown se calcula sobre la curva diaria a valor de mercado.

El informe identifica las fechas inicial y final, el número de observaciones y
el hash SHA-256 de los mismos bytes del CSV que se analizaron.

Indica explícitamente el capital y los costes por lado en puntos básicos (bps):

```powershell
python -m investment_agent.backtest data\crypto\kraken_xbtusd_1d.csv --capital 10000 --commission-bps 0 --slippage-bps 0
```

En cada compra, el precio simulado incluye deslizamiento adverso; la venta
también lo incluye. Las comisiones se aplican al valor ejecutado. Los valores
de coste deben corresponder al escenario que se quiere estudiar: cero bps es
un resultado bruto, no una estimación realista. El informe separa comisiones,
deslizamiento, ejecuciones y operaciones completas, y calcula rentabilidad y
drawdown máximo.

El cierre diario no revela la trayectoria intradía, el spread, la liquidez ni
los precios que habrían estado disponibles durante la ejecución. El historial
reciente de BTC/USD tampoco basta para demostrar robustez, y estas pruebas
sintéticas solo verifican las fórmulas, no la rentabilidad de la estrategia.

Antes de optimizar estrategias, separaremos los datos cronológicamente en un
periodo de investigación y otro de validación. Los parámetros se desarrollarán
solo con el periodo de investigación; el periodo de validación permanecerá
intacto hasta congelar estrategia, costes y reglas. No seleccionaremos ni
ajustaremos estrategias según los resultados del periodo reservado. Cada
evaluación registrará el hash del CSV y los supuestos usados. Con el historial
reciente disponible, no se debe asumir que un corte concreto produce una
validación estadísticamente suficiente.

## Ejecutar las pruebas

No hace falta instalar pytest; se usa el módulo de pruebas incluido con Python:

```powershell
python -m unittest discover -s tests -v
```

## Límites y siguientes etapas

La consulta devuelve un historial diario reciente, no un historial completo
para backtests de varios años. El analizador descriptivo actual no comprueba si
faltan días; el motor de backtesting sí los rechaza.

Los siguientes pasos serán evaluar otros proveedores y mercados por separado,
investigar estrategias con costes y datos históricos adecuados y, más adelante,
añadir simulación y controles de riesgo. Esta versión no conecta a servicios de
trading ni ejecuta órdenes.
