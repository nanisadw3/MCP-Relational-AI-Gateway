import asyncio
import httpx
import json
import signal
import sys
from termcolor import colored
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

import os

API_KEY = os.environ.get("GEMINI_API_KEY", "")
if not API_KEY:
    try:
        API_KEY = input("Introduce tu Gemini API Key (o presiona Enter si la tienes configurada en la variable GEMINI_API_KEY): ").strip()
    except (KeyboardInterrupt, EOFError):
        print("\nSaliendo...")
        sys.exit(0)

if not API_KEY:
    print(colored("Error: La API Key de Gemini es requerida para el funcionamiento del agente.", "red"))
    sys.exit(1)

GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.1-flash-lite:generateContent?key={API_KEY}"

# Manejador seguro para Ctrl+C (SIGINT)
def signal_handler(sig, frame):
    print("\n" + colored("👋 Saliendo del chat de forma segura. ¡Hasta luego!", "yellow", attrs=["bold"]))
    sys.exit(0)

signal.signal(signal.SIGINT, signal_handler)

async def run_agent():
    print(colored("==========================================================", "cyan"))
    print(colored("🤖 Chat Interactivo de Northwind con Memoria (MCP + Gemini) 🤖", "cyan", attrs=["bold"]))
    print(colored("==========================================================", "cyan"))
    print(colored("Escribe tus preguntas sobre la base de datos (Ctrl+C o 'salir' para terminar)", "white"))
    print(colored("El asistente recordará el contexto de las preguntas anteriores.", "dark_grey"))

    server_params = StdioServerParameters(
        command="./venv/bin/python",
        args=["server.py"]
    )
    
    print("\n" + colored("[Agente]", "blue", attrs=["bold"]) + " Iniciando y conectando con el Servidor MCP local...")
    print(colored(f"   ↳ Lanzando servidor local mediante stdio: python3 server.py", "light_grey"))
    
    try:
        async with stdio_client(server_params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                print(colored(f"   ↳ Sesión MCP establecida e inicializada con éxito.", "light_grey"))
                
                print(colored("[Agente]", "blue", attrs=["bold"]) + " Leyendo el esquema de la base de datos a través de MCP...")
                print(colored(f"   ↳ MCP CLIENT session.read_resource('db://schema')", "light_grey"))
                schema_content = await session.read_resource("db://schema")
                schema_text = schema_content.contents[0].text
                print(colored(f"   ↳ MCP SERVER retornó el esquema de base de datos ({len(schema_text)} bytes)", "light_grey"))
                
                # Inicializar el historial de conversación en el formato de Gemini API
                chat_history = []
                
                # Definimos las herramientas del sistema
                tools_config = [
                    {
                        "functionDeclarations": [
                            {
                                "name": "query_db",
                                "description": "Ejecuta una consulta SQL SELECT en la base de datos de Northwind y devuelve el resultado en JSON.",
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
                
                # Configuración del sistema (esquema y comportamiento del analista)
                system_instruction = {
                    "parts": [
                        {
                            "text": (
                                f"Eres un analista de datos experto. Tienes acceso a una base de datos de Northwind ejecutándose sobre Microsoft SQL Server (T-SQL).\n"
                                f"Aquí tienes el esquema de la base de datos:\n{schema_text}\n\n"
                                f"Instrucciones:\n"
                                f"1. IMPORTANTE: La base de datos es SQL Server. Usa sintaxis T-SQL válida. Por ejemplo, usa 'SELECT TOP N' en lugar de 'LIMIT N', y pon corchetes a tablas con espacios como [Order Details].\n"
                                f"2. Explica brevemente tu pensamiento en español (qué tablas necesitas y por qué) y genera la consulta SQL SELECT adecuada.\n"
                                f"3. Utiliza la herramienta query_db cuando sea necesario para obtener datos reales y responder al usuario.\n"
                                f"4. Sintetiza una respuesta final clara en español basándote en los datos obtenidos."
                            )
                        }
                    ]
                }
                
                print(colored(f"   ↳ Inyectando a Gemini las directivas del sistema (System Instruction) que contienen el esquema obtenido de MCP.", "light_grey"))
                
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
                            
                        # Agregar el mensaje del usuario al historial
                        chat_history.append({
                            "role": "user",
                            "parts": [{"text": user_query}]
                        })
                        
                        payload = {
                            "contents": chat_history,
                            "tools": tools_config,
                            "systemInstruction": system_instruction
                        }
                        
                        print(colored("[Pensamiento de la IA]", "magenta", attrs=["bold"]) + " Analizando la pregunta con memoria histórica...")
                        print(colored(f"   ↳ POST {GEMINI_URL}", "light_grey"))
                        
                        response = await client.post(GEMINI_URL, json=payload, timeout=45.0)
                        
                        if response.status_code != 200:
                            print(colored(f"\n❌ Error del API de Gemini ({response.status_code}):", "red", attrs=["bold"]))
                            print(response.text)
                            chat_history.pop()
                            continue
                        
                        response_data = response.json()
                        candidates = response_data.get("candidates", [])
                        if not candidates:
                            print(colored("\n❌ No se obtuvieron candidatos en la respuesta.", "red"))
                            chat_history.pop()
                            continue
                            
                        candidate = candidates[0]
                        content = candidate.get("content", {})
                        parts = content.get("parts", [])
                        
                        reasoning = ""
                        function_call = None
                        for part in parts:
                            if "text" in part:
                                reasoning += part["text"]
                            if "functionCall" in part:
                                function_call = part["functionCall"]
                        
                        if reasoning:
                            print("\n" + colored("🧠 [Pensamiento de la IA - Estrategia]:", "magenta", attrs=["bold"]))
                            print(colored(reasoning.strip(), "cyan"))
                            
                        if function_call:
                            tool_name = function_call["name"]
                            tool_args = function_call["args"]
                            sql_query = tool_args.get("sql")
                            
                            print("\n" + colored("⚙️ [La IA decidió ejecutar una herramienta MCP]:", "yellow", attrs=["bold"]) + f" '{tool_name}'")
                            print(colored("📜 [Query SQL Generado]:", "green", attrs=["bold"]) + f" {sql_query}")
                            
                            # Ejecutar en el servidor local MCP
                            print(colored("🔌 [MCP]", "blue", attrs=["bold"]) + " Ejecutando consulta en SQL Server...")
                            print(colored(f"   ↳ MCP CLIENT session.call_tool('{tool_name}', args={{'sql': '{sql_query}'}})", "light_grey"))
                            
                            try:
                                mcp_result = await session.call_tool(tool_name, arguments={"sql": sql_query})
                                result_text = mcp_result.content[0].text
                                print(colored(f"   ↳ MCP SERVER respondió con éxito ({len(result_text)} bytes en JSON)", "light_grey"))
                            except Exception as db_err:
                                result_text = f"Error al ejecutar SQL en la base de datos: {db_err}"
                                print(colored(f"⚠️ [Error del Servidor MCP/BD]: {db_err}", "yellow"))
                            
                            # Agregamos la llamada del modelo y el resultado de la función al historial
                            chat_history.append(content)
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
                            
                            # Volvemos a consultar a Gemini para que genere la respuesta final con los datos
                            payload = {
                                "contents": chat_history,
                                "tools": tools_config,
                                "systemInstruction": system_instruction
                            }
                            
                            print(colored("[Agente]", "blue", attrs=["bold"]) + " Solicitando a Gemini que sintetice la respuesta final...")
                            print(colored(f"   ↳ POST {GEMINI_URL} (con los datos agregados al historial)", "light_grey"))
                            final_response = await client.post(GEMINI_URL, json=payload, timeout=45.0)
                            
                            if final_response.status_code != 200:
                                print(colored(f"❌ Error en respuesta final ({final_response.status_code})", "red"))
                                continue
                                
                            final_data = final_response.json()
                            final_candidates = final_data.get("candidates", [])
                            if not final_candidates:
                                print(colored("❌ No se obtuvo respuesta final.", "red"))
                                continue
                                
                            final_content = final_candidates[0]["content"]
                            final_text = final_content["parts"][0]["text"]
                            
                            print("\n" + colored("🤖 [Respuesta Final]:", "cyan", attrs=["bold"]))
                            print(final_text)
                            
                            # Guardamos la respuesta final en el historial
                            chat_history.append(final_content)
                        else:
                            # Si no se necesitó llamada a base de datos
                            print(colored("   ↳ Gemini decidió responder directamente SIN usar herramientas (no se llamó a query_db ni hubo llamadas MCP).", "light_grey"))
                            chat_history.append(content)
                            if not reasoning:
                                print("\n🤖 [Respuesta vacía o formato inesperado de la IA]")
                            
    except Exception as e:
        print(colored(f"\n❌ Ocurrió un error inesperado durante la ejecución: {e}", "red", attrs=["bold"]))

if __name__ == "__main__":
    try:
        asyncio.run(run_agent())
    except KeyboardInterrupt:
        print("\n" + colored("👋 Saliendo del chat de forma segura. ¡Hasta luego!", "yellow", attrs=["bold"]))
