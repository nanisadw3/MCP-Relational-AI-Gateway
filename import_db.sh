#!/bin/bash
# Script para importar automáticamente la base de datos Northwind al contenedor Docker

echo "🚀 Iniciando importación de base de datos Northwind..."

# Copiar el script SQL al contenedor
echo "📦 Copiando script SQL al contenedor sql_northwind..."
docker cp database_setup/instnwnd.sql sql_northwind:/tmp/instnwnd.sql

if [ $? -ne 0 ]; then
    echo "❌ Error: Asegúrate de que el contenedor 'sql_northwind' esté corriendo (ejecuta primero 'docker compose up -d')."
    exit 1
fi

# Ejecutar la restauración usando sqlcmd del contenedor
echo "⚡ Restaurando base de datos SQL Server..."
docker exec -it sql_northwind /opt/mssql-tools18/bin/sqlcmd -S localhost -U sa -P 'TuPasswordSeguro123!' -C -i /tmp/instnwnd.sql

if [ $? -eq 0 ]; then
    echo "✅ ¡Base de datos Northwind restaurada con éxito en SQL Server!"
else
    echo "❌ Error al ejecutar el script de restauración."
    exit 1
fi
