import psycopg2
from collections import defaultdict

BASE = "user=postgres password=admin host=host.docker.internal"
SPLIT_DBS = ["anagrafica_db", "operativo_db", "percorsi_db", "forecast_db", "alerting_db"]


def connect(db_name: str):
    return psycopg2.connect(f"dbname={db_name} {BASE}")


def get_tables(db_name: str):
    conn = connect(db_name)
    cur = conn.cursor()
    cur.execute(
        """
        SELECT table_name
        FROM information_schema.tables
        WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
        ORDER BY table_name;
        """
    )
    rows = [r[0] for r in cur.fetchall()]
    cur.close()
    conn.close()
    return rows


def get_fks(db_name: str):
    conn = connect(db_name)
    cur = conn.cursor()
    cur.execute(
        """
        SELECT tc.table_name,
               kcu.column_name,
               ccu.table_name,
               ccu.column_name,
               tc.constraint_name
        FROM information_schema.table_constraints tc
        JOIN information_schema.key_column_usage kcu
          ON tc.constraint_name = kcu.constraint_name
         AND tc.table_schema = kcu.table_schema
        JOIN information_schema.constraint_column_usage ccu
          ON tc.constraint_name = ccu.constraint_name
         AND tc.table_schema = ccu.table_schema
        WHERE tc.table_schema = 'public'
          AND tc.constraint_type = 'FOREIGN KEY'
        ORDER BY tc.table_name, tc.constraint_name;
        """
    )
    rows = [
        {
            "table": r[0],
            "column": r[1],
            "ref_table": r[2],
            "ref_column": r[3],
            "constraint": r[4],
        }
        for r in cur.fetchall()
    ]
    cur.close()
    conn.close()
    return rows


def main():
    table_owner = {}
    for db in SPLIT_DBS:
        for table in get_tables(db):
            table_owner[table] = db

    monolith_fks = get_fks("travelmar_db")

    split_fk_index = defaultdict(list)
    for db in SPLIT_DBS:
        for fk in get_fks(db):
            key = (fk["table"], fk["column"], fk["ref_table"], fk["ref_column"])
            split_fk_index[key].append((db, fk["constraint"]))

    report = []
    for fk in monolith_fks:
        table_db = table_owner.get(fk["table"])
        ref_db = table_owner.get(fk["ref_table"])
        key = (fk["table"], fk["column"], fk["ref_table"], fk["ref_column"])

        if table_db is None or ref_db is None:
            status = "NOT_SPLIT"
            detail = "una o entrambe le tabelle non sono presenti nei DB split"
        elif table_db != ref_db:
            status = "CROSS_DB"
            detail = f"{table_db} -> {ref_db} (FK fisica cross-DB non applicabile)"
        else:
            present = split_fk_index.get(key, [])
            if any(db == table_db for db, _ in present):
                status = "PRESERVED"
                constraints = [c for db, c in present if db == table_db]
                detail = f"presente in {table_db}: {constraints}"
            else:
                status = "MISSING_INTRA_DB"
                detail = f"entrambe le tabelle in {table_db}, FK non trovata"

        report.append(
            {
                "status": status,
                "fk": fk,
                "table_db": table_db,
                "ref_db": ref_db,
                "detail": detail,
            }
        )

    summary = defaultdict(int)
    for item in report:
        summary[item["status"]] += 1

    print("SUMMARY", dict(summary))
    for item in report:
        fk = item["fk"]
        print(
            f"{item['status']}: {fk['table']}.{fk['column']} -> "
            f"{fk['ref_table']}.{fk['ref_column']} [{fk['constraint']}] | {item['detail']}"
        )


if __name__ == "__main__":
    main()
