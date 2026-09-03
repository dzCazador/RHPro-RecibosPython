# ReciboPdfPY

Aplicacion Python para obtener recibos de sueldo desde SQL Server y generar archivos PDF a partir de una plantilla Jinja2.

## Requisitos

- Windows.
- Python 3.13 o compatible.
- Microsoft ODBC Driver 17 for SQL Server.
- `wkhtmltopdf` instalado.
- Acceso a la base de datos configurada.

La aplicacion busca `wkhtmltopdf` en estas ubicaciones:

- `wkhtmltopdf\bin\wkhtmltopdf.exe`, junto al programa.
- `C:\Program Files\wkhtmltopdf\bin\wkhtmltopdf.exe`.
- `C:\Program Files (x86)\wkhtmltopdf\bin\wkhtmltopdf.exe`.
- El `PATH` del sistema.

## Instalacion

Crear o activar el entorno virtual:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

Instalar las dependencias Python desde el archivo del proyecto:

```powershell
python -m pip install -r requirements.txt
```

Verificar `wkhtmltopdf`:

```powershell
wkhtmltopdf --version
```

Si no esta en el `PATH`, instalarlo desde [wkhtmltopdf.org](https://wkhtmltopdf.org/downloads.html). La aplicacion tambien detecta automaticamente la ruta habitual de instalacion.

## Configuracion

Editar `config.ini`:

```ini
[DATABASE]
SERVER = servidor_sql
DATABASE = base_de_datos
USERNAME = usuario
PASSWORD = contrasena
DRIVER = {ODBC Driver 17 for SQL Server}

[REPORTS]
TEMPLATE_FILE = template_recibo-doble.html
OUTPUT_PREFIX = D:\Reportes\
```

`OUTPUT_PREFIX` debe terminar en una carpeta existente o creable por el usuario que ejecuta el programa.

No publicar `config.ini` con credenciales reales. Usar un archivo local y excluirlo del control de versiones cuando corresponda.

## Uso

El argumento obligatorio es el numero de periodo `bpronro`.

### Parametros

| Parametro | Obligatorio | Valores | Predeterminado | Descripcion |
|---|---:|---|---|---|
| `bpronro` | Si | Numero entero | Sin valor | Periodo de liquidacion que se consultara en la base de datos. |
| `-html` / `--html-only` | No | Opcion sin valor | Desactivado | Genera solamente el HTML para depuracion y no convierte a PDF. |
| `-landscape` | No | `True` o `False` | `False` | Define la orientacion del PDF. `True` usa A4 horizontal; `False` usa A4 vertical. |
| `-multiple` | No | `True` o `False` | `False` | `True` genera un unico PDF con todos los recibos; `False` genera un PDF por empleado y luego un ZIP. |

Los parametros `-landscape` y `-multiple` reciben texto, por lo que deben escribirse con un valor explicito. No usar solamente `-landscape` o `-multiple` sin `=True` o `=False`.

Ver la ayuda completa del programa:

```powershell
python .\generar_recibos.py --help
```

Generar un ZIP con un PDF por empleado:

```powershell
python .\generar_recibos.py 586323
```

El resultado se guarda como:

```text
<OUTPUT_PREFIX>586323.zip
```

Generar un unico PDF con todos los recibos:

```powershell
python .\generar_recibos.py 586323 -multiple=true -landscape=true
```

Generar solamente HTML para revisar el resultado:

```powershell
python .\generar_recibos.py 586323 --html-only
```

Forzar orientacion horizontal para PDF:

```powershell
python .\generar_recibos.py 586323 -landscape=true
```

## Salida del recibo

La plantilla `template_recibo-doble.html` genera dos ejemplares por recibo:

- Original.
- Duplicado.

Cada recibo incluye:

- Datos de empresa y empleado.
- Detalle de conceptos salariales.
- Totales y neto pagado.
- Costo total del empleador dividido en dos columnas.
- Composicion salarial agrupada por costo sindical, INSSJP, seguridad social, ART, obra social y SCVO.
- Grafico de torta 2D con porciones separadas y leyenda inferior.
- Escala de grises para impresion blanco y negro.

Los datos de costo patronal y composicion se obtienen mediante:

```sql
dbo.fnRHProReciboContribuciones_Tabla(cliqnro)
```

## Dependencias de datos

La consulta de cabeceras obtiene `CQ.cliqnro` desde `cabliq`. Ese valor se utiliza para consultar los registros de contribuciones del empleado.

La funcion de contribuciones debe devolver, como minimo, estas columnas:

- `Conccod`
- `Concabr`
- `Monto`
- `Dlicant`
- `Tipo`
- `IsTotal`

Los registros `Tipo = Detalle` se muestran en costo total del empleador. El registro con `IsTotal = 1` se muestra como `Total Contrib. Patronales`. Los registros `Tipo = Composicion` se agrupan en el detalle de composicion salarial.

## Compilacion opcional

El proyecto incluye `generar_recibos.spec` para PyInstaller. Instalarlo y compilar con:

```powershell
python -m pip install pyinstaller
pyinstaller .\generar_recibos.spec
```

El ejecutable se genera en `dist\generar_recibos.exe`.

Al distribuir el ejecutable, incluir junto a el:

- `config.ini`
	- `template_recibo-doble.html`
- El ejecutable de `wkhtmltopdf`, o una instalacion de `wkhtmltopdf` en el equipo destino.

## Problemas frecuentes

### `ModuleNotFoundError`

Instalar el modulo faltante en el mismo entorno con el que se ejecuta el programa:

```powershell
python -m pip install -r requirements.txt
```

### `No wkhtmltopdf executable found`

Verificar:

```powershell
wkhtmltopdf --version
```

Si el comando no existe, instalar `wkhtmltopdf` o agregar su carpeta `bin` al `PATH`.

### No se encontraron recibos

Confirmar que el periodo `bpronro` exista en la base de datos y que las credenciales de `config.ini` sean correctas.

## Archivos principales

- `generar_recibos.py`: conexion, consultas, calculos y generacion de archivos.
- `template_recibo-doble.html`: plantilla HTML de Original y Duplicado.
- `requirements.txt`: dependencias Python del proyecto.
- `num_a_letras.py`: conversion del importe neto a letras.
- `config.ini`: configuracion local de base de datos y reportes.
- `generar_recibos.spec`: configuracion opcional de PyInstaller.
