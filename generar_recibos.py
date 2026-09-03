import pyodbc
from jinja2 import Environment, FileSystemLoader
import pdfkit 
import configparser
import argparse
import sys
from datetime import datetime
import re
import os
import shutil # <-- PARA GESTIÓN DE ARCHIVOS Y COMPRESIÓN
import tempfile # Para obtener el directorio temporal del sistema
import math
from num_a_letras import convertir_neto_a_letras


# Define la ruta base donde se encuentra este script
# --- NUEVA LÓGICA PARA DETECTAR RUTA DEL EJECUTABLE ---
if getattr(sys, 'frozen', False):
    # Si el script está "congelado" (es un .exe), usa la ruta del ejecutable
    BASE_DIR = os.path.dirname(sys.executable)
else:
    # Si corre como script normal .py, usa la ruta del archivo
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

print(f"Ruta base detectada: {BASE_DIR}")

WKHTMLTOPDF_CANDIDATES = [
    os.path.join(BASE_DIR, 'wkhtmltopdf', 'bin', 'wkhtmltopdf.exe'),
    r'C:\Program Files\wkhtmltopdf\bin\wkhtmltopdf.exe',
    r'C:\Program Files (x86)\wkhtmltopdf\bin\wkhtmltopdf.exe',
]
WKHTMLTOPDF_PATH = next(
    (path for path in WKHTMLTOPDF_CANDIDATES if os.path.isfile(path)),
    shutil.which('wkhtmltopdf')
)



# --- 1. Cargar Configuración ---
def cargar_configuracion(config_file='config.ini'):
    """Carga la configuración de DB y Reportes desde un archivo .ini."""
    config = configparser.ConfigParser()
    try:
        # CONCATENAMOS la ruta base con el nombre del archivo
        config_path = os.path.join(BASE_DIR, config_file) 
        config.read_file(open(config_path)) # Usamos la ruta completa
        return config
    except Exception as e:
        print(f"Error al leer el archivo de configuración '{config_path}': {e}") # Mostramos la ruta que falló
        sys.exit(1)

# --- 2. Obtener Parámetros de Entrada ---
def obtener_argumentos():
    """Define y parsea los argumentos de línea de comandos."""
    parser = argparse.ArgumentParser(
        description="Genera recibos de sueldo en PDF a partir de una base de datos MSSQL."
    )
    parser.add_argument(
        'bpronro', 
        type=int, 
        help="Número de periodo (BPRONRO) para el cual se generarán los recibos. Ejemplo: 202411"
    )
    parser.add_argument(
        '-html', 
        '--html-only', 
        action='store_true', 
        help="Si se especifica, genera solo el archivo HTML para debug en lugar del PDF."
    )
    parser.add_argument(
        '-landscape', 
        type=str,
        default='False',
        help="Establece la orientación del PDF. Valores: 'True' o 'False'."
    )    
    parser.add_argument(
        '-multiple', 
        type=str,
        default='False',
        help="Controla la salida del PDF. 'True' (un solo PDF con todos los recibos) o 'False' (un PDF por empleado)."
    )
    # parse_known_args devuelve una tupla: (argumentos_conocidos, lista_de_sobrantes)
    args, _ = parser.parse_known_args()
    
    return args


# --- 3. Funciones de UTILIDAD y ESTADO DE BATCH ---

def obtener_conexion(config):
    """Establece y devuelve la conexión a la DB."""
    DB_SERVER = config['DATABASE']['SERVER']
    DB_DATABASE = config['DATABASE']['DATABASE']
    DB_USERNAME = config['DATABASE']['USERNAME']
    DB_PASSWORD = config['DATABASE']['PASSWORD']
    DRIVER = config['DATABASE']['DRIVER']
    
    conn_str = (
        f'DRIVER={DRIVER};'
        f'SERVER={DB_SERVER};'
        f'DATABASE={DB_DATABASE};'
        f'UID={DB_USERNAME};'
        f'PWD={DB_PASSWORD};'
    )
    return pyodbc.connect(conn_str)

def actualizar_batch(config, bpronro, estado=None, progreso=None):
    """
    Actualiza el estado y/o el progreso en la tabla batch_proceso.
    """
    if estado is None and progreso is None:
        return

    conn = None
    try:
        conn = obtener_conexion(config)
        cursor = conn.cursor()
        
        # Construimos la consulta dinámicamente según lo que se envíe
        campos = []
        valores = []
        
        if estado is not None:
            campos.append("bprcestado = ?")
            valores.append(estado)
        
        if progreso is not None:
            campos.append("bprcprogreso = ?")
            valores.append(float(progreso))
            
        valores.append(bpronro) # Para el WHERE
        
        query = f"UPDATE batch_proceso SET {', '.join(campos)} WHERE bpronro = ?"
        
        cursor.execute(query, *valores)
        conn.commit()
        
    except pyodbc.Error as ex:
        print(f"!!! ADVERTENCIA: No se pudo actualizar batch_proceso: {ex}")
    finally:
        if conn:
            conn.close()
            

# --- Funciones Auxiliares de Lógica ASP (Mes, clasificar_concepto, etc.) ---
# [Mantenemos las funciones auxiliares de clasificación y formato de la respuesta anterior]

def clasificar_concepto(concepto_data):
    """Clasifica el concepto según la lógica del ASP: conctipo (1, 2) y tconnro (6, 13) para descuentos."""
    conctipo = concepto_data.get('conctipo')
    tconnro = concepto_data.get('tconnro')
    
    if conctipo is None: return None
    try:
        conctipo = int(conctipo)
        tconnro = int(tconnro) if tconnro is not None else None
    except ValueError:
        return None 

    if tconnro == 1:
        return 'REMUNERATIVO'
    elif tconnro == 2:
        return 'NO_REMUNERATIVO'
    elif tconnro == 3:
        if tconnro in (6, 13):
            return 'DESCUENTO'
        else:
            return 'OTROS_DESC'
            
    return None

def formatear_dni_desde_cuil(cuil):
    """Extrae el DNI del formato CUIL XX-XXXXXXXX-X, replicando la lógica ASP: mid(l_cuil, 4, 8)"""
    if cuil is None: return 'N/A'
    cuil_str = str(cuil).replace('-', '').replace(' ', '')
    if len(cuil_str) >= 11:
        return cuil_str[2:10]
    return cuil_str


def Mes(nro):
    """Función Auxiliar Mes() replicada de ASP."""
    meses = {
        1: "Enero", 2: "Febrero", 3: "Marzo", 4: "Abril", 5: "Mayo", 6: "Junio", 
        7: "Julio", 8: "Agosto", 9: "Septiembre", 10: "Octubre", 11: "Noviembre", 12: "Diciembre"
    }
    return meses.get(nro, str(nro))

def format_date_safe(date_val):
    """Manejo de fechas para formatear sin AttributeError."""
    if date_val is None:
        return ''
    if isinstance(date_val, datetime):
        return date_val.strftime('%d/%m/%Y')
    try:
        # Asumimos formato 'YYYY-MM-DD' si viene como string de la DB (el error anterior)
        date_obj = datetime.strptime(str(date_val).split()[0], '%Y-%m-%d')
        return date_obj.strftime('%d/%m/%Y')
    except Exception:
        return str(date_val)

# --- Formato Numerico
def fmt(valor):
    """Formato: 14.000.000 (Sin decimales, miles con punto)"""
    if valor is None or valor == 0 or valor == "":
        return ""
    try:
        # Formateamos como entero con separador de miles
        # El replace final asegura el punto para los miles
        return "{:,.2f}".format(float(valor))
    except (ValueError, TypeError):
        return ""

def numero(valor):
    try:
        return float(valor or 0)
    except (ValueError, TypeError):
        return 0.0

def crear_segmentos_torta(valores):
    colores = ['#222222', '#666666', '#999999', '#c0c0c0', '#eeeeee']
    nombres = ['Neto', 'Seg. Soc.', 'Sind.', 'O. Soc.', 'ART']
    posiciones = [(137, 18), (2, 18), (2, 76), (137, 76), (137, 108)]
    total = sum(max(valor, 0) for valor in valores)
    segmentos = []
    angulo_actual = -90.0
    centro_x, centro_y, radio, separacion = 80, 55, 40, 3

    for indice, valor in enumerate(valores):
        porcentaje = round(max(valor, 0) / total * 100, 2) if total else 0.0
        angulo = porcentaje * 3.6
        inicio = math.radians(angulo_actual)
        fin = math.radians(angulo_actual + angulo)
        mitad = math.radians(angulo_actual + angulo / 2)
        desplazamiento_x = separacion * math.cos(mitad)
        desplazamiento_y = separacion * math.sin(mitad)
        sector_x = centro_x + desplazamiento_x
        sector_y = centro_y + desplazamiento_y
        x1, y1 = sector_x + radio * math.cos(inicio), sector_y + radio * math.sin(inicio)
        x2, y2 = sector_x + radio * math.cos(fin), sector_y + radio * math.sin(fin)
        arco_grande = 1 if angulo > 180 else 0
        path = f'M {sector_x:.3f} {sector_y:.3f} L {x1:.3f} {y1:.3f} A {radio} {radio} 0 {arco_grande} 1 {x2:.3f} {y2:.3f} Z'
        punto_x = sector_x + radio * math.cos(mitad)
        punto_y = sector_y + radio * math.sin(mitad)
        etiqueta_x, etiqueta_y = posiciones[indice]
        lado_derecho = etiqueta_x > centro_x
        codo_x = 133 if lado_derecho else 37
        salida_x = etiqueta_x - 2 if lado_derecho else etiqueta_x + 32
        leader_path = (
            f'M {punto_x:.2f} {punto_y:.2f} '
            f'L {codo_x} {punto_y:.2f} L {codo_x} {etiqueta_y} '
            f'L {salida_x} {etiqueta_y}'
        )
        segmentos.append({
            'path': path,
            'color': colores[indice],
            'porcentaje': porcentaje,
            'nombre': nombres[indice],
            'line_x1': punto_x,
            'line_y1': punto_y,
            'line_x2': salida_x,
            'line_y2': etiqueta_y,
            'leader_path': leader_path,
            'label_x': etiqueta_x,
            'label_y': etiqueta_y,
            'anchor': 'start' if lado_derecho else 'start',
        })
        angulo_actual += angulo

    return segmentos

# --- 4. Función de Conexión y Consulta de Datos (Aislamos la lógica de conexión) ---
def conectar_y_obtener_datos(config, bpronro_filtro):
    """
    Conecta a la DB y obtiene los datos, procesándolos según la lógica ASP.
    """
    conn = None
    try:
        conn = obtener_conexion(config)
        cursor = conn.cursor()
        print(f"Buscando recibos para BPRONRO: {bpronro_filtro}...")
        
        # 1. Consulta para obtener las cabeceras (replicando la consulta ASP)
        query_cabeceras = f"""
        SELECT 
            bpronro, R.ternro, R.pronro, apellido AS terape, nombre AS terape_nombre, 
            auxchar6 AS terdom, legajo, R.pliqnro, pliqmes, pliqanio, pliqdepant, pliqfecdep, 
            pliqbco, cuil, empfecalta AS terfecing, sueldo AS sueldo_base, 
            categoria, centrocosto, R.profecpago, formapago, empnombre, empdire, empcuit, 
            emplogo, emplogoalto, emplogoancho, empfirma, empfirmaalto, empfirmaancho,
            tprocdesc AS tipoproc, bandesc AS banco_desc,
            categoria AS calificacion, auxchar3 AS os_eleg, auxchar2 AS sector, 
            auxchar1 AS empfecbaja, auxchar5 AS sucursal,puesto, auxchar1 AS gerencia,
            auxchar3 AS periodo_desde, auxchar4 AS periodo_hasta,
            DNI.nrodoc DNI, TEL.telnro AS telefono,
            CQ.cliqnro
            
        FROM rep_recibo R
        INNER JOIN proceso P ON P.pronro = R.pronro
        LEFT  JOIN cabliq CQ ON CQ.pronro = P.pronro AND CQ.empleado = R.ternro
        INNER JOIN tipoproc TP ON TP.tprocnro = P.tprocnro
        LEFT JOIN ctabancaria CB ON CB.ctabestado = -1 AND CB.ternro = R.ternro
        LEFT JOIN ter_doc DNI ON DNI.ternro = R.ternro AND DNI.tidnro <= 4
        LEFT JOIN banco B ON B.ternro = CB.banco
		LEFT JOIN cabdom CD ON CD.ternro = R.ternro 
		LEFT JOIN telefono TEL ON TEL.domnro = CD.domnro AND TEL.tipotel = 1        
        WHERE bpronro = ?
        ORDER BY centrocosto, legajo;
        """
        #print(query_cabeceras)
        cursor.execute(query_cabeceras, bpronro_filtro)
        cabeceras = [dict(zip([column[0] for column in cursor.description], row)) for row in cursor.fetchall()]
        
        if not cabeceras:
            print(query_cabeceras + "\n")
            print("No se encontraron recibos con ese filtro.")
            return []

        # 2. Consulta para obtener todos los detalles (rep_recibo_det)
        query_detalles = f"""
        SELECT 
            R.bpronro, R.ternro, R.pronro, R.concnro, R.tconnro, R.conctipo,
            R.dlicant AS cantid,
            R.dlimonto AS monto, -- Monto total del concepto (haber/descuento)
            C.concabr AS descri,
            C.concimp AS es_monto_unitario_flag ,
            C.conccod
        FROM rep_recibo_det R
        INNER JOIN concepto C ON C.concnro = R.concnro 
        WHERE R.bpronro = ?
        ORDER BY R.ternro, C.conccod;
        """
        cursor.execute(query_detalles, bpronro_filtro)
        detalles_raw = [dict(zip([column[0] for column in cursor.description], row)) for row in cursor.fetchall()]

        query_contribuciones = """
        SELECT Conccod, Concabr, Monto, Dlicant, Tipo, IsTotal
        FROM dbo.fnRHProReciboContribuciones_Tabla(?)
        ORDER BY IsTotal, Conccod;
        """

        # 3. Estructurar los datos y calcular totales por empleado
        recibos = []
        for cabecera in cabeceras:
            ternro = cabecera['ternro']
            detalles_empleado = [d for d in detalles_raw if d['ternro'] == ternro]

            contribuciones = []
            if cabecera.get('cliqnro') is not None:
                cursor.execute(query_contribuciones, cabecera['cliqnro'])
                contribuciones = [
                    dict(zip([column[0] for column in cursor.description], row))
                    for row in cursor.fetchall()
                ]

            contribuciones_detalle = [
                item for item in contribuciones
                if str(item.get('Tipo', '')).strip().lower() == 'detalle'
            ]
            contribuciones_composicion = [
                item for item in contribuciones
                if str(item.get('Tipo', '')).strip().lower() == 'composicion'
            ]
            costo_total = next(
                (item for item in contribuciones_detalle if item.get('IsTotal') == 1),
                None
            )
            contrib_por_codigo = {
                int(item['Conccod']): numero(item.get('Monto'))
                for item in contribuciones_composicion
                if item.get('Conccod') is not None
            }

            comp_sind_emp = contrib_por_codigo.get(101, 0.0)
            comp_sind_tra = contrib_por_codigo.get(102, 0.0)
            comp_seg_social_emp = contrib_por_codigo.get(103, 0.0)
            comp_seg_social_tra = contrib_por_codigo.get(104, 0.0)
            comp_os_emp = contrib_por_codigo.get(105, 0.0)
            comp_os_tra = contrib_por_codigo.get(106, 0.0)
            comp_inssjp_emp = contrib_por_codigo.get(107, 0.0)
            comp_inssjp_tra = contrib_por_codigo.get(108, 0.0)
            comp_art_emp = contrib_por_codigo.get(109, 0.0)
            comp_scvo_emp = contrib_por_codigo.get(110, 0.0)
            
            # Inicializar totales
            total_remun = 0.0
            total_noremun = 0.0
            total_desc = 0.0 	
            total_desc2 = 0.0
            
            detalles_procesados = []
            
            # --- PASADA 1: Cálculos Matemáticos (Floats puros) ---
            total_remun, total_noremun, total_desc, total_desc2 = 0.0, 0.0, 0.0, 0.0
            detalles_procesados = []
            
            for detalle in detalles_empleado:
                # Aseguramos tipos numéricos para no fallar en cálculos [cite: 22]
                m_val = float(detalle.get('monto') or 0)
                c_val = float(detalle.get('cantid') or 0)
                tipo = clasificar_concepto(detalle)
                
                # Cálculo de unitario antes de formatear
                v_unit = (m_val / c_val) if c_val > 0 and detalle.get('tconnro') != 6 else 0.0
                
                # Acumuladores numéricos
                if tipo == 'REMUNERATIVO':
                    total_remun += m_val
                elif tipo == 'NO_REMUNERATIVO':
                    total_noremun += m_val
                elif tipo in ('DESCUENTO', 'OTROS_DESC'):
                    total_desc += abs(m_val)
                

                # Guardamos los valores numéricos para la segunda pasada
                detalles_procesados.append({
                    'conccod':detalle.get('conccod'),
                    'descri': detalle.get('descri'),
                    'tipo_monto': "REMUNERATIVO" if m_val>=0 else "DESCUENTO",
                    'cantid': fmt(c_val),
                    'haber': fmt(m_val) if m_val>=0 else 0.0,
                    'debe': fmt(-m_val) if m_val<0 else 0.0,
                    'v_unit_num': fmt(v_unit)
                })



            # Neto final para la función de letras (se envía el float) 
            neto_pagado = (total_remun + total_noremun) - (total_desc + total_desc2)      
            total_contribuciones = numero(costo_total.get('Monto')) if costo_total else 0.0
            costo_total_empleador = total_remun + total_noremun + total_contribuciones
            valores_torta = [
                neto_pagado,
                comp_seg_social_emp + comp_seg_social_tra,
                comp_sind_emp + comp_sind_tra,
                comp_os_emp + comp_os_tra,
                comp_art_emp,
            ]

            recibo_cabecera = {
                **cabecera,
                'terfecing': format_date_safe(cabecera.get('terfecing')),
                'fecha_pago': format_date_safe(cabecera.get('profecpago')),
                'banco_pago': cabecera.get('banco_desc') if cabecera.get('banco_desc') else 'Efectivo',
                'mes_liquidacion': Mes(cabecera.get('pliqmes')), 
                'dni': formatear_dni_desde_cuil(cabecera.get('cuil')),
                'sueldo_base_fmt': fmt(float(cabecera["sueldo_base"])) if cabecera.get("sueldo_base") else '',
                'terape_nombre': f'{cabecera["terape"]}, {cabecera["terape_nombre"]}', 
                'sucursal': f'{cabecera["sucursal"]}',
                'puesto': f'{cabecera["puesto"]}',
                'gerencia': f'{cabecera["gerencia"]}',
                'periodo_desde': f'{cabecera["periodo_desde"]}',
                'periodo_hasta': f'{cabecera["periodo_hasta"]}',
                'sector': f'{cabecera["sector"]}',
                'tercuil': f'{cabecera["cuil"]}',
                'terdom': f'{cabecera["terdom"]}',
            }
            #print(recibo_cabecera)
            
            recibo = {
                'cabecera': recibo_cabecera,
                'detalles': detalles_procesados,
                'costo_total_empleador': fmt(costo_total_empleador),
                'costos_empleador': [
                    {
                        'concepto': item.get('Concabr'),
                        'unidad': fmt(item.get('Dlicant')),
                        'monto': fmt(item.get('Monto')),
                        'es_total': item.get('IsTotal') == 1,
                    }
                    for item in contribuciones_detalle
                ],
                'composicion_salarial': [
                    {'titulo': 'Total Costo Sindical', 'total': comp_sind_emp + comp_sind_tra, 'empleador': comp_sind_emp, 'trabajador': comp_sind_tra},
                    {'titulo': 'Total costo INSSJP', 'total': comp_inssjp_emp + comp_inssjp_tra, 'empleador': comp_inssjp_emp, 'trabajador': comp_inssjp_tra},
                    {'titulo': 'Total Seguridad Social', 'total': comp_seg_social_emp + comp_seg_social_tra, 'empleador': comp_seg_social_emp, 'trabajador': comp_seg_social_tra},
                    {'titulo': 'Total costo ART', 'total': comp_art_emp, 'empleador': comp_art_emp, 'trabajador': 0.0},
                    {'titulo': 'Total Obra Social', 'total': comp_os_emp + comp_os_tra, 'empleador': comp_os_emp, 'trabajador': comp_os_tra},
                    {'titulo': 'Total Costo SCVO', 'total': comp_scvo_emp, 'empleador': comp_scvo_emp, 'trabajador': 0.0},
                ],
                'grafico_torta': crear_segmentos_torta(valores_torta),
                'totales': {
                    'total_remunerativo': fmt(total_remun),
                    'total_no_remunerativo': fmt(total_noremun),
                    'total_haberes':fmt(total_remun + total_noremun),
                    'total_descuentos': fmt(total_desc + total_desc2), 
                    'total_otros_desc': fmt(total_desc2),
                    'neto_pagado': fmt(neto_pagado),
                    'neto_letras': convertir_neto_a_letras(neto_pagado),
                }
            }
            recibos.append(recibo)
            
        print(f"Datos de {len(recibos)} recibos obtenidos exitosamente.")
        return recibos

    except pyodbc.Error as ex:
        sqlstate = ex.args[0]
        raise Exception(f"Error en la consulta DB: {sqlstate}") from ex # Elevamos la excepción para el manejo de estado
    finally:
        if conn:
            conn.close()


# --- 5. Funciones de Generación de Archivos ---

def generar_html_content(recibos_data, config):
    """Genera y devuelve el contenido HTML renderizado."""
    TEMPLATE_FILE = config['REPORTS']['TEMPLATE_FILE']
    
    env = Environment(loader=FileSystemLoader(BASE_DIR)) 
    template = env.get_template(TEMPLATE_FILE)  

    html_content = ""
    for i, recibo in enumerate(recibos_data):
        rendered_html = template.render(r=recibo)
        html_content += rendered_html
        
        if i < len(recibos_data) - 1:
            html_content += '<div style="page-break-after: always; height: 1px;"></div>' 
            
    return html_content

def generar_html_content_list(recibos_data, config):
    """
    Genera el contenido HTML para CADA recibo. 
    Devuelve una lista de diccionarios {filename_base: str, html_content: str}.
    """
    TEMPLATE_FILE = config['REPORTS']['TEMPLATE_FILE']
    
    # Usamos BASE_DIR definido al inicio del script
    env = Environment(loader=FileSystemLoader(BASE_DIR))
    template = env.get_template(TEMPLATE_FILE)

    output_list = []
    
    for i, recibo in enumerate(recibos_data):
        
        # 1. Nombre de archivo base: LEGAJO-APELLIDO NOMBRE
        DNI = str(recibo['cabecera'].get('dni'))
        telefono = (recibo['cabecera'].get('telefono') or "0000000000").replace('-', '').strip()
        apellido_nombre_raw = recibo['cabecera'].get('terape_nombre', 'Empleado Desconocido').replace(',', '').replace('.', '').strip()
        apellido_nombre_limpio = re.sub(r'[^\w\s-]', '', apellido_nombre_raw)
        
        # Limpiar caracteres especiales que no son válidos en nombres de archivo
        filename_base = f"{DNI}-{telefono}-{apellido_nombre_limpio}"

        # 2. Renderizar el HTML para un solo recibo
        rendered_html = template.render(r=recibo)
        
        # 3. Almacenar el resultado
        output_list.append({
            'filename_base': filename_base,
            'html_content': rendered_html
        })
            
    return output_list

def generar_pdf(config, recibos_data, bpronro_filtro, is_landscape, is_multiple):
    """Genera el PDF, manejando la salida unificada o por empleado."""
    if not WKHTMLTOPDF_PATH:
        raise FileNotFoundError(
            "No se encontró wkhtmltopdf. Instálelo o configure la ruta en WKHTMLTOPDF_CANDIDATES."
        )
    pdfkit_config = pdfkit.configuration(wkhtmltopdf=WKHTMLTOPDF_PATH)
    
    # Lógica de Opciones
    orientation = 'Landscape' if is_landscape.lower() == 'true' else 'Portrait'
    OPCIONES = {
        'encoding': "UTF-8",
        'orientation': orientation, 
        'page-size': 'A4',
        'enable-local-file-access': None,
#        'page-offset': 0 
    } 

    # Generamos la lista de HTML individuales
    html_list = generar_html_content_list(recibos_data, config)
    total_recibos = len(html_list)    
    OUTPUT_PREFIX = config['REPORTS']['OUTPUT_PREFIX']
    
    if is_multiple.lower() == 'true':
        # --- MODO UNIFICADO (UN SOLO PDF) ---
        output_filename = f'{OUTPUT_PREFIX}{bpronro_filtro}.pdf'
        print(f"Generando PDF UNIFICADO en {output_filename}...")
        
        # Concatenar todos los contenidos HTML, añadiendo saltos de página
        full_html_content = ""
        for i, item in enumerate(html_list):
            full_html_content += item['html_content']
            if i < len(html_list) - 1:
                full_html_content += '<div style="page-break-after: always;"></div>' 

        pdfkit.from_string(full_html_content, output_filename, options=OPCIONES, configuration=pdfkit_config)
        print(f"✅ PDF unificado generado exitosamente: {output_filename}")
        
    else:
        # --- MODO MÚLTIPLE (UN PDF POR EMPLEADO) ---
        # 1. Definir rutas de directorio
        OUTPUT_DIR_BASE = os.path.dirname(OUTPUT_PREFIX)
        FOLDER_NAME = str(bpronro_filtro)
        TEMP_FOLDER_PATH = os.path.join(OUTPUT_DIR_BASE, FOLDER_NAME)
        ZIP_BASE_NAME = os.path.join(OUTPUT_DIR_BASE, FOLDER_NAME) 

        print(f"Generando {len(html_list)} PDF individuales...")

        # 2. CREAR CARPETA (si existe, borrarla y recrearla)
        if os.path.exists(TEMP_FOLDER_PATH):
            print(f"   -> Eliminando carpeta existente: {TEMP_FOLDER_PATH}")
            shutil.rmtree(TEMP_FOLDER_PATH)        

        os.makedirs(TEMP_FOLDER_PATH, exist_ok=True)    
        i = 0

        print(f"Carpeta {TEMP_FOLDER_PATH} Creada")
        # 3. GENERAR PDFs INDIVIDUALES DENTRO DE LA CARPETA TEMPORAL
        for item in html_list:
            i += 1
            # La ruta de salida final del PDF individual
            output_filename_pdf = os.path.join(TEMP_FOLDER_PATH, f'{item["filename_base"]}.pdf')
            
            temp_html_path = None
            try:
                # Usamos tempfile para crear un archivo HTML temporal dentro de la carpeta BPRONRO
                temp_html_path = os.path.join(TEMP_FOLDER_PATH, f"temp_{item['filename_base']}.html")
                
                with open(temp_html_path, 'w', encoding='utf-8') as f:
                    f.write(item['html_content'])
                    
                # Llamamos a from_file. wkhtmltopdf ahora puede resolver 'fotos/'
                # porque está en el mismo directorio temporal.
                pdfkit.from_file(temp_html_path,
                                 output_filename_pdf,
                                 options=OPCIONES,
                                 configuration=pdfkit_config)
                # ACTUALIZACIÓN DE PROGRESO (Hasta 95%)
                progreso_actual = ((i + 1) / total_recibos) * 95
                actualizar_batch(config, bpronro_filtro, estado='Procesando', progreso=progreso_actual)                                 
                
            except Exception as e:
                print(f"!!! ERROR al generar {output_filename_pdf}: {e}")
            
            finally:
                # Limpiar el archivo HTML temporal individual
                if temp_html_path and os.path.exists(temp_html_path):
                    os.remove(temp_html_path)                
        # 4. COMPRIMIR Y LIMPIAR
        
        print(f"-> Comprimiendo carpeta '{FOLDER_NAME}' en ZIP...")
        
        # Crea el ZIP (ruta sin extensión) y borra el origen (directorio)
        shutil.make_archive(
            base_name=ZIP_BASE_NAME,    # Nombre base del archivo de salida
            format='zip',             # Formato (zip, tar, etc.)
            root_dir=OUTPUT_DIR_BASE, # Directorio base que contiene la carpeta a comprimir
            base_dir=FOLDER_NAME      # La carpeta específica a comprimir
        )
        
        # Borrar el directorio temporal original después de la compresión
        shutil.rmtree(TEMP_FOLDER_PATH)     
     
                
        print("✅ Proceso de generación de PDFs individuales finalizado.")


# --- 6. Flujo Principal (Manejo de Estados) ---
if __name__ == '__main__':
    print("Iniciando proceso de recibos...")
    
    try:
        config = cargar_configuracion()
        args = obtener_argumentos()
        FILTRO_BPRONRO = args.bpronro
        HTML_ONLY = args.html_only 
        

        # 2. OBTENER DATOS
        datos_recibos = conectar_y_obtener_datos(config, FILTRO_BPRONRO)

        if not datos_recibos:
            # Si no hay datos, terminamos el proceso sin generar archivos
            print("Proceso finalizado. No hay datos para generar el PDF.")
        else:
            # 3. GENERAR ARCHIVO (HTML o PDF)
            if HTML_ONLY:
                output_filename = f"{config['REPORTS']['OUTPUT_PREFIX']}{FILTRO_BPRONRO}.html"
                html_content = generar_html_content(datos_recibos, config)
                
                with open(output_filename, 'w', encoding='utf-8') as f:
                    f.write(html_content)
                    
                print(f"✅ HTML generado exitosamente para debug: {output_filename}")
            else:
                generar_pdf(config, datos_recibos, FILTRO_BPRONRO, args.landscape, args.multiple)
        
        # 4. ACTUALIZAR ESTADO FINAL (ÉXITO): 'Procesado'
        actualizar_batch(config, FILTRO_BPRONRO,'Completo', 100.0 )

    except Exception as e:
        print(f"!!! ERROR CRÍTICO DURANTE EL PROCESO: {e}")
        
        # 4. ACTUALIZAR ESTADO FINAL (ERROR): 'Error'
        try:
            # Solo si config y FILTRO_BPRONRO están definidos
            if 'config' in locals() and 'FILTRO_BPRONRO' in locals():
                 actualizar_batch(config, FILTRO_BPRONRO,'Error',100.0 )
        except Exception:
            # Ignoramos si el manejo de error en sí mismo falla
            pass
