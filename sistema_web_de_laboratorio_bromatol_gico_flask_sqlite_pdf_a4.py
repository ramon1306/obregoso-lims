"""
Sistema Web de Gestión de Laboratorio Bromatológico y Análisis de Agua
Basado en el Protocolo N° 26419749 - Laboratorio Dr. Raymundo Motter

Características principales:
1. Backend en Python (Flask) con API RESTful y servidor de interfaz integrado en un solo archivo.
2. Persistencia de datos en SQLite (creación automática de esquema y datos semilla del protocolo 26419749).
3. Interfaz moderna y responsiva con Tailwind CSS y FontAwesome.
4. Motor de parametrización dinámica de datos del laboratorio, firmantes y valores de referencia (CAA / INTA).
5. Evaluación automática de cumplimiento normativo (CAA).
6. Generador y vista previa de Informe Oficial tamaño A4 listo para exportación directa a PDF.

Requisitos de ejecución:
    pip install flask
    python app.py
"""

import os
import json
import hmac
import sqlite3
from datetime import datetime
from flask import Flask, Response, request, jsonify, render_template_string

app = Flask(__name__)
DB_PATH = os.environ.get(
    "LAB_DB_PATH",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "laboratorio_bromatologia.db"),
)


@app.before_request
def require_production_authentication():
    if os.environ.get("APP_ENV", "development").lower() != "production":
        return None

    username = os.environ.get("APP_USERNAME", "")
    password = os.environ.get("APP_PASSWORD", "")
    if not username or len(password) < 16:
        app.logger.error("Production authentication credentials are not configured")
        return Response("Application access is not configured.", status=503)

    credentials = request.authorization
    valid_username = credentials is not None and hmac.compare_digest(
        credentials.username or "", username
    )
    valid_password = credentials is not None and hmac.compare_digest(
        credentials.password or "", password
    )
    if not (valid_username and valid_password):
        return Response(
            "Authentication required.",
            status=401,
            headers={"WWW-Authenticate": 'Basic realm="OBREGOSO LIMS"'},
        )

    return None


# ==============================================================================
# CAPA DE BASE DE DATOS Y PERSISTENCIA (SQLite)
# ==============================================================================


def get_db_connection():
    """Establece conexión con SQLite habilitando acceso por nombre de columna."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Inicializa las tablas y carga los datos iniciales basados en el Protocolo 26419749."""
    conn = get_db_connection()
    cursor = conn.cursor()

    # 1. Tabla de configuración general del laboratorio
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS configuracion_lab (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            nombre TEXT NOT NULL,
            subtitulo TEXT NOT NULL,
            direccion TEXT NOT NULL,
            telefono TEXT NOT NULL,
            email TEXT NOT NULL,
            consideraciones_legales TEXT NOT NULL
        )
    """)

    # 2. Tabla de firmantes / profesionales matriculados
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS firmantes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL,
            matricula TEXT NOT NULL,
            rol TEXT NOT NULL,
            activo INTEGER NOT NULL DEFAULT 1
        )
    """)

    # 3. Tabla de parámetros y valores de referencia (CAA / INTA Balcarce)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS parametros_referencia (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            orden INTEGER NOT NULL,
            categoria TEXT NOT NULL, -- 'FISICO_QUIMICO' o 'MICROBIOLOGICO'
            nombre TEXT NOT NULL,
            tipo_dato TEXT NOT NULL, -- 'NUMERICO' o 'CUALITATIVO'
            unidad TEXT,
            caa_texto TEXT,
            caa_operador TEXT, -- '<', 'RANGO', 'IGUAL', 'NINGUNO'
            caa_min REAL,
            caa_max REAL,
            caa_valor_cualitativo TEXT,
            inta_texto TEXT,
            limite_deteccion TEXT,
            incertidumbre TEXT,
            metodo TEXT,
            nota_tecnica TEXT
        )
    """)

    # 4. Tabla de protocolos de análisis
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS protocolos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            numero_protocolo TEXT UNIQUE NOT NULL,
            fecha_informe TEXT NOT NULL,
            es_reimpresion INTEGER NOT NULL DEFAULT 0,
            cliente_nombre TEXT NOT NULL,
            cliente_cuit TEXT NOT NULL,
            informe_para TEXT NOT NULL,
            doctor TEXT DEFAULT '--',
            estudio_solicitado TEXT NOT NULL,
            responsable_toma TEXT NOT NULL,
            tipo_muestra TEXT NOT NULL,
            rotulo_muestra TEXT NOT NULL,
            punto_toma TEXT NOT NULL,
            fecha_toma TEXT NOT NULL,
            fecha_recepcion TEXT NOT NULL,
            nota_adicional TEXT DEFAULT '',
            cumple_caa INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL
        )
    """)

    # 5. Tabla de resultados asociados a cada protocolo
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS protocolo_resultados (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            protocolo_id INTEGER NOT NULL,
            parametro_id INTEGER NOT NULL,
            operador TEXT DEFAULT '=',
            valor_numerico REAL,
            valor_texto TEXT,
            cumple_caa INTEGER NOT NULL DEFAULT 1,
            FOREIGN KEY (protocolo_id) REFERENCES protocolos(id) ON DELETE CASCADE,
            FOREIGN KEY (parametro_id) REFERENCES parametros_referencia(id)
        )
    """)

    # Cargar datos iniciales si la base está vacía
    cursor.execute("SELECT COUNT(*) FROM configuracion_lab")
    if cursor.fetchone()[0] == 0:
        consideraciones = (
            "Los resultados se refieren únicamente a las muestras sometidas a Análisis.\n"
            "El presente informe solo puede ser reproducido íntegramente, y con autorización escrita del Laboratorio.\n"
            "La identificación de las muestras corresponde a los datos suministrados por el cliente.\n"
            "El laboratorio declina toda responsabilidad acerca del valor representativo de las muestras recepcionadas, "
            "salvo que hayan sido extraídas con intervención expresa del personal de este laboratorio en la etapa de muestreo."
        )
        cursor.execute(
            """
            INSERT INTO configuracion_lab (id, nombre, subtitulo, direccion, telefono, email, consideraciones_legales)
            VALUES (1, ?, ?, ?, ?, ?, ?)
        """,
            (
                "LABORATORIO OBREGOSO",
                "ANÁLISIS CLÍNICOS Y BROMATOLOGÍA",
                "Calle Maipú 243 - Formosa",
                "0370 - 4422822",
                "comunicacion@motter.com.ar",
                consideraciones,
            ),
        )

        # Firmantes oficiales del documento
        firmantes_seed = [
            ("Dr. Raymundo Motter", "M.P.P.: 11", "Director / Firmante General", 1),
            ("Dr. Carlos A. Palacio", "M.P.P.: 182", "Firmante General", 1),
            ("Dr. Guillermo J. Coronel", "M.P.P.: 171", "Validador Microbiológico", 1),
            ("Dra. Graciela L. Tessaro", "M.P.P.: 184", "Validadora Microbiológica", 1),
        ]
        cursor.executemany(
            "INSERT INTO firmantes (nombre, matricula, rol, activo) VALUES (?, ?, ?, ?)",
            firmantes_seed,
        )

        # Parámetros físico-químicos y microbiológicos con normativa CAA / INTA
        parametros_seed = [
            # FÍSICO-QUÍMICOS
            (
                1,
                "FISICO_QUIMICO",
                "Color",
                "CUALITATIVO",
                "-",
                "Incolora",
                "IGUAL",
                None,
                None,
                "Incoloro",
                "-",
                "-",
                "-",
                "-",
                "",
            ),
            (
                2,
                "FISICO_QUIMICO",
                "Olor",
                "CUALITATIVO",
                "-",
                "sin olores",
                "IGUAL",
                None,
                None,
                "Inodora",
                "-",
                "-",
                "-",
                "St. Met. 2150-23°",
                "",
            ),
            (
                3,
                "FISICO_QUIMICO",
                "Turbiedad",
                "NUMERICO",
                "NTU",
                "< 3 NTU",
                "<",
                None,
                3.0,
                None,
                "-",
                "1 NTU",
                "-",
                "St. Met. 2130-23°",
                "",
            ),
            (
                4,
                "FISICO_QUIMICO",
                "pH",
                "NUMERICO",
                "-",
                "6.5-8.5",
                "RANGO",
                6.5,
                8.5,
                None,
                "6.8-9.2",
                "1.00",
                "+/-1.37%",
                "St. Met. 4500H-23°",
                "",
            ),
            (
                5,
                "FISICO_QUIMICO",
                "Dureza Total (en CaCO3)",
                "NUMERICO",
                "mg/l",
                "<400",
                "<",
                None,
                400.0,
                None,
                "-",
                "2.0 mg/l",
                "+/-8.20%",
                "St. Met. 2340C-23°",
                "",
            ),
            (
                6,
                "FISICO_QUIMICO",
                "Calcio",
                "NUMERICO",
                "mg/l",
                "--",
                "NINGUNO",
                None,
                None,
                None,
                "<200",
                "2 mg/l (ppm)",
                "-",
                "St. Met. 3500D-23°",
                "",
            ),
            (
                7,
                "FISICO_QUIMICO",
                "Magnesio",
                "NUMERICO",
                "mg/l",
                "--",
                "NINGUNO",
                None,
                None,
                None,
                "<500",
                "-",
                "-",
                "St. Met. 3500E-23° ICP-AES",
                "",
            ),
            (
                8,
                "FISICO_QUIMICO",
                "Sodio",
                "NUMERICO",
                "mg/l",
                "--",
                "NINGUNO",
                None,
                None,
                None,
                "<5000",
                "0.0250 mg/l",
                "-",
                "Espectroscopía de emisión de plasma acoplado inductivamente",
                "",
            ),
            (
                9,
                "FISICO_QUIMICO",
                "Cloruros",
                "NUMERICO",
                "mg/l",
                "<350",
                "<",
                None,
                350.0,
                None,
                "<4000",
                "1.0 mg/l",
                "+/-9.38%",
                "St. Met. 4500CI-B-23°",
                "",
            ),
            (
                10,
                "FISICO_QUIMICO",
                "Sulfatos",
                "NUMERICO",
                "mg/l",
                "<400",
                "<",
                None,
                400.0,
                None,
                "<1500",
                "25 mg/l",
                "-",
                "Turbidimétrico",
                "",
            ),
            (
                11,
                "FISICO_QUIMICO",
                "Nitratos",
                "NUMERICO",
                "mg/l",
                "<45",
                "<",
                None,
                45.0,
                None,
                "-",
                "2.50 mg/l",
                "+/-10.13%",
                "St. Met. 4500NO3-B-23°",
                "",
            ),
            (
                12,
                "FISICO_QUIMICO",
                "Nitritos",
                "NUMERICO",
                "mg/l",
                "<0.10",
                "<",
                None,
                0.10,
                None,
                "-",
                "0.05 mg/l",
                "+/-13.1%",
                "St. Met. 4500NO2-C-23°",
                "",
            ),
            (
                13,
                "FISICO_QUIMICO",
                "Amonio",
                "NUMERICO",
                "mg/l",
                "<0.20",
                "<",
                None,
                0.20,
                None,
                "-",
                "0.10 mg/l",
                "+/-28.2%",
                "St. Met. 4500NH3-C-23°",
                "",
            ),
            (
                14,
                "FISICO_QUIMICO",
                "Sólidos disueltos totales",
                "NUMERICO",
                "mg/l",
                "<1500 mg/l",
                "<",
                None,
                1500.0,
                None,
                "<7000 mg/l",
                "-",
                "-",
                "St. Met.",
                "",
            ),
            (
                15,
                "FISICO_QUIMICO",
                "Arsénico",
                "NUMERICO",
                "mg/l",
                "<0.05 mg/l",
                "<",
                None,
                0.05,
                None,
                "-",
                "0.05 mg/l",
                "-",
                "St. Met.",
                "NOTA: La autoridad sanitaria competente podrá admitir valores distintos si la composición normal del agua de la zona y la imposibilidad de aplicar tecnología de corrección lo hicieran necesario (Res. conjunta SPReI N° 34/2012 y SAGyP N° 50/2012).",
            ),
            (
                16,
                "FISICO_QUIMICO",
                "Fluoruros",
                "NUMERICO",
                "mg/l",
                "1.0 mg/l",
                "<",
                None,
                1.0,
                None,
                "<2 mg/l",
                "0.4 mg/l",
                "-",
                "St. Met.",
                "Interpretado según el máximo permitido por el CAA sin tener en cuenta las variables Temperatura media y Temperatura máxima del año de la zona.",
            ),
            (
                17,
                "FISICO_QUIMICO",
                "Potasio",
                "NUMERICO",
                "mg/l",
                "--",
                "NINGUNO",
                None,
                None,
                None,
                "-",
                "-",
                "-",
                "ICP - AES - Espectroscopía de emisión de plasma acoplado inductivamente",
                "",
            ),
            # MICROBIOLÓGICOS
            (
                18,
                "MICROBIOLOGICO",
                "Aerobios Mesófilos Totales",
                "NUMERICO",
                "UFC/ml",
                "Menor a 500 UFC/ml",
                "<",
                None,
                500.0,
                None,
                "-",
                "-",
                "-",
                "APHA (1995)",
                "",
            ),
            (
                19,
                "MICROBIOLOGICO",
                "Coliformes Totales",
                "NUMERICO",
                "NMP/100ml",
                "< 3 (NMP/100ml)",
                "<",
                None,
                3.0,
                None,
                "-",
                "-",
                "-",
                "APHA (1995)",
                "",
            ),
            (
                20,
                "MICROBIOLOGICO",
                "Escherichia coli en 100 ml",
                "CUALITATIVO",
                "-",
                "Ausencia",
                "IGUAL",
                None,
                None,
                "Ausencia",
                "-",
                "-",
                "-",
                "APHA (1995)",
                "",
            ),
            (
                21,
                "MICROBIOLOGICO",
                "Pseudomona aeruginosa en 100 ml",
                "CUALITATIVO",
                "-",
                "Ausencia",
                "IGUAL",
                None,
                None,
                "Ausencia",
                "-",
                "-",
                "-",
                "APHA (1995)",
                "",
            ),
        ]
        cursor.executemany(
            """
            INSERT INTO parametros_referencia (
                orden, categoria, nombre, tipo_dato, unidad, caa_texto, caa_operador,
                caa_min, caa_max, caa_valor_cualitativo, inta_texto, limite_deteccion,
                incertidumbre, metodo, nota_tecnica
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            parametros_seed,
        )

        # Insertar el Protocolo 26419749 como ejemplo real inicial
        cursor.execute(
            """
            INSERT INTO protocolos (
                numero_protocolo, fecha_informe, es_reimpresion, cliente_nombre, cliente_cuit,
                informe_para, doctor, estudio_solicitado, responsable_toma, tipo_muestra,
                rotulo_muestra, punto_toma, fecha_toma, fecha_recepcion, nota_adicional,
                cumple_caa, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                "26419749",
                "2026-04-22",
                1,
                "AGUAS, INDUSTRIAL Y CONSTRUCTORA",
                "30654431279",
                "INDUSTRIAL Y CONSTRUCTORA S.A",
                "--",
                "Evaluación de calidad de agua para consumo humano",
                "Gimenez Denisse",
                "Agua domiciliaria",
                "Laguna Blanca, Industrial y Constructora - Acueducto Primavera",
                "Acueducto Primavera",
                "2026-04-22T12:00",
                "2026-04-22T18:24",
                "",
                1,
                datetime.now().isoformat(),
            ),
        )
        proto_id = cursor.lastrowid

        # Resultados reales del Protocolo 26419749
        resultados_seed = [
            (proto_id, 1, "=", None, "Incoloro", 1),
            (proto_id, 2, "=", None, "Inodora", 1),
            (proto_id, 3, "=", 1.00, "1.00", 1),
            (proto_id, 4, "=", 7.10, "7.10", 1),
            (proto_id, 5, "=", 158.00, "158.00", 1),
            (proto_id, 6, "=", 37.00, "37.00", 1),
            (proto_id, 7, "=", 16.00, "16.00", 1),
            (proto_id, 8, "=", 85.00, "85.00", 1),
            (proto_id, 9, "=", 82.00, "82.00", 1),
            (proto_id, 10, "=", 146.00, "146.00", 1),
            (proto_id, 11, "<", 1.0, "Menor a 1", 1),
            (proto_id, 12, "<", 0.05, "<0.05", 1),
            (proto_id, 13, "<", 0.1, "<0.1", 1),
            (proto_id, 14, "=", 495.00, "495.00", 1),
            (proto_id, 15, "<", 0.05, "<0.05", 1),
            (proto_id, 16, "<", 0.4, "<0.4", 1),
            (proto_id, 17, "=", 9.00, "9.00", 1),
            (proto_id, 18, "<", 500.0, "<500", 1),
            (proto_id, 19, "<", 3.0, "<3", 1),
            (proto_id, 20, "=", None, "Ausencia", 1),
            (proto_id, 21, "=", None, "Ausencia", 1),
        ]
        cursor.executemany(
            """
            INSERT INTO protocolo_resultados (protocolo_id, parametro_id, operador, valor_numerico, valor_texto, cumple_caa)
            VALUES (?, ?, ?, ?, ?, ?)
        """,
            resultados_seed,
        )

    conn.commit()
    conn.close()


# ==============================================================================
# MOTOR DE VALIDACIÓN NORMATIVA (CAA)
# ==============================================================================


def evaluar_cumplimiento_parametro(param, operador, valor_num, valor_txt):
    """
    Evalúa si un resultado cumple con el límite establecido por el Código Alimentario Argentino (CAA).
    Retorna True si cumple o no tiene límite restrictivo, False si excede la norma.
    """
    caa_op = param["caa_operador"]
    if not caa_op or caa_op == "NINGUNO":
        return True

    if param["tipo_dato"] == "CUALITATIVO":
        esperado = (param["caa_valor_cualitativo"] or "").strip().lower()
        obtenido = (valor_txt or "").strip().lower()
        if not obtenido:
            return True
        # Equivalencias comunes (Incoloro/Incolora, Inodoro/Inodora)
        if esperado.startswith("incolor") and obtenido.startswith("incolor"):
            return True
        if esperado.startswith("inodor") and obtenido.startswith("inodor"):
            return True
        return esperado == obtenido

    # Evaluación numérica
    if valor_num is None:
        return True

    try:
        val = float(valor_num)
    except (ValueError, TypeError):
        return True

    if caa_op == "<" and param["caa_max"] is not None:
        limite = float(param["caa_max"])
        if operador == "<":
            return val <= limite
        return val < limite

    if (
        caa_op == "RANGO"
        and param["caa_min"] is not None
        and param["caa_max"] is not None
    ):
        return float(param["caa_min"]) <= val <= float(param["caa_max"])

    return True


# ==============================================================================
# RUTAS API RESTful
# ==============================================================================


@app.route("/")
def index():
    """Sirve la aplicación web SPA completa."""
    return render_template_string(HTML_TEMPLATE)


@app.route("/api/bootstrap", methods=["GET"])
def api_bootstrap():
    """Devuelve toda la configuración inicial, firmantes, parámetros y lista de protocolos."""
    conn = get_db_connection()
    config = dict(
        conn.execute("SELECT * FROM configuracion_lab WHERE id = 1").fetchone()
    )
    firmantes = [
        dict(r)
        for r in conn.execute("SELECT * FROM firmantes ORDER BY id ASC").fetchall()
    ]
    parametros = [
        dict(r)
        for r in conn.execute(
            "SELECT * FROM parametros_referencia ORDER BY orden ASC, id ASC"
        ).fetchall()
    ]
    protocolos = [
        dict(r)
        for r in conn.execute("SELECT * FROM protocolos ORDER BY id DESC").fetchall()
    ]
    conn.close()
    return jsonify(
        {
            "config": config,
            "firmantes": firmantes,
            "parametros": parametros,
            "protocolos": protocolos,
        }
    )


@app.route("/api/protocolos/<int:proto_id>", methods=["GET"])
def api_get_protocolo(proto_id):
    """Obtiene el detalle completo de un protocolo junto con sus resultados y metadatos."""
    conn = get_db_connection()
    proto = conn.execute(
        "SELECT * FROM protocolos WHERE id = ?", (proto_id,)
    ).fetchone()
    if not proto:
        conn.close()
        return jsonify({"error": "Protocolo no encontrado"}), 404

    resultados = conn.execute(
        """
        SELECT pr.*, p.nombre, p.categoria, p.tipo_dato, p.unidad, p.caa_texto,
               p.inta_texto, p.limite_deteccion, p.incertidumbre, p.metodo, p.nota_tecnica, p.orden
        FROM protocolo_resultados pr
        JOIN parametros_referencia p ON pr.parametro_id = p.id
        WHERE pr.protocolo_id = ?
        ORDER BY p.orden ASC, p.id ASC
    """,
        (proto_id,),
    ).fetchall()
    conn.close()

    return jsonify(
        {"protocolo": dict(proto), "resultados": [dict(r) for r in resultados]}
    )


@app.route("/api/protocolos", methods=["POST"])
def api_save_protocolo():
    """Crea o actualiza un protocolo y recalcula automáticamente el cumplimiento CAA."""
    data = request.json
    proto_id = data.get("id")
    conn = get_db_connection()
    cursor = conn.cursor()

    # Obtener parámetros para validar
    params_map = {
        r["id"]: dict(r)
        for r in cursor.execute("SELECT * FROM parametros_referencia").fetchall()
    }

    resultados_input = data.get("resultados", [])
    cumple_global = True
    resultados_procesados = []

    for item in resultados_input:
        param_id = int(item["parametro_id"])
        param = params_map.get(param_id)
        if not param:
            continue
        operador = item.get("operador", "=")
        valor_num = item.get("valor_numerico")
        if valor_num == "" or valor_num is None:
            valor_num = None
        else:
            valor_num = float(valor_num)
        valor_texto = item.get("valor_texto", "")

        # Formatear texto de visualización si es numérico y no tiene texto personalizado
        if param["tipo_dato"] == "NUMERICO" and valor_num is not None:
            if not valor_texto:
                if operador in ("<", ">"):
                    valor_texto = f"{operador}{valor_num}"
                else:
                    valor_texto = f"{valor_num:.2f}"

        cumple_item = evaluar_cumplimiento_parametro(
            param, operador, valor_num, valor_texto
        )
        if not cumple_item:
            cumple_global = False

        resultados_procesados.append(
            (param_id, operador, valor_num, valor_texto, 1 if cumple_item else 0)
        )

    try:
        if proto_id:
            cursor.execute(
                """
                UPDATE protocolos SET
                    numero_protocolo = ?, fecha_informe = ?, es_reimpresion = ?,
                    cliente_nombre = ?, cliente_cuit = ?, informe_para = ?, doctor = ?,
                    estudio_solicitado = ?, responsable_toma = ?, tipo_muestra = ?,
                    rotulo_muestra = ?, punto_toma = ?, fecha_toma = ?, fecha_recepcion = ?,
                    nota_adicional = ?, cumple_caa = ?
                WHERE id = ?
            """,
                (
                    data["numero_protocolo"],
                    data["fecha_informe"],
                    1 if data.get("es_reimpresion") else 0,
                    data["cliente_nombre"],
                    data["cliente_cuit"],
                    data["informe_para"],
                    data.get("doctor", "--"),
                    data["estudio_solicitado"],
                    data["responsable_toma"],
                    data["tipo_muestra"],
                    data["rotulo_muestra"],
                    data["punto_toma"],
                    data["fecha_toma"],
                    data["fecha_recepcion"],
                    data.get("nota_adicional", ""),
                    1 if cumple_global else 0,
                    proto_id,
                ),
            )
            cursor.execute(
                "DELETE FROM protocolo_resultados WHERE protocolo_id = ?", (proto_id,)
            )
        else:
            cursor.execute(
                """
                INSERT INTO protocolos (
                    numero_protocolo, fecha_informe, es_reimpresion, cliente_nombre, cliente_cuit,
                    informe_para, doctor, estudio_solicitado, responsable_toma, tipo_muestra,
                    rotulo_muestra, punto_toma, fecha_toma, fecha_recepcion, nota_adicional,
                    cumple_caa, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    data["numero_protocolo"],
                    data["fecha_informe"],
                    1 if data.get("es_reimpresion") else 0,
                    data["cliente_nombre"],
                    data["cliente_cuit"],
                    data["informe_para"],
                    data.get("doctor", "--"),
                    data["estudio_solicitado"],
                    data["responsable_toma"],
                    data["tipo_muestra"],
                    data["rotulo_muestra"],
                    data["punto_toma"],
                    data["fecha_toma"],
                    data["fecha_recepcion"],
                    data.get("nota_adicional", ""),
                    1 if cumple_global else 0,
                    datetime.now().isoformat(),
                ),
            )
            proto_id = cursor.lastrowid

        for res in resultados_procesados:
            cursor.execute(
                """
                INSERT INTO protocolo_resultados (protocolo_id, parametro_id, operador, valor_numerico, valor_texto, cumple_caa)
                VALUES (?, ?, ?, ?, ?, ?)
            """,
                (proto_id, res[0], res[1], res[2], res[3], res[4]),
            )

        conn.commit()
    except sqlite3.IntegrityError:
        conn.close()
        return (
            jsonify({"error": "El número de protocolo ya existe en el sistema."}),
            400,
        )
    except Exception as e:
        conn.close()
        return jsonify({"error": str(e)}), 500

    conn.close()
    return jsonify({"id": proto_id, "cumple_caa": cumple_global})


@app.route("/api/protocolos/<int:proto_id>", methods=["DELETE"])
def api_delete_protocolo(proto_id):
    """Elimina un protocolo y sus resultados asociados."""
    conn = get_db_connection()
    conn.execute("DELETE FROM protocolo_resultados WHERE protocolo_id = ?", (proto_id,))
    conn.execute("DELETE FROM protocolos WHERE id = ?", (proto_id,))
    conn.commit()
    conn.close()
    return jsonify({"status": "deleted"})


@app.route("/api/configuracion", methods=["POST"])
def api_save_configuracion():
    """Actualiza los datos del laboratorio y las consideraciones legales."""
    data = request.json
    conn = get_db_connection()
    conn.execute(
        """
        UPDATE configuracion_lab SET
            nombre = ?, subtitulo = ?, direccion = ?, telefono = ?, email = ?, consideraciones_legales = ?
        WHERE id = 1
    """,
        (
            data["nombre"],
            data["subtitulo"],
            data["direccion"],
            data["telefono"],
            data["email"],
            data["consideraciones_legales"],
        ),
    )
    conn.commit()
    conn.close()
    return jsonify({"status": "ok"})


@app.route("/api/firmantes", methods=["POST"])
def api_save_firmante():
    """Crea o actualiza un profesional firmante."""
    data = request.json
    conn = get_db_connection()
    if data.get("id"):
        conn.execute(
            """
            UPDATE firmantes SET nombre = ?, matricula = ?, rol = ?, activo = ? WHERE id = ?
        """,
            (
                data["nombre"],
                data["matricula"],
                data["rol"],
                1 if data.get("activo", True) else 0,
                data["id"],
            ),
        )
    else:
        conn.execute(
            """
            INSERT INTO firmantes (nombre, matricula, rol, activo) VALUES (?, ?, ?, ?)
        """,
            (data["nombre"], data["matricula"], data["rol"], 1),
        )
    conn.commit()
    conn.close()
    return jsonify({"status": "ok"})


@app.route("/api/firmantes/<int:fid>", methods=["DELETE"])
def api_delete_firmante(fid):
    """Elimina un firmante."""
    conn = get_db_connection()
    conn.execute("DELETE FROM firmantes WHERE id = ?", (fid,))
    conn.commit()
    conn.close()
    return jsonify({"status": "ok"})


@app.route("/api/parametros", methods=["POST"])
def api_save_parametro():
    """Actualiza o crea un parámetro y sus valores de referencia CAA / INTA."""
    data = request.json
    conn = get_db_connection()
    caa_min = float(data["caa_min"]) if data.get("caa_min") not in (None, "") else None
    caa_max = float(data["caa_max"]) if data.get("caa_max") not in (None, "") else None

    if data.get("id"):
        conn.execute(
            """
            UPDATE parametros_referencia SET
                orden = ?, categoria = ?, nombre = ?, tipo_dato = ?, unidad = ?,
                caa_texto = ?, caa_operador = ?, caa_min = ?, caa_max = ?,
                caa_valor_cualitativo = ?, inta_texto = ?, limite_deteccion = ?,
                incertidumbre = ?, metodo = ?, nota_tecnica = ?
            WHERE id = ?
        """,
            (
                int(data.get("orden", 99)),
                data["categoria"],
                data["nombre"],
                data["tipo_dato"],
                data.get("unidad", "-"),
                data.get("caa_texto", "--"),
                data.get("caa_operador", "NINGUNO"),
                caa_min,
                caa_max,
                data.get("caa_valor_cualitativo", ""),
                data.get("inta_texto", "-"),
                data.get("limite_deteccion", "-"),
                data.get("incertidumbre", "-"),
                data.get("metodo", "-"),
                data.get("nota_tecnica", ""),
                data["id"],
            ),
        )
    else:
        conn.execute(
            """
            INSERT INTO parametros_referencia (
                orden, categoria, nombre, tipo_dato, unidad, caa_texto, caa_operador,
                caa_min, caa_max, caa_valor_cualitativo, inta_texto, limite_deteccion,
                incertidumbre, metodo, nota_tecnica
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                int(data.get("orden", 99)),
                data["categoria"],
                data["nombre"],
                data["tipo_dato"],
                data.get("unidad", "-"),
                data.get("caa_texto", "--"),
                data.get("caa_operador", "NINGUNO"),
                caa_min,
                caa_max,
                data.get("caa_valor_cualitativo", ""),
                data.get("inta_texto", "-"),
                data.get("limite_deteccion", "-"),
                data.get("incertidumbre", "-"),
                data.get("metodo", "-"),
                data.get("nota_tecnica", ""),
            ),
        )
    conn.commit()
    conn.close()
    return jsonify({"status": "ok"})


# ==============================================================================
# INTERFAZ WEB COMPLETA + MOTOR DE IMPRESIÓN PDF TAMAÑO A4
# ==============================================================================

HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>LIMS Bromatología - Laboratorio Obregoso</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css">
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
    <style>
        body {
            font-family: 'Inter', sans-serif;
            background-color: #f1f5f9;
        }

        /* Estilos específicos para la hoja A4 en vista previa e impresión PDF */
        .a4-sheet {
            width: 210mm;
            min-height: 297mm;
            background: #ffffff;
            margin: 0 auto;
            padding: 12mm 14mm;
            box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.15);
            color: #1e293b;
            font-size: 9.5pt;
            line-height: 1.35;
        }

        @media print {
            @page {
                size: A4 portrait;
                margin: 10mm 12mm;
            }
            body {
                background: #ffffff !important;
                margin: 0 !important;
                padding: 0 !important;
            }
            .no-print {
                display: none !important;
            }
            .print-only-container {
                padding: 0 !important;
                margin: 0 !important;
                background: #ffffff !important;
            }
            .a4-sheet {
                width: 100% !important;
                min-height: auto !important;
                box-shadow: none !important;
                padding: 0 !important;
                margin: 0 !important;
            }
            .avoid-break {
                break-inside: avoid;
                page-break-inside: avoid;
            }
        }
    </style>
</head>
<body class="text-slate-800 antialiased">

    <!-- Contenedor Principal de la Aplicación (Oculto al imprimir) -->
    <div id="app-shell" class="min-h-screen flex flex-col lg:flex-row no-print">

        <!-- Barra Lateral de Navegación -->
        <aside class="w-full lg:w-64 bg-slate-900 text-slate-100 flex flex-col shrink-0">
            <div class="p-5 border-b border-slate-800 flex items-center gap-3">
                <div class="w-10 h-10 rounded-xl bg-sky-500/20 border border-sky-400/30 flex items-center justify-center text-sky-400 font-bold text-xl">
                    <i class="fa-solid fa-flask-vial"></i>
                </div>
                <div>
                    <h1 class="font-bold text-sm tracking-wide text-white leading-tight">OBREGOSO LIMS</h1>
                    <p class="text-xs text-slate-400">Bromatología & Aguas</p>
                </div>
            </div>

            <nav class="flex-1 p-3 space-y-1 flex lg:flex-col overflow-x-auto">
                <button onclick="switchView('dashboard')" id="nav-dashboard"
                    class="nav-btn flex items-center gap-3 px-4 py-3 rounded-xl text-sm font-medium transition-all bg-sky-600 text-white whitespace-nowrap">
                    <i class="fa-solid fa-chart-pie w-5 text-center"></i>
                    <span>Panel General</span>
                </button>
                <button onclick="openNewProtocol()" id="nav-editor"
                    class="nav-btn flex items-center gap-3 px-4 py-3 rounded-xl text-sm font-medium text-slate-300 hover:bg-slate-800 hover:text-white transition-all whitespace-nowrap">
                    <i class="fa-solid fa-file-circle-plus w-5 text-center"></i>
                    <span>Nuevo Protocolo</span>
                </button>
                <button onclick="switchView('parametros')" id="nav-parametros"
                    class="nav-btn flex items-center gap-3 px-4 py-3 rounded-xl text-sm font-medium text-slate-300 hover:bg-slate-800 hover:text-white transition-all whitespace-nowrap">
                    <i class="fa-solid fa-sliders w-5 text-center"></i>
                    <span>Normativas CAA / INTA</span>
                </button>
                <button onclick="switchView('configuracion')" id="nav-configuracion"
                    class="nav-btn flex items-center gap-3 px-4 py-3 rounded-xl text-sm font-medium text-slate-300 hover:bg-slate-800 hover:text-white transition-all whitespace-nowrap">
                    <i class="fa-solid fa-building-shield w-5 text-center"></i>
                    <span>Configuración Lab</span>
                </button>
            </nav>

            <div class="hidden lg:block p-4 m-3 rounded-xl bg-slate-800/70 border border-slate-700/60 text-xs text-slate-400">
                <div class="flex items-center gap-2 text-emerald-400 font-semibold mb-1">
                    <i class="fa-solid fa-database"></i> SQLite Activo
                </div>
                <p>Normativa vigente: Código Alimentario Argentino (CAA) & INTA Balcarce.</p>
            </div>
        </aside>

        <!-- Área de Contenido Principal -->
        <main class="flex-1 flex flex-col min-w-0">

            <!-- Barra Superior -->
            <header class="bg-white border-b border-slate-200 px-6 py-4 flex flex-wrap items-center justify-between gap-4">
                <div>
                    <h2 id="page-title" class="text-xl font-bold text-slate-800">Panel de Control Bromatológico</h2>
                    <p id="page-subtitle" class="text-xs text-slate-500">Gestión de protocolos de análisis físico-químicos y microbiológicos de agua</p>
                </div>
                <div class="flex items-center gap-3">
                    <span class="hidden sm:inline-flex items-center gap-2 px-3 py-1.5 rounded-full text-xs font-medium bg-sky-50 text-sky-700 border border-sky-200">
                        <i class="fa-solid fa-location-dot"></i> Formosa, Argentina
                    </span>
                    <button onclick="openNewProtocol()" class="px-4 py-2 bg-sky-600 hover:bg-sky-700 text-white text-sm font-medium rounded-xl shadow-sm transition flex items-center gap-2">
                        <i class="fa-solid fa-plus"></i> Cargar Muestra
                    </button>
                </div>
            </header>

            <!-- Notificación Toast Flotante -->
            <div id="toast" class="fixed bottom-5 right-5 z-50 hidden transform transition-all duration-300">
                <div id="toast-box" class="flex items-center gap-3 px-4 py-3 rounded-xl shadow-lg text-white text-sm font-medium bg-slate-900">
                    <i id="toast-icon" class="fa-solid fa-circle-check text-emerald-400"></i>
                    <span id="toast-msg">Operación exitosa</span>
                </div>
            </div>

            <!-- ==================== VISTA 1: DASHBOARD ==================== -->
            <section id="view-dashboard" class="p-6 space-y-6">
                <!-- Tarjetas KPI -->
                <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
                    <div class="bg-white p-5 rounded-2xl border border-slate-200 shadow-sm flex items-center gap-4">
                        <div class="w-12 h-12 rounded-xl bg-sky-100 text-sky-600 flex items-center justify-center text-xl">
                            <i class="fa-solid fa-vials"></i>
                        </div>
                        <div>
                            <p class="text-xs font-medium text-slate-500 uppercase">Protocolos Emitidos</p>
                            <p id="kpi-total" class="text-2xl font-bold text-slate-800">0</p>
                        </div>
                    </div>
                    <div class="bg-white p-5 rounded-2xl border border-slate-200 shadow-sm flex items-center gap-4">
                        <div class="w-12 h-12 rounded-xl bg-emerald-100 text-emerald-600 flex items-center justify-center text-xl">
                            <i class="fa-solid fa-circle-check"></i>
                        </div>
                        <div>
                            <p class="text-xs font-medium text-slate-500 uppercase">Aptos Consumo (CAA)</p>
                            <p id="kpi-aptos" class="text-2xl font-bold text-emerald-600">0</p>
                        </div>
                    </div>
                    <div class="bg-white p-5 rounded-2xl border border-slate-200 shadow-sm flex items-center gap-4">
                        <div class="w-12 h-12 rounded-xl bg-amber-100 text-amber-600 flex items-center justify-center text-xl">
                            <i class="fa-solid fa-triangle-exclamation"></i>
                        </div>
                        <div>
                            <p class="text-xs font-medium text-slate-500 uppercase">Fuera de Norma</p>
                            <p id="kpi-no-aptos" class="text-2xl font-bold text-amber-600">0</p>
                        </div>
                    </div>
                    <div class="bg-white p-5 rounded-2xl border border-slate-200 shadow-sm flex items-center gap-4">
                        <div class="w-12 h-12 rounded-xl bg-indigo-100 text-indigo-600 flex items-center justify-center text-xl">
                            <i class="fa-solid fa-microscope"></i>
                        </div>
                        <div>
                            <p class="text-xs font-medium text-slate-500 uppercase">Parámetros Activos</p>
                            <p id="kpi-params" class="text-2xl font-bold text-slate-800">21</p>
                        </div>
                    </div>
                </div>

                <!-- Tabla de Protocolos Registrados -->
                <div class="bg-white rounded-2xl border border-slate-200 shadow-sm overflow-hidden">
                    <div class="p-5 border-b border-slate-200 flex flex-wrap items-center justify-between gap-4">
                        <div class="flex items-center gap-2">
                            <i class="fa-solid fa-folder-open text-sky-600"></i>
                            <h3 class="font-bold text-slate-800">Protocolos de Análisis Registrados</h3>
                        </div>
                        <div class="relative w-full sm:w-72">
                            <i class="fa-solid fa-magnifying-glass absolute left-3.5 top-3 text-slate-400 text-sm"></i>
                            <input type="text" id="search-protocol" oninput="renderProtocolsTable()"
                                placeholder="Buscar por N°, cliente o rótulo..."
                                class="w-full pl-9 pr-4 py-2 text-sm border border-slate-300 rounded-xl focus:ring-2 focus:ring-sky-500 focus:border-sky-500 outline-none">
                        </div>
                    </div>

                    <div class="overflow-x-auto">
                        <table class="w-full text-left border-collapse">
                            <thead>
                                <tr class="bg-slate-50 border-b border-slate-200 text-xs font-semibold text-slate-500 uppercase">
                                    <th class="py-3.5 px-4">Protocolo</th>
                                    <th class="py-3.5 px-4">Fecha</th>
                                    <th class="py-3.5 px-4">Cliente / Razón Social</th>
                                    <th class="py-3.5 px-4">Rótulo / Punto de Toma</th>
                                    <th class="py-3.5 px-4">Estado CAA</th>
                                    <th class="py-3.5 px-4 text-right">Acciones</th>
                                </tr>
                            </thead>
                            <tbody id="protocols-tbody" class="divide-y divide-slate-100 text-sm">
                                <!-- Dinámico -->
                            </tbody>
                        </table>
                    </div>
                </div>
            </section>

            <!-- ==================== VISTA 2: EDITOR DE PROTOCOLO ==================== -->
            <section id="view-editor" class="p-6 space-y-6 hidden">
                <form id="protocol-form" onsubmit="saveProtocol(event)" class="space-y-6">
                    <input type="hidden" id="edit-proto-id">

                    <!-- Bloque 1: Datos Administrativos y de Muestra -->
                    <div class="bg-white p-6 rounded-2xl border border-slate-200 shadow-sm space-y-4">
                        <div class="flex items-center justify-between border-b border-slate-100 pb-3">
                            <h3 class="font-bold text-slate-800 flex items-center gap-2">
                                <i class="fa-solid fa-clipboard-list text-sky-600"></i>
                                <span>1. Identificación del Protocolo y Muestra</span>
                            </h3>
                            <label class="inline-flex items-center gap-2 text-xs font-medium text-slate-600 cursor-pointer">
                                <input type="checkbox" id="f-reimpresion" class="rounded text-sky-600 focus:ring-sky-500">
                                <span>Marcar como Reimpresión de resultados</span>
                            </label>
                        </div>

                        <div class="grid grid-cols-1 md:grid-cols-3 lg:grid-cols-4 gap-4">
                            <div>
                                <label class="block text-xs font-semibold text-slate-600 mb-1">N° de Protocolo *</label>
                                <input type="text" id="f-numero" required placeholder="Ej: 26419750"
                                    class="w-full px-3 py-2 text-sm border border-slate-300 rounded-xl focus:ring-2 focus:ring-sky-500 outline-none font-mono font-bold">
                            </div>
                            <div>
                                <label class="block text-xs font-semibold text-slate-600 mb-1">Fecha del Informe *</label>
                                <input type="date" id="f-fecha-informe" required
                                    class="w-full px-3 py-2 text-sm border border-slate-300 rounded-xl focus:ring-2 focus:ring-sky-500 outline-none">
                            </div>
                            <div>
                                <label class="block text-xs font-semibold text-slate-600 mb-1">Cliente / Titular *</label>
                                <input type="text" id="f-cliente" required placeholder="AGUAS, INDUSTRIAL Y CONSTRUCTORA"
                                    class="w-full px-3 py-2 text-sm border border-slate-300 rounded-xl focus:ring-2 focus:ring-sky-500 outline-none">
                            </div>
                            <div>
                                <label class="block text-xs font-semibold text-slate-600 mb-1">CUIT / DNI *</label>
                                <input type="text" id="f-cuit" required placeholder="30654431279"
                                    class="w-full px-3 py-2 text-sm border border-slate-300 rounded-xl focus:ring-2 focus:ring-sky-500 outline-none">
                            </div>

                            <div>
                                <label class="block text-xs font-semibold text-slate-600 mb-1">Informe Para *</label>
                                <input type="text" id="f-informe-para" required placeholder="INDUSTRIAL Y CONSTRUCTORA S.A"
                                    class="w-full px-3 py-2 text-sm border border-slate-300 rounded-xl focus:ring-2 focus:ring-sky-500 outline-none">
                            </div>
                            <div>
                                <label class="block text-xs font-semibold text-slate-600 mb-1">Responsable Toma Muestra *</label>
                                <input type="text" id="f-responsable" required placeholder="Gimenez Denisse"
                                    class="w-full px-3 py-2 text-sm border border-slate-300 rounded-xl focus:ring-2 focus:ring-sky-500 outline-none">
                            </div>
                            <div>
                                <label class="block text-xs font-semibold text-slate-600 mb-1">Tipo de Muestra *</label>
                                <input type="text" id="f-tipo-muestra" required value="Agua domiciliaria"
                                    class="w-full px-3 py-2 text-sm border border-slate-300 rounded-xl focus:ring-2 focus:ring-sky-500 outline-none">
                            </div>
                            <div>
                                <label class="block text-xs font-semibold text-slate-600 mb-1">Punto de Toma *</label>
                                <input type="text" id="f-punto-toma" required placeholder="Acueducto Primavera"
                                    class="w-full px-3 py-2 text-sm border border-slate-300 rounded-xl focus:ring-2 focus:ring-sky-500 outline-none">
                            </div>

                            <div class="md:col-span-2">
                                <label class="block text-xs font-semibold text-slate-600 mb-1">Rótulo de la Muestra *</label>
                                <input type="text" id="f-rotulo" required placeholder="Laguna Blanca, Industrial y Constructora - Acueducto Primavera"
                                    class="w-full px-3 py-2 text-sm border border-slate-300 rounded-xl focus:ring-2 focus:ring-sky-500 outline-none">
                            </div>
                            <div>
                                <label class="block text-xs font-semibold text-slate-600 mb-1">Fecha y Hora Toma *</label>
                                <input type="datetime-local" id="f-fecha-toma" required
                                    class="w-full px-3 py-2 text-sm border border-slate-300 rounded-xl focus:ring-2 focus:ring-sky-500 outline-none">
                            </div>
                            <div>
                                <label class="block text-xs font-semibold text-slate-600 mb-1">Fecha y Hora Recepción *</label>
                                <input type="datetime-local" id="f-fecha-recepcion" required
                                    class="w-full px-3 py-2 text-sm border border-slate-300 rounded-xl focus:ring-2 focus:ring-sky-500 outline-none">
                            </div>

                            <div class="md:col-span-3">
                                <label class="block text-xs font-semibold text-slate-600 mb-1">Estudio Solicitado</label>
                                <input type="text" id="f-estudio" required value="Evaluación de calidad de agua para consumo humano"
                                    class="w-full px-3 py-2 text-sm border border-slate-300 rounded-xl focus:ring-2 focus:ring-sky-500 outline-none">
                            </div>
                            <div>
                                <label class="block text-xs font-semibold text-slate-600 mb-1">Doctor / Derivante</label>
                                <input type="text" id="f-doctor" value="--"
                                    class="w-full px-3 py-2 text-sm border border-slate-300 rounded-xl focus:ring-2 focus:ring-sky-500 outline-none">
                            </div>
                        </div>
                    </div>

                    <!-- Bloque 2: Determinaciones Físico-Químicas -->
                    <div class="bg-white p-6 rounded-2xl border border-slate-200 shadow-sm space-y-4">
                        <div class="flex items-center justify-between border-b border-slate-100 pb-3">
                            <h3 class="font-bold text-slate-800 flex items-center gap-2">
                                <i class="fa-solid fa-droplet text-sky-600"></i>
                                <span>2. Resultados Análisis Físico-Químico</span>
                            </h3>
                            <span class="text-xs text-slate-500">Validación automática en tiempo real contra límites CAA</span>
                        </div>
                        <div class="overflow-x-auto">
                            <table class="w-full text-left border-collapse text-sm">
                                <thead>
                                    <tr class="bg-slate-50 border-b border-slate-200 text-xs font-semibold text-slate-500 uppercase">
                                        <th class="py-2.5 px-3">Parámetro</th>
                                        <th class="py-2.5 px-3 w-24">Operador</th>
                                        <th class="py-2.5 px-3 w-40">Resultado</th>
                                        <th class="py-2.5 px-3">Unidad</th>
                                        <th class="py-2.5 px-3">Ref. CAA</th>
                                        <th class="py-2.5 px-3">Ref. INTA</th>
                                        <th class="py-2.5 px-3 text-center">Estado</th>
                                    </tr>
                                </thead>
                                <tbody id="editor-fq-tbody" class="divide-y divide-slate-100">
                                    <!-- Dinámico -->
                                </tbody>
                            </table>
                        </div>
                    </div>

                    <!-- Bloque 3: Determinaciones Microbiológicas -->
                    <div class="bg-white p-6 rounded-2xl border border-slate-200 shadow-sm space-y-4">
                        <div class="flex items-center justify-between border-b border-slate-100 pb-3">
                            <h3 class="font-bold text-slate-800 flex items-center gap-2">
                                <i class="fa-solid fa-bacterium text-emerald-600"></i>
                                <span>3. Estudio Microbiológico</span>
                            </h3>
                            <span class="text-xs text-slate-500">Método estándar APHA (1995)</span>
                        </div>
                        <div class="overflow-x-auto">
                            <table class="w-full text-left border-collapse text-sm">
                                <thead>
                                    <tr class="bg-slate-50 border-b border-slate-200 text-xs font-semibold text-slate-500 uppercase">
                                        <th class="py-2.5 px-3">Determinación</th>
                                        <th class="py-2.5 px-3 w-24">Operador</th>
                                        <th class="py-2.5 px-3 w-40">Resultado</th>
                                        <th class="py-2.5 px-3">Unidad</th>
                                        <th class="py-2.5 px-3">Valor Recomendado</th>
                                        <th class="py-2.5 px-3 text-center">Estado</th>
                                    </tr>
                                </thead>
                                <tbody id="editor-micro-tbody" class="divide-y divide-slate-100">
                                    <!-- Dinámico -->
                                </tbody>
                            </table>
                        </div>
                    </div>

                    <!-- Barra de Acción del Formulario -->
                    <div class="flex flex-wrap items-center justify-end gap-3 bg-white p-4 rounded-2xl border border-slate-200 shadow-sm">
                        <button type="button" onclick="switchView('dashboard')" class="px-5 py-2.5 rounded-xl border border-slate-300 text-slate-700 text-sm font-medium hover:bg-slate-50 transition">
                            Cancelar
                        </button>
                        <button type="submit" class="px-6 py-2.5 rounded-xl bg-sky-600 hover:bg-sky-700 text-white text-sm font-semibold shadow-sm transition flex items-center gap-2">
                            <i class="fa-solid fa-floppy-disk"></i> Guardar Protocolo y Generar Informe A4
                        </button>
                    </div>
                </form>
            </section>

            <!-- ==================== VISTA 3: PARAMETRIZACIÓN CAA / INTA ==================== -->
            <section id="view-parametros" class="p-6 space-y-6 hidden">
                <div class="bg-white p-6 rounded-2xl border border-slate-200 shadow-sm space-y-4">
                    <div class="flex flex-wrap items-center justify-between gap-4 border-b border-slate-100 pb-4">
                        <div>
                            <h3 class="font-bold text-slate-800 flex items-center gap-2">
                                <i class="fa-solid fa-scale-balanced text-sky-600"></i>
                                <span>Parametrización de Determinaciones y Valores de Referencia</span>
                            </h3>
                            <p class="text-xs text-slate-500 mt-1">Configure los límites del Código Alimentario Argentino (CAA), INTA Balcarce, métodos analíticos e incertidumbres.</p>
                        </div>
                        <button onclick="openParamModal()" class="px-4 py-2 bg-sky-600 hover:bg-sky-700 text-white text-sm font-medium rounded-xl flex items-center gap-2">
                            <i class="fa-solid fa-plus"></i> Nuevo Parámetro
                        </button>
                    </div>

                    <div class="overflow-x-auto">
                        <table class="w-full text-left border-collapse text-sm">
                            <thead>
                                <tr class="bg-slate-50 border-b border-slate-200 text-xs font-semibold text-slate-500 uppercase">
                                    <th class="py-3 px-3">Orden</th>
                                    <th class="py-3 px-3">Categoría</th>
                                    <th class="py-3 px-3">Parámetro</th>
                                    <th class="py-3 px-3">Unidad</th>
                                    <th class="py-3 px-3">Regla CAA</th>
                                    <th class="py-3 px-3">Texto CAA</th>
                                    <th class="py-3 px-3">Ref. INTA</th>
                                    <th class="py-3 px-3">Método</th>
                                    <th class="py-3 px-3 text-right">Editar</th>
                                </tr>
                            </thead>
                            <tbody id="params-config-tbody" class="divide-y divide-slate-100">
                                <!-- Dinámico -->
                            </tbody>
                        </table>
                    </div>
                </div>
            </section>

            <!-- ==================== VISTA 4: CONFIGURACIÓN DEL LABORATORIO ==================== -->
            <section id="view-configuracion" class="p-6 space-y-6 hidden">
                <div class="grid grid-cols-1 lg:grid-cols-2 gap-6">
                    <!-- Datos Institucionales -->
                    <form onsubmit="saveLabConfig(event)" class="bg-white p-6 rounded-2xl border border-slate-200 shadow-sm space-y-4">
                        <h3 class="font-bold text-slate-800 flex items-center gap-2 border-b border-slate-100 pb-3">
                            <i class="fa-solid fa-hospital text-sky-600"></i>
                            <span>Datos Institucionales del Laboratorio</span>
                        </h3>
                        <div>
                            <label class="block text-xs font-semibold text-slate-600 mb-1">Nombre del Laboratorio</label>
                            <input type="text" id="cfg-nombre" required class="w-full px-3 py-2 text-sm border border-slate-300 rounded-xl">
                        </div>
                        <div>
                            <label class="block text-xs font-semibold text-slate-600 mb-1">Subtítulo / Especialidad</label>
                            <input type="text" id="cfg-subtitulo" required class="w-full px-3 py-2 text-sm border border-slate-300 rounded-xl">
                        </div>
                        <div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
                            <div>
                                <label class="block text-xs font-semibold text-slate-600 mb-1">Dirección</label>
                                <input type="text" id="cfg-direccion" required class="w-full px-3 py-2 text-sm border border-slate-300 rounded-xl">
                            </div>
                            <div>
                                <label class="block text-xs font-semibold text-slate-600 mb-1">Teléfono</label>
                                <input type="text" id="cfg-telefono" required class="w-full px-3 py-2 text-sm border border-slate-300 rounded-xl">
                            </div>
                        </div>
                        <div>
                            <label class="block text-xs font-semibold text-slate-600 mb-1">Correo Electrónico</label>
                            <input type="email" id="cfg-email" required class="w-full px-3 py-2 text-sm border border-slate-300 rounded-xl">
                        </div>
                        <div>
                            <label class="block text-xs font-semibold text-slate-600 mb-1">Consideraciones Legales (Una por línea)</label>
                            <textarea id="cfg-consideraciones" rows="5" required class="w-full px-3 py-2 text-sm border border-slate-300 rounded-xl"></textarea>
                        </div>
                        <div class="pt-2 flex justify-end">
                            <button type="submit" class="px-5 py-2.5 bg-sky-600 hover:bg-sky-700 text-white text-sm font-semibold rounded-xl flex items-center gap-2">
                                <i class="fa-solid fa-check"></i> Guardar Configuración
                            </button>
                        </div>
                    </form>

                    <!-- Cuerpo de Bioquímicos y Firmantes -->
                    <div class="bg-white p-6 rounded-2xl border border-slate-200 shadow-sm space-y-4">
                        <div class="flex items-center justify-between border-b border-slate-100 pb-3">
                            <h3 class="font-bold text-slate-800 flex items-center gap-2">
                                <i class="fa-solid fa-signature text-sky-600"></i>
                                <span>Profesionales y Firmantes Electrónicos</span>
                            </h3>
                        </div>

                        <form onsubmit="addFirmante(event)" class="grid grid-cols-1 sm:grid-cols-3 gap-2 bg-slate-50 p-3 rounded-xl border border-slate-200">
                            <input type="text" id="new-firm-nombre" placeholder="Nombre (Ej: Dr. Juan Pérez)" required class="px-3 py-2 text-xs border border-slate-300 rounded-lg bg-white">
                            <input type="text" id="new-firm-mat" placeholder="Matrícula (Ej: M.P.P.: 190)" required class="px-3 py-2 text-xs border border-slate-300 rounded-lg bg-white">
                            <div class="flex gap-2">
                                <select id="new-firm-rol" class="flex-1 px-2 py-2 text-xs border border-slate-300 rounded-lg bg-white">
                                    <option value="Firmante General">Firmante General</option>
                                    <option value="Validador Microbiológico">Validador Microbiológico</option>
                                </select>
                                <button type="submit" class="px-3 py-2 bg-emerald-600 hover:bg-emerald-700 text-white rounded-lg text-xs font-semibold">
                                    <i class="fa-solid fa-plus"></i>
                                </button>
                            </div>
                        </form>

                        <div id="firmantes-list" class="space-y-2">
                            <!-- Dinámico -->
                        </div>
                    </div>
                </div>
            </section>

        </main>
    </div>

    <!-- ==================== MODAL EDICIÓN DE PARÁMETRO ==================== -->
    <div id="param-modal" class="fixed inset-0 bg-slate-900/60 backdrop-blur-sm z-50 hidden flex items-center justify-center p-4 no-print">
        <div class="bg-white rounded-2xl max-w-2xl w-full p-6 shadow-2xl space-y-4 max-h-[90vh] overflow-y-auto">
            <div class="flex items-center justify-between border-b border-slate-100 pb-3">
                <h3 class="font-bold text-slate-800 text-lg">Configurar Parámetro y Valores de Referencia</h3>
                <button onclick="closeParamModal()" class="text-slate-400 hover:text-slate-600">
                    <i class="fa-solid fa-xmark text-xl"></i>
                </button>
            </div>
            <form onsubmit="saveParametro(event)" class="space-y-4">
                <input type="hidden" id="pm-id">
                <div class="grid grid-cols-1 sm:grid-cols-3 gap-4">
                    <div>
                        <label class="block text-xs font-semibold text-slate-600 mb-1">Orden Visual</label>
                        <input type="number" id="pm-orden" required class="w-full px-3 py-2 text-sm border border-slate-300 rounded-xl">
                    </div>
                    <div>
                        <label class="block text-xs font-semibold text-slate-600 mb-1">Categoría</label>
                        <select id="pm-categoria" class="w-full px-3 py-2 text-sm border border-slate-300 rounded-xl">
                            <option value="FISICO_QUIMICO">Físico-Químico</option>
                            <option value="MICROBIOLOGICO">Microbiológico</option>
                        </select>
                    </div>
                    <div>
                        <label class="block text-xs font-semibold text-slate-600 mb-1">Tipo de Dato</label>
                        <select id="pm-tipo" class="w-full px-3 py-2 text-sm border border-slate-300 rounded-xl">
                            <option value="NUMERICO">Numérico</option>
                            <option value="CUALITATIVO">Cualitativo (Texto)</option>
                        </select>
                    </div>
                </div>

                <div class="grid grid-cols-1 sm:grid-cols-3 gap-4">
                    <div class="sm:col-span-2">
                        <label class="block text-xs font-semibold text-slate-600 mb-1">Nombre de la Determinación</label>
                        <input type="text" id="pm-nombre" required class="w-full px-3 py-2 text-sm border border-slate-300 rounded-xl">
                    </div>
                    <div>
                        <label class="block text-xs font-semibold text-slate-600 mb-1">Unidad de Medida</label>
                        <input type="text" id="pm-unidad" class="w-full px-3 py-2 text-sm border border-slate-300 rounded-xl">
                    </div>
                </div>

                <div class="p-4 bg-sky-50/70 rounded-xl border border-sky-100 space-y-3">
                    <p class="text-xs font-bold text-sky-800 uppercase">Regla de Validación Automática (CAA)</p>
                    <div class="grid grid-cols-1 sm:grid-cols-3 gap-3">
                        <div>
                            <label class="block text-xs font-semibold text-slate-600 mb-1">Operador Evaluación</label>
                            <select id="pm-caa-op" class="w-full px-3 py-2 text-sm border border-slate-300 rounded-xl bg-white">
                                <option value="NINGUNO">Sin límite restrictivo (--)</option>
                                <option value="<">Menor que (&lt; Máximo)</option>
                                <option value="RANGO">Rango (Mínimo - Máximo)</option>
                                <option value="IGUAL">Igual a texto esperado</option>
                            </select>
                        </div>
                        <div>
                            <label class="block text-xs font-semibold text-slate-600 mb-1">Valor Mínimo (si Rango)</label>
                            <input type="number" step="any" id="pm-caa-min" class="w-full px-3 py-2 text-sm border border-slate-300 rounded-xl bg-white">
                        </div>
                        <div>
                            <label class="block text-xs font-semibold text-slate-600 mb-1">Valor Máximo (CAA)</label>
                            <input type="number" step="any" id="pm-caa-max" class="w-full px-3 py-2 text-sm border border-slate-300 rounded-xl bg-white">
                        </div>
                    </div>
                    <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
                        <div>
                            <label class="block text-xs font-semibold text-slate-600 mb-1">Texto Impreso Ref. CAA</label>
                            <input type="text" id="pm-caa-texto" placeholder="Ej: < 3 NTU o 6.5-8.5" class="w-full px-3 py-2 text-sm border border-slate-300 rounded-xl bg-white">
                        </div>
                        <div>
                            <label class="block text-xs font-semibold text-slate-600 mb-1">Valor Cualitativo Esperado</label>
                            <input type="text" id="pm-caa-cual" placeholder="Ej: Ausencia / Incoloro" class="w-full px-3 py-2 text-sm border border-slate-300 rounded-xl bg-white">
                        </div>
                    </div>
                </div>

                <div class="grid grid-cols-1 sm:grid-cols-3 gap-4">
                    <div>
                        <label class="block text-xs font-semibold text-slate-600 mb-1">Ref. Consumo Bovino (INTA)</label>
                        <input type="text" id="pm-inta" class="w-full px-3 py-2 text-sm border border-slate-300 rounded-xl">
                    </div>
                    <div>
                        <label class="block text-xs font-semibold text-slate-600 mb-1">Límite de Detección</label>
                        <input type="text" id="pm-ld" class="w-full px-3 py-2 text-sm border border-slate-300 rounded-xl">
                    </div>
                    <div>
                        <label class="block text-xs font-semibold text-slate-600 mb-1">Incertidumbre</label>
                        <input type="text" id="pm-inc" class="w-full px-3 py-2 text-sm border border-slate-300 rounded-xl">
                    </div>
                </div>

                <div>
                    <label class="block text-xs font-semibold text-slate-600 mb-1">Método Analítico</label>
                    <input type="text" id="pm-metodo" class="w-full px-3 py-2 text-sm border border-slate-300 rounded-xl">
                </div>

                <div>
                    <label class="block text-xs font-semibold text-slate-600 mb-1">Nota Técnica al Pie (Opcional)</label>
                    <textarea id="pm-nota" rows="2" class="w-full px-3 py-2 text-sm border border-slate-300 rounded-xl"></textarea>
                </div>

                <div class="flex justify-end gap-3 pt-2">
                    <button type="button" onclick="closeParamModal()" class="px-4 py-2 rounded-xl border border-slate-300 text-sm">Cancelar</button>
                    <button type="submit" class="px-5 py-2 rounded-xl bg-sky-600 text-white text-sm font-semibold">Guardar Cambios</button>
                </div>
            </form>
        </div>
    </div>

    <!-- ==================== VISTA PREVIA E IMPRESIÓN PDF TAMAÑO A4 ==================== -->
    <div id="print-preview-overlay" class="fixed inset-0 bg-slate-900/80 z-50 hidden overflow-y-auto print-only-container">
        <!-- Barra de herramientas superior de vista previa (Oculta en PDF/Impresión) -->
        <div class="sticky top-0 z-10 bg-slate-900 text-white px-6 py-3 flex flex-wrap items-center justify-between gap-4 shadow-lg no-print">
            <div class="flex items-center gap-3">
                <i class="fa-solid fa-file-pdf text-rose-400 text-xl"></i>
                <div>
                    <h4 class="font-bold text-sm">Vista Previa de Informe Oficial - Formato A4</h4>
                    <p class="text-xs text-slate-400">Listo para imprimir o guardar como archivo PDF tamaño A4</p>
                </div>
            </div>
            <div class="flex items-center gap-3">
                <button onclick="window.print()" class="px-5 py-2 bg-emerald-600 hover:bg-emerald-500 text-white text-sm font-semibold rounded-xl shadow flex items-center gap-2 transition">
                    <i class="fa-solid fa-print"></i> Exportar PDF / Imprimir A4
                </button>
                <button onclick="closePrintPreview()" class="px-4 py-2 bg-slate-700 hover:bg-slate-600 text-white text-sm rounded-xl transition">
                    <i class="fa-solid fa-xmark"></i> Cerrar Vista Previa
                </button>
            </div>
        </div>

        <!-- Hoja A4 Oficial -->
        <div class="py-8 px-4 print-only-container">
            <div id="a4-document-content" class="a4-sheet">
                <!-- Se renderiza dinámicamente con los datos exactos del protocolo -->
            </div>
        </div>
    </div>

    <!-- ==================== LÓGICA JAVASCRIPT ==================== -->
    <script>
        let STATE = {
            config: {},
            firmantes: [],
            parametros: [],
            protocolos: []
        };

        document.addEventListener("DOMContentLoaded", () => {
            loadBootstrapData();
        });

        async function loadBootstrapData() {
            const res = await fetch("/api/bootstrap");
            STATE = await res.json();
            updateDashboardKPIs();
            renderProtocolsTable();
            renderParametrosConfigTable();
            populateLabConfigForm();
        }

        function showToast(msg, isError = false) {
            const toast = document.getElementById("toast");
            const box = document.getElementById("toast-box");
            const icon = document.getElementById("toast-icon");
            const text = document.getElementById("toast-msg");

            text.textContent = msg;
            if (isError) {
                box.className = "flex items-center gap-3 px-4 py-3 rounded-xl shadow-lg text-white text-sm font-medium bg-rose-600";
                icon.className = "fa-solid fa-circle-exclamation text-white";
            } else {
                box.className = "flex items-center gap-3 px-4 py-3 rounded-xl shadow-lg text-white text-sm font-medium bg-slate-900";
                icon.className = "fa-solid fa-circle-check text-emerald-400";
            }
            toast.classList.remove("hidden");
            setTimeout(() => toast.classList.add("hidden"), 3200);
        }

        function switchView(viewName) {
            ["dashboard", "editor", "parametros", "configuracion"].forEach(v => {
                document.getElementById(`view-${v}`).classList.add("hidden");
                const navBtn = document.getElementById(`nav-${v}`);
                if (navBtn) {
                    navBtn.className = "nav-btn flex items-center gap-3 px-4 py-3 rounded-xl text-sm font-medium text-slate-300 hover:bg-slate-800 hover:text-white transition-all whitespace-nowrap";
                }
            });

            document.getElementById(`view-${viewName}`).classList.remove("hidden");
            const activeBtn = document.getElementById(`nav-${viewName}`);
            if (activeBtn) {
                activeBtn.className = "nav-btn flex items-center gap-3 px-4 py-3 rounded-xl text-sm font-medium transition-all bg-sky-600 text-white whitespace-nowrap";
            }

            const titles = {
                dashboard: ["Panel de Control Bromatológico", "Gestión de protocolos de análisis físico-químicos y microbiológicos de agua"],
                editor: ["Carga y Edición de Protocolo", "Ingreso de determinaciones con validación automática CAA / INTA"],
                parametros: ["Normativas y Valores de Referencia", "Parametrización de límites del Código Alimentario Argentino e INTA Balcarce"],
                configuracion: ["Configuración del Laboratorio", "Datos institucionales, consideraciones legales y cuerpo de firmantes"]
            };
            document.getElementById("page-title").textContent = titles[viewName][0];
            document.getElementById("page-subtitle").textContent = titles[viewName][1];
        }

        // -------------------- DASHBOARD --------------------
        function updateDashboardKPIs() {
            const total = STATE.protocolos.length;
            const aptos = STATE.protocolos.filter(p => p.cumple_caa === 1).length;
            const noAptos = total - aptos;

            document.getElementById("kpi-total").textContent = total;
            document.getElementById("kpi-aptos").textContent = aptos;
            document.getElementById("kpi-no-aptos").textContent = noAptos;
            document.getElementById("kpi-params").textContent = STATE.parametros.length;
        }

        function renderProtocolsTable() {
            const query = (document.getElementById("search-protocol").value || "").toLowerCase();
            const tbody = document.getElementById("protocols-tbody");
            const filtered = STATE.protocolos.filter(p =>
                p.numero_protocolo.toLowerCase().includes(query) ||
                p.cliente_nombre.toLowerCase().includes(query) ||
                p.rotulo_muestra.toLowerCase().includes(query)
            );

            if (filtered.length === 0) {
                tbody.innerHTML = `<tr><td colspan="6" class="py-8 text-center text-slate-400">No se encontraron protocolos registrados.</td></tr>`;
                return;
            }

            tbody.innerHTML = filtered.map(p => {
                const badge = p.cumple_caa === 1
                    ? `<span class="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold bg-emerald-50 text-emerald-700 border border-emerald-200"><i class="fa-solid fa-check-circle"></i> Cumple CAA</span>`
                    : `<span class="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold bg-rose-50 text-rose-700 border border-rose-200"><i class="fa-solid fa-circle-exclamation"></i> Fuera de Norma</span>`;

                return `
                    <tr class="hover:bg-slate-50/80 transition">
                        <td class="py-3.5 px-4 font-mono font-bold text-slate-800">#${p.numero_protocolo}</td>
                        <td class="py-3.5 px-4 text-slate-600">${formatDateAR(p.fecha_informe)}</td>
                        <td class="py-3.5 px-4">
                            <div class="font-semibold text-slate-800">${p.cliente_nombre}</div>
                            <div class="text-xs text-slate-400">CUIT/DNI: ${p.cliente_cuit}</div>
                        </td>
                        <td class="py-3.5 px-4">
                            <div class="text-slate-700">${p.rotulo_muestra}</div>
                            <div class="text-xs text-slate-400"><i class="fa-solid fa-location-dot mr-1"></i>${p.punto_toma}</div>
                        </td>
                        <td class="py-3.5 px-4">${badge}</td>
                        <td class="py-3.5 px-4 text-right space-x-1 whitespace-nowrap">
                            <button onclick="openPrintPreview(${p.id})" title="Ver Informe A4 / PDF"
                                class="px-3 py-1.5 bg-rose-50 hover:bg-rose-100 text-rose-700 rounded-lg text-xs font-semibold transition inline-flex items-center gap-1.5">
                                <i class="fa-solid fa-file-pdf"></i> Informe A4
                            </button>
                            <button onclick="editProtocol(${p.id})" title="Editar Protocolo"
                                class="px-3 py-1.5 bg-sky-50 hover:bg-sky-100 text-sky-700 rounded-lg text-xs font-semibold transition inline-flex items-center gap-1">
                                <i class="fa-solid fa-pen"></i> Editar
                            </button>
                            <button onclick="deleteProtocol(${p.id})" title="Eliminar"
                                class="px-2.5 py-1.5 text-slate-400 hover:text-rose-600 rounded-lg text-xs transition">
                                <i class="fa-solid fa-trash"></i>
                            </button>
                        </td>
                    </tr>
                `;
            }).join("");
        }

        // -------------------- EDITOR DE PROTOCOLO --------------------
        function buildEditorRows(existingResultsMap = {}) {
            const fqBody = document.getElementById("editor-fq-tbody");
            const microBody = document.getElementById("editor-micro-tbody");
            fqBody.innerHTML = "";
            microBody.innerHTML = "";

            STATE.parametros.forEach(param => {
                const prev = existingResultsMap[param.id] || {};
                const op = prev.operador || "=";
                const valNum = prev.valor_numerico !== null && prev.valor_numerico !== undefined ? prev.valor_numerico : "";
                const valTxt = prev.valor_texto || (param.tipo_dato === "CUALITATIVO" ? (param.caa_valor_cualitativo || "") : "");

                let inputHtml = "";
                if (param.tipo_dato === "CUALITATIVO") {
                    inputHtml = `
                        <input type="text" data-param-id="${param.id}" data-field="valor_texto" value="${valTxt}"
                            oninput="validateRowLive(${param.id})"
                            class="w-full px-2.5 py-1.5 text-sm border border-slate-300 rounded-lg focus:ring-2 focus:ring-sky-500 outline-none">
                    `;
                } else {
                    inputHtml = `
                        <input type="number" step="any" data-param-id="${param.id}" data-field="valor_numerico" value="${valNum}"
                            oninput="validateRowLive(${param.id})" placeholder="0.00"
                            class="w-full px-2.5 py-1.5 text-sm border border-slate-300 rounded-lg focus:ring-2 focus:ring-sky-500 outline-none font-mono">
                    `;
                }

                const opSelectHtml = param.tipo_dato === "NUMERICO" ? `
                    <select data-param-id="${param.id}" data-field="operador" onchange="validateRowLive(${param.id})"
                        class="w-full px-2 py-1.5 text-sm border border-slate-300 rounded-lg bg-white font-mono">
                        <option value="=" ${op === "=" ? "selected" : ""}>=</option>
                        <option value="<" ${op === "<" ? "selected" : ""}>&lt;</option>
                        <option value=">" ${op === ">" ? "selected" : ""}>&gt;</option>
                    </select>
                ` : `<span class="text-xs text-slate-400 font-mono">Texto</span>`;

                const rowHtml = `
                    <tr class="hover:bg-slate-50/60">
                        <td class="py-2 px-3 font-medium text-slate-800">
                            ${param.nombre}
                            <div class="text-[11px] text-slate-400">${param.metodo || ""}</div>
                        </td>
                        <td class="py-2 px-3">${opSelectHtml}</td>
                        <td class="py-2 px-3">${inputHtml}</td>
                        <td class="py-2 px-3 text-slate-600 text-xs">${param.unidad || "-"}</td>
                        <td class="py-2 px-3 text-xs font-medium text-sky-700">${param.caa_texto || "--"}</td>
                        ${param.categoria === "FISICO_QUIMICO" ? `<td class="py-2 px-3 text-xs text-slate-500">${param.inta_texto || "-"}</td>` : ""}
                        <td class="py-2 px-3 text-center" id="status-badge-${param.id}">
                            <span class="px-2 py-0.5 rounded-full text-xs bg-emerald-50 text-emerald-700 font-medium">OK</span>
                        </td>
                    </tr>
                `;

                if (param.categoria === "FISICO_QUIMICO") {
                    fqBody.insertAdjacentHTML("beforeend", rowHtml);
                } else {
                    microBody.insertAdjacentHTML("beforeend", rowHtml);
                }
                validateRowLive(param.id);
            });
        }

        function validateRowLive(paramId) {
            const param = STATE.parametros.find(p => p.id === paramId);
            const badge = document.getElementById(`status-badge-${paramId}`);
            if (!param || !badge) return;

            let cumple = true;
            if (param.tipo_dato === "CUALITATIVO") {
                const input = document.querySelector(`[data-param-id="${paramId}"][data-field="valor_texto"]`);
                const val = (input ? input.value : "").trim().toLowerCase();
                const esp = (param.caa_valor_cualitativo || "").trim().toLowerCase();
                if (param.caa_operador === "IGUAL" && val && esp) {
                    if (esp.startsWith("incolor") && val.startsWith("incolor")) cumple = true;
                    else if (esp.startsWith("inodor") && val.startsWith("inodor")) cumple = true;
                    else cumple = val === esp;
                }
            } else {
                const numInput = document.querySelector(`[data-param-id="${paramId}"][data-field="valor_numerico"]`);
                const opInput = document.querySelector(`[data-param-id="${paramId}"][data-field="operador"]`);
                const raw = numInput ? numInput.value : "";
                const op = opInput ? opInput.value : "=";
                if (raw !== "") {
                    const val = parseFloat(raw);
                    if (param.caa_operador === "<" && param.caa_max !== null) {
                        cumple = op === "<" ? val <= param.caa_max : val < param.caa_max;
                    } else if (param.caa_operador === "RANGO" && param.caa_min !== null && param.caa_max !== null) {
                        cumple = val >= param.caa_min && val <= param.caa_max;
                    }
                }
            }

            badge.innerHTML = cumple
                ? `<span class="px-2 py-0.5 rounded-full text-xs bg-emerald-50 text-emerald-700 font-semibold">Cumple</span>`
                : `<span class="px-2 py-0.5 rounded-full text-xs bg-rose-100 text-rose-700 font-bold">Excede</span>`;
        }

        function openNewProtocol() {
            document.getElementById("protocol-form").reset();
            document.getElementById("edit-proto-id").value = "";
            const today = new Date().toISOString().split("T")[0];
            document.getElementById("f-fecha-informe").value = today;
            document.getElementById("f-fecha-toma").value = `${today}T12:00`;
            document.getElementById("f-fecha-recepcion").value = `${today}T18:00`;
            document.getElementById("f-numero").value = Math.floor(26419750 + Math.random() * 900);
            buildEditorRows({});
            switchView("editor");
        }

        async function editProtocol(protoId) {
            const res = await fetch(`/api/protocolos/${protoId}`);
            const data = await res.json();
            const p = data.protocolo;

            document.getElementById("edit-proto-id").value = p.id;
            document.getElementById("f-numero").value = p.numero_protocolo;
            document.getElementById("f-fecha-informe").value = p.fecha_informe;
            document.getElementById("f-reimpresion").checked = p.es_reimpresion === 1;
            document.getElementById("f-cliente").value = p.cliente_nombre;
            document.getElementById("f-cuit").value = p.cliente_cuit;
            document.getElementById("f-informe-para").value = p.informe_para;
            document.getElementById("f-doctor").value = p.doctor || "--";
            document.getElementById("f-estudio").value = p.estudio_solicitado;
            document.getElementById("f-responsable").value = p.responsable_toma;
            document.getElementById("f-tipo-muestra").value = p.tipo_muestra;
            document.getElementById("f-rotulo").value = p.rotulo_muestra;
            document.getElementById("f-punto-toma").value = p.punto_toma;
            document.getElementById("f-fecha-toma").value = p.fecha_toma;
            document.getElementById("f-fecha-recepcion").value = p.fecha_recepcion;

            const resultsMap = {};
            data.resultados.forEach(r => { resultsMap[r.parametro_id] = r; });
            buildEditorRows(resultsMap);
            switchView("editor");
        }

        async function saveProtocol(e) {
            e.preventDefault();
            const resultados = STATE.parametros.map(param => {
                const opEl = document.querySelector(`[data-param-id="${param.id}"][data-field="operador"]`);
                const numEl = document.querySelector(`[data-param-id="${param.id}"][data-field="valor_numerico"]`);
                const txtEl = document.querySelector(`[data-param-id="${param.id}"][data-field="valor_texto"]`);

                const op = opEl ? opEl.value : "=";
                const valNum = numEl && numEl.value !== "" ? parseFloat(numEl.value) : null;
                let valTxt = txtEl ? txtEl.value : "";

                if (param.tipo_dato === "NUMERICO" && valNum !== null) {
                    if (param.nombre === "Nitratos" && op === "<" && valNum === 1) {
                        valTxt = "Menor a 1";
                    } else if (op === "<" || op === ">") {
                        valTxt = `${op}${valNum}`;
                    } else {
                        valTxt = valNum.toFixed(2);
                    }
                }

                return {
                    parametro_id: param.id,
                    operador: op,
                    valor_numerico: valNum,
                    valor_texto: valTxt
                };
            });

            const payload = {
                id: document.getElementById("edit-proto-id").value || null,
                numero_protocolo: document.getElementById("f-numero").value.trim(),
                fecha_informe: document.getElementById("f-fecha-informe").value,
                es_reimpresion: document.getElementById("f-reimpresion").checked,
                cliente_nombre: document.getElementById("f-cliente").value.trim(),
                cliente_cuit: document.getElementById("f-cuit").value.trim(),
                informe_para: document.getElementById("f-informe-para").value.trim(),
                doctor: document.getElementById("f-doctor").value.trim(),
                estudio_solicitado: document.getElementById("f-estudio").value.trim(),
                responsable_toma: document.getElementById("f-responsable").value.trim(),
                tipo_muestra: document.getElementById("f-tipo-muestra").value.trim(),
                rotulo_muestra: document.getElementById("f-rotulo").value.trim(),
                punto_toma: document.getElementById("f-punto-toma").value.trim(),
                fecha_toma: document.getElementById("f-fecha-toma").value,
                fecha_recepcion: document.getElementById("f-fecha-recepcion").value,
                resultados
            };

            const res = await fetch("/api/protocolos", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload)
            });

            const result = await res.json();
            if (!res.ok) {
                showToast(result.error || "Error al guardar protocolo", true);
                return;
            }

            showToast("Protocolo guardado correctamente");
            await loadBootstrapData();
            switchView("dashboard");
            openPrintPreview(result.id);
        }

        async function deleteProtocol(id) {
            await fetch(`/api/protocolos/${id}`, { method: "DELETE" });
            showToast("Protocolo eliminado");
            loadBootstrapData();
        }

        // -------------------- PARAMETRIZACIÓN --------------------
        function renderParametrosConfigTable() {
            const tbody = document.getElementById("params-config-tbody");
            tbody.innerHTML = STATE.parametros.map(p => `
                <tr class="hover:bg-slate-50">
                    <td class="py-2.5 px-3 font-mono text-xs text-slate-500">${p.orden}</td>
                    <td class="py-2.5 px-3">
                        <span class="px-2 py-0.5 rounded-md text-[11px] font-semibold ${p.categoria === 'FISICO_QUIMICO' ? 'bg-sky-50 text-sky-700' : 'bg-emerald-50 text-emerald-700'}">
                            ${p.categoria === 'FISICO_QUIMICO' ? 'Físico-Químico' : 'Microbiológico'}
                        </span>
                    </td>
                    <td class="py-2.5 px-3 font-semibold text-slate-800">${p.nombre}</td>
                    <td class="py-2.5 px-3 text-xs text-slate-600">${p.unidad || "-"}</td>
                    <td class="py-2.5 px-3 font-mono text-xs text-slate-600">${p.caa_operador}</td>
                    <td class="py-2.5 px-3 text-xs font-semibold text-sky-700">${p.caa_texto || "--"}</td>
                    <td class="py-2.5 px-3 text-xs text-slate-600">${p.inta_texto || "-"}</td>
                    <td class="py-2.5 px-3 text-xs text-slate-500 max-w-[180px] truncate" title="${p.metodo || ''}">${p.metodo || "-"}</td>
                    <td class="py-2.5 px-3 text-right">
                        <button onclick="openParamModal(${p.id})" class="px-3 py-1 bg-slate-100 hover:bg-sky-100 text-slate-700 hover:text-sky-700 rounded-lg text-xs font-medium transition">
                            <i class="fa-solid fa-pen-to-square"></i> Configurar
                        </button>
                    </td>
                </tr>
            `).join("");
        }

        function openParamModal(paramId = null) {
            const modal = document.getElementById("param-modal");
            if (paramId) {
                const p = STATE.parametros.find(x => x.id === paramId);
                document.getElementById("pm-id").value = p.id;
                document.getElementById("pm-orden").value = p.orden;
                document.getElementById("pm-categoria").value = p.categoria;
                document.getElementById("pm-tipo").value = p.tipo_dato;
                document.getElementById("pm-nombre").value = p.nombre;
                document.getElementById("pm-unidad").value = p.unidad || "";
                document.getElementById("pm-caa-op").value = p.caa_operador || "NINGUNO";
                document.getElementById("pm-caa-min").value = p.caa_min !== null ? p.caa_min : "";
                document.getElementById("pm-caa-max").value = p.caa_max !== null ? p.caa_max : "";
                document.getElementById("pm-caa-texto").value = p.caa_texto || "";
                document.getElementById("pm-caa-cual").value = p.caa_valor_cualitativo || "";
                document.getElementById("pm-inta").value = p.inta_texto || "";
                document.getElementById("pm-ld").value = p.limite_deteccion || "";
                document.getElementById("pm-inc").value = p.incertidumbre || "";
                document.getElementById("pm-metodo").value = p.metodo || "";
                document.getElementById("pm-nota").value = p.nota_tecnica || "";
            } else {
                document.getElementById("pm-id").value = "";
                document.getElementById("pm-orden").value = STATE.parametros.length + 1;
                document.getElementById("pm-categoria").value = "FISICO_QUIMICO";
                document.getElementById("pm-tipo").value = "NUMERICO";
                document.getElementById("pm-nombre").value = "";
                document.getElementById("pm-unidad").value = "mg/l";
                document.getElementById("pm-caa-op").value = "<";
                document.getElementById("pm-caa-min").value = "";
                document.getElementById("pm-caa-max").value = "";
                document.getElementById("pm-caa-texto").value = "";
                document.getElementById("pm-caa-cual").value = "";
                document.getElementById("pm-inta").value = "-";
                document.getElementById("pm-ld").value = "-";
                document.getElementById("pm-inc").value = "-";
                document.getElementById("pm-metodo").value = "St. Met.";
                document.getElementById("pm-nota").value = "";
            }
            modal.classList.remove("hidden");
        }

        function closeParamModal() {
            document.getElementById("param-modal").classList.add("hidden");
        }

        async function saveParametro(e) {
            e.preventDefault();
            const payload = {
                id: document.getElementById("pm-id").value || null,
                orden: document.getElementById("pm-orden").value,
                categoria: document.getElementById("pm-categoria").value,
                tipo_dato: document.getElementById("pm-tipo").value,
                nombre: document.getElementById("pm-nombre").value,
                unidad: document.getElementById("pm-unidad").value,
                caa_operador: document.getElementById("pm-caa-op").value,
                caa_min: document.getElementById("pm-caa-min").value,
                caa_max: document.getElementById("pm-caa-max").value,
                caa_texto: document.getElementById("pm-caa-texto").value,
                caa_valor_cualitativo: document.getElementById("pm-caa-cual").value,
                inta_texto: document.getElementById("pm-inta").value,
                limite_deteccion: document.getElementById("pm-ld").value,
                incertidumbre: document.getElementById("pm-inc").value,
                metodo: document.getElementById("pm-metodo").value,
                nota_tecnica: document.getElementById("pm-nota").value
            };

            await fetch("/api/parametros", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload)
            });

            closeParamModal();
            showToast("Parámetro y valores de referencia actualizados");
            loadBootstrapData();
        }

        // -------------------- CONFIGURACIÓN LAB Y FIRMANTES --------------------
        function populateLabConfigForm() {
            const c = STATE.config;
            document.getElementById("cfg-nombre").value = c.nombre || "";
            document.getElementById("cfg-subtitulo").value = c.subtitulo || "";
            document.getElementById("cfg-direccion").value = c.direccion || "";
            document.getElementById("cfg-telefono").value = c.telefono || "";
            document.getElementById("cfg-email").value = c.email || "";
            document.getElementById("cfg-consideraciones").value = c.consideraciones_legales || "";

            const list = document.getElementById("firmantes-list");
            list.innerHTML = STATE.firmantes.map(f => `
                <div class="flex items-center justify-between p-3 rounded-xl border border-slate-200 bg-white">
                    <div>
                        <p class="font-semibold text-sm text-slate-800">${f.nombre}</p>
                        <p class="text-xs text-slate-500">${f.matricula} • <span class="text-sky-600 font-medium">${f.rol}</span></p>
                    </div>
                    <button onclick="deleteFirmante(${f.id})" class="text-slate-400 hover:text-rose-600 p-2">
                        <i class="fa-solid fa-trash-can"></i>
                    </button>
                </div>
            `).join("");
        }

        async function saveLabConfig(e) {
            e.preventDefault();
            const payload = {
                nombre: document.getElementById("cfg-nombre").value,
                subtitulo: document.getElementById("cfg-subtitulo").value,
                direccion: document.getElementById("cfg-direccion").value,
                telefono: document.getElementById("cfg-telefono").value,
                email: document.getElementById("cfg-email").value,
                consideraciones_legales: document.getElementById("cfg-consideraciones").value
            };
            await fetch("/api/configuracion", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload)
            });
            showToast("Configuración del laboratorio guardada");
            loadBootstrapData();
        }

        async function addFirmante(e) {
            e.preventDefault();
            const payload = {
                nombre: document.getElementById("new-firm-nombre").value,
                matricula: document.getElementById("new-firm-mat").value,
                rol: document.getElementById("new-firm-rol").value
            };
            await fetch("/api/firmantes", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload)
            });
            document.getElementById("new-firm-nombre").value = "";
            document.getElementById("new-firm-mat").value = "";
            showToast("Profesional firmante agregado");
            loadBootstrapData();
        }

        async function deleteFirmante(id) {
            await fetch(`/api/firmantes/${id}`, { method: "DELETE" });
            showToast("Firmante eliminado");
            loadBootstrapData();
        }

        // -------------------- GENERACIÓN DE INFORME OFICIAL A4 --------------------
        function formatDateAR(isoDate) {
            if (!isoDate) return "";
            const parts = isoDate.split("T")[0].split("-");
            if (parts.length !== 3) return isoDate;
            return `${parts[2]}/${parts[1]}/${parts[0]}`;
        }

        function formatDateTimeAR(isoDateTime) {
            if (!isoDateTime) return "";
            const [d, t] = isoDateTime.split("T");
            return `${formatDateAR(d)}, ${t || ""}h`;
        }

        async function openPrintPreview(protoId) {
            const res = await fetch(`/api/protocolos/${protoId}`);
            const data = await res.json();
            const p = data.protocolo;
            const cfg = STATE.config;

            const fqRows = data.resultados.filter(r => r.categoria === "FISICO_QUIMICO");
            const microRows = data.resultados.filter(r => r.categoria === "MICROBIOLOGICO");

            const validadoresMicro = STATE.firmantes
                .filter(f => f.rol.toLowerCase().includes("micro"))
                .map(f => `<div>Bioq. ${f.nombre.replace(/^Dr\.?\s*/i, '').replace(/^Dra\.?\s*/i, '')} - ${f.matricula.replace('M.P.P.:', 'M.P.')}</div>`)
                .join("");

            const consideracionesHtml = (cfg.consideraciones_legales || "")
                .split("\\n")
                .filter(line => line.trim() !== "")
                .map(line => `<li>- ${line.trim()}</li>`)
                .join("");

            const conclusionTexto = p.cumple_caa === 1
                ? "La muestra analizada, en base a los análisis efectuados, cumple con los requisitos exigidos por el CAA (Código Alimentario Argentino)"
                : "ATENCIÓN: La muestra analizada presenta parámetros fuera de los límites recomendados por el CAA (Código Alimentario Argentino).";

            const fqHtml = fqRows.map(r => {
                const resDisplay = r.valor_texto ? `${r.valor_texto} ${r.unidad && r.unidad !== '-' ? r.unidad : ''}` : '-';
                const refCaa = r.caa_texto && r.caa_texto !== '--' && r.caa_texto !== '-'
                    ? `<div>Valor recomendado por el CAA: <strong>${r.caa_texto}</strong></div>`
                    : (r.caa_texto === '--' ? `<div>Valor recomendado para consumo humano (CAA): --</div>` : '');
                const refInta = r.inta_texto && r.inta_texto !== '-'
                    ? `<div>Valor recomendado para consumo bovino (INTA BALCARCE): ${r.inta_texto}</div>`
                    : '';
                const incHtml = r.incertidumbre && r.incertidumbre !== '-'
                    ? `<div>Incertidumbre: ${r.incertidumbre}</div>`
                    : '';
                const ldHtml = r.limite_deteccion && r.limite_deteccion !== '-'
                    ? `<div>Límite de Detección: ${r.limite_deteccion}</div>`
                    : '';
                const metHtml = r.metodo && r.metodo !== '-'
                    ? `<div>Método: ${r.metodo}</div>`
                    : '';
                const notaHtml = r.nota_tecnica
                    ? `<div class="text-[7.5pt] text-slate-600 mt-1 leading-tight">${r.nota_tecnica}</div>`
                    : '';

                return `
                    <div class="py-1.5 border-b border-slate-100 avoid-break">
                        <div class="flex justify-between items-baseline">
                            <span class="font-bold text-slate-900">${r.nombre}</span>
                            <span class="font-bold text-slate-900 ${r.cumple_caa === 0 ? 'text-rose-700 underline' : ''}">${resDisplay}</span>
                        </div>
                        <div class="pl-3 text-[8.5pt] text-slate-700 space-y-0.5 mt-0.5">
                            ${refCaa}
                            ${refInta}
                            ${incHtml}
                            ${ldHtml}
                            ${metHtml}
                            ${notaHtml}
                        </div>
                    </div>
                `;
            }).join("");

            const microHtml = microRows.map(r => {
                return `
                    <div class="py-1.5 border-b border-slate-100 avoid-break">
                        <div class="grid grid-cols-12 items-baseline">
                            <span class="col-span-5 font-bold text-slate-900">${r.nombre}</span>
                            <span class="col-span-4 font-bold text-slate-900 ${r.cumple_caa === 0 ? 'text-rose-700' : ''}">${r.valor_texto || '-'}</span>
                            <span class="col-span-3 text-right text-[8.5pt] text-slate-700">${r.unidad && r.unidad !== '-' ? r.unidad : ''}</span>
                        </div>
                        <div class="pl-3 text-[8.5pt] text-slate-700 space-y-0.5 mt-0.5">
                            <div>Valor Recomendado: ${r.caa_texto || '-'}</div>
                            <div>Método: ${r.metodo || 'APHA (1995)'}</div>
                        </div>
                    </div>
                `;
            }).join("");

            const firmasHtml = STATE.firmantes.map(f => `
                <div class="text-center px-2">
                    <div class="h-12 flex items-end justify-center mb-1">
                        <span class="font-serif italic text-slate-500 text-xs border-b border-slate-400 px-4 pb-0.5">Firmado electrónicamente</span>
                    </div>
                    <div class="font-bold text-[8.5pt] text-slate-900">${f.nombre}</div>
                    <div class="text-[8pt] text-slate-600">${f.matricula}</div>
                </div>
            `).join("");

            const docHtml = `
                <!-- Encabezado Institucional -->
                <div class="flex justify-between items-start border-b-2 border-slate-800 pb-3 mb-3">
                    <div class="flex items-center gap-3">
                        <div class="w-12 h-12 bg-slate-800 text-white flex items-center justify-center font-black text-2xl tracking-tighter rounded-sm">
                            M
                        </div>
                        <div>
                            <div class="font-bold text-sm tracking-wide text-slate-900 uppercase">${cfg.nombre}</div>
                            <div class="bg-slate-700 text-white text-[7.5pt] px-2 py-0.5 tracking-widest uppercase inline-block font-semibold">
                                ${cfg.subtitulo}
                            </div>
                        </div>
                    </div>
                    <div class="text-right text-[8.5pt] text-slate-700 leading-snug">
                        <div>${cfg.direccion}</div>
                        <div>Tel: ${cfg.telefono}</div>
                        <div>E-mail: ${cfg.email}</div>
                    </div>
                </div>

                <!-- Caja de Datos del Cliente y Protocolo -->
                <div class="bg-slate-100 border border-slate-300 p-2.5 mb-2 text-[8.5pt]">
                    <div class="grid grid-cols-12 gap-2">
                        <div class="col-span-7 space-y-1">
                            <div class="font-bold text-slate-900 text-[9.5pt]">${p.cliente_nombre}</div>
                            <div><span class="font-semibold">DNI / CUIT:</span> ${p.cliente_cuit}</div>
                            <div><span class="font-semibold">Doctor:</span> ${p.doctor || '--'}</div>
                        </div>
                        <div class="col-span-5 space-y-1 text-right">
                            <div class="bg-slate-300/80 px-2 py-0.5 font-bold text-slate-900 flex justify-between">
                                <span>Número de protocolo:</span>
                                <span class="font-mono">${p.numero_protocolo}</span>
                            </div>
                            <div><span class="font-semibold">Fecha:</span> ${formatDateAR(p.fecha_informe)}</div>
                            <div><span class="font-semibold">Informe para:</span> ${p.informe_para}</div>
                            ${p.es_reimpresion ? `<div class="italic text-slate-600 text-[8pt]">Reimpresión de resultados</div>` : ''}
                        </div>
                    </div>
                </div>

                <!-- Cabecera de Columnas -->
                <div class="grid grid-cols-12 border-y border-slate-800 py-1 text-[8.5pt] font-bold text-slate-800 uppercase mb-2">
                    <div class="col-span-5">PRUEBA</div>
                    <div class="col-span-3 text-right">RESULTADO</div>
                    <div class="col-span-1 text-center">UNIDAD</div>
                    <div class="col-span-3 text-right">VALORES DE REFERENCIA</div>
                </div>

                <!-- Título Sección Bromatología -->
                <div class="text-center font-bold underline text-[10pt] tracking-wide mb-2">BROMATOLOGÍA</div>

                <!-- Datos de la Muestra -->
                <div class="mb-3 text-[8.5pt] space-y-0.5 bg-slate-50/70 p-2.5 border border-slate-200">
                    <div class="font-bold uppercase text-slate-900">ANÁLISIS DE AGUAS</div>
                    <div class="italic font-semibold text-slate-700">DATOS DE LA MUESTRA</div>
                    <div class="text-slate-600 mb-1">Datos informados por el cliente</div>
                    <div><span class="font-semibold">Estudio solicitado:</span> ${p.estudio_solicitado}</div>
                    <div><span class="font-semibold">Responsable de la toma de muestra:</span> ${p.responsable_toma}</div>
                    <div><span class="font-semibold">Tipo de muestra:</span> ${p.tipo_muestra}</div>
                    <div><span class="font-semibold">Rótulo de la muestra:</span> ${p.rotulo_muestra}</div>
                    <div><span class="font-semibold">Punto de toma de muestra:</span> ${p.punto_toma}</div>
                    <div><span class="font-semibold">Toma de muestra:</span> ${formatDateTimeAR(p.fecha_toma)}</div>
                    <div><span class="font-semibold">Recepción de muestra:</span> ${formatDateTimeAR(p.fecha_recepcion)}</div>
                </div>

                <!-- Análisis Físico-Químico -->
                <div class="mb-4">
                    <div class="font-bold uppercase text-[9pt] border-b border-slate-400 pb-0.5 mb-1">ANÁLISIS FÍSICO-QUÍMICO</div>
                    ${fqHtml}
                </div>

                <!-- Estudio Microbiológico -->
                <div class="mb-4 avoid-break">
                    <div class="flex justify-between items-start border-b border-slate-400 pb-1 mb-1.5">
                        <div>
                            <div class="font-bold uppercase text-[9pt]">ESTUDIO MICROBIOLÓGICO</div>
                            <div class="font-bold text-[8.5pt]">Muestra Analizada: AGUA</div>
                        </div>
                        <div class="text-right text-[8pt] text-slate-700">
                            <span class="font-semibold">Validado por:</span>
                            ${validadoresMicro}
                        </div>
                    </div>
                    ${microHtml}
                </div>

                <!-- Conclusión y Consideraciones Legales -->
                <div class="mt-4 p-3 border border-slate-300 bg-slate-50 avoid-break text-[8.5pt]">
                    <div class="font-bold mb-1">CONCLUSIÓN:</div>
                    <p class="italic font-semibold text-slate-900 mb-2">${conclusionTexto}</p>
                    <div class="font-bold text-[8pt] mb-1">CONSIDERACIONES:</div>
                    <ul class="space-y-0.5 text-[7.8pt] text-slate-700">
                        ${consideracionesHtml}
                    </ul>
                </div>

                <!-- Bloque de Firmas Electrónicas -->
                <div class="mt-8 pt-4 avoid-break">
                    <div class="text-[8pt] text-slate-600 mb-2">Protocolo firmado electrónicamente por:</div>
                    <div class="grid grid-cols-2 sm:grid-cols-4 gap-2">
                        ${firmasHtml}
                    </div>
                </div>
            </div>
        </div>
    `;

            document.getElementById("a4-document-content").innerHTML = docHtml;
            document.getElementById("print-preview-overlay").classList.remove("hidden");
        }

        function closePrintPreview() {
            document.getElementById("print-preview-overlay").classList.add("hidden");
        }
    </script>
</body>
</html>
"""

if __name__ == "__main__":
    init_db()
    print("=" * 65)
    print("  LIMS BROMATOLOGÍA - LABORATORIO OBREGOSO")
    print("  Servidor iniciado en: http://127.0.0.1:5000")
    print("  Base de datos SQLite: ", DB_PATH)
    print("=" * 65)
    app.run(
        host="127.0.0.1",
        port=5000,
        debug=os.environ.get("APP_ENV", "development").lower() != "production",
    )
