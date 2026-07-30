# MCP Relational AI Gateway 🚀

Un portal de análisis y administración de bases de datos relacionales inteligente y ultra premium, potenciado por **Google Gemini** bajo el estándar **Model Context Protocol (MCP)**. Esta herramienta está diseñada para la comunidad de código abierto de GitHub.

Este repositorio consolida tanto el motor de base de datos relacional (Microsoft SQL Server bajo Docker) como la interfaz de usuario web interactiva (Flask, HTML Glassmorphic, Chart.js y Marked.js).

---

## 🌟 Características Clave

*   **🧠 Asistente de IA Inteligente**: Consulta tus bases de datos usando lenguaje natural. La IA deducirá las relaciones, generará los joins y ejecutará las consultas óptimas.
*   **📈 Gráficos Dinámicos en Tiempo Real**: Auto-detecta columnas métricas y de texto para dibujar gráficos interactivos de barras, líneas, pastel o dona directamente desde el chat.
*   **💻 Consola SQL Sandbox (SSMS Integrada)**: Ejecuta sentencias SQL de forma manual desde el navegador y observa los resultados tabulares al instante.
*   **📜 Bitácora de Queries & Historial**: Mapea y guarda en la barra lateral todas las consultas SQL ejecutadas para copiarlas o reutilizarlas rápidamente en la consola.
*   **📥 Exportación Inteligente a Excel (CSV)**: Descarga tus tablas de resultados con formato optimizado en un clic (con codificación UTF-8 BOM compatible con Excel y sanitización de binarios).
*   **🛡️ Selección de Modelos con Fallback Cascading**: Si un modelo supera su cuota gratuita de Gemini (error 429), el sistema cambia de manera invisible al siguiente modelo disponible en cascada (`gemini-3.1-flash-lite` ➔ `gemini-2.0-flash-lite` ➔ `gemini-2.0-flash` ➔ `gemini-3.5-flash`).
*   **🌌 Interfaz Glassmorphism Premium**: Temática oscura futurista con fondos de nebulosas estelares en CSS fluido, auras de foco interactivo y barras de scroll translúcidas.

---

## 📂 Estructura del Repositorio

*   `docker-compose.yml`: Archivo de orquestación para iniciar SQL Server 2022.
*   `import_db.sh`: Script automatizado para restaurar la base de datos Northwind.
*   `Northwind/`: Contiene el script SQL de restauración de Northwind y configuraciones iniciales.
*   `northwind_mcp/`: Código fuente del panel Flask y del frontend interactivo (chat, consolas, gráficos).
*   `.gitignore`: Filtros para evitar subir archivos temporales, configuraciones de IDEs o entornos virtuales.

---

## 🚀 Guía de Inicio Rápido

Sigue estos tres sencillos pasos para iniciar todo el entorno en tu computadora local:

### Paso 1: Levantar e Importar la Base de Datos (Docker)
Asegúrate de tener Docker instalado y ejecutándose en tu sistema. Luego abre una terminal en la raíz del repositorio y ejecuta:

```bash
# 1. Iniciar el contenedor de SQL Server en segundo plano
docker compose up -d

# 2. Ejecutar el script automatizado para restaurar la base de datos
./import_db.sh
```

### Paso 2: Configurar e Iniciar el Dashboard Web (Flask)
Ingresa al directorio de la aplicación web y arranca el entorno de Python:

```bash
cd northwind_mcp

# 1. Crear entorno virtual
python -m venv venv

# 2. Activar el entorno virtual
# En macOS/Linux:
source venv/bin/activate
# En Windows:
# .\venv\Scripts\activate

# 3. Instalar las dependencias
pip install -r requirements.txt # O instala Flask, httpx, pymssql, psycopg2, flask[async], termcolor

# 4. Iniciar la aplicación
python app.py
```

### Paso 3: Conectarse y Analizar
1. Abre tu navegador e ingresa a: **`http://localhost:5050`**
2. Introduce tu **API Key de Gemini** (Obtenla gratis en Google AI Studio).
3. Configura la conexión de la base de datos con las credenciales por defecto:
    *   **Motor**: Microsoft SQL Server
    *   **Host**: `127.0.0.1`
    *   **Puerto**: `1433`
    *   **Usuario**: `sa`
    *   **Contraseña**: `TuPasswordSeguro123!`
    *   **Base de Datos**: `Northwind`
4. ¡Listo! Haz clic en **Conectar y Analizar** para ingresar al panel de control interactivo.

---

## 📄 Licencia

Este proyecto se distribuye de forma **totalmente gratuita y libre** para la comunidad bajo la Licencia MIT. ¡Siéntete libre de clonarlo, hacerle fork, mejorarlo y subir tus contribuciones!
