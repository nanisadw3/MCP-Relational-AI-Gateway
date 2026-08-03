import json
from fastmcp import FastMCP
import pymssql

# Initialize FastMCP Server
mcp = FastMCP("Northwind")

DB_CONFIG = {
    "server": "127.0.0.1",
    "port": 1433,
    "user": "sa",
    "password": "TuPasswordSeguro123!",
    "database": "master",
    "autocommit": True,
}


def get_conn():
    return pymssql.connect(**DB_CONFIG)


@mcp.resource("db://schema")
def get_db_schema() -> str:
    """Returns the schema of all tables in the Northwind database."""
    conn = get_conn()
    cursor = conn.cursor()

    # Query tables and columns info
    query = """
    SELECT 
        t.TABLE_NAME, 
        c.COLUMN_NAME, 
        c.DATA_TYPE
    FROM INFORMATION_SCHEMA.TABLES t
    INNER JOIN INFORMATION_SCHEMA.COLUMNS c ON t.TABLE_NAME = c.TABLE_NAME
    WHERE t.TABLE_TYPE = 'BASE TABLE'
    ORDER BY t.TABLE_NAME, c.ORDINAL_POSITION
    """
    cursor.execute(query)

    schema = {}
    for table_name, column_name, data_type in cursor.fetchall():
        if table_name not in schema:
            schema[table_name] = []
        schema[table_name].append(f"{column_name} ({data_type})")

    conn.close()
    return json.dumps(schema, indent=2)


@mcp.tool()
def query_db(sql: str) -> str:
    """
    Executes a SQL query on the Northwind database and returns the results.
    Only read queries (SELECT) are recommended.
    """
    # Check if the query is a SELECT query (basic security check)
    clean_sql = sql.strip().upper()
    if not clean_sql.startswith("SELECT") and not clean_sql.startswith("WITH"):
        return "Error: Only read-only queries (SELECT) are permitted."

    try:
        conn = get_conn()
        cursor = conn.cursor(as_dict=True)
        cursor.execute(sql)
        results = cursor.fetchall()
        conn.close()

        # Format dates and decimals so they are JSON serializable
        def serialize_item(val):
            import datetime
            from decimal import Decimal

            if isinstance(val, (datetime.date, datetime.datetime)):
                return val.isoformat()
            if isinstance(val, Decimal):
                return float(val)
            return val

        serializable_results = [
            {k: serialize_item(v) for k, v in row.items()} for row in results
        ]

        return json.dumps(serializable_results, indent=2)
    except Exception as e:
        return f"Error executing query: {str(e)}"


if __name__ == "__main__":
    mcp.run()
