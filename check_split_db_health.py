import psycopg2

BASE = "user=postgres password=admin host=host.docker.internal"
DBS = ["anagrafica_db", "operativo_db", "percorsi_db", "forecast_db", "alerting_db"]

for db in DBS:
    conn = psycopg2.connect(f"dbname={db} {BASE}")
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='public' AND table_type='BASE TABLE'")
    tables = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM information_schema.table_constraints WHERE table_schema='public' AND constraint_type='PRIMARY KEY'")
    pks = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM information_schema.table_constraints WHERE table_schema='public' AND constraint_type='FOREIGN KEY'")
    fks = cur.fetchone()[0]
    print(f"{db}: tables={tables}, pk={pks}, fk={fks}")
    cur.close()
    conn.close()
