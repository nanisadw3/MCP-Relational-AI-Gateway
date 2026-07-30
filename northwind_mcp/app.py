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
        
        form_submitted = {**config, "api_key": api_key, "gemini_model": gemini_model}
        
        if not api_key:
            return render_template_string(HTML_LOGIN, error="La clave API de Google Gemini es obligatoria.", form_data=form_submitted)
            
        try:
            schema_dict = fetch_schema(config)
            
            schema_text = ""
            for table, cols in schema_dict.items():
                col_strs = [f"{c['name']} ({c['type']})" for c in cols]
                schema_text += f"Tabla: {table}\nColumnas: {', '.join(col_strs)}\n\n"
                
            session["db_config"] = config
            session["db_schema"] = schema_text
            session["db_schema_dict"] = schema_dict
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
    
    display_model = "Auto Fallback" if session["gemini_model"] == "auto" else session["gemini_model"]
    return render_template_string(
        HTML_CHAT, 
        db_name=session["db_config"]["database"], 
        db_type=session["db_config"]["db_type"], 
        db_user=session["db_config"]["user"],
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
    
    chat_history.append({
        "role": "user",
        "parts": [{"text": user_message}]
    })
    
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
    
    models_to_try = AUTOMATIC_MODELS if model_selection == "auto" else [model_selection]
    
    response_data = None
    successful_model = None
    error_logs = []
    
    async with httpx.AsyncClient() as client:
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
        
        if function_call:
            tool_name = function_call["name"]
            tool_args = function_call["args"]
            query_used = tool_args.get("sql")
            
            db_res = execute_sql(db_config, query_used)
            if db_res["status"] == "success":
                raw_db_results = db_res["data"]
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
        "query_data": raw_db_results,
        "reasoning": reasoning if function_call else None,
        "model_used": successful_model
    })

# --- HTML LOGIN con Google Material Design 3 ---

HTML_LOGIN = """
<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>MCP Database Gateway</title>
    <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@300;400;500;600;700&display=swap" rel="stylesheet">
    <link href="https://fonts.googleapis.com/icon?family=Material+Symbols+Rounded" rel="stylesheet">
    <style>
        :root {
            /* M3 Dark por defecto */
            --bg-color: #141218;
            --card-bg: rgba(28, 27, 31, 0.7);
            --border-color: rgba(208, 188, 255, 0.15);
            --primary: #D0BCFF;
            --primary-hover: #EADDFF;
            --accent: #b8f397;
            --accent-hover: #c8ffb0;
            --text-main: #E6E1E5;
            --text-muted: #CAC4D0;
            --surface-variant: rgba(73, 69, 79, 0.2);
        }
        body.light-theme {
            /* M3 Light */
            --bg-color: #f8f9ff;
            --card-bg: rgba(255, 255, 255, 0.75);
            --border-color: rgba(103, 80, 164, 0.15);
            --primary: #6750A4;
            --primary-hover: #21005D;
            --accent: #386a20;
            --accent-hover: #1b5e20;
            --text-main: #1c1b1f;
            --text-muted: #49454f;
            --surface-variant: rgba(231, 224, 236, 0.5);
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
            transition: background-color 0.4s ease, color 0.4s ease;
            overflow-x: hidden;
            position: relative;
        }
        
        /* Tema Switcher Flotante */
        .theme-switcher-float {
            position: fixed;
            top: 24px;
            right: 24px;
            background: var(--card-bg);
            border: 1px solid var(--border-color);
            padding: 10px;
            border-radius: 50%;
            cursor: pointer;
            display: flex;
            align-items: center;
            justify-content: center;
            color: var(--primary);
            box-shadow: 0 4px 15px rgba(0,0,0,0.2);
            transition: all 0.3s ease;
            z-index: 100;
        }
        .theme-switcher-float:hover {
            transform: scale(1.1) rotate(15deg);
            background: var(--surface-variant);
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
            box-shadow: 0 25px 50px -12px rgba(103, 80, 164, 0.15);
            transition: all 0.3s;
        }
        .card:hover {
            border-color: var(--primary);
            box-shadow: 0 25px 60px -10px rgba(103, 80, 164, 0.25);
        }
        h2 {
            margin-top: 0;
            font-weight: 800;
            font-size: 30px;
            letter-spacing: -0.8px;
            background: linear-gradient(135deg, var(--primary), var(--accent));
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
            border-bottom: 1px solid var(--border-color);
            padding-bottom: 6px;
            display: flex;
            align-items: center;
            gap: 6px;
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
            background: var(--surface-variant);
            border: 1px solid var(--border-color);
            border-radius: 14px;
            color: var(--text-main);
            font-size: 15px;
            box-sizing: border-box;
            transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
        }
        input:focus, select:focus {
            outline: none;
            border-color: var(--primary);
            box-shadow: 0 0 0 4px rgba(103, 80, 164, 0.2);
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
            background: var(--primary);
            border: none;
            border-radius: 14px;
            color: var(--bg-color);
            font-size: 16px;
            font-weight: 700;
            cursor: pointer;
            transition: all 0.3s ease;
            box-shadow: 0 8px 24px rgba(103, 80, 164, 0.2);
            margin-top: 20px;
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 8px;
        }
        body.light-theme .btn {
            color: #fff;
        }
        .btn:hover {
            transform: translateY(-2px);
            box-shadow: 0 12px 30px rgba(103, 80, 164, 0.35);
            background: var(--primary-hover);
        }
        .btn-load {
            padding: 14px 18px;
            background: var(--surface-variant);
            border: 1px solid var(--border-color);
            border-radius: 14px;
            color: var(--accent);
            cursor: pointer;
            font-size: 13px;
            font-weight: bold;
            transition: all 0.2s;
            display: flex;
            align-items: center;
            gap: 6px;
        }
        .btn-load:hover {
            background: var(--border-color);
            color: var(--accent-hover);
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
        function handleDbTypeChange() {
            const dbTypeSelect = document.getElementById("db_type");
            const portInput = document.getElementById("port");
            
            if (dbTypeSelect.value === "mssql") {
                portInput.value = "1433";
            } else if (dbTypeSelect.value === "postgresql") {
                portInput.value = "5432";
            }
        }

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
            
            const originalText = btn.innerHTML;
            btn.innerHTML = '<span class="material-symbols-rounded">sync</span> Cargando...';
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
                btn.innerHTML = originalText;
                btn.disabled = false;
            }
        }

        function toggleTheme() {
            const body = document.body;
            const icon = document.getElementById("theme-icon");
            if (body.classList.contains("light-theme")) {
                body.classList.remove("light-theme");
                icon.innerText = "light_mode";
                localStorage.setItem("m3-theme", "dark");
            } else {
                body.classList.add("light-theme");
                icon.innerText = "dark_mode";
                localStorage.setItem("m3-theme", "light");
            }
        }

        document.addEventListener("DOMContentLoaded", () => {
            const savedTheme = localStorage.getItem("m3-theme");
            if (savedTheme === "light") {
                document.body.classList.add("light-theme");
                document.getElementById("theme-icon").innerText = "dark_mode";
            }
        });
    </script>
</head>
<body>
    <button class="theme-switcher-float" onclick="toggleTheme()">
        <span class="material-symbols-rounded" id="theme-icon">light_mode</span>
    </button>
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
                <div class="section-title"><span class="material-symbols-rounded">psychology</span> 1. Configuración de IA (Google Gemini)</div>
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

                <div class="section-title"><span class="material-symbols-rounded">database</span> 2. Conexión a la Base de Datos</div>
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
                        <button type="button" onclick="loadDatabases()" id="btn-load-dbs" class="btn-load">
                            <span class="material-symbols-rounded">sync</span> Cargar
                        </button>
                    </div>
                </div>
                <button type="submit" class="btn"><span class="material-symbols-rounded">login</span> Conectar y Analizar</button>
            </form>
        </div>
    </div>
</body>
</html>
"""

# --- HTML CHAT con Google Material Design 3 y Switcher de Temas ---

HTML_CHAT = """
<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>MCP Chat - {{ db_name }}</title>
    <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@300;400;500;600;700&display=swap" rel="stylesheet">
    <link href="https://fonts.googleapis.com/icon?family=Material+Symbols+Rounded" rel="stylesheet">
    <!-- Cargar marked.js y Chart.js para visualizaciones y MD -->
    <script src="https://cdn.jsdelivr.net/npm/marked/marked.min.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/hammerjs@2.0.8"></script>
    <script src="https://cdn.jsdelivr.net/npm/chartjs-plugin-zoom@2.0.1/dist/chartjs-plugin-zoom.min.js"></script>
    <style>
        :root {
            /* M3 Dark Theme */
            --bg-color: #141218;
            --sidebar-bg: rgba(28, 27, 31, 0.85);
            --chat-bg: #141218;
            --card-bg: rgba(37, 35, 41, 0.6);
            --border-color: rgba(208, 188, 255, 0.12);
            --primary: #D0BCFF;
            --primary-hover: #EADDFF;
            --accent: #b8f397;
            --accent-hover: #c8ffb0;
            --text-main: #E6E1E5;
            --text-muted: #CAC4D0;
            --surface-variant: rgba(73, 69, 79, 0.35);
        }
        body.light-theme {
            /* M3 Light Theme */
            --bg-color: #f8f9ff;
            --sidebar-bg: rgba(240, 244, 248, 0.9);
            --chat-bg: #f8f9ff;
            --card-bg: rgba(255, 255, 255, 0.7);
            --border-color: rgba(103, 80, 164, 0.12);
            --primary: #6750A4;
            --primary-hover: #21005D;
            --accent: #386a20;
            --accent-hover: #1b5e20;
            --text-main: #1c1b1f;
            --text-muted: #49454f;
            --surface-variant: rgba(231, 224, 236, 0.6);
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
            transition: background-color 0.4s ease, color 0.4s ease;
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
            box-shadow: 5px 0 25px rgba(0, 0, 0, 0.2);
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
            width: 48px;
            height: 48px;
            position: absolute;
            top: 14px;
            right: 16px; /* Integrado dentro del sidebar por defecto */
            cursor: pointer;
            border-radius: 16px;
            background: var(--card-bg);
            border: 1px solid var(--border-color);
            display: flex;
            align-items: center;
            justify-content: center;
            transition: all 0.4s cubic-bezier(0.22, 1, 0.36, 1);
            box-shadow: 0 4px 15px rgba(0,0,0,0.15);
            z-index: 35;
        }
        /* Solo si el panel está colapsado, el botón se posiciona por fuera */
        .sidebar.collapsed .sidebar-toggle-btn {
            right: -60px;
            box-shadow: 0 6px 20px rgba(0,0,0,0.25);
        }
        .sidebar-toggle-btn:hover {
            background: var(--surface-variant);
            transform: translateY(-1px);
        }
        .sidebar-toggle-btn .db-toggle-icon {
            font-size: 24px;
            color: var(--accent);
            transition: all 0.4s ease;
        }
        /* Cuando el sidebar está abierto: el icono brilla y pulsa suavemente */
        .sidebar-toggle-btn.is-open .db-toggle-icon {
            color: var(--primary);
            animation: dbPulse 2s ease-in-out infinite;
        }
        @keyframes dbPulse {
            0%, 100% { transform: scale(1); }
            50% { transform: scale(1.15); }
        }
        /* Cuando el sidebar está cerrado: el icono se atenúa */
        .sidebar-toggle-btn:not(.is-open) .db-toggle-icon {
            color: var(--text-muted);
        }
        
        .sidebar-scroll-panel {
            flex: 1;
            overflow-y: auto;
            display: flex;
            flex-direction: column;
            padding-top: 10px;
        }
        
        /* Scrollbars Premium Ultradelgados */
        ::-webkit-scrollbar {
            width: 6px;
            height: 6px;
        }
        ::-webkit-scrollbar-track {
            background: rgba(0,0,0,0.05);
        }
        ::-webkit-scrollbar-thumb {
            background: var(--border-color);
            border-radius: 4px;
        }
        ::-webkit-scrollbar-thumb:hover {
            background: var(--primary);
        }
        
        .db-tree-container {
            padding: 16px 14px;
        }
        .db-node {
            font-size: 13.5px;
            font-weight: 700;
            color: var(--text-main);
            margin-bottom: 16px;
            display: flex;
            align-items: center;
            gap: 8px;
        }
        .db-node span.material-symbols-rounded {
            font-size: 20px;
            color: var(--accent);
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
            background: var(--surface-variant);
            color: var(--primary);
        }
        .table-name-wrapper {
            display: flex;
            align-items: center;
            gap: 8px;
        }
        .table-header-node span.table-icon {
            font-size: 18px;
            color: var(--primary);
        }
        .table-header-node span.caret-icon {
            font-size: 16px;
            color: var(--text-muted);
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
            background: rgba(184, 243, 151, 0.1);
            border: 1px solid var(--border-color);
            text-transform: uppercase;
            letter-spacing: 0.5px;
            display: flex;
            align-items: center;
            gap: 2px;
        }
        .table-header-node:hover .preview-btn {
            opacity: 1;
        }
        .preview-btn:hover {
            transform: scale(1.1);
            background: var(--surface-variant);
        }
        
        .column-list {
            margin-left: 26px;
            max-height: 0;
            overflow: hidden;
            transition: max-height 0.4s cubic-bezier(0.16, 1, 0.3, 1), opacity 0.3s ease;
            opacity: 0;
            padding-left: 10px;
            border-left: 1px dashed var(--border-color);
            margin-top: 4px;
            margin-bottom: 4px;
        }
        .column-list.open {
            max-height: 500px;
            opacity: 1;
        }
        .column-node {
            font-size: 11.5px;
            color: var(--text-muted);
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
            background: var(--surface-variant);
            color: var(--primary);
            padding-left: 12px;
        }
        .column-info {
            display: flex;
            align-items: center;
            gap: 6px;
        }
        .column-node span.material-symbols-rounded {
            font-size: 14px;
            color: var(--text-muted);
        }
        
        .attr-preview-btn {
            opacity: 0;
            font-size: 9px;
            color: var(--accent);
            background: rgba(184, 243, 151, 0.05);
            border: 1px solid var(--border-color);
            padding: 1px 4px;
            border-radius: 4px;
            transition: opacity 0.2s, background 0.2s;
        }
        .column-node:hover .attr-preview-btn {
            opacity: 1;
        }
        .attr-preview-btn:hover {
            background: var(--surface-variant);
            color: var(--accent-hover);
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
            background: var(--card-bg);
            backdrop-filter: blur(16px);
            border-bottom: 1px solid var(--border-color);
            box-shadow: 0 4px 30px rgba(0, 0, 0, 0.05);
            z-index: 10;
        }
        header h1 {
            margin: 0;
            font-size: 20px;
            font-weight: 800;
            letter-spacing: -0.6px;
            background: linear-gradient(135deg, var(--primary), var(--accent));
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            margin-left: 20px;
            transition: margin-left 0.4s cubic-bezier(0.22, 1, 0.36, 1);
        }
        /* Se recorre el título para dejar espacio al botón cuando el sidebar se cierra */
        .sidebar.collapsed + .main-chat-area header h1 {
            margin-left: 64px;
        }
        .badges-wrapper {
            display: flex;
            gap: 12px;
            align-items: center;
        }
        .db-badge {
            background: var(--surface-variant);
            border: 1px solid var(--border-color);
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
            background: var(--surface-variant);
            border: 1px solid var(--border-color);
            color: var(--primary);
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
            background: var(--surface-variant);
            border: 1px solid var(--border-color);
            color: var(--text-main);
        }
        .header-btn:hover {
            background: var(--border-color);
            transform: translateY(-1px);
        }
        .header-btn .material-symbols-rounded {
            font-size: 20px;
        }
        
        .chat-container {
            flex: 1;
            overflow-y: auto;
            padding: 32px 32px 140px 32px; /* Mayor separación inferior para evitar superposiciones con la caja de entrada */
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
            box-shadow: 0 4px 15px rgba(0, 0, 0, 0.05);
        }
        .message.user .bubble {
            background: var(--primary);
            color: var(--bg-color);
            border-bottom-right-radius: 4px;
        }
        body.light-theme .message.user .bubble {
            color: #ffffff;
            background: var(--primary);
        }
        .message.assistant .bubble {
            background: var(--card-bg);
            border: 1px solid var(--border-color);
            color: var(--text-main);
            border-bottom-left-radius: 4px;
        }
        
        /* Rendering de Markdown */
        .bubble p { margin-top: 0; margin-bottom: 12px; }
        .bubble p:last-child { margin-bottom: 0; }
        .bubble ul, .bubble ol { margin: 8px 0; padding-left: 20px; }
        .bubble table { border-collapse: collapse; width: 100%; margin: 12px 0; font-size: 13.5px; }
        .bubble table th, .bubble table td { border: 1px solid var(--border-color); padding: 8px 12px; text-align: left; }
        .bubble table th { background: var(--surface-variant); }
        
        /* Botones de acción del query */
        .query-actions {
            display: flex;
            gap: 10px;
            margin-top: 12px;
        }
        .action-tab-btn {
            background: var(--surface-variant);
            border: 1px solid var(--border-color);
            color: var(--text-main);
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
        .action-tab-btn .material-symbols-rounded {
            font-size: 18px;
        }
        .action-tab-btn:hover {
            background: var(--border-color);
            transform: translateY(-1px);
        }
        .action-tab-btn.active {
            background: var(--primary);
            color: var(--bg-color);
            border-color: var(--primary);
        }
        body.light-theme .action-tab-btn.active {
            color: #fff;
        }
        
        /* Panel del Query y la Tabla de Datos */
        .query-container {
            margin-top: 10px;
            background: var(--card-bg);
            border: 1px solid var(--border-color);
            border-radius: 14px;
            overflow: hidden;
            box-shadow: 0 6px 20px rgba(0, 0, 0, 0.1);
            display: block;
            max-height: 0;
            opacity: 0;
            transition: max-height 0.4s cubic-bezier(0.16, 1, 0.3, 1), opacity 0.35s ease, margin-top 0.4s ease;
        }
        .query-container.open {
            max-height: 580px;
            opacity: 1;
            margin-top: 10px;
        }
        .query-body {
            padding: 14px 18px;
            background: var(--surface-variant);
        }
        .query-body pre {
            margin: 0;
            font-family: 'Courier New', Courier, monospace;
            font-size: 13.5px;
            color: var(--primary);
            overflow-x: auto;
            white-space: pre-wrap;
            line-height: 1.5;
        }
        
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
            background: var(--surface-variant);
            color: var(--primary);
            padding: 10px 12px;
            font-weight: 700;
            border-bottom: 1px solid var(--border-color);
            position: sticky;
            top: 0;
        }
        table.db-data-table td {
            padding: 8px 12px;
            border-bottom: 1px solid var(--border-color);
            color: var(--text-main);
        }
        table.db-data-table tr:hover {
            background: rgba(255, 255, 255, 0.02);
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
            background: var(--card-bg);
            backdrop-filter: blur(24px);
            border: 1px solid var(--border-color);
            border-radius: 24px;
            padding: 8px 12px;
            box-shadow: 0 10px 30px rgba(0, 0, 0, 0.1), 0 0 15px rgba(103, 80, 164, 0.05);
            display: flex;
            gap: 12px;
            align-items: center;
            transition: all 0.35s cubic-bezier(0.4, 0, 0.2, 1);
        }
        .input-wrapper:focus-within {
            border-color: var(--primary);
            box-shadow: 0 12px 35px rgba(0, 0, 0, 0.2), 0 0 25px rgba(103, 80, 164, 0.15);
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
            background: var(--primary);
            color: var(--bg-color);
            border: none;
            border-radius: 18px;
            width: 48px;
            height: 48px;
            display: flex;
            justify-content: center;
            align-items: center;
            cursor: pointer;
            transition: all 0.3s cubic-bezier(0.175, 0.885, 0.32, 1.275);
            box-shadow: 0 6px 15px rgba(103, 80, 164, 0.2);
            flex-shrink: 0;
        }
        body.light-theme .send-btn {
            color: #fff;
        }
        .send-btn:hover {
            transform: scale(1.08) rotate(5deg);
            box-shadow: 0 8px 22px rgba(103, 80, 164, 0.35);
            background: var(--primary-hover);
        }
        .send-btn:active {
            transform: scale(0.95);
        }
        .send-btn span.material-symbols-rounded {
            font-size: 24px;
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
            background: var(--primary);
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
            <!-- Botón Retráctil Integrado al Sidebar que sobresale en su parte derecha -->
            <button onclick="toggleSidebar()" class="sidebar-toggle-btn is-open" id="sidebar-toggle" title="Mostrar/Ocultar SQL Manager">
                <span class="material-symbols-rounded db-toggle-icon">database</span>
            </button>
            
            <!-- Cabecera del Panel Izquierdo con Usuario de Conexión -->
            <div style="padding: 20px 20px 18px 20px; display: flex; align-items: center; justify-content: space-between; border-bottom: 1px solid var(--border-color); background: rgba(0,0,0,0.05); padding-right: 76px; min-height: 48px; box-sizing: border-box;">
                <div style="display: flex; align-items: center; gap: 8px; color: var(--primary);">
                    <span class="material-symbols-rounded" style="font-size: 24px; color: var(--primary);">account_circle</span>
                    <div style="display: flex; flex-direction: column; gap: 2px;">
                        <span style="font-size: 9px; font-weight: 700; text-transform: uppercase; color: var(--text-muted); letter-spacing: 0.5px; line-height: 1;">Usuario SQL</span>
                        <span style="font-size: 14px; font-weight: 800; color: var(--accent); letter-spacing: 0.2px; line-height: 1.2;">{{ db_user }}</span>
                    </div>
                </div>
            </div>
            
            <div class="sidebar-scroll-panel">
                <div class="db-tree-container">
                    <!-- Nodo Raíz: Base de datos -->
                    <div class="db-node">
                        <span class="material-symbols-rounded">database</span>
                        Database: <span style="color: var(--accent); font-weight: bold;">{{ db_name }}</span>
                    </div>
                    
                    <!-- Hijos: Tablas -->
                    {% for table, cols in schema_dict.items() %}
                    <div class="table-node">
                        <div class="table-header-node" onclick="toggleTableNode(this)">
                            <div class="table-name-wrapper">
                                <span class="material-symbols-rounded caret-icon">chevron_right</span>
                                <span class="material-symbols-rounded table-icon">table_chart</span>
                                <strong>{{ table }}</strong>
                            </div>
                            <button class="preview-btn" onclick="previewTable(event, '{{ table }}')" title="Consultar 5 filas rápidas">
                                <span class="material-symbols-rounded" style="font-size: 14px;">visibility</span> Vista
                            </button>
                        </div>
                        <div class="column-list">
                            {% for col in cols %}
                            <div class="column-node" onclick="insertColumn('{{ table }}', '{{ col.name }}')">
                                <div class="column-info">
                                    <span class="material-symbols-rounded">key</span>
                                    <span>{{ col.name }}</span> <span style="color: var(--text-muted); font-size: 10px;">({{ col.type }})</span>
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
                    <h1>MCP Relational AI</h1>
                    <div class="badges-wrapper">
                        <div class="db-badge">
                            <span class="material-symbols-rounded" style="font-size: 14px;">database</span> {{ db_type.upper() }} ({{ db_name }})
                        </div>
                        <div class="model-badge" id="active-model-badge">
                            <span class="material-symbols-rounded" style="font-size: 14px;">psychology</span> {{ model_name }}
                        </div>
                    </div>
                </div>
                <div class="actions-wrapper">
                    <!-- Botón de Tema M3 -->
                    <button class="header-btn" onclick="toggleTheme()" title="Cambiar Tema (Claro/Oscuro)">
                        <span class="material-symbols-rounded" id="theme-icon">light_mode</span>
                    </button>
                    <a href="/" class="header-btn" title="Modificar Conexión">
                        <span class="material-symbols-rounded">settings</span>
                    </a>
                    <a href="/disconnect" class="header-btn" title="Desconectar / Salir" style="color: #ff4d4d; border-color: rgba(255, 77, 77, 0.2);">
                        <span class="material-symbols-rounded">logout</span>
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
                        <span class="material-symbols-rounded">send</span>
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

        // Cambiar entre tema claro y oscuro
        function toggleTheme() {
            const body = document.body;
            const icon = document.getElementById("theme-icon");
            if (body.classList.contains("light-theme")) {
                body.classList.remove("light-theme");
                icon.innerText = "light_mode";
                localStorage.setItem("m3-theme", "dark");
            } else {
                body.classList.add("light-theme");
                icon.innerText = "dark_mode";
                localStorage.setItem("m3-theme", "light");
            }
        }

        // Control del Panel del Árbol SQL
        function toggleTableNode(nodeEl) {
            const list = nodeEl.nextElementSibling;
            const caret = nodeEl.querySelector('.caret-icon');
            
            list.classList.toggle('open');
            if (list.classList.contains('open')) {
                caret.style.transform = 'rotate(90deg)';
                caret.style.color = 'var(--primary)';
            } else {
                caret.style.transform = 'rotate(0deg)';
                caret.style.color = 'var(--text-muted)';
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
            
            // Colores adaptados del tema activo
            const isLightTheme = document.body.classList.contains("light-theme");
            const strokeColor = isLightTheme ? '#6750A4' : '#D0BCFF';
            const accentColor = isLightTheme ? '#386a20' : '#b8f397';
            const gridColor = isLightTheme ? 'rgba(0,0,0,0.05)' : 'rgba(255,255,255,0.05)';
            const textColor = isLightTheme ? '#1c1b1f' : '#E6E1E5';
            
            const gradient = ctx.createLinearGradient(0, 0, 0, 300);
            gradient.addColorStop(0, isLightTheme ? 'rgba(103, 80, 164, 0.4)' : 'rgba(208, 188, 255, 0.4)');
            gradient.addColorStop(0.5, isLightTheme ? 'rgba(103, 80, 164, 0.15)' : 'rgba(208, 188, 255, 0.15)');
            gradient.addColorStop(1, 'rgba(0, 0, 0, 0.0)');
            
            if (canvas.chartInstance) {
                canvas.chartInstance.destroy();
            }
            
            canvas.chartInstance = new Chart(ctx, {
                type: 'line',
                data: {
                    labels: labels,
                    datasets: [{
                        label: valueKey,
                        data: dataPoints,
                        borderColor: strokeColor,
                        backgroundColor: gradient,
                        borderWidth: 3,
                        fill: true,
                        tension: 0.35,
                        pointBackgroundColor: accentColor,
                        pointBorderColor: isLightTheme ? '#ffffff' : '#141218',
                        pointBorderWidth: 2,
                        pointRadius: 5,
                        pointHoverRadius: 8
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    animation: {
                        duration: 400,
                        easing: 'easeOutCubic'
                    },
                    transitions: {
                        zoom: {
                            animation: {
                                duration: 500,
                                easing: 'easeOutCubic'
                            }
                        }
                    },
                    plugins: {
                        legend: {
                            display: true,
                            labels: { color: textColor, font: { family: 'Plus Jakarta Sans', weight: '600' } }
                        },
                        zoom: {
                            zoom: {
                                drag: {
                                    enabled: true,
                                    backgroundColor: isLightTheme ? 'rgba(103, 80, 164, 0.12)' : 'rgba(208, 188, 255, 0.12)',
                                    borderColor: isLightTheme ? 'rgba(103, 80, 164, 0.5)' : 'rgba(208, 188, 255, 0.5)',
                                    borderWidth: 1
                                },
                                mode: 'xy'
                            }
                        }
                    },
                    scales: {
                        x: {
                            grid: { color: gridColor },
                            ticks: { color: textColor, font: { family: 'Plus Jakarta Sans' } }
                        },
                        y: {
                            grid: { color: gridColor },
                            ticks: { color: textColor, font: { family: 'Plus Jakarta Sans' } }
                        }
                    }
                }
            });
            
            // Doble clic para resetear zoom con animación suave
            canvas.addEventListener('dblclick', () => {
                if (canvas.chartInstance) {
                    canvas.chartInstance.resetZoom('default');
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
            if (!dataList || dataList.length === 0) return "<p style='padding:12px;color:var(--text-muted);margin:0;'>La consulta no retornó datos o está vacía.</p>";
            
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
                        cellVal = `<img src="${cellVal}" style="max-height: 48px; border-radius: 6px; box-shadow: 0 2px 8px rgba(0,0,0,0.15);" alt="Image" onerror="this.outerHTML='<span style=\\'color:gray;\\'>[Imagen no renderizable]</span>'" />`;
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
                
                if (userExplicitlyRequestedChart) {
                    chartButton = `
                    <button class="action-tab-btn active" onclick="toggleViewContainer(this, 'chart-panel')">
                        <span class="material-symbols-rounded">insert_chart</span> Ver Gráfico
                    </button>`;
                    
                    chartPanelHtml = `
                    <div class="query-container chart-panel open" style="max-height: 580px; opacity: 1; margin-top: 10px;">
                        <div class="query-body" style="padding:0; position:relative; min-height: 380px;">
                            <div style="padding: 10px 16px; display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid var(--border-color); background: var(--surface-variant);">
                                <label style="margin:0; font-size:12px; text-transform:none; font-weight:700; color:var(--accent);">📊 Visualización Gráfica M3</label>
                                <div style="display: flex; gap: 8px; align-items: center;">
                                    <label style="margin:0; font-size:11px; text-transform:none; font-weight:bold; color:var(--text-muted);">Tipo:</label>
                                    <select onchange="updateChartType(this)" style="padding: 4px 8px; font-size: 11px; width: auto; height: auto; border-radius: 6px; background:var(--card-bg); border:1px solid var(--border-color); color:var(--text-main); outline:none; cursor:pointer;">
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
                            <div style="padding: 6px 16px 10px; display: flex; align-items: center; gap: 6px; color: var(--text-muted); font-size: 10px; border-top: 1px solid var(--border-color);">
                                <span class="material-symbols-rounded" style="font-size: 14px;">zoom_in</span>
                                Arrastra una región para hacer zoom · Doble clic para regresar
                            </div>
                        </div>
                    </div>`;
                }

                bubbleHtml += `
                <div class="query-actions">
                    <button class="action-tab-btn" onclick="toggleViewContainer(this, 'query-panel')">
                        <span class="material-symbols-rounded">code</span> Ver SQL
                    </button>
                    <button class="action-tab-btn ${userExplicitlyRequestedChart ? '' : 'active'}" onclick="toggleViewContainer(this, 'table-panel')">
                        <span class="material-symbols-rounded">table_chart</span> Ver Tabla
                    </button>
                    ${chartButton}
                    <button class="action-tab-btn" onclick="exportToCSV(this)" style="color: var(--accent); border-color: var(--border-color);">
                        <span class="material-symbols-rounded">download</span> Excel
                    </button>
                </div>
                
                <div class="query-container query-panel">
                    <div class="query-body">
                        <pre><code>${query}</code></pre>
                    </div>
                </div>
                
                <div class="query-container table-panel ${userExplicitlyRequestedChart ? '' : 'open'}" style="${userExplicitlyRequestedChart ? '' : 'max-height: 450px; opacity: 1;'}">
                    <div class="query-body" style="padding:0;">
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

        // Controlar la visualización mutua de los paneles
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
                if (!b.innerText.includes("Excel")) {
                    b.classList.remove('active');
                }
            });
            
            if (!isTargetOpen) {
                targetPanel.classList.add('open');
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
                        activeModelBadge.innerHTML = `<span class="material-symbols-rounded" style="font-size: 14px;">psychology</span> ` + data.model_used;
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

        // Cargar el tema al inicializar
        document.addEventListener("DOMContentLoaded", () => {
            const savedTheme = localStorage.getItem("m3-theme");
            if (savedTheme === "light") {
                document.body.classList.add("light-theme");
                document.getElementById("theme-icon").innerText = "dark_mode";
            }
        });
    </script>
</body>
</html>
"""

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5050, debug=True)
