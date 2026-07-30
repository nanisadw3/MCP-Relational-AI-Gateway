import asyncio
import httpx
import json
import signal
import sys
import os
from termcolor import colored
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

# Selector de proveedores y claves API
print(colored("==========================================================", "cyan"))
print(colored("🤖 Selector de Proveedor de Inteligencia Artificial 🤖", "cyan", attrs=["bold"]))
print(colored("==========================================================", "cyan"))
print("1) Google Gemini (Predeterminado)")
print("2) Anthropic Claude")
print("3) OpenAI GPT")

try:
    choice = input(colored("\nSelecciona una opción (1-3): ", "green", attrs=["bold"])).strip()
except (KeyboardInterrupt, EOFError):
    print("\nSaliendo...")
    sys.exit(0)

if choice == "2":
    PROVIDER = "anthropic"
    API_KEY_ENV = "ANTHROPIC_API_KEY"
    DEFAULT_MODELS = ["claude-3-5-haiku-latest", "claude-3-5-sonnet-latest", "claude-3-opus-latest"]
    PROVIDER_NAME = "Anthropic Claude"
elif choice == "3":
    PROVIDER = "openai"
    API_KEY_ENV = "OPENAI_API_KEY"
    DEFAULT_MODELS = ["gpt-4o-mini", "gpt-4o"]
    PROVIDER_NAME = "OpenAI GPT"
else:
    PROVIDER = "google"
    API_KEY_ENV = "GEMINI_API_KEY"
    DEFAULT_MODELS = ["gemini-3.1-flash-lite", "gemini-2.0-flash-lite", "gemini-2.0-flash", "gemini-3.5-flash"]
    PROVIDER_NAME = "Google Gemini"

API_KEY = os.environ.get(API_KEY_ENV, "")
if not API_KEY:
    try:
        API_KEY = input(f"Introduce tu API Key para {PROVIDER_NAME}: ").strip()
    except (KeyboardInterrupt, EOFError):
        print("\nSaliendo...")
        sys.exit(0)

if not API_KEY:
    print(colored(f"Error: La API Key de {PROVIDER_NAME} es requerida.", "red"))
    sys.exit(1)

# Selector de modelo
print(colored(f"\nModelos disponibles para {PROVIDER_NAME}:", "white"))
print("0) Selección Automática (Cascada / Resiliente) - Recomendado")
for idx, model in enumerate(DEFAULT_MODELS, 1):
    print(f"{idx}) {model}")

try:
    model_choice = input(colored("Selecciona modelo (0 o Enter para automático): ", "green", attrs=["bold"])).strip()
except (KeyboardInterrupt, EOFError):
    print("\nSaliendo...")
    sys.exit(0)

if model_choice and model_choice != "0":
    try:
        selected_model_idx = int(model_choice) - 1
        if 0 <= selected_model_idx < len(DEFAULT_MODELS):
            MODELS_TO_TRY = [DEFAULT_MODELS[selected_model_idx]]
        else:
            MODELS_TO_TRY = DEFAULT_MODELS
    except ValueError:
        MODELS_TO_TRY = DEFAULT_MODELS
else:
    MODELS_TO_TRY = DEFAULT_MODELS

# Manejador seguro para Ctrl+C (SIGINT)
def signal_handler(sig, frame):
    print("\n" + colored("👋 Saliendo del chat de forma segura. ¡Hasta luego!", "yellow", attrs=["bold"]))
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)

# --- Funciones para llamar a las APIs de los Proveedores ---

async def call_google(client, model, api_key, system_prompt, history, tools):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    
    # Adaptar herramientas al formato de Gemini
    gemini_tools = [{"functionDeclarations": [t for t in tools]}] if tools else []
    
    # Construir historial para Gemini
    gemini_history = []
    for h in history:
        if h["role"] in ["user", "model", "function"]:
            gemini_history.append(h)
    
    payload = {
        "contents": gemini_history,
        "tools": gemini_tools,
        "systemInstruction": {"parts": [{"text": system_prompt}]}
    }
    
    response = await client.post(url, json=payload, timeout=45.0)
    if response.status_code != 200:
        raise httpx.HTTPStatusError(f"Error {response.status_code}: {response.text}", request=response.request, response=response)
        
    res_data = response.json()
    candidate = res_data.get("candidates", [{}])[0]
    content = candidate.get("content", {})
    parts = content.get("parts", [])
    
    text_content = ""
    function_call = None
    for p in parts:
        if "text" in p:
            text_content += p["text"]
        if "functionCall" in p:
            fc = p["functionCall"]
            function_call = {"name": fc["name"], "args": fc["args"]}
            
    return text_content, function_call, content

async def call_openai(client, model, api_key, system_prompt, history, tools):
    url = "https://api.openai.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    # Formatear herramientas
    openai_tools = []
    for t in tools:
        openai_tools.append({
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t["description"],
                "parameters": t["parameters"]
            }
        })
        
    # Formatear mensajes
    messages = [{"role": "system", "content": system_prompt}]
    for msg in history:
        if msg["role"] == "user":
            messages.append({"role": "user", "content": msg["parts"][0]["text"]})
        elif msg["role"] == "model":
            # Si tiene llamadas de función previas en el historial
            # Para simplificar la compatibilidad del agente CLI, adaptamos
            parts = msg["parts"]
            content_text = ""
            tool_calls = []
            for p in parts:
                if "text" in p:
                    content_text = p["text"]
                if "functionCall" in p:
                    fc = p["functionCall"]
                    # OpenAI necesita un ID de llamada de función ficticio para mantener el orden
                    tool_calls.append({
                        "id": "call_" + fc["name"],
                        "type": "function",
                        "function": {
                            "name": fc["name"],
                            "arguments": json.dumps(fc["args"])
                        }
                    })
            msg_obj = {"role": "assistant"}
            if content_text:
                msg_obj["content"] = content_text
            if tool_calls:
                msg_obj["tool_calls"] = tool_calls
            messages.append(msg_obj)
        elif msg["role"] == "function":
            # Respuesta de la función
            resp = msg["parts"][0]["functionResponse"]
            messages.append({
                "role": "tool",
                "tool_call_id": "call_" + resp["name"],
                "content": resp["response"]["result"]
            })
            
    payload = {
        "model": model,
        "messages": messages,
    }
    if openai_tools:
        payload["tools"] = openai_tools
        
    response = await client.post(url, headers=headers, json=payload, timeout=45.0)
    if response.status_code != 200:
        raise httpx.HTTPStatusError(f"Error {response.status_code}: {response.text}", request=response.request, response=response)
        
    res_data = response.json()
    choice_msg = res_data["choices"][0]["message"]
    text_content = choice_msg.get("content") or ""
    
    function_call = None
    if choice_msg.get("tool_calls"):
        tc = choice_msg["tool_calls"][0]
        function_call = {
            "name": tc["function"]["name"],
            "args": json.loads(tc["function"]["arguments"])
        }
        
    # Reconstruir la estructura compatible de Gemini para guardar en el historial
    raw_history_obj = {"role": "model", "parts": []}
    if text_content:
        raw_history_obj["parts"].append({"text": text_content})
    if function_call:
        raw_history_obj["parts"].append({"functionCall": {"name": function_call["name"], "args": function_call["args"]}})
        
    return text_content, function_call, raw_history_obj

async def call_anthropic(client, model, api_key, system_prompt, history, tools):
    url = "https://api.anthropic.com/v1/messages"
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json"
    }
    
    # Formatear herramientas
    anthropic_tools = []
    for t in tools:
        anthropic_tools.append({
            "name": t["name"],
            "description": t["description"],
            "input_schema": t["parameters"]
        })
        
    # Formatear mensajes
    messages = []
    for msg in history:
        if msg["role"] == "user":
            messages.append({"role": "user", "content": msg["parts"][0]["text"]})
        elif msg["role"] == "model":
            content_blocks = []
            for p in msg["parts"]:
                if "text" in p:
                    content_blocks.append({"type": "text", "text": p["text"]})
                if "functionCall" in p:
                    fc = p["functionCall"]
                    content_blocks.append({
                        "type": "tool_use",
                        "id": "call_" + fc["name"],
                        "name": fc["name"],
                        "input": fc["args"]
                    })
            messages.append({"role": "assistant", "content": content_blocks})
        elif msg["role"] == "function":
            resp = msg["parts"][0]["functionResponse"]
            messages.append({
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "call_" + resp["name"],
                        "content": resp["response"]["result"]
                    }
                ]
            })
            
    payload = {
        "model": model,
        "system": system_prompt,
        "messages": messages,
        "max_tokens": 4000
    }
    if anthropic_tools:
        payload["tools"] = anthropic_tools
        
    response = await client.post(url, headers=headers, json=payload, timeout=45.0)
    if response.status_code != 200:
        raise httpx.HTTPStatusError(f"Error {response.status_code}: {response.text}", request=response.request, response=response)
        
    res_data = response.json()
    content_blocks = res_data["content"]
    
    text_content = ""
    function_call = None
    
    for block in content_blocks:
        if block["type"] == "text":
            text_content += block["text"]
        elif block["type"] == "tool_use":
            function_call = {
                "name": block["name"],
                "args": block["input"]
            }
            
    raw_history_obj = {"role": "model", "parts": []}
    if text_content:
        raw_history_obj["parts"].append({"text": text_content})
    if function_call:
        raw_history_obj["parts"].append({"functionCall": {"name": function_call["name"], "args": function_call["args"]}})
        
    return text_content, function_call, raw_history_obj

# --- Loop Principal del Agente ---

async def run_agent():
    print(colored("==========================================================", "cyan"))
    print(colored(f"🤖 Chat de Base de Datos Interactivo ({PROVIDER_NAME}) 🤖", "cyan", attrs=["bold"]))
    print(colored("==========================================================", "cyan"))
    print(colored("Escribe tus preguntas sobre la base de datos (Ctrl+C o 'salir' para terminar)", "white"))
    print(colored("El asistente recordará el contexto de las preguntas anteriores.", "dark_grey"))

    server_params = StdioServerParameters(
        command="./venv/bin/python",
        args=["server.py"]
    )
    
    print("\n" + colored("[Agente]", "blue", attrs=["bold"]) + " Iniciando y conectando con el Servidor MCP local...")
    
    try:
        async with stdio_client(server_params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                print(colored(f"   ↳ Sesión MCP establecida e inicializada con éxito.", "light_grey"))
                
                schema_content = await session.read_resource("db://schema")
                schema_text = schema_content.contents[0].text
                
                # Inicializar el historial de conversación (con estructura interna de Gemini)
                chat_history = []
                
                tools_config = [
                    {
                        "name": "query_db",
                        "description": "Ejecuta una consulta SQL SELECT en la base de datos de Northwind y devuelve el resultado en JSON.",
                        "parameters": {
                            "type": "object",
                            "properties": {
                                "sql": {
                                    "type": "string",
                                    "description": "La consulta SQL SELECT válida a ejecutar."
                                }
                            },
                            "required": ["sql"]
                        }
                    }
                ]
                
                system_instruction = (
                    "Eres un analista de datos experto. Tienes acceso a una base de datos de Northwind ejecutándose sobre Microsoft SQL Server (T-SQL).\n"
                    f"Aquí tienes el esquema de la base de datos:\n{schema_text}\n\n"
                    "Instrucciones:\n"
                    "1. IMPORTANTE: La base de datos es SQL Server. Usa sintaxis T-SQL válida. Por ejemplo, usa 'SELECT TOP N' en lugar de 'LIMIT N', y pon corchetes a tablas con espacios como [Order Details].\n"
                    "2. Explica brevemente tu pensamiento en español (qué tablas necesitas y por qué) y genera la consulta SQL SELECT adecuada.\n"
                    "3. Utiliza la herramienta query_db cuando sea necesario para obtener datos reales y responder al usuario.\n"
                    "4. Sintetiza una respuesta final clara en español basándote en los datos obtenidos."
                )
                
                async with httpx.AsyncClient() as client:
                    while True:
                        try:
                            user_query = input(colored("\nPregunta ❯ ", "green", attrs=["bold"]))
                        except EOFError:
                            break
                            
                        clean_query = user_query.strip().lower()
                        if clean_query in ["salir", "exit", "quit"]:
                            print(colored("👋 Saliendo del chat de forma segura. ¡Hasta luego!", "yellow", attrs=["bold"]))
                            break
                            
                        if not user_query.strip():
                            continue
                            
                        # Agregar mensaje al historial
                        chat_history.append({
                            "role": "user",
                            "parts": [{"text": user_query}]
                        })
                        
                        print(colored("[Pensamiento de la IA]", "magenta", attrs=["bold"]) + " Analizando la pregunta con memoria histórica...")
                        
                        # Ejecución en cascada / selección de modelo
                        response_data = None
                        successful_model = None
                        errors = []
                        
                        for model in MODELS_TO_TRY:
                            try:
                                print(f"   ↳ Intentando con el modelo: {model}")
                                if PROVIDER == "google":
                                    text_content, function_call, raw_history_obj = await call_google(
                                        client, model, API_KEY, system_instruction, chat_history, tools_config
                                    )
                                elif PROVIDER == "openai":
                                    text_content, function_call, raw_history_obj = await call_openai(
                                        client, model, API_KEY, system_instruction, chat_history, tools_config
                                    )
                                elif PROVIDER == "anthropic":
                                    text_content, function_call, raw_history_obj = await call_anthropic(
                                        client, model, API_KEY, system_instruction, chat_history, tools_config
                                    )
                                    
                                response_data = (text_content, function_call, raw_history_obj)
                                successful_model = model
                                break
                            except Exception as e:
                                errors.append(f"{model} falló: {str(e)}")
                                
                        if not response_data:
                            print(colored("\n❌ Todos los modelos seleccionados fallaron:", "red"))
                            for err in errors:
                                print(f"   - {err}")
                            chat_history.pop()
                            continue
                            
                        text_content, function_call, raw_history_obj = response_data
                        
                        if text_content:
                            print("\n" + colored("🧠 [Pensamiento de la IA - Estrategia]:", "magenta", attrs=["bold"]))
                            print(colored(text_content.strip(), "cyan"))
                            
                        if function_call:
                            tool_name = function_call["name"]
                            sql_query = function_call["args"].get("sql")
                            
                            print("\n" + colored("⚙️ [La IA decidió ejecutar una herramienta MCP]:", "yellow", attrs=["bold"]) + f" '{tool_name}'")
                            print(colored("📜 [Query SQL Generado]:", "green", attrs=["bold"]) + f" {sql_query}")
                            
                            # Ejecutar en el servidor local MCP
                            print(colored("🔌 [MCP]", "blue", attrs=["bold"]) + " Ejecutando consulta en SQL Server...")
                            
                            try:
                                mcp_result = await session.call_tool(tool_name, arguments={"sql": sql_query})
                                result_text = mcp_result.content[0].text
                                print(colored(f"   ↳ MCP SERVER respondió con éxito ({len(result_text)} bytes en JSON)", "light_grey"))
                            except Exception as db_err:
                                result_text = f"Error al ejecutar SQL en la base de datos: {db_err}"
                                print(colored(f"⚠️ [Error del Servidor MCP/BD]: {db_err}", "yellow"))
                                
                            # Agregamos la llamada del modelo y el resultado al historial
                            chat_history.append(raw_history_obj)
                            chat_history.append({
                                "role": "function",
                                "parts": [
                                    {
                                        "functionResponse": {
                                            "name": tool_name,
                                            "response": {
                                                "result": result_text
                                            }
                                        }
                                    }
                                ]
                            })
                            
                            # Segunda llamada para sintetizar respuesta final
                            print(colored("[Agente]", "blue", attrs=["bold"]) + f" Solicitando a {PROVIDER_NAME} que sintetice la respuesta final...")
                            
                            try:
                                if PROVIDER == "google":
                                    final_text, _, final_history_obj = await call_google(
                                        client, successful_model, API_KEY, system_instruction, chat_history, None
                                    )
                                elif PROVIDER == "openai":
                                    final_text, _, final_history_obj = await call_openai(
                                        client, successful_model, API_KEY, system_instruction, chat_history, None
                                    )
                                elif PROVIDER == "anthropic":
                                    final_text, _, final_history_obj = await call_anthropic(
                                        client, successful_model, API_KEY, system_instruction, chat_history, None
                                    )
                                    
                                print("\n" + colored("🤖 [Respuesta Final]:", "cyan", attrs=["bold"]))
                                print(final_text)
                                chat_history.append(final_history_obj)
                            except Exception as e:
                                print(colored(f"❌ Error al sintetizar respuesta final: {e}", "red"))
                        else:
                            chat_history.append(raw_history_obj)
                            
    except Exception as e:
        print(colored(f"\n❌ Ocurrió un error inesperado durante la ejecución: {e}", "red", attrs=["bold"]))

if __name__ == "__main__":
    try:
        asyncio.run(run_agent())
    except KeyboardInterrupt:
        print("\n" + colored("👋 Saliendo del chat de forma segura. ¡Hasta luego!", "yellow", attrs=["bold"]))
