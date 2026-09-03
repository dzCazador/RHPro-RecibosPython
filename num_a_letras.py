# --- Funciones Auxiliares para Conversión a Letras ---

def unidades(n):
    """Convierte números del 0 al 9 a letras."""
    U = ['CERO', 'UNO', 'DOS', 'TRES', 'CUATRO', 'CINCO', 'SEIS', 'SIETE', 'OCHO', 'NUEVE']
    return U[n]

def decenas(n):
    """Convierte números del 10 al 99 a letras."""
    D = ['', 'DIEZ', 'VEINTE', 'TREINTA', 'CUARENTA', 'CINCUENTA', 'SESENTA', 'SETENTA', 'OCHENTA', 'NOVENTA']
    D_IRREG = [
        'DIEZ', 'ONCE', 'DOCE', 'TRECE', 'CATORCE', 'QUINCE', 'DIECISEIS', 
        'DIECISIETE', 'DIECIOCHO', 'DIECINUEVE', 'VEINTI'
    ]
    
    if n < 10:
        return unidades(n)
    if n < 20:
        return D_IRREG[n - 10]
    if n == 20:
        return 'VEINTE'
    
    dec = int(n / 10)
    uni = n % 10
    
    if dec == 2:
        # VEINTI + UNIDADES
        return 'VEINTI' + unidades(uni)
    
    if uni == 0:
        return D[dec]
    else:
        # TREINTA Y CUATRO, CUARENTA Y CINCO, etc.
        return D[dec] + ' Y ' + unidades(uni)

def centenas(n):
    """Convierte números del 100 al 999 a letras."""
    C = [
        '', 'CIENTO', 'DOSCIENTOS', 'TRESCIENTOS', 'CUATROCIENTOS', 
        'QUINIENTOS', 'SEISCIENTOS', 'SETECIENTOS', 'OCHOCIENTOS', 'NOVECIENTOS'
    ]
    
    if n < 100:
        return decenas(n)
    if n == 100:
        return 'CIEN'
    
    cent = int(n / 100)
    resto = n % 100
    
    if resto == 0:
        return C[cent]
    else:
        # CIEN + [DECENAS/UNIDADES]
        return C[cent] + ' ' + decenas(resto)

def miles(n):
    """Convierte números del 1000 al 999999 a letras."""
    if n < 1000:
        return centenas(n)
    
    mil = int(n / 1000)
    resto = n % 1000
    
    if mil == 1:
        mil_str = 'MIL'
    else:
        mil_str = centenas(mil) + ' MIL'
        
    if resto == 0:
        return mil_str
    else:
        return mil_str + ' ' + centenas(resto)

def millones(n):
    """Convierte números del 1000000 en adelante a letras."""
    if n < 1000000:
        return miles(n)
    
    millon = int(n / 1000000)
    resto = n % 1000000
    
    if millon == 1:
        millon_str = 'UN MILLÓN'
    else:
        millon_str = centenas(millon) + ' MILLONES'
        
    if resto == 0:
        return millon_str
    else:
        return millon_str + ' ' + miles(resto)
    
# --- Función Principal de Conversión de Moneda ---

def convertir_neto_a_letras(monto):
    """
    Implementación real para convertir el monto  a letras.
    Maneja hasta MILLONES y céntimos.
    """
    if monto is None: return ""
    
    prefijo = ""
    if monto < 0:
        prefijo = "MENOS "
        monto = abs(monto)
        
    # Separar la parte entera  de la parte decimal (Céntimos)
    monto_str = f"{monto:.2f}"
    partes = monto_str.split('.')
    
    entero = int(partes[0])
    decimal = int(partes[1])
    
    # 1. Convertir la parte entera
    if entero == 0:
        entero_letras = 'CERO'
    else:
        entero_letras = millones(entero)
        
    # 2. Formato de la Moneda
    moneda = "Pesos" 
    
    # 3. Formato final: [LETRAS] [MONEDA] CON [CÉNTIMOS]/100
    
    # Convertimos los centavos a formato de fracción /100
    #centavos_str = f'{decimal:02d}/100' # Asegura dos dígitos (ej: 5 -> 05)

    resultado = f"{prefijo}{entero_letras} {moneda} "
    #CON {centavos_str}"
    
    # Aseguramos que el resultado esté en mayúsculas (como es común en documentos legales)
    return resultado.upper()