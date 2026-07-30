import pymssql

try:
    conn = pymssql.connect(
        server='127.0.0.1',
        port=1433,
        user='sa',
        password='TuPasswordSeguro123!',
        database='Northwind',
        autocommit=True
    )
    cursor = conn.cursor()
    cursor.execute("SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_TYPE = 'BASE TABLE'")
    tables = [row[0] for row in cursor.fetchall()]
    print("Tables in Northwind:", tables)
    
    # Query a few products
    cursor.execute("SELECT TOP 5 ProductName, UnitPrice FROM Products")
    for row in cursor.fetchall():
        print(f"Product: {row[0]} - Price: ${row[1]}")
        
    conn.close()
except Exception as e:
    print("Error connecting:", e)
