# Northwind MCP Server & Client Project 🚀

Este proyecto es una práctica diseñada para entender a fondo el **Model Context Protocol (MCP)** mediante un agente de terminal escrito en Python que interactúa con la base de datos de ejemplo **Northwind** (corriendo en un contenedor Docker de SQL Server) y el modelo de lenguaje **Gemini 3.1 Flash Lite** de Google.

---

## 🏗️ Arquitectura MCP de este Proyecto

El protocolo MCP permite estructurar la comunicación entre una Inteligencia Artificial y fuentes de datos locales mediante tres componentes principales:

```
                  ┌───────────────────────────────┐
                  │          IA (Gemini)          │
                  │   (API de Google en la nube)   │
                  └──────────────┬▲───────────────┘
                                 ││ HTTP POST (JSON)
                                 ││ (Historial, Herramientas, Razonamiento)
                  ┌──────────────▼┬───────────────┐
                  │    HOST / CLIENTE MCP (Python)│
                  │          (agent.py)           │
                  └──────────────┬▲───────────────┘
                                 ││ stdio (Entrada/Salida Estándar)
                                 ││ JSON-RPC (Handshake, Recursos, Tools)
                  ┌──────────────▼┬───────────────┐
                  │     SERVIDOR MCP (Python)     │
                  │          (server.py)          │
                  └──────────────┬▲───────────────┘
                                 ││ TCP/IP (Librería pymssql)
                  ┌──────────────▼┬───────────────┐
                  │     Base de Datos Northwind   │
                  │   (Docker - SQL Server 2022)  │
                  └───────────────────────────────┘
```

1. **La Base de Datos (Docker)**: Almacena los registros de clientes, pedidos, empleados y productos de la distribuidora de comida gourmet *Northwind Traders*.
2. **El Servidor MCP (`server.py`)**: Es el "puente seguro" y traductor. Se conecta a la base de datos local y expone los datos a través de la interfaz del protocolo MCP como:
   * **Recursos (Resources)**: Datos estáticos de lectura, en este caso el esquema de la base de datos (`db://schema`).
   * **Herramientas (Tools)**: Acciones ejecutables, en este caso una función para correr consultas de lectura en la base de datos (`query_db`).
3. **El Host/Cliente MCP (`agent.py`)**: Es el coordinador y "cerebro" interactivo de terminal. Mantiene la conversación con el usuario, administra la memoria (el historial del chat), y cuando la IA solicita ejecutar una herramienta, el Cliente la ejecuta en el Servidor MCP local y le devuelve la información.

---

## 📁 Descripción de los Archivos del Proyecto

* **[server.py](file:///Users/inakisobera/Documents/MCP/northwind_mcp/server.py)**: Implementa el servidor MCP utilizando el framework de alto nivel `fastmcp`. Define cómo conectarse a SQL Server en Docker, expone el esquema relacional en formato JSON y permite la ejecución segura de sentencias `SELECT`.
* **[agent.py](file:///Users/inakisobera/Documents/MCP/northwind_mcp/agent.py)**: El cliente interactivo de consola. Mantiene un chat infinito (con soporte para salir limpiamente con `Ctrl+C`), maneja el historial acumulativo de mensajes para que la IA tenga memoria, y muestra en **color gris** cada llamada HTTP a Google o petición local de MCP para desmitificar las tripas del protocolo.
* **[test_conn.py](file:///Users/inakisobera/Documents/MCP/northwind_mcp/test_conn.py)**: Script auxiliar para validar la conexión directa de Python hacia la base de datos de Docker sin pasar por el protocolo MCP.
* **[venv/](file:///Users/inakisobera/Documents/MCP/northwind_mcp/venv/)**: Entorno virtual que aísla y contiene las librerías necesarias (`fastmcp`, `mcp`, `pymssql`, `httpx` y `termcolor`).

---

## ⚡ Guía de Uso del Proyecto

### 1. Requisitos Previos
Asegúrate de que tu contenedor Docker de SQL Server esté corriendo en el puerto `1433`:
```bash
docker ps
```

### 2. Ejecutar el Agente
Navega a la carpeta del proyecto, activa el entorno virtual y ejecuta el agente interactivo:
```bash
cd /Users/inakisobera/Documents/MCP/northwind_mcp
source venv/bin/activate
python3 agent.py
```

### 3. Prueba la memoria y las herramientas del Agente
Prueba a realizar la siguiente secuencia de preguntas continuas en el chat:
* **Pregunta 1:** *¿Cuáles son las categorías de productos que vendemos?* (Verás a la IA generar una consulta SQL automatizada).
* **Pregunta 2:** *¿Cuál de ellas tiene más cantidad de productos asociados?* (La IA recordará la lista de categorías previa, hará una nueva consulta a la BD y te dará la respuesta exacta).
* **Pregunta 3:** *Salúdame* (La IA decidirá responder directamente sin mandar consultas a MCP ni a SQL Server).
