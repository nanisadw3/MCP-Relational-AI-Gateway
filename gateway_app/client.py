import asyncio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def run_client():
    server_params = StdioServerParameters(
        command="./venv/bin/python", args=["server.py"]
    )

    print("Starting MCP Server and establishing session...")
    async with stdio_client(server_params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            print("Session initialized successfully!\n")

            # 1. Leer el recurso del esquema (ahora leyendo desde 'master')
            print("--- Checking Available Resources ---")
            resources = await session.list_resources()
            for r in resources.resources:
                print(f"Resource URI: {r.uri} - Name: {r.name}")

            print("\nReading schema resource 'db://schema'...")
            schema_content = await session.read_resource("db://schema")
            print("Schema returned from server:")
            # Nueva línea (imprime todo el esquema completo):
            print(schema_content.contents[0].text)

            # 2. Listar y llamar a la herramienta query_db
            print("--- Checking Available Tools ---")
            tools = await session.list_tools()
            for t in tools.tools:
                print(f"Tool Name: {t.name} - Description: {t.description}")

            print("\nCalling tool 'query_db' to get top 3 customers...")
            query = "SELECT TOP 3 CustomerID, CompanyName, ContactName FROM Customers"
            result = await session.call_tool("query_db", arguments={"sql": query})

            print("Result from tool:")
            print(result.content[0].text)


if __name__ == "__main__":
    asyncio.run(run_client())
