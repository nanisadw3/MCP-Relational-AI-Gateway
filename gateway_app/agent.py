import asyncio
import httpx
import json
import signal
import sys
import os
from termcolor import colored
from rich.console import Console
from rich.markdown import Markdown
from rich.table import Table
from rich.panel import Panel
from rich.syntax import Syntax
from rich.rule import Rule
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

# Instancia global para renderizar en terminal
console = Console()

# Selector de proveedores y claves API
print(colored("==========================================================", "cyan"))
print(
    colored(
        "🤖 Selector de Proveedor de Inteligencia Artificial 🤖", "cyan", attrs=["bold"]
    )
)
print(colored("==========================================================", "cyan"))
print("1) Google Gemini (Predeterminado)")
print("2) Anthropic Claude")
print("3) OpenAI GPT")

try:
    choice = input(
        colored("\nSelecciona una opción (1-3): ", "green", attrs=["bold"])
    ).strip()
except (KeyboardInterrupt, EOFError):
    print("\nSaliendo...")
    sys.exit(0)

if choice == "2":
    PROVIDER = "anthropic"
    API_KEY_ENV = "ANTHROPIC_API_KEY"
    DEFAULT_MODELS = [
        "claude-3-5-haiku-latest",
        "claude-3-5-sonnet-latest",
        "claude-3-opus-latest",
    ]
    PROVIDER_NAME = "Anthropic Claude"
elif choice == "3":
    PROVIDER = "openai"
    API_KEY_ENV = "OPENAI_API_KEY"
    DEFAULT_MODELS = ["gpt-4o-mini", "gpt-4o"]
    PROVIDER_NAME = "OpenAI GPT"
else:
    PROVIDER = "google"
    API_KEY_ENV = "GEMINI_API_KEY"
    DEFAULT_MODELS = [
        "gemini-3.1-flash-lite",
        "gemini-2.0-flash-lite",
        "gemini-2.0-flash",
        "gemini-3.5-flash",
    ]
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
    model_choice = input(
        colored(
            "Selecciona modelo (0 o Enter para automático): ", "green", attrs=["bold"]
        )
    ).strip()
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
    print(
        "\n"
        + colored(
            "👋 Saliendo del chat de forma segura. ¡Hasta luego!",
            "yellow",
            attrs=["bold"],
        )
    )
    sys.exit(0)


signal.signal(signal.SIGINT, signal_handler)

# --- Funciones para llamar a las APIs (Con Extracción de Tokens) ---


async def call_google(client, model, api_key, system_prompt, history, tools):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"

    gemini_tools = [{"functionDeclarations": [t for t in tools]}] if tools else []

    gemini_history = []
    for h in history:
        if h["role"] in ["user", "model", "function"]:
            gemini_history.append(h)

    payload = {
        "contents": gemini_history,
        "tools": gemini_tools,
        "systemInstruction": {"parts": [{"text": system_prompt}]},
    }

    response = await client.post(url, json=payload, timeout=45.0)
    if response.status_code != 200:
        raise httpx.HTTPStatusError(
            f"Error {response.status_code}: {response.text}",
            request=response.request,
            response=response,
        )

    res_data = response.json()
    meta = res_data.get("usageMetadata", {})
    usage = {
        "input": meta.get("promptTokenCount", 0),
        "output": meta.get("candidatesTokenCount", 0),
        "total": meta.get("totalTokenCount", 0),
    }

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

    return text_content, function_call, content, usage


async def call_openai(client, model, api_key, system_prompt, history, tools):
    url = "https://api.openai.com/v1/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    openai_tools = []
    for t in tools:
        openai_tools.append(
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t["description"],
                    "parameters": t["parameters"],
                },
            }
        )

    messages = [{"role": "system", "content": system_prompt}]
    for msg in history:
        if msg["role"] == "user":
            messages.append({"role": "user", "content": msg["parts"][0]["text"]})
        elif msg["role"] == "model":
            parts = msg["parts"]
            content_text = ""
            tool_calls = []
            for p in parts:
                if "text" in p:
                    content_text = p["text"]
                if "functionCall" in p:
                    fc = p["functionCall"]
                    tool_calls.append(
                        {
                            "id": "call_" + fc["name"],
                            "type": "function",
                            "function": {
                                "name": fc["name"],
                                "arguments": json.dumps(fc["args"]),
                            },
                        }
                    )
            msg_obj = {"role": "assistant"}
            if content_text:
                msg_obj["content"] = content_text
            if tool_calls:
                msg_obj["tool_calls"] = tool_calls
            messages.append(msg_obj)
        elif msg["role"] == "function":
            resp = msg["parts"][0]["functionResponse"]
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": "call_" + resp["name"],
                    "content": resp["response"]["result"],
                }
            )

    payload = {
        "model": model,
        "messages": messages,
    }
    if openai_tools:
        payload["tools"] = openai_tools

    response = await client.post(url, headers=headers, json=payload, timeout=45.0)
    if response.status_code != 200:
        raise httpx.HTTPStatusError(
            f"Error {response.status_code}: {response.text}",
            request=response.request,
            response=response,
        )

    res_data = response.json()
    meta = res_data.get("usage", {})
    usage = {
        "input": meta.get("prompt_tokens", 0),
        "output": meta.get("completion_tokens", 0),
        "total": meta.get("total_tokens", 0),
    }

    choice_msg = res_data["choices"][0]["message"]
    text_content = choice_msg.get("content") or ""

    function_call = None
    if choice_msg.get("tool_calls"):
        tc = choice_msg["tool_calls"][0]
        function_call = {
            "name": tc["function"]["name"],
            "args": json.loads(tc["function"]["arguments"]),
        }

    raw_history_obj = {"role": "model", "parts": []}
    if text_content:
        raw_history_obj["parts"].append({"text": text_content})
    if function_call:
        raw_history_obj["parts"].append(
            {
                "functionCall": {
                    "name": function_call["name"],
                    "args": function_call["args"],
                }
            }
        )

    return text_content, function_call, raw_history_obj, usage


async def call_anthropic(client, model, api_key, system_prompt, history, tools):
    url = "https://api.anthropic.com/v1/messages"
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }

    anthropic_tools = []
    for t in tools:
        anthropic_tools.append(
            {
                "name": t["name"],
                "description": t["description"],
                "input_schema": t["parameters"],
            }
        )

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
                    content_blocks.append(
                        {
                            "type": "tool_use",
                            "id": "call_" + fc["name"],
                            "name": fc["name"],
                            "input": fc["args"],
                        }
                    )
            messages.append({"role": "assistant", "content": content_blocks})
        elif msg["role"] == "function":
            resp = msg["parts"][0]["functionResponse"]
            messages.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "call_" + resp["name"],
                            "content": resp["response"]["result"],
                        }
                    ],
                }
            )

    payload = {
        "model": model,
        "system": system_prompt,
        "messages": messages,
        "max_tokens": 4000,
    }
    if anthropic_tools:
        payload["tools"] = anthropic_tools

    response = await client.post(url, headers=headers, json=payload, timeout=45.0)
    if response.status_code != 200:
        raise httpx.HTTPStatusError(
            f"Error {response.status_code}: {response.text}",
            request=response.request,
            response=response,
        )

    res_data = response.json()
    meta = res_data.get("usage", {})
    in_tok = meta.get("input_tokens", 0)
    out_tok = meta.get("output_tokens", 0)
    usage = {"input": in_tok, "output": out_tok, "total": in_tok + out_tok}

    content_blocks = res_data["content"]
    text_content = ""
    function_call = None

    for block in content_blocks:
        if block["type"] == "text":
            text_content += block["text"]
        elif block["type"] == "tool_use":
            function_call = {"name": block["name"], "args": block["input"]}

    raw_history_obj = {"role": "model", "parts": []}
    if text_content:
        raw_history_obj["parts"].append({"text": text_content})
    if function_call:
        raw_history_obj["parts"].append(
            {
                "functionCall": {
                    "name": function_call["name"],
                    "args": function_call["args"],
                }
            }
        )

    return text_content, function_call, raw_history_obj, usage


# --- Loop Principal del Agente ---


async def run_agent():
    print(colored("==========================================================", "cyan"))
    print(
        colored(
            f"🤖 Chat de Base de Datos Interactivo ({PROVIDER_NAME}) 🤖",
            "cyan",
            attrs=["bold"],
        )
    )
    print(colored("==========================================================", "cyan"))
    print(
        colored(
            "Escribe tus preguntas sobre la base de datos (Ctrl+C o 'salir' para terminar)",
            "white",
        )
    )
    print(
        colored(
            "El asistente recordará el contexto de las preguntas anteriores.",
            "dark_grey",
        )
    )

    server_params = StdioServerParameters(
        command="./venv/bin/python", args=["server.py"]
    )

    print(
        "\n"
        + colored("[Agente]", "blue", attrs=["bold"])
        + " Iniciando y conectando con el Servidor MCP local..."
    )

    try:
        async with stdio_client(server_params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                print(
                    colored(
                        f"   ↳ Sesión MCP establecida e inicializada con éxito.",
                        "light_grey",
                    )
                )

                # ==========================================================
                # --- ESQUEMA EN TABLA FORMAL ---
                # ==========================================================
                schema_content = await session.read_resource("db://schema")
                schema_text = schema_content.contents[0].text

                try:
                    schema_json = json.loads(schema_text)
                    table_ui = Table(
                        title=f"\n🔍 [bold yellow]MCP Discovery — Esquema SQL ({len(schema_json)} Tablas)[/bold yellow]",
                        show_lines=True,
                    )
                    table_ui.add_column("Tabla SQL", style="cyan bold", no_wrap=True)
                    table_ui.add_column("Cols", style="magenta", justify="center")
                    table_ui.add_column(
                        "Esquema de Columnas y Tipos de Datos", style="white"
                    )

                    for table_name, columns in schema_json.items():
                        table_ui.add_row(
                            f"\\[{table_name}]", str(len(columns)), ", ".join(columns)
                        )

                    console.print(table_ui)
                except Exception:
                    print(colored("   ↳ Esquema crudo recibido:", "green"))
                    print(schema_text)

                print(
                    colored(
                        "   ↳ Herramienta MCP registrada: 'query_db' (T-SQL en SQL Server)",
                        "cyan",
                    )
                )
                print(
                    colored(
                        "   ↳ Inyectando esquema completo al System Prompt...\n",
                        "dark_grey",
                    )
                )

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
                                    "description": "La consulta SQL SELECT válida a ejecutar.",
                                }
                            },
                            "required": ["sql"],
                        },
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
                            user_query = input(
                                colored("\nPregunta ❯ ", "green", attrs=["bold"])
                            )
                        except EOFError:
                            break

                        clean_query = user_query.strip().lower()
                        if clean_query in ["salir", "exit", "quit"]:
                            print(
                                colored(
                                    "👋 Saliendo del chat de forma segura. ¡Hasta luego!",
                                    "yellow",
                                    attrs=["bold"],
                                )
                            )
                            break

                        if not user_query.strip():
                            continue

                        chat_history.append(
                            {"role": "user", "parts": [{"text": user_query}]}
                        )

                        console.print(
                            f"\n[bold magenta]🧠 Analizando pregunta con memoria histórica...[/bold magenta]"
                        )

                        # ==========================================================
                        # --- BUCLE DE EJECUCIÓN MULTI-STEP (TOOL LOOP) ---
                        # ==========================================================
                        while True:
                            response_data = None
                            successful_model = None
                            errors = []

                            for model in MODELS_TO_TRY:
                                try:
                                    if PROVIDER == "google":
                                        (
                                            text_content,
                                            function_call,
                                            raw_history_obj,
                                            usage,
                                        ) = await call_google(
                                            client,
                                            model,
                                            API_KEY,
                                            system_instruction,
                                            chat_history,
                                            tools_config,
                                        )
                                    elif PROVIDER == "openai":
                                        (
                                            text_content,
                                            function_call,
                                            raw_history_obj,
                                            usage,
                                        ) = await call_openai(
                                            client,
                                            model,
                                            API_KEY,
                                            system_instruction,
                                            chat_history,
                                            tools_config,
                                        )
                                    elif PROVIDER == "anthropic":
                                        (
                                            text_content,
                                            function_call,
                                            raw_history_obj,
                                            usage,
                                        ) = await call_anthropic(
                                            client,
                                            model,
                                            API_KEY,
                                            system_instruction,
                                            chat_history,
                                            tools_config,
                                        )

                                    response_data = (
                                        text_content,
                                        function_call,
                                        raw_history_obj,
                                        usage,
                                    )
                                    successful_model = model
                                    break
                                except Exception as e:
                                    errors.append(f"{model} falló: {str(e)}")

                            if not response_data:
                                print(
                                    colored(
                                        "\n❌ Todos los modelos seleccionados fallaron:",
                                        "red",
                                    )
                                )
                                for err in errors:
                                    print(f"   - {err}")
                                chat_history.pop()
                                break

                            text_content, function_call, raw_history_obj, usage = (
                                response_data
                            )

                            # Etiqueta visual de tokens para la barra divisoria
                            token_badge = f"[yellow]Tokens: In {usage['input']} | Out {usage['output']} | Total {usage['total']}[/yellow]"

                            # 1. SI LA IA DECIDE EJECUTAR UNA HERRAMIENTA MCP
                            if function_call:
                                tool_name = function_call["name"]
                                sql_query = function_call["args"].get("sql", "")

                                # Si el modelo razonó en texto antes de disparar la herramienta
                                if text_content and text_content.strip():
                                    console.print(
                                        f"[cyan]{text_content.strip()}[/cyan]\n"
                                    )

                                # --- RENDERIZADO VISUAL PROFESIONAL DE HERRAMIENTA ---
                                console.print(
                                    Rule(
                                        f"⚙️  [bold yellow]EJECUCIÓN DE HERRAMIENTA MCP[/bold yellow] • {token_badge}",
                                        style="yellow",
                                    )
                                )
                                console.print(
                                    f"  [bold white]🛠️  Herramienta :[/bold white] [cyan]{tool_name}[/cyan]"
                                )
                                console.print(
                                    f"  [bold white]🔌  Estado      :[/bold white] [blue]Ejecutando en Microsoft SQL Server...[/blue]"
                                )

                                try:
                                    mcp_result = await session.call_tool(
                                        tool_name, arguments={"sql": sql_query}
                                    )
                                    result_text = mcp_result.content[0].text
                                    console.print(
                                        f"  [bold white]📦  Respuesta   :[/bold white] [green]{len(result_text)} bytes recibidos en JSON[/green]\n"
                                    )
                                except Exception as db_err:
                                    result_text = f"Error al ejecutar SQL en la base de datos: {db_err}"
                                    console.print(
                                        f"  [bold red]⚠️  Error BD   :[/bold red] [red]{db_err}[/red]\n"
                                    )

                                # Dibujamos el SQL con resaltado de sintaxis T-SQL dentro de un Panel elegante
                                sql_ui = Syntax(
                                    sql_query,
                                    "tsql",
                                    theme="monokai",
                                    line_numbers=True,
                                    word_wrap=True,
                                )
                                console.print(
                                    Panel(
                                        sql_ui,
                                        title="[bold green]📜 Query SQL Generado (T-SQL)[/bold green]",
                                        border_style="green",
                                        expand=False,
                                    )
                                )
                                console.print(Rule(style="yellow"))
                                console.print()
                                # -----------------------------------------------------

                                chat_history.append(raw_history_obj)
                                chat_history.append(
                                    {
                                        "role": "function",
                                        "parts": [
                                            {
                                                "functionResponse": {
                                                    "name": tool_name,
                                                    "response": {"result": result_text},
                                                }
                                            }
                                        ],
                                    }
                                )
                                console.print(
                                    "[bold blue]🤖 Analizando resultados de la base de datos...[/bold blue]"
                                )

                            # 2. SI LA IA YA TIENE LOS DATOS Y DA LA RESPUESTA FINAL
                            else:
                                console.print()
                                console.print(
                                    Rule(
                                        f"🤖  [bold cyan]RESPUESTA FINAL ({PROVIDER_NAME})[/bold cyan] • {token_badge}",
                                        style="cyan",
                                    )
                                )
                                console.print()
                                console.print(Markdown(text_content.strip()))
                                console.print()
                                console.print(Rule(style="cyan"))
                                chat_history.append(raw_history_obj)
                                break

    except Exception as e:
        print(
            colored(
                f"\n❌ Ocurrió un error inesperado durante la ejecución: {e}",
                "red",
                attrs=["bold"],
            )
        )


if __name__ == "__main__":
    try:
        asyncio.run(run_agent())
    except KeyboardInterrupt:
        print(
            "\n"
            + colored(
                "👋 Saliendo del chat de forma segura. ¡Hasta luego!",
                "yellow",
                attrs=["bold"],
            )
        )
