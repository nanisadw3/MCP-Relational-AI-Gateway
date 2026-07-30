# MCP Relational AI Gateway 🚀

Un portal de análisis y administración de bases de datos relacionales inteligente y ultra premium, potenciado por **Google Gemini** bajo el estándar **Model Context Protocol (MCP)**. Esta herramienta está diseñada para la comunidad de código abierto de GitHub.

Este repositorio consolida tanto el motor de base de datos relacional (Microsoft SQL Server bajo Docker) como la interfaz de usuario web interactiva (Flask, Google Material Design 3, Chart.js y Marked.js).

---

## 🌟 Características Clave

*   **🧠 Asistente de IA Inteligente**: Consulta tus bases de datos usando lenguaje natural. La IA deducirá las relaciones, generará los joins y ejecutará las consultas óptimas.
*   **📈 Gráficos Dinámicos con Zoom Interactivo**: Auto-detecta columnas métricas y de texto para dibujar gráficos interactivos de barras, líneas, pastel o dona. Soporta **drag-to-zoom** (arrastra para hacer zoom en una región) y **doble clic para regresar** al tamaño original con animación suave.
*   **🌗 Tema Claro / Oscuro (Material Design 3)**: Switcher de tema integrado que alterna entre el tema claro y oscuro de M3, con persistencia automática en `localStorage`.
*   **🗄️ Panel SQL Manager Retráctil**: Sidebar con el árbol de estructura completo (tablas, columnas, tipos de dato) que se oculta y muestra con una animación GPU-accelerated. Incluye el nombre del usuario conectado en la cabecera.
*   **📥 Exportación Inteligente a Excel (CSV)**: Descarga tus tablas de resultados con formato optimizado en un clic (con codificación UTF-8 BOM compatible con Excel y sanitización de binarios).
*   **🛡️ Selección de Modelos con Fallback Cascading**: Si un modelo supera su cuota gratuita de Gemini (error 429), el sistema cambia de manera invisible al siguiente modelo disponible en cascada (`gemini-3.1-flash-lite` ➔ `gemini-2.0-flash-lite` ➔ `gemini-2.0-flash` ➔ `gemini-3.5-flash`).
*   **🔌 Soporte Multi-Motor**: Compatible con **Microsoft SQL Server (T-SQL)** y **PostgreSQL**, con detección automática de dialectos y puertos.
*   **🔍 Combobox Dinámico de Bases de Datos**: En la pantalla de login, al ingresar las credenciales y pulsar "Cargar", se consultan las bases de datos disponibles en el servidor y se muestran en un selector desplegable.

---

## 🎨 Google Material Design 3: Iconos y Diseño Visual

La interfaz completa del proyecto utiliza el sistema de diseño **Material Design 3 (M3)** de Google, implementado de la siguiente manera:

### Material Symbols (Iconos)

Todos los íconos de la aplicación provienen de la librería oficial **[Google Material Symbols](https://fonts.google.com/icons)**, cargada directamente desde la CDN pública de Google Fonts:

```html
<link href="https://fonts.googleapis.com/icon?family=Material+Symbols+Rounded" rel="stylesheet">
```

**¿Cómo funciona?** Google Fonts ofrece esta familia tipográfica de íconos de forma **gratuita y sin límites**. Al cargar esta hoja de estilos, se descarga la fuente de íconos una sola vez y queda disponible en toda la página. Luego, para usar cualquier ícono, solo se necesita un `<span>` con la clase y el nombre del ícono:

```html
<!-- Ejemplos de uso -->
<span class="material-symbols-rounded">database</span>      <!-- Icono de base de datos -->
<span class="material-symbols-rounded">send</span>           <!-- Icono de enviar -->
<span class="material-symbols-rounded">light_mode</span>     <!-- Icono de tema claro -->
<span class="material-symbols-rounded">account_circle</span> <!-- Icono de usuario -->
<span class="material-symbols-rounded">table_chart</span>    <!-- Icono de tabla -->
<span class="material-symbols-rounded">insert_chart</span>   <!-- Icono de gráfico -->
<span class="material-symbols-rounded">zoom_in</span>        <!-- Icono de zoom -->
```

> 💡 **Consejo**: Puedes explorar los +3,000 íconos disponibles en [fonts.google.com/icons](https://fonts.google.com/icons). Los íconos se pueden personalizar en tamaño, color y peso directamente con CSS.

### Paleta de Colores M3

Los colores siguen las **Design Tokens** de Material Design 3, definidos como variables CSS que se alternan automáticamente entre los temas claro y oscuro:

| Token CSS | Tema Oscuro | Tema Claro | Propósito |
|---|---|---|---|
| `--primary` | `#D0BCFF` | `#6750A4` | Color primario (botones, encabezados) |
| `--primary-hover` | `#EADDFF` | `#21005D` | Hover del primario |
| `--accent` | `#b8f397` | `#386a20` | Acento (indicadores, badges) |
| `--bg-color` | `#141218` | `#f8f9ff` | Fondo principal |
| `--card-bg` | `rgba(37,35,41,0.6)` | `rgba(255,255,255,0.7)` | Fondo de tarjetas/burbujas |
| `--text-main` | `#E6E1E5` | `#1c1b1f` | Texto principal |
| `--text-muted` | `#CAC4D0` | `#49454f` | Texto secundario |
| `--surface-variant` | `rgba(73,69,79,0.35)` | `rgba(231,224,236,0.6)` | Superficies elevadas |

### Tipografía

Se utiliza la fuente **[Plus Jakarta Sans](https://fonts.google.com/specimen/Plus+Jakarta+Sans)** de Google Fonts, cargada con la misma técnica CDN:

```html
<link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@300;400;500;600;700&display=swap" rel="stylesheet">
```

---

## 📊 Librerías de Terceros (CDN)

Todas las librerías externas se cargan desde CDN públicos sin necesidad de instalación local:

| Librería | Propósito | CDN |
|---|---|---|
| **Chart.js** | Gráficos interactivos (línea, barra, pastel, dona) | `cdn.jsdelivr.net/npm/chart.js` |
| **chartjs-plugin-zoom** | Zoom drag-to-select y reset en gráficos | `cdn.jsdelivr.net/npm/chartjs-plugin-zoom` |
| **Hammer.js** | Soporte de gestos táctiles para el plugin de zoom | `cdn.jsdelivr.net/npm/hammerjs` |
| **Marked.js** | Renderizado de Markdown en las respuestas de la IA | `cdn.jsdelivr.net/npm/marked` |
| **Material Symbols Rounded** | Iconos vectoriales M3 de Google | `fonts.googleapis.com` |
| **Plus Jakarta Sans** | Tipografía moderna premium | `fonts.googleapis.com` |

---

## 📂 Estructura del Repositorio

*   `docker-compose.yml`: Archivo de orquestación para iniciar SQL Server 2022.
*   `import_db.sh`: Script automatizado para restaurar la base de datos Northwind.
*   `Northwind/`: Contiene el script SQL de restauración de Northwind y configuraciones iniciales.
*   `northwind_mcp/`: Código fuente del panel Flask y del frontend interactivo (chat, árbol SQL, gráficos).
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
2. Introduce tu **API Key de Gemini** (Obtenla gratis en [Google AI Studio](https://aistudio.google.com/apikey)).
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
