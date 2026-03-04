import psycopg2

conn = psycopg2.connect("dbname=operativo_db user=postgres password=admin host=localhost")
try:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT t.tgname
            FROM pg_trigger t
            JOIN pg_class c ON c.oid = t.tgrelid
            WHERE c.relname = 'assegnazione'
              AND NOT t.tgisinternal
            ORDER BY t.tgname;
            """
        )
        print(cur.fetchall())
finally:
    conn.close()
