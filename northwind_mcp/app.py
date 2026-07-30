import os
import json
import httpx
import decimal
import datetime
import base64
from flask import Flask, request, jsonify, render_template_string, session, redirect, url_for
from termcolor import colored

app = Flask(__name__)
app.secret_key = "clave_secreta_super_segura_para_el_mcp"

# Lista de modelos en orden de prioridad para la selección automática
AUTOMATIC_MODELS = [
    "gemini-3.1-flash-lite",
    "gemini-2.0-flash-lite",
    "gemini-2.0-flash",
    "gemini-3.5-flash"
]

# Serializador personalizado para tipos de datos de bases de datos
def db_serialize(val):
    if isinstance(val, (datetime.date, datetime.datetime)):
        return val.isoformat()
    if isinstance(val, decimal.Decimal):
        return float(val)
    if isinstance(val, (bytes, bytearray)):
        # Gestión especial para el OLE header de Microsoft Access en Northwind (78 bytes iniciales)
        try:
            if len(val) > 78 and val[0:2] == b'\x15\x1c':
                img_data = val[78:]
            else:
                img_data = val
            encoded = base64.b64encode(img_data).decode('utf-8')
            return f"data:image/bmp;base64,{encoded}"
        except Exception:
            return f"<Binary: {len(val)} bytes>"
    return val

# Función para probar la conexión y obtener el esquema según el motor
def get_db_connection(config):
    db_type = config.get("db_type")
    if db_type == "mssql":
        import pymssql
        return pymssql.connect(
            server=config.get("host"),
            port=int(config.get("port", 1433)),
            user=config.get("user"),
            password=config.get("password"),
            database=config.get("database"),
            autocommit=True
        )
    elif db_type == "postgresql":
        import psycopg2
        return psycopg2.connect(
            host=config.get("host"),
            port=int(config.get("port", 5432)),
            user=config.get("user"),
            password=config.get("password"),
            database=config.get("database")
        )
    else:
        raise ValueError(f"Motor de base de datos '{db_type}' no soportado.")

def fetch_schema(config):
    conn = get_db_connection(config)
    cursor = conn.cursor()
    db_type = config.get("db_type")
    
    if db_type == "mssql":
        query = """
        SELECT t.TABLE_NAME, c.COLUMN_NAME, c.DATA_TYPE
        FROM INFORMATION_SCHEMA.TABLES t
        INNER JOIN INFORMATION_SCHEMA.COLUMNS c ON t.TABLE_NAME = c.TABLE_NAME
        WHERE t.TABLE_TYPE = 'BASE TABLE'
        ORDER BY t.TABLE_NAME, c.ORDINAL_POSITION
        """
    elif db_type == "postgresql":
        query = """
        SELECT table_name, column_name, data_type
        FROM information_schema.columns
        WHERE table_schema = 'public'
        ORDER BY table_name, ordinal_position
        """
        
    cursor.execute(query)
    rows = cursor.fetchall()
    conn.close()
    
    schema = {}
    for table, col, dtype in rows:
        if table not in schema:
            schema[table] = []
        schema[table].append({"name": col, "type": dtype})
        
    return schema

# Ejecutar consulta SQL
def execute_sql(config, sql):
    conn = get_db_connection(config)
    db_type = config.get("db_type")
    results = []
    
    try:
        if db_type == "mssql":
            cursor = conn.cursor(as_dict=True)
            cursor.execute(sql)
            results = cursor.fetchall()
        elif db_type == "postgresql":
            import psycopg2.extras
            cursor = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
            cursor.execute(sql)
            results = cursor.fetchall()
            conn.commit()
            
        conn.close()
        
        # Serializar los tipos especiales
        serialized_results = []
        for row in results:
            serialized_row = {k: db_serialize(v) for k, v in row.items()}
            serialized_results.append(serialized_row)
            
        return {"status": "success", "data": serialized_results}
    except Exception as e:
        if conn:
            conn.close()
        return {"status": "error", "message": str(e)}

# --- Rutas de Flask ---

@app.route("/", methods=["GET", "POST"])
def index():
    # Cargar valores previos de la sesión para rellenar el formulario si se está modificando
    saved_data = session.get("db_config", {})
    saved_api = session.get("api_key", "")
    saved_model = session.get("gemini_model", "auto")
    
    form_initial = {
        "db_type": saved_data.get("db_type", "mssql"),
        "host": saved_data.get("host", "127.0.0.1"),
        "port": saved_data.get("port", "1433"),
        "user": saved_data.get("user", ""),
        "password": saved_data.get("password", ""),
        "database": saved_data.get("database", ""),
        "api_key": saved_api,
        "gemini_model": saved_model
    }

    if request.method == "POST":
        config = {
            "db_type": request.form.get("db_type"),
            "host": request.form.get("host"),
            "port": request.form.get("port"),
            "user": request.form.get("user"),
            "password": request.form.get("password"),
            "database": request.form.get("database")
        }
        
        api_key = request.form.get("api_key")
        gemini_model = request.form.get("gemini_model")
        
        # Combinar para volver a pintar si hay error
        form_submitted = {**config, "api_key": api_key, "gemini_model": gemini_model}
        
        if not api_key:
            return render_template_string(HTML_LOGIN, error="La clave API de Google Gemini es obligatoria.", form_data=form_submitted)
            
        try:
            # Obtener el esquema estructurado
            schema_dict = fetch_schema(config)
            
            # Formatear el esquema en texto plano para el prompt de Gemini
            schema_text = ""
            for table, cols in schema_dict.items():
                col_strs = [f"{c['name']} ({c['type']})" for c in cols]
                schema_text += f"Tabla: {table}\nColumnas: {', '.join(col_strs)}\n\n"
                
            session["db_config"] = config
            session["db_schema"] = schema_text
            session["db_schema_dict"] = schema_dict  # Guardar esquema estructurado para el panel izquierdo
            session["api_key"] = api_key
            session["gemini_model"] = gemini_model
            session["chat_history"] = []
            return redirect(url_for("chat"))
        except Exception as e:
            return render_template_string(HTML_LOGIN, error=str(e), form_data=form_submitted)
            
    return render_template_string(HTML_LOGIN, error=None, form_data=form_initial)

@app.route("/chat")
def chat():
    if "db_config" not in session:
        return redirect(url_for("index"))
    
    display_model = "Auto Fallback (Inteligente)" if session["gemini_model"] == "auto" else session["gemini_model"]
    return render_template_string(
        HTML_CHAT, 
        db_name=session["db_config"]["database"], 
        db_type=session["db_config"]["db_type"], 
        model_name=display_model,
        schema_dict=session.get("db_schema_dict", {})
    )

@app.route("/disconnect")
def disconnect():
    session.clear()
    return redirect(url_for("index"))

@app.route("/execute_raw_sql", methods=["POST"])
def execute_raw_sql_route():
    if "db_config" not in session:
        return jsonify({"error": "No conectado"}), 401
    sql = request.json.get("sql")
    if not sql:
        return jsonify({"error": "Consulta vacía"}), 400
    res = execute_sql(session["db_config"], sql)
    return jsonify(res)

@app.route("/fetch_databases", methods=["POST"])
def fetch_databases():
    data = request.json
    db_type = data.get("db_type")
    host = data.get("host")
    port = data.get("port")
    user = data.get("user")
    password = data.get("password")
    
    # Conectar a una base de datos por defecto para listar las demás
    default_db = "master" if db_type == "mssql" else "postgres"
    
    temp_config = {
        "db_type": db_type,
        "host": host,
        "port": port,
        "user": user,
        "password": password,
        "database": default_db
    }
    
    try:
        conn = get_db_connection(temp_config)
        cursor = conn.cursor()
        
        if db_type == "mssql":
            query = "SELECT name FROM sys.databases WHERE name NOT IN ('master', 'tempdb', 'model', 'msdb', 'Resource') ORDER BY name"
        elif db_type == "postgresql":
            query = "SELECT datname FROM pg_database WHERE datistemplate = false AND datname NOT IN ('postgres') ORDER BY datname"
            
        cursor.execute(query)
        rows = cursor.fetchall()
        conn.close()
        
        db_names = []
        for row in rows:
            if isinstance(row, dict):
                val = list(row.values())[0]
            elif isinstance(row, (list, tuple)):
                val = row[0]
            else:
                val = row
            db_names.append(val)
            
        db_names.append(default_db)
        # Quitar duplicados preservando orden
        db_names = list(dict.fromkeys(db_names))
        
        return jsonify({"status": "success", "databases": db_names})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})

@app.route("/send_message", methods=["POST"])
async def send_message():
    if "db_config" not in session or "api_key" not in session:
        return jsonify({"error": "No conectado o falta API Key"}), 401
        
    user_message = request.json.get("message")
    if not user_message:
        return jsonify({"error": "Mensaje vacío"}), 400
        
    db_config = session["db_config"]
    schema_text = session["db_schema"]
    api_key = session["api_key"]
    model_selection = session.get("gemini_model", "auto")
    chat_history = session.get("chat_history", [])
    
    # 1. Agregar pregunta del usuario al historial
    chat_history.append({
        "role": "user",
        "parts": [{"text": user_message}]
    })
    
    # Configurar herramientas del sistema
    tools_config = [
        {
            "functionDeclarations": [
                {
                    "name": "query_db",
                    "description": "Ejecuta una consulta SQL SELECT en la base de datos y devuelve el resultado en JSON.",
                    "parameters": {
                        "type": "OBJECT",
                        "properties": {
                            "sql": {
                                "type": "STRING",
                                "description": "La consulta SQL SELECT válida a ejecutar."
                            }
                        },
                        "required": ["sql"]
                    }
                }
            ]
        }
    ]
    
    # Instrucciones del sistema para el dialecto correcto
    engine_name = "Microsoft SQL Server (T-SQL)" if db_config["db_type"] == "mssql" else "PostgreSQL"
    dialect_rules = (
        "La base de datos es SQL Server. Usa sintaxis T-SQL válida. Por ejemplo, usa 'SELECT TOP N' en lugar de 'LIMIT N', y pon corchetes a tablas con espacios como [Order Details]."
        if db_config["db_type"] == "mssql" else
        "La base de datos es PostgreSQL. Usa sintaxis estándar válida. Por ejemplo, usa 'LIMIT N' para limitar resultados y pon comillas dobles si las tablas tienen mayúsculas o caracteres especiales."
    )
    
    system_instruction = {
        "parts": [
            {
                "text": (
                    f"Eres un analista de datos experto. Tienes acceso a una base de datos ejecutándose sobre {engine_name}.\n"
                    f"Aquí tienes el esquema de la base de datos:\n{schema_text}\n\n"
                    f"Instrucciones:\n"
                    f"1. IMPORTANTE: {dialect_rules}\n"
                    f"2. Explica brevemente tu pensamiento en español (qué tablas necesitas y por qué) y genera la consulta SQL SELECT adecuada.\n"
                    f"3. Utiliza la herramienta query_db cuando sea necesario para obtener datos reales y responder al usuario.\n"
                    f"4. Sintetiza una respuesta final clara en español basándote en los datos obtenidos."
                )
            }
        ]
    }
    
    payload = {
        "contents": chat_history,
        "tools": tools_config,
        "systemInstruction": system_instruction
    }
    
    # Definir la lista de modelos a intentar
    models_to_try = AUTOMATIC_MODELS if model_selection == "auto" else [model_selection]
    
    response_data = None
    successful_model = None
    error_logs = []
    
    async with httpx.AsyncClient() as client:
        # Intentar conectar con la lista de modelos en cascada
        for current_model in models_to_try:
            gemini_url = f"https://generativelanguage.googleapis.com/v1beta/models/{current_model}:generateContent?key={api_key}"
            try:
                print(f"[Fallback System] Intentando consulta con el modelo: {current_model}")
                response = await client.post(gemini_url, json=payload, timeout=45.0)
                
                if response.status_code == 200:
                    response_data = response.json()
                    successful_model = current_model
                    print(colored(f"[Fallback System] Éxito con el modelo: {current_model}", "green"))
                    break
                else:
                    err_msg = f"{current_model} falló con status {response.status_code}: {response.text[:150]}"
                    print(colored(f"[Fallback System] {err_msg}", "yellow"))
                    error_logs.append(err_msg)
            except Exception as e:
                err_msg = f"{current_model} arrojó excepción: {str(e)}"
                print(colored(f"[Fallback System] {err_msg}", "red"))
                error_logs.append(err_msg)
                
        if not response_data:
            chat_history.pop()
            return jsonify({
                "error": "Todos los modelos gratuitos fallaron o excedieron su cuota.",
                "detalles": error_logs
            }), 500
            
        candidate = response_data.get("candidates", [{}])[0]
        content = candidate.get("content", {})
        parts = content.get("parts", [])
        
        reasoning = ""
        function_call = None
        for part in parts:
            if "text" in part:
                reasoning += part["text"]
            if "functionCall" in part:
                function_call = part["functionCall"]
        
        query_used = None
        raw_db_results = None
        response_text = ""
        
        # Si el modelo decidió llamar a la consulta SQL
        if function_call:
            tool_name = function_call["name"]
            tool_args = function_call["args"]
            query_used = tool_args.get("sql")
            
            # Ejecutar consulta SQL
            db_res = execute_sql(db_config, query_used)
            if db_res["status"] == "success":
                raw_db_results = db_res["data"]
                # Crear una copia limpia sin imágenes Base64 pesadas para no inflar la cookie de sesión
                clean_db_results = []
                for row in raw_db_results:
                    clean_row = {}
                    for k, v in row.items():
                        if isinstance(v, str) and v.startswith("data:image/"):
                            clean_row[k] = "<Binary Image Data>"
                        else:
                            clean_row[k] = v
                    clean_db_results.append(clean_row)
                db_result_str = json.dumps(clean_db_results, indent=2)
            else:
                db_result_str = f"Error al ejecutar SQL: {db_res['message']}"
            
            # Guardar en historial
            chat_history.append(content)
            chat_history.append({
                "role": "function",
                "parts": [
                    {
                        "functionResponse": {
                            "name": tool_name,
                            "response": {
                                "result": db_result_str
                            }
                        }
                    }
                ]
            })
            
            # Volver a llamar a Gemini (usando el modelo que funcionó en el paso anterior)
            final_payload = {
                "contents": chat_history,
                "tools": tools_config,
                "systemInstruction": system_instruction
            }
            
            final_gemini_url = f"https://generativelanguage.googleapis.com/v1beta/models/{successful_model}:generateContent?key={api_key}"
            
            try:
                final_response = await client.post(final_gemini_url, json=final_payload, timeout=45.0)
                if final_response.status_code != 200:
                    return jsonify({"error": f"Error en la síntesis final ({successful_model}): {final_response.text}"}), 500
                    
                final_data = final_response.json()
                final_content = final_data.get("candidates", [{}])[0].get("content", {})
                response_text = final_content.get("parts", [{}])[0].get("text", "")
                chat_history.append(final_content)
            except Exception as e:
                return jsonify({"error": f"Error en la síntesis final: {str(e)}"}), 500
        else:
            response_text = reasoning
            chat_history.append(content)
            
    session["chat_history"] = chat_history
    return jsonify({
        "response": response_text,
        "query_used": query_used,
        "query_data": raw_db_results, # Datos puros en JSON de la BD para la tabla del chat
        "reasoning": reasoning if function_call else None,
        "model_used": successful_model
    })

# --- HTML LOGIN con Glassmorphism ---

HTML_LOGIN = """
<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>MCP Database Gateway</title>
    <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@300;400;500;600;700&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg-color: #0a0a12;
            --card-bg: rgba(18, 14, 30, 0.5);
            --border-color: rgba(139, 92, 246, 0.15);
            --primary: #8b5cf6;
            --primary-hover: #a78bfa;
            --accent: #10b981;
            --accent-hover: #34d399;
            --text-main: #e8e4f0;
            --text-muted: #9a8fae;
        }
        body {
            font-family: 'Plus Jakarta Sans', sans-serif;
            background-color: var(--bg-color);
            color: var(--text-main);
            display: flex;
            justify-content: center;
            align-items: center;
            min-height: 100vh;
            margin: 0;
            background-image: 
                radial-gradient(at 0% 0%, rgba(139, 92, 246, 0.2) 0px, transparent 50%),
                radial-gradient(at 100% 100%, rgba(16, 185, 129, 0.1) 0px, transparent 50%);
            overflow-x: hidden;
        }
        .container {
            width: 100%;
            max-width: 500px;
            padding: 20px;
            animation: slideUp 0.6s cubic-bezier(0.16, 1, 0.3, 1);
        }
        @keyframes slideUp {
            from { opacity: 0; transform: translateY(30px); }
            to { opacity: 1; transform: translateY(0); }
        }
        .card {
            background: var(--card-bg);
            border: 1px solid var(--border-color);
            backdrop-filter: blur(24px);
            border-radius: 28px;
            padding: 40px;
            box-shadow: 0 25px 50px -12px rgba(139, 92, 246, 0.15);
            transition: all 0.3s;
        }
        .card:hover {
            border-color: rgba(139, 92, 246, 0.35);
            box-shadow: 0 25px 60px -10px rgba(139, 92, 246, 0.25);
        }
        h2 {
            margin-top: 0;
            font-weight: 800;
            font-size: 30px;
            letter-spacing: -0.8px;
            background: linear-gradient(135deg, #a78bfa, #10b981);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            text-align: center;
            margin-bottom: 8px;
        }
        .subtitle {
            text-align: center;
            color: var(--text-muted);
            font-size: 14px;
            margin-bottom: 30px;
        }
        .section-title {
            font-size: 11px;
            font-weight: 700;
            color: var(--accent);
            text-transform: uppercase;
            letter-spacing: 1.5px;
            margin: 25px 0 15px 0;
            border-bottom: 1px solid rgba(16, 185, 129, 0.2);
            padding-bottom: 6px;
        }
        .form-group {
            margin-bottom: 20px;
        }
        label {
            display: block;
            margin-bottom: 8px;
            font-size: 11px;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.8px;
            color: var(--text-muted);
        }
        input, select {
            width: 100%;
            padding: 14px 18px;
            background: rgba(255, 255, 255, 0.02);
            border: 1px solid var(--border-color);
            border-radius: 14px;
            color: var(--text-main);
            font-size: 15px;
            box-sizing: border-box;
            transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
        }
        input:focus, select:focus {
            outline: none;
            border-color: var(--primary-hover);
            box-shadow: 0 0 0 4px rgba(139, 92, 246, 0.18);
            background: rgba(255, 255, 255, 0.05);
            transform: scale(1.01);
        }
        .row {
            display: flex;
            gap: 16px;
        }
        .row .form-group {
            flex: 1;
        }
        .btn {
            width: 100%;
            padding: 16px;
            background: linear-gradient(135deg, var(--primary), var(--accent));
            border: none;
            border-radius: 14px;
            color: white;
            font-size: 16px;
            font-weight: 700;
            cursor: pointer;
            transition: all 0.3s ease;
            box-shadow: 0 8px 24px rgba(139, 92, 246, 0.25);
            margin-top: 20px;
        }
        .btn:hover {
            transform: translateY(-2px);
            box-shadow: 0 12px 30px rgba(139, 92, 246, 0.4);
            background: linear-gradient(135deg, var(--primary-hover), var(--accent-hover));
        }
        .btn:active {
            transform: translateY(1px);
        }
        .error {
            background: rgba(239, 68, 68, 0.1);
            border: 1px solid rgba(239, 68, 68, 0.2);
            color: #f87171;
            padding: 12px 16px;
            border-radius: 12px;
            font-size: 14px;
            margin-bottom: 24px;
            line-height: 1.4;
            animation: shake 0.5s ease-in-out;
        }
        @keyframes shake {
            0%, 100% { transform: translateX(0); }
            25% { transform: translateX(-6px); }
            75% { transform: translateX(6px); }
        }
    </style>
    <script>
        // Cambiar puerto automáticamente al cambiar el motor de BD
        function handleDbTypeChange() {
            const dbTypeSelect = document.getElementById("db_type");
            const portInput = document.getElementById("port");
            
            if (dbTypeSelect.value === "mssql") {
                portInput.value = "1433";
            } else if (dbTypeSelect.value === "postgresql") {
                portInput.value = "5432";
            }
        }

        // Carga dinámicamente las bases de datos desde las credenciales actuales
        async function loadDatabases() {
            const btn = document.getElementById("btn-load-dbs");
            const dbSelect = document.getElementById("database");
            const dbType = document.getElementById("db_type").value;
            const host = document.getElementsByName("host")[0].value;
            const port = document.getElementById("port").value;
            const user = document.getElementsByName("user")[0].value;
            const password = document.getElementsByName("password")[0].value;
            
            if (!host || !port || !user || !password) {
                alert("Por favor rellena primero el Host, Puerto, Usuario y Contraseña.");
                return;
            }
            
            const originalText = btn.innerText;
            btn.innerText = "⏳ ...";
            btn.disabled = true;
            
            try {
                const res = await fetch("/fetch_databases", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        db_type: dbType,
                        host: host,
                        port: port,
                        user: user,
                        password: password
                    })
                });
                
                const data = await res.json();
                
                if (data.status === "success") {
                    dbSelect.innerHTML = "";
                    data.databases.forEach(db => {
                        const opt = document.createElement("option");
                        opt.value = db;
                        opt.innerText = db;
                        // Pre-seleccionar 'Northwind' si se encuentra disponible
                        if (db.toLowerCase() === "northwind") {
                            opt.selected = true;
                        }
                        dbSelect.appendChild(opt);
                    });
                } else {
                    alert("Error al conectar: " + data.message);
                }
            } catch (err) {
                alert("Error de comunicación con el servidor al buscar las bases de datos.");
            } finally {
                btn.innerText = originalText;
                btn.disabled = false;
            }
        }
    </script>
</head>
<body>
    <div class="container">
        <div class="card">
            <h2>MCP Database Gateway</h2>
            <div class="subtitle">Conectividad inteligente impulsada por Gemini</div>
            
            {% if error %}
            <div class="error">
                <strong>Fallo de Configuración:</strong><br>{{ error }}
            </div>
            {% endif %}
            
            <form method="POST">
                <div class="section-title">1. Configuración de IA (Google Gemini)</div>
                <div class="form-group">
                    <label>API Key de Gemini</label>
                    <input type="password" name="api_key" placeholder="Pega tu API Key de Google AI Studio" value="{{ form_data.api_key or '' }}" required>
                </div>
                <div class="form-group">
                    <label>Modelo (Plan Gratuito / Experimental)</label>
                    <select name="gemini_model">
                        <option value="auto" {% if form_data.gemini_model == 'auto' or not form_data.gemini_model %}selected{% endif %}>🚀 Selección Automática (Resiliente)</option>
                        <option value="gemini-3.1-flash-lite" {% if form_data.gemini_model == 'gemini-3.1-flash-lite' %}selected{% endif %}>Gemini 3.1 Flash Lite (Más cuota)</option>
                        <option value="gemini-2.0-flash-lite" {% if form_data.gemini_model == 'gemini-2.0-flash-lite' %}selected{% endif %}>Gemini 2.0 Flash Lite</option>
                        <option value="gemini-2.0-flash" {% if form_data.gemini_model == 'gemini-2.0-flash' %}selected{% endif %}>Gemini 2.0 Flash</option>
                        <option value="gemini-3.5-flash" {% if form_data.gemini_model == 'gemini-3.5-flash' %}selected{% endif %}>Gemini 3.5 Flash</option>
                    </select>
                </div>

                <div class="section-title">2. Conexión a la Base de Datos</div>
                <div class="form-group">
                    <label>Motor de Base de Datos</label>
                    <select name="db_type" id="db_type" onchange="handleDbTypeChange()">
                        <option value="mssql" {% if form_data.db_type == 'mssql' %}selected{% endif %}>Microsoft SQL Server (T-SQL)</option>
                        <option value="postgresql" {% if form_data.db_type == 'postgresql' %}selected{% endif %}>PostgreSQL</option>
                    </select>
                </div>
                <div class="row">
                    <div class="form-group">
                        <label>Servidor / Host</label>
                        <input type="text" name="host" placeholder="127.0.0.1" value="{{ form_data.host or '127.0.0.1' }}" required>
                    </div>
                    <div class="form-group">
                        <label>Puerto</label>
                        <input type="number" name="port" id="port" placeholder="1433" value="{{ form_data.port or '1433' }}" required>
                    </div>
                </div>
                <div class="row">
                    <div class="form-group">
                        <label>Usuario</label>
                        <input type="text" name="user" placeholder="sa / postgres" value="{{ form_data.user or '' }}" required>
                    </div>
                    <div class="form-group">
                        <label>Contraseña</label>
                        <input type="password" name="password" placeholder="••••••••" value="{{ form_data.password or '' }}" required>
                    </div>
                </div>
                <div class="form-group">
                    <label>Nombre de la Base de Datos</label>
                    <div style="display: flex; gap: 10px; align-items: center;">
                        <select name="database" id="database" style="flex: 1;" required>
                            {% if form_data.database %}
                                <option value="{{ form_data.database }}" selected>{{ form_data.database }}</option>
                            {% else %}
                                <option value="" disabled selected>Introduce credenciales y pulsa Cargar ➔</option>
                            {% endif %}
                        </select>
                        <button type="button" onclick="loadDatabases()" id="btn-load-dbs" style="padding: 14px 18px; background: rgba(139, 92, 246, 0.15); border: 1px solid var(--border-color); border-radius: 14px; color: var(--accent); cursor: pointer; font-size: 13px; font-weight: bold; transition: all 0.2s;">
                            🔄 Cargar
                        </button>
                    </div>
                </div>
                <button type="submit" class="btn">Conectar y Analizar</button>
            </form>
        </div>
    </div>
</body>
</html>
"""

HTML_CHAT = """
<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>MCP Chat - {{ db_name }}</title>
    <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@300;400;500;600;700&display=swap" rel="stylesheet">
    <!-- Cargar marked.js y Chart.js para visualizaciones y MD -->
    <script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        :root {
            --bg-color: #0a0a12;
            --sidebar-bg: rgba(14, 10, 26, 0.75);
            --chat-bg: #0a0a12;
            --card-bg: rgba(18, 14, 30, 0.5);
            --border-color: rgba(139, 92, 246, 0.15);
            --primary: #8b5cf6;
            --primary-hover: #a78bfa;
            --accent: #10b981;
            --accent-hover: #34d399;
            --text-main: #e8e4f0;
            --text-muted: #9a8fae;
        }
        body {
            font-family: 'Plus Jakarta Sans', sans-serif;
            background-color: var(--bg-color);
            color: var(--text-main);
            margin: 0;
            display: flex;
            height: 100vh;
            overflow: hidden;
            position: relative;
        }
        
        /* Stars Background Animado por CSS hardware accelerated */
        body::before {
            content: '';
            position: fixed;
            top: 0; left: 0; width: 100vw; height: 100vh;
            background-image: 
                radial-gradient(1px 1px at 20px 30px, #fff, rgba(0,0,0,0)),
                radial-gradient(1px 1px at 75px 120px, #fff, rgba(0,0,0,0)),
                radial-gradient(1.5px 1.5px at 150px 80px, #a78bfa, rgba(0,0,0,0)),
                radial-gradient(1px 1px at 280px 240px, #fff, rgba(0,0,0,0)),
                radial-gradient(2px 2px at 310px 45px, #10b981, rgba(0,0,0,0));
            background-repeat: repeat;
            background-size: 400px 400px;
            opacity: 0.12;
            animation: moveStars 160s linear infinite;
            z-index: -1;
            pointer-events: none;
        }
        @keyframes moveStars {
            from { background-position: 0 0; }
            to { background-position: 1000px 1000px; }
        }
        
        /* Contenedor Principal Izquierda (Sidebar) y Derecha (Chat) */
        .app-layout {
            display: flex;
            width: 100%;
            height: 100vh;
            z-index: 2;
            position: relative;
            overflow: hidden;
        }
        
        /* 1. Sidebar Retráctil con Animación GPU-accelerated */
        .sidebar {
            width: 320px;
            min-width: 320px;
            background: var(--sidebar-bg);
            border-right: 1px solid var(--border-color);
            backdrop-filter: blur(24px);
            display: flex;
            flex-direction: column;
            box-sizing: border-box;
            flex-shrink: 0;
            box-shadow: 5px 0 25px rgba(0, 0, 0, 0.4);
            z-index: 30;
            height: 100%;
            transform: translateX(0);
            transition: transform 0.4s cubic-bezier(0.22, 1, 0.36, 1);
            will-change: transform;
            position: relative;
        }
        .sidebar.collapsed {
            transform: translateX(-100%);
            box-shadow: none;
        }
        /* El área de chat se ajusta dinámicamente al sidebar con transición suave */
        .main-chat-area {
            transition: margin-left 0.4s cubic-bezier(0.22, 1, 0.36, 1);
        }
        .sidebar.collapsed + .main-chat-area {
            margin-left: -320px;
        }
        
        /* Botón Toggle con Icono de Base de Datos */
        .sidebar-toggle-btn {
            width: 40px;
            height: 40px;
            position: relative;
            cursor: pointer;
            border-radius: 12px;
            background: rgba(139, 92, 246, 0.1);
            border: 1px solid rgba(139, 92, 246, 0.3);
            display: flex;
            align-items: center;
            justify-content: center;
            transition: all 0.35s cubic-bezier(0.4, 0, 0.2, 1);
            flex-shrink: 0;
        }
        .sidebar-toggle-btn:hover {
            background: rgba(139, 92, 246, 0.25);
            transform: translateY(-1px);
            box-shadow: 0 4px 16px rgba(139, 92, 246, 0.3);
        }
        .sidebar-toggle-btn .db-toggle-icon {
            width: 20px;
            height: 20px;
            fill: var(--accent);
            transition: all 0.4s cubic-bezier(0.4, 0, 0.2, 1);
            filter: drop-shadow(0 0 4px rgba(16, 185, 129, 0.4));
        }
        /* Cuando el sidebar está abierto: el icono brilla y pulsa suavemente */
        .sidebar-toggle-btn.is-open .db-toggle-icon {
            fill: var(--accent-hover);
            filter: drop-shadow(0 0 8px rgba(52, 211, 153, 0.6));
            animation: dbPulse 2s ease-in-out infinite;
        }
        .sidebar-toggle-btn.is-open {
            background: rgba(16, 185, 129, 0.12);
            border-color: rgba(16, 185, 129, 0.35);
        }
        @keyframes dbPulse {
            0%, 100% { transform: scale(1); }
            50% { transform: scale(1.1); }
        }
        /* Cuando el sidebar está cerrado: el icono se atenúa */
        .sidebar-toggle-btn:not(.is-open) .db-toggle-icon {
            fill: var(--text-muted);
            filter: none;
        }
        .sidebar-header {
            padding: 20px 18px;
            border-bottom: 1px solid var(--border-color);
        }
        .sidebar-header h3 {
            margin: 0;
            font-size: 13px;
            font-weight: 800;
            text-transform: uppercase;
            letter-spacing: 1.5px;
            color: var(--accent);
            display: flex;
            align-items: center;
            gap: 8px;
            text-shadow: 0 0 10px rgba(16, 185, 129, 0.3);
        }
        
        .sidebar-scroll-panel {
            flex: 1;
            overflow-y: auto;
            display: flex;
            flex-direction: column;
        }
        
        /* Scrollbars Premium Ultradelgados */
        ::-webkit-scrollbar {
            width: 6px;
            height: 6px;
        }
        ::-webkit-scrollbar-track {
            background: rgba(0,0,0,0.1);
        }
        ::-webkit-scrollbar-thumb {
            background: rgba(139, 92, 246, 0.2);
            border-radius: 4px;
        }
        ::-webkit-scrollbar-thumb:hover {
            background: rgba(167, 139, 250, 0.55);
        }
        
        .db-tree-container {
            padding: 16px 14px;
        }
        .db-node {
            font-size: 13px;
            font-weight: 700;
            color: var(--text-main);
            margin-bottom: 16px;
            display: flex;
            align-items: center;
            gap: 8px;
        }
        .db-node svg {
            width: 16px;
            height: 16px;
            fill: var(--accent);
        }
        .table-node {
            margin-left: 10px;
            margin-bottom: 10px;
        }
        .table-header-node {
            font-size: 13px;
            color: var(--text-muted);
            cursor: pointer;
            padding: 6px 10px;
            border-radius: 8px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1);
            user-select: none;
        }
        .table-header-node:hover {
            background: rgba(139, 92, 246, 0.08);
            color: var(--primary-hover);
        }
        .table-name-wrapper {
            display: flex;
            align-items: center;
            gap: 8px;
        }
        .table-header-node svg.table-icon {
            width: 14px;
            height: 14px;
            fill: var(--primary);
        }
        .table-header-node svg.caret-icon {
            width: 10px;
            height: 10px;
            fill: var(--text-muted);
            transition: transform 0.3s cubic-bezier(0.4, 0, 0.2, 1);
        }
        
        .preview-btn {
            opacity: 0;
            transition: all 0.2s ease;
            color: var(--accent);
            font-size: 10px;
            font-weight: bold;
            padding: 2px 6px;
            border-radius: 6px;
            background: rgba(16, 185, 129, 0.1);
            border: 1px solid rgba(16, 185, 129, 0.25);
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }
        .table-header-node:hover .preview-btn {
            opacity: 1;
        }
        .preview-btn:hover {
            transform: scale(1.1);
            background: rgba(16, 185, 129, 0.2);
            box-shadow: 0 0 8px rgba(16, 185, 129, 0.4);
        }
        
        /* Lista de Columnas con Animación de Altura */
        .column-list {
            margin-left: 26px;
            max-height: 0;
            overflow: hidden;
            transition: max-height 0.4s cubic-bezier(0.16, 1, 0.3, 1), opacity 0.3s ease;
            opacity: 0;
            padding-left: 10px;
            border-left: 1px dashed rgba(139, 92, 246, 0.2);
            margin-top: 4px;
            margin-bottom: 4px;
        }
        .column-list.open {
            max-height: 500px;
            opacity: 1;
        }
        .column-node {
            font-size: 11.5px;
            color: #8fa0b5;
            padding: 5px 8px;
            font-family: monospace;
            display: flex;
            justify-content: space-between;
            align-items: center;
            cursor: pointer;
            border-radius: 6px;
            transition: all 0.2s ease;
            user-select: none;
            margin-bottom: 2px;
        }
        .column-node:hover {
            background: rgba(139, 92, 246, 0.08);
            color: var(--primary-hover);
            padding-left: 12px;
        }
        .column-info {
            display: flex;
            align-items: center;
            gap: 6px;
        }
        .column-node svg {
            width: 10px;
            height: 10px;
            fill: currentColor;
        }
        
        .attr-preview-btn {
            opacity: 0;
            font-size: 9px;
            color: var(--primary);
            background: rgba(139, 92, 246, 0.1);
            border: 1px solid rgba(139, 92, 246, 0.2);
            padding: 1px 4px;
            border-radius: 4px;
            transition: opacity 0.2s, background 0.2s;
        }
        .column-node:hover .attr-preview-btn {
            opacity: 1;
        }
        .attr-preview-btn:hover {
            background: rgba(139, 92, 246, 0.25);
            color: var(--primary-hover);
        }
        
        /* 2. Sección de Chat */
        .main-chat-area {
            flex: 1;
            display: flex;
            flex-direction: column;
            height: 100vh;
            background: transparent;
            box-sizing: border-box;
            position: relative;
        }
        
        header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 16px 32px;
            background: rgba(10, 10, 18, 0.5);
            backdrop-filter: blur(16px);
            border-bottom: 1px solid var(--border-color);
            box-shadow: 0 4px 30px rgba(0, 0, 0, 0.2);
            z-index: 10;
        }
        header h1 {
            margin: 0;
            font-size: 20px;
            font-weight: 800;
            letter-spacing: -0.6px;
            background: linear-gradient(135deg, #a78bfa, #34d399);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }
        .badges-wrapper {
            display: flex;
            gap: 12px;
            align-items: center;
        }
        .db-badge {
            background: rgba(16, 185, 129, 0.1);
            border: 1px solid rgba(16, 185, 129, 0.25);
            color: var(--accent);
            padding: 6px 12px;
            border-radius: 20px;
            font-size: 12px;
            font-weight: 600;
            display: flex;
            align-items: center;
            gap: 6px;
        }
        .model-badge {
            background: rgba(139, 92, 246, 0.1);
            border: 1px solid rgba(139, 92, 246, 0.25);
            color: var(--primary-hover);
            padding: 6px 12px;
            border-radius: 20px;
            font-size: 12px;
            font-weight: 600;
            display: flex;
            align-items: center;
            gap: 6px;
        }
        .actions-wrapper {
            display: flex;
            gap: 8px;
            align-items: center;
        }
        .header-btn {
            text-decoration: none;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            width: 38px;
            height: 38px;
            border-radius: 12px;
            transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
            cursor: pointer;
            box-sizing: border-box;
        }
        .btn-modify {
            background: rgba(139, 92, 246, 0.1);
            border: 1px solid rgba(139, 92, 246, 0.3);
            color: var(--primary-hover);
        }
        .btn-modify:hover {
            background: rgba(139, 92, 246, 0.25);
            transform: translateY(-1px);
        }
        .btn-disconnect {
            background: transparent;
            color: #ff4d4d;
            border: 1px solid transparent;
        }
        .btn-disconnect:hover {
            background: rgba(255, 77, 77, 0.1);
            border-color: rgba(255, 77, 77, 0.2);
        }
        
        .chat-container {
            flex: 1;
            overflow-y: auto;
            padding: 32px 32px 100px 32px; /* Más padding abajo para no tapar el chat con el floating bar */
            display: flex;
            flex-direction: column;
            gap: 24px;
            max-width: 900px;
            width: 100%;
            margin: 0 auto;
            box-sizing: border-box;
            scroll-behavior: smooth;
        }
        .message {
            display: flex;
            flex-direction: column;
            max-width: 85%;
            animation: popIn 0.35s cubic-bezier(0.34, 1.56, 0.64, 1);
        }
        @keyframes popIn {
            from { opacity: 0; transform: scale(0.96) translateY(10px); }
            to { opacity: 1; transform: scale(1) translateY(0); }
        }
        .message.user {
            align-self: flex-end;
        }
        .message.assistant {
            align-self: flex-start;
        }
        .bubble {
            padding: 16px 20px;
            border-radius: 20px;
            font-size: 15px;
            line-height: 1.6;
            word-wrap: break-word;
            box-shadow: 0 4px 15px rgba(0, 0, 0, 0.1);
        }
        .message.user .bubble {
            background: linear-gradient(135deg, var(--primary), #1e1b4b);
            color: white;
            border-bottom-right-radius: 4px;
        }
        .message.assistant .bubble {
            background: var(--card-bg);
            border: 1px solid var(--border-color);
            color: var(--text-main);
            border-bottom-left-radius: 4px;
        }
        
        /* Soporte para rendering de Markdown */
        .bubble p { margin-top: 0; margin-bottom: 12px; }
        .bubble p:last-child { margin-bottom: 0; }
        .bubble ul, .bubble ol { margin: 8px 0; padding-left: 20px; }
        .bubble table { border-collapse: collapse; width: 100%; margin: 12px 0; font-size: 13.5px; }
        .bubble table th, .bubble table td { border: 1px solid var(--border-color); padding: 8px 12px; text-align: left; }
        .bubble table th { background: rgba(139, 92, 246, 0.1); }
        
        /* Botones de acción del query */
        .query-actions {
            display: flex;
            gap: 10px;
            margin-top: 12px;
        }
        .action-tab-btn {
            background: rgba(139, 92, 246, 0.08);
            border: 1px solid var(--border-color);
            color: var(--primary-hover);
            padding: 8px 14px;
            font-size: 12.5px;
            font-weight: 600;
            border-radius: 10px;
            cursor: pointer;
            display: flex;
            align-items: center;
            gap: 6px;
            transition: all 0.3s ease;
        }
        .action-tab-btn:hover {
            background: rgba(139, 92, 246, 0.18);
            border-color: rgba(139, 92, 246, 0.3);
            transform: translateY(-1px);
        }
        .action-tab-btn.active {
            background: rgba(16, 185, 129, 0.1);
            border-color: rgba(16, 185, 129, 0.3);
            color: var(--accent);
        }
        
        /* Panel del Query y la Tabla de Datos con Animaciones de Apertura y Cierre */
        .query-container {
            margin-top: 10px;
            background: rgba(4, 8, 20, 0.5);
            border: 1px solid var(--border-color);
            border-radius: 14px;
            overflow: hidden;
            box-shadow: 0 6px 20px rgba(0, 0, 0, 0.2);
            display: block;
            max-height: 0;
            opacity: 0;
            transition: max-height 0.4s cubic-bezier(0.16, 1, 0.3, 1), opacity 0.35s ease, margin-top 0.4s ease;
        }
        .query-container.open {
            max-height: 550px; /* Incrementado para gráficos grandes */
            opacity: 1;
            margin-top: 10px;
        }
        .query-body {
            padding: 14px 18px;
            background: #08060f;
        }
        .query-body pre {
            margin: 0;
            font-family: 'Courier New', Courier, monospace;
            font-size: 13.5px;
            color: var(--accent);
            overflow-x: auto;
            white-space: pre-wrap;
            line-height: 1.5;
        }
        
        /* Contenedor de la Tabla de Datos */
        .data-table-container {
            max-height: 250px;
            overflow-y: auto;
            overflow-x: auto;
            width: 100%;
        }
        table.db-data-table {
            width: 100%;
            border-collapse: collapse;
            font-size: 12.5px;
            text-align: left;
        }
        table.db-data-table th {
            background: rgba(139, 92, 246, 0.15);
            color: var(--primary-hover);
            padding: 10px 12px;
            font-weight: 700;
            border-bottom: 1px solid rgba(139, 92, 246, 0.25);
            position: sticky;
            top: 0;
        }
        table.db-data-table td {
            padding: 8px 12px;
            border-bottom: 1px solid rgba(255, 255, 255, 0.05);
            color: var(--text-main);
        }
        table.db-data-table tr:hover {
            background: rgba(255, 255, 255, 0.03);
        }
        
        /* Footer del Chat Flotante */
        .footer-input {
            padding: 16px 24px;
            background: transparent;
            border-top: none;
            position: absolute;
            bottom: 16px;
            left: 50%;
            transform: translateX(-50%);
            width: 90%;
            max-width: 800px;
            z-index: 10;
        }
        .input-wrapper {
            background: rgba(14, 10, 26, 0.8);
            backdrop-filter: blur(24px);
            border: 1px solid rgba(139, 92, 246, 0.25);
            border-radius: 24px;
            padding: 8px 12px;
            box-shadow: 0 10px 30px rgba(0, 0, 0, 0.5), 0 0 15px rgba(139, 92, 246, 0.15);
            display: flex;
            gap: 12px;
            align-items: center;
            transition: all 0.35s cubic-bezier(0.4, 0, 0.2, 1);
        }
        .input-wrapper:focus-within {
            border-color: var(--primary-hover);
            box-shadow: 0 12px 35px rgba(0, 0, 0, 0.6), 0 0 25px rgba(139, 92, 246, 0.3);
            transform: translateY(-2px);
        }
        textarea {
            flex: 1;
            background: transparent !important;
            border: none !important;
            border-radius: 0;
            padding: 10px 14px;
            color: var(--text-main);
            font-size: 15px;
            font-family: inherit;
            resize: none;
            height: 44px;
            box-sizing: border-box;
            outline: none;
            box-shadow: none !important;
        }
        .send-btn {
            background: linear-gradient(135deg, var(--primary), var(--accent));
            color: white;
            border: none;
            border-radius: 18px;
            width: 48px;
            height: 48px;
            display: flex;
            justify-content: center;
            align-items: center;
            cursor: pointer;
            transition: all 0.3s cubic-bezier(0.175, 0.885, 0.32, 1.275);
            box-shadow: 0 6px 15px rgba(139, 92, 246, 0.3);
            flex-shrink: 0;
        }
        .send-btn:hover {
            transform: scale(1.08) rotate(5deg);
            box-shadow: 0 8px 22px rgba(139, 92, 246, 0.5);
            background: linear-gradient(135deg, var(--primary-hover), var(--accent-hover));
        }
        .send-btn:active {
            transform: scale(0.95);
        }
        .send-btn svg {
            width: 20px;
            height: 20px;
            fill: none;
            stroke: currentColor;
            stroke-width: 2;
            stroke-linecap: round;
            stroke-linejoin: round;
        }
        
        /* Spinner de carga */
        .typing-loader {
            display: flex;
            align-items: center;
            gap: 5px;
            padding: 8px 12px;
        }
        .dot {
            width: 8px;
            height: 8px;
            background: var(--primary-hover);
            border-radius: 50%;
            animation: bounce 1.4s infinite ease-in-out both;
        }
        .dot:nth-child(1) { animation-delay: -0.32s; }
        .dot:nth-child(2) { animation-delay: -0.16s; }
        @keyframes bounce {
            0%, 80%, 100% { transform: scale(0); }
            40% { transform: scale(1.0); }
        }
    </style>
</head>
<body>
    <div class="app-layout">
        <!-- 1. PANEL IZQUIERDO: SQL MANAGER -->
        <aside class="sidebar">
            <div class="sidebar-header">
                <h3>🗄️ SQL Manager Tree</h3>
            </div>
            
            <div class="sidebar-scroll-panel">
                <div class="db-tree-container">
                    <!-- Nodo Raíz: Base de datos -->
                    <div class="db-node">
                        <svg viewBox="0 0 24 24">
                            <path d="M12 2C6.5 2 2 4.2 2 7s4.5 5 10 5 10-2.2 10-5-4.5-5-10-5zm0 16c-5.5 0-10-1.8-10-4v-2c0 2.2 4.5 4 10 4s10-1.8 10-4v2c0 2.2-4.5 4-10 4zm0 4c-5.5 0-10-1.8-10-4v-2c0 2.2 4.5 4 10 4s10-1.8 10-4v2c0 2.2-4.5 4-10 4z"/>
                        </svg>
                        Database: <span style="color: var(--accent);">{{ db_name }}</span>
                    </div>
                    
                    <!-- Hijos: Tablas -->
                    {% for table, cols in schema_dict.items() %}
                    <div class="table-node">
                        <div class="table-header-node" onclick="toggleTableNode(this)">
                            <div class="table-name-wrapper">
                                <svg class="caret-icon" viewBox="0 0 24 24" style="transform: rotate(0deg); width: 8px; height: 8px;">
                                    <polygon points="8 5 16 12 8 19 8 5"></polygon>
                                </svg>
                                <svg class="table-icon" viewBox="0 0 24 24" style="fill: #1e90ff; width: 14px; height: 14px;">
                                    <path d="M4 3h16c1.1 0 2 .9 2 2v14c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V5c0-1.1.9-2 2-2zm0 4h16V5H4v2zm0 5h7V9H4v3zm9 0h7V9h-7v3zm-9 5h7v-3H4v3zm9 0h7v-3h-7v3z"/>
                                </svg>
                                <strong>{{ table }}</strong>
                            </div>
                            <button class="preview-btn" onclick="previewTable(event, '{{ table }}')" title="Consultar 5 filas rápidas">Preview</button>
                        </div>
                        <!-- Lista de Columnas Plegables -->
                        <div class="column-list">
                            {% for col in cols %}
                            <div class="column-node" onclick="insertColumn('{{ table }}', '{{ col.name }}')">
                                <div class="column-info">
                                    <svg viewBox="0 0 24 24" style="fill: currentColor; width: 10px; height: 10px;">
                                        <path d="M12.65 11.35c.02-.11.03-.23.03-.35 0-1.93-1.57-3.5-3.5-3.5s-3.5 1.57-3.5 3.5 1.57 3.5 3.5 3.5c.12 0 .24-.01.35-.03L12 17v2h2v-2h2v-2h-3.35z"/>
                                    </svg>
                                    <span>{{ col.name }}</span> <span style="color: #6a7c92; font-size: 10px;">({{ col.type }})</span>
                                </div>
                                <button class="attr-preview-btn" onclick="previewColumn(event, '{{ table }}', '{{ col.name }}')" title="Ver valores únicos de esta columna">Analizar</button>
                            </div>
                            {% endfor %}
                        </div>
                    </div>
                    {% endfor %}
                </div>
            </div>
        </aside>

        <!-- 2. AREA PRINCIPAL: CHAT -->
        <main class="main-chat-area">
            <header>
                <div style="display: flex; align-items: center; gap: 16px;">
                    <!-- Botón Retráctil con Icono de Base de Datos -->
                    <button onclick="toggleSidebar()" class="sidebar-toggle-btn is-open" id="sidebar-toggle" title="Mostrar/Ocultar SQL Manager">
                        <svg class="db-toggle-icon" viewBox="0 0 24 24">
                            <path d="M12 2C6.5 2 2 4.2 2 7s4.5 5 10 5 10-2.2 10-5-4.5-5-10-5zm0 16c-5.5 0-10-1.8-10-4v-2c0 2.2 4.5 4 10 4s10-1.8 10-4v2c0 2.2-4.5 4-10 4zm0 4c-5.5 0-10-1.8-10-4v-2c0 2.2 4.5 4 10 4s10-1.8 10-4v2c0 2.2-4.5 4-10 4z"/>
                        </svg>
                    </button>
                    <h1>MCP Relational AI</h1>
                    <div class="badges-wrapper">
                        <div class="db-badge">
                            <span style="font-size: 8px;">●</span> {{ db_type.upper() }} ({{ db_name }})
                        </div>
                        <div class="model-badge" id="active-model-badge">
                            ⚡ {{ model_name }}
                        </div>
                    </div>
                </div>
                <div class="actions-wrapper">
                    <a href="/" class="header-btn btn-modify" title="Modificar Conexión">
                        <svg viewBox="0 0 24 24" style="width: 18px; height: 18px; fill: none; stroke: currentColor; stroke-width: 2; stroke-linecap: round; stroke-linejoin: round;">
                            <path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"></path>
                        </svg>
                    </a>
                    <a href="/disconnect" class="header-btn btn-disconnect" title="Desconectar / Salir">
                        <svg viewBox="0 0 24 24" style="width: 18px; height: 18px; fill: none; stroke: currentColor; stroke-width: 2; stroke-linecap: round; stroke-linejoin: round;">
                            <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"></path>
                            <polyline points="16 17 21 12 16 7"></polyline>
                            <line x1="21" y1="12" x2="9" y2="12"></line>
                        </svg>
                    </a>
                </div>
            </header>

            <div class="chat-container" id="chat">
                <div class="message assistant">
                    <div class="bubble" id="welcome-bubble">
                        ¡Hola! Conexión establecida con éxito y esquema cargado en memoria de la IA.<br>
                        ¿En qué puedo ayudarte a consultar o analizar hoy sobre la base de datos <strong>{{ db_name }}</strong>?
                    </div>
                </div>
            </div>

            <div class="footer-input">
                <div class="input-wrapper">
                    <textarea id="message-input" placeholder="Pregunta algo sobre tus datos (ej. ¿cuántos registros hay en total?)..." rows="1"></textarea>
                    <button class="send-btn" id="send-button" title="Preguntar a la IA">
                        <svg viewBox="0 0 24 24">
                            <line x1="22" y1="2" x2="11" y2="13"></line>
                            <polygon points="22 2 15 22 11 13 2 9 22 2"></polygon>
                        </svg>
                    </button>
                </div>
            </div>
        </main>
    </div>

    <script>
        const chatEl = document.getElementById('chat');
        const inputEl = document.getElementById('message-input');
        const sendBtn = document.getElementById('send-button');
        const activeModelBadge = document.getElementById('active-model-badge');

        let userExplicitlyRequestedChart = false;

        // Toggle del Menú Izquierdo Retráctil con Icono de Base de Datos
        function toggleSidebar() {
            const sidebar = document.querySelector('.sidebar');
            const toggleBtn = document.getElementById('sidebar-toggle');
            sidebar.classList.toggle('collapsed');
            toggleBtn.classList.toggle('is-open');
        }

        // Control del Panel del Árbol SQL con transiciones de CSS
        function toggleTableNode(nodeEl) {
            const list = nodeEl.nextElementSibling;
            const caret = nodeEl.querySelector('.caret-icon');
            
            list.classList.toggle('open');
            if (list.classList.contains('open')) {
                caret.style.transform = 'rotate(90deg)';
                caret.style.fill = '#a78bfa';
            } else {
                caret.style.transform = 'rotate(0deg)';
                caret.style.fill = '#8fa0b5';
            }
        }

        // Consultar 5 filas rápidas de la tabla
        function previewTable(event, tableName) {
            event.stopPropagation();
            inputEl.value = `Muestra los primeros 5 registros de la tabla ${tableName}`;
            handleSend();
        }

        // Analizar columna (valores únicos)
        function previewColumn(event, tableName, columnName) {
            event.stopPropagation();
            inputEl.value = `Dame una estadística de la columna ${columnName} de la tabla ${tableName} mostrando sus valores más recurrentes.`;
            handleSend();
        }

        // Insertar columna en el cursor del textarea para autocompletar
        function insertColumn(tableName, columnName) {
            const isMssql = "{{ db_type }}" === "mssql";
            const formattedTable = isMssql && tableName.includes(" ") ? `[${tableName}]` : tableName;
            const formattedCol = isMssql && columnName.includes(" ") ? `[${columnName}]` : columnName;
            
            const insertText = ` ${formattedTable}.${formattedCol} `;
            
            const start = inputEl.selectionStart;
            const end = inputEl.selectionEnd;
            const text = inputEl.value;
            
            inputEl.value = text.substring(0, start) + insertText + text.substring(end);
            inputEl.focus();
            inputEl.selectionStart = inputEl.selectionEnd = start + insertText.length;
        }

        // Exportar tabla a Excel / CSV con soporte para UTF-8 BOM
        function exportToCSV(btnEl) {
            const messageWrapper = btnEl.closest('.message');
            const table = messageWrapper.querySelector('table.db-data-table');
            if (!table) {
                alert("No hay tabla de resultados para exportar.");
                return;
            }
            
            let csv = [];
            const rows = table.querySelectorAll("tr");
            
            for (let i = 0; i < rows.length; i++) {
                let row = [], cols = rows[i].querySelectorAll("td, th");
                
                for (let j = 0; j < cols.length; j++) {
                    let data = cols[j].innerText;
                    if (cols[j].querySelector('img')) {
                        data = "[Imagen Binaria]";
                    }
                    data = data.replace(/"/g, '""');
                    row.push('"' + data + '"');
                }
                
                csv.push(row.join(","));
            }
            
            const csvString = "\\uFEFF" + csv.join("\\n");
            const blob = new Blob([csvString], { type: 'text/csv;charset=utf-8;' });
            const link = document.createElement("a");
            const url = URL.createObjectURL(blob);
            link.setAttribute("href", url);
            link.setAttribute("download", "resultados_mcp_query.csv");
            link.style.visibility = 'hidden';
            document.body.appendChild(link);
            link.click();
            document.body.removeChild(link);
        }

        // Detectar variables y crear/actualizar Gráficos dinámicamente con estética ultra profesional
        function initChartForPanel(panelEl, queryData) {
            if (!queryData || queryData.length === 0) return;
            
            const canvas = panelEl.querySelector('.my-db-chart');
            if (!canvas) return;
            
            // Auto-detectar columnas de etiquetas (Label) y valores (Data)
            const keys = Object.keys(queryData[0]);
            let labelKey = keys[0];
            let valueKey = keys[1] || keys[0];
            
            for (const key of keys) {
                const val = queryData[0][key];
                if (typeof val === 'string' || val instanceof Date) {
                    labelKey = key;
                } else if (typeof val === 'number') {
                    valueKey = key;
                }
            }
            
            const labels = queryData.map(row => String(row[labelKey]));
            const dataPoints = queryData.map(row => Number(row[valueKey]) || 0);
            
            const ctx = canvas.getContext('2d');
            
            // Crear gradiente azul translúcido profesional para el relleno de línea
            const gradient = ctx.createLinearGradient(0, 0, 0, 300);
            gradient.addColorStop(0, 'rgba(139, 92, 246, 0.4)');
            gradient.addColorStop(0.5, 'rgba(139, 92, 246, 0.15)');
            gradient.addColorStop(1, 'rgba(139, 92, 246, 0.0)');
            
            if (canvas.chartInstance) {
                canvas.chartInstance.destroy();
            }
            
            canvas.chartInstance = new Chart(ctx, {
                type: 'line', // Línea por defecto
                data: {
                    labels: labels,
                    datasets: [{
                        label: valueKey,
                        data: dataPoints,
                        borderColor: '#a78bfa',
                        backgroundColor: gradient,
                        borderWidth: 3,
                        fill: true,
                        tension: 0.35, // Suavizado bezier
                        pointBackgroundColor: '#34d399',
                        pointBorderColor: '#0a0a12',
                        pointBorderWidth: 2,
                        pointRadius: 5,
                        pointHoverRadius: 8
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: {
                            display: true,
                            labels: { color: '#f0f4f8', font: { family: 'Plus Jakarta Sans', weight: '600' } }
                        }
                    },
                    scales: {
                        x: {
                            grid: { color: 'rgba(255,255,255,0.03)' },
                            ticks: { color: '#8fa0b5', font: { family: 'Plus Jakarta Sans' } }
                        },
                        y: {
                            grid: { color: 'rgba(255,255,255,0.03)' },
                            ticks: { color: '#8fa0b5', font: { family: 'Plus Jakarta Sans' } }
                        }
                    }
                }
            });
        }

        // Cambiar dinámicamente tipo de gráfico
        function updateChartType(selectEl) {
            const chartPanel = selectEl.closest('.chart-panel');
            const canvas = chartPanel.querySelector('.my-db-chart');
            if (canvas && canvas.chartInstance) {
                const type = selectEl.value;
                canvas.chartInstance.config.type = type;
                canvas.chartInstance.update();
            }
        }

        // Crear una tabla HTML a partir del JSON de datos
        function generateHTMLTable(dataList) {
            if (!dataList || dataList.length === 0) return "<p style='padding:12px;color:#8fa0b5;margin:0;'>La consulta no retornó datos o está vacía.</p>";
            
            const headers = Object.keys(dataList[0]);
            let tableHtml = `<div class="data-table-container"><table class="db-data-table"><thead><tr>`;
            
            headers.forEach(h => {
                tableHtml += `<th>${h}</th>`;
            });
            tableHtml += `</tr></thead><tbody>`;
            
            dataList.forEach(row => {
                tableHtml += `<tr>`;
                headers.forEach(h => {
                    let cellVal = row[h];
                    if (cellVal === null) {
                        cellVal = "<span style='color:gray;'>NULL</span>";
                    } else if (typeof cellVal === 'string' && cellVal.startsWith('data:image/')) {
                        cellVal = `<img src="${cellVal}" style="max-height: 48px; border-radius: 6px; box-shadow: 0 2px 8px rgba(0,0,0,0.3);" alt="Image" onerror="this.outerHTML='<span style=\\'color:gray;\\'>[Imagen no renderizable]</span>'" />`;
                    }
                    tableHtml += `<td>${cellVal}</td>`;
                });
                tableHtml += `</tr>`;
            });
            
            tableHtml += `</tbody></table></div>`;
            return tableHtml;
        }

        // Agregar mensaje en el Chat
        function appendMessage(role, content, query = null, queryData = null) {
            const msgDiv = document.createElement('div');
            msgDiv.className = `message ${role}`;
            
            let parsedText = content;
            if (role === 'assistant') {
                parsedText = marked.parse(content);
            } else {
                parsedText = content.replace(/\\n/g, '<br>');
            }
            
            let bubbleHtml = `<div class="bubble">${parsedText}</div>`;
            
            if (query) {
                let chartButton = '';
                let chartPanelHtml = '';
                
                // Mostrar gráficos únicamente si el usuario lo solicitó de forma explícita
                if (userExplicitlyRequestedChart) {
                    chartButton = `
                    <button class="action-tab-btn active" onclick="toggleViewContainer(this, 'chart-panel')">
                        📈 Ver Gráfico
                    </button>`;
                    
                    chartPanelHtml = `
                    <!-- Panel de Gráfico Profesional Abierto por Defecto en Tamaño Grande -->
                    <div class="query-container chart-panel open" style="max-height: 580px; opacity: 1; margin-top: 10px;">
                        <div class="query-body" style="background:#030710; padding:0; position:relative; min-height: 380px;">
                            <div style="padding: 10px 16px; display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid var(--border-color); background: rgba(30,144,255,0.08);">
                                <label style="margin:0; font-size:12px; text-transform:none; font-weight:700; color:var(--accent);">📊 Visualización Gráfica Profesional</label>
                                <div style="display: flex; gap: 8px; align-items: center;">
                                    <label style="margin:0; font-size:11px; text-transform:none; font-weight:bold; color:var(--text-muted);">Tipo:</label>
                                    <select onchange="updateChartType(this)" style="padding: 4px 8px; font-size: 11px; width: auto; height: auto; border-radius: 6px; background:#040812; border:1px solid var(--border-color); color:var(--text-main); outline:none; cursor:pointer;">
                                        <option value="line">Línea (Line)</option>
                                        <option value="bar">Barra (Bar)</option>
                                        <option value="pie">Pastel (Pie)</option>
                                        <option value="doughnut">Dona (Doughnut)</option>
                                    </select>
                                </div>
                            </div>
                            <div style="height: 320px; position:relative; width:100%; padding: 16px; box-sizing: border-box;">
                                <canvas class="my-db-chart"></canvas>
                            </div>
                        </div>
                    </div>`;
                }

                bubbleHtml += `
                <div class="query-actions">
                    <button class="action-tab-btn" onclick="toggleViewContainer(this, 'query-panel')">
                        📝 Ver Query SQL
                    </button>
                    <button class="action-tab-btn ${userExplicitlyRequestedChart ? '' : 'active'}" onclick="toggleViewContainer(this, 'table-panel')">
                        📊 Ver Tabla
                    </button>
                    ${chartButton}
                    <button class="action-tab-btn" onclick="exportToCSV(this)" style="color: var(--accent); border-color: rgba(16, 185, 129, 0.25); background: rgba(16, 185, 129, 0.05);">
                        📥 Exportar a Excel
                    </button>
                </div>
                
                <!-- Panel de Código Query -->
                <div class="query-container query-panel">
                    <div class="query-body">
                        <pre><code>${query}</code></pre>
                    </div>
                </div>
                
                <!-- Panel de la Tabla de Datos -->
                <div class="query-container table-panel ${userExplicitlyRequestedChart ? '' : 'open'}" style="${userExplicitlyRequestedChart ? '' : 'max-height: 450px; opacity: 1;'}">
                    <div class="query-body" style="padding:0;background: #030710;">
                        ${generateHTMLTable(queryData)}
                    </div>
                </div>
                
                ${chartPanelHtml}`;
            }
            
            msgDiv.innerHTML = bubbleHtml;
            chatEl.appendChild(msgDiv);
            
            if (query && queryData && userExplicitlyRequestedChart) {
                const chartPanel = msgDiv.querySelector('.chart-panel');
                initChartForPanel(chartPanel, queryData);
            }
            
            chatEl.scrollTop = chatEl.scrollHeight;
        }

        // Controlar la visualización mutua de los paneles con animaciones suaves de apertura/cierre
        function toggleViewContainer(btnEl, targetClass) {
            const messageWrapper = btnEl.closest('.message');
            const targetPanel = messageWrapper.querySelector(`.${targetClass}`);
            
            const panels = messageWrapper.querySelectorAll('.query-container');
            const buttons = messageWrapper.querySelectorAll('.action-tab-btn');
            
            const isTargetOpen = targetPanel.classList.contains('open');
            
            panels.forEach(p => {
                p.classList.remove('open');
                p.style.maxHeight = '0';
                p.style.opacity = '0';
            });
            buttons.forEach(b => {
                if (!b.innerText.includes("Exportar")) {
                    b.classList.remove('active');
                }
            });
            
            if (!isTargetOpen) {
                targetPanel.classList.add('open');
                // Asignar altura máxima dinámicamente según clase
                if (targetClass === 'chart-panel') {
                    targetPanel.style.maxHeight = '580px';
                } else {
                    targetPanel.style.maxHeight = '450px';
                }
                targetPanel.style.opacity = '1';
                btnEl.classList.add('active');
            }
            
            setTimeout(() => {
                chatEl.scrollTop = chatEl.scrollHeight;
            }, 350);
        }

        async function handleSend() {
            const message = inputEl.value.trim();
            if (!message) return;

            // Determinar si el usuario pide explícitamente un gráfico
            const lowerMsg = message.toLowerCase();
            userExplicitlyRequestedChart = lowerMsg.includes("grafic") || lowerMsg.includes("gráfico") || lowerMsg.includes("chart") || lowerMsg.includes("plot") || lowerMsg.includes("dibuj") || lowerMsg.includes("barra") || lowerMsg.includes("linea");

            inputEl.value = '';
            appendMessage('user', message);

            const loaderDiv = document.createElement('div');
            loaderDiv.className = 'message assistant';
            loaderDiv.id = 'temp-loader';
            loaderDiv.innerHTML = `
                <div class="bubble">
                    <div class="typing-loader">
                        <div class="dot"></div>
                        <div class="dot"></div>
                        <div class="dot"></div>
                    </div>
                </div>`;
            chatEl.appendChild(loaderDiv);
            chatEl.scrollTop = chatEl.scrollHeight;

            try {
                const res = await fetch('/send_message', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ message: message })
                });
                
                const data = await res.json();
                
                document.getElementById('temp-loader').remove();

                if (data.error) {
                    appendMessage('assistant', `⚠️ Ocurrió un error: ${data.error}`);
                } else {
                    appendMessage('assistant', data.response, data.query_used, data.query_data);
                    if (data.model_used) {
                        activeModelBadge.textContent = `⚡ ${data.model_used}`;
                    }
                }
            } catch (err) {
                document.getElementById('temp-loader').remove();
                appendMessage('assistant', '⚠️ Error de comunicación con el servidor.');
            }
        }

        sendBtn.addEventListener('click', handleSend);
        inputEl.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                handleSend();
            }
        });
    </script>
</body>
</html>
"""

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5050, debug=True)
