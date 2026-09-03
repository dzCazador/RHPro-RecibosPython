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

# Define la ruta base donde se encuentra este script
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def fmt(valor):
    return "{:,.2f}".format(valor).replace(",", "X").replace(".", ",").replace("X", ".")

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
        default='True',
        help="Controla la salida del PDF. 'True' (un solo PDF con todos los recibos) o 'False' (un PDF por empleado)."
    )
    return parser.parse_args()


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

def actualizar_estado_batch(config, bpronro, estado):
    """
    Actualiza el campo bprcestado en la tabla batch_proceso.
    Estados posibles: 'Procesando', 'Procesado', 'Error'.
    """
    print(f"-> Actualizando estado de BPRONRO {bpronro} a '{estado}'...")
    conn = None
    try:
        conn = obtener_conexion(config)
        cursor = conn.cursor()
        
        # Consulta de UPDATE
        query_update = f"""
        UPDATE batch_proceso 
        SET bprcestado = ? 
        WHERE bpronro = ?;
        """
        cursor.execute(query_update, estado, bpronro)
        conn.commit()
        print(f"-> Estado actualizado a '{estado}'.")

    except pyodbc.Error as ex:
        print(f"!!! ADVERTENCIA: No se pudo actualizar el estado en la DB: {ex}")
        print("El proceso continuará, pero el estado de batch_proceso es incorrecto.")
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

    if conctipo == 1:
        return 'REMUNERATIVO'
    elif conctipo == 2:
        return 'NO_REMUNERATIVO'
    elif conctipo == 3:
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

def convertir_neto_a_letras(monto):
    """Función de ejemplo, debe ser reemplazada por una implementación real de NumerosALetras."""
    if monto is None: return ""
    if monto < 0:
        prefijo = "Menos "
        monto = abs(monto)
    else:
        prefijo = ""
        
    monto_redondeado = int(monto)
    return f"{prefijo}Monto en letras: {monto_redondeado:,.2f} (DEMO)"

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
            direccion AS terdom, legajo, R.pliqnro, pliqmes, pliqanio, pliqdepant, pliqfecdep, 
            pliqbco, cuil, empfecalta AS terfecing, sueldo AS sueldo_base, 
            categoria, centrocosto, R.profecpago, formapago, empnombre, empdire, empcuit, 
            emplogo, emplogoalto, emplogoancho, empfirma, empfirmaalto, empfirmaancho,
            tprocdesc AS tipoproc, bandesc AS banco_desc,
            categoria AS calificacion, auxchar3 AS os_eleg, auxchar2 AS regimenhor, 
            auxchar1 AS empfecbaja 
        FROM rep_recibo R
        INNER JOIN proceso P ON P.pronro = R.pronro
        INNER JOIN tipoproc TP ON TP.tprocnro = P.tprocnro
        LEFT JOIN ctabancaria CB ON CB.ctabestado = -1 AND CB.ternro = R.ternro
        LEFT JOIN banco B ON B.ternro = CB.banco
        WHERE bpronro = ?
        ORDER BY centrocosto, legajo;
        """
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
            C.concimp AS es_monto_unitario_flag 
        FROM rep_recibo_det R
        INNER JOIN concepto C ON C.concnro = R.concnro 
        WHERE R.bpronro = ?
        ORDER BY R.ternro, C.conccod;
        """
        cursor.execute(query_detalles, bpronro_filtro)
        detalles_raw = [dict(zip([column[0] for column in cursor.description], row)) for row in cursor.fetchall()]

        # 3. Estructurar los datos y calcular totales por empleado
        recibos = []
        for cabecera in cabeceras:
            ternro = cabecera['ternro']
            detalles_empleado = [d for d in detalles_raw if d['ternro'] == ternro]
            
            # Inicializar totales
            total_remun = 0.0
            total_noremun = 0.0
            total_desc = 0.0 	
            total_desc2 = 0.0
            
            detalles_procesados = []
            
            for detalle in detalles_empleado:
                monto = float(detalle['monto']) if detalle['monto'] is not None else 0.0
                cantid = float(detalle['cantid']) if detalle['cantid'] is not None else 0
                
                # Clasificar y Acumular
                tipo = clasificar_concepto(detalle)
                detalle['tipo_monto'] = tipo
                
                es_excluido = (cantid == 0.0) or (detalle.get('tconnro') == 6)
                detalle['v_unit'] = (monto / cantid) if cantid != 0.0 and not es_excluido else None
                
                detalle['haber'] = 0.0
                detalle['debe'] = 0.0 
                detalle['cantid'] = cantid
                
                if tipo == 'REMUNERATIVO':
                    detalle['haber'] = monto
                    total_remun += monto
                elif tipo == 'NO_REMUNERATIVO':
                    detalle['haber'] = monto
                    total_noremun += monto
                elif tipo == 'DESCUENTO':
                    detalle['debe'] = monto 
                    total_desc += monto
                elif tipo == 'OTROS_DESC':
                    detalle['debe'] = monto 
                    total_desc2 += monto
                
                detalles_procesados.append(detalle)
            
            # Cálculo del Neto a Pagar
            neto_pagado = (total_remun + total_noremun) - (total_desc + total_desc2)
            
            recibo_cabecera = {
                **cabecera,
                'terfecing': format_date_safe(cabecera.get('terfecing')),
                'fecha_pago': format_date_safe(cabecera.get('profecpago')),
                'banco_pago': cabecera.get('banco_desc') if cabecera.get('banco_desc') else 'Efectivo',
                'mes_liquidacion': Mes(cabecera.get('pliqmes')), 
                'dni': formatear_dni_desde_cuil(cabecera.get('cuil')),
                'sueldo_base_fmt': f'{float(cabecera["sueldo_base"]):,.2f}' if cabecera.get("sueldo_base") else '',
                'terape_nombre': f'{cabecera["terape"]}, {cabecera["terape_nombre"]}' 
            }
            
            recibo = {
                'cabecera': recibo_cabecera,
                'detalles': detalles_procesados,
                'totales': {
                    'total_remunerativo': fmt(total_remun),
                    'total_no_remunerativo': fmt(total_noremun),
                    'total_descuentos': fmt(total_desc), 
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
        cuil = str(recibo['cabecera'].get('cuil', '00000000'))
        apellido_nombre_raw = recibo['cabecera'].get('terape_nombre', 'Empleado Desconocido').replace(',', '').replace('.', '').strip()
        
        # Limpiar caracteres especiales que no son válidos en nombres de archivo
        filename_base = f"{cuil}-{re.sub(r'[^\w\s-]', '', apellido_nombre_raw)}"

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

        pdfkit.from_string(full_html_content, output_filename, options=OPCIONES)
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

        print(f"Carpeta {TEMP_FOLDER_PATH} Creada")
        # 3. GENERAR PDFs INDIVIDUALES DENTRO DE LA CARPETA TEMPORAL
        for item in html_list:
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
                                 options=OPCIONES)
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
        
        # 1. ACTUALIZAR ESTADO INICIAL: 'Procesando'
        actualizar_estado_batch(config, FILTRO_BPRONRO, 'Procesando')

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
        actualizar_estado_batch(config, FILTRO_BPRONRO, 'Procesado')

    except Exception as e:
        print(f"!!! ERROR CRÍTICO DURANTE EL PROCESO: {e}")
        
        # 4. ACTUALIZAR ESTADO FINAL (ERROR): 'Error'
        try:
            # Solo si config y FILTRO_BPRONRO están definidos
            if 'config' in locals() and 'FILTRO_BPRONRO' in locals():
                 actualizar_estado_batch(config, FILTRO_BPRONRO, 'Error')
        except Exception:
            # Ignoramos si el manejo de error en sí mismo falla
            pass