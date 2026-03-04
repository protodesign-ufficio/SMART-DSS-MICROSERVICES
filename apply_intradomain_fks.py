import os
import psycopg2


FK_CANDIDATES = [
    ("tratta_porto_partenza_id_fkey", "tratta", "porto_partenza_id", "porto", "id"),
    ("tratta_porto_arrivo_id_fkey", "tratta", "porto_arrivo_id", "porto", "id"),
    ("componente_vascello_id_fkey", "componente", "vascello_id", "vascello", "id"),
    ("assegnazione_piano_id_fkey", "assegnazione", "piano_id", "piano_operativo", "id"),
    ("deadhead_trips_piano_id_fkey", "deadhead_trips", "piano_id", "piano_operativo", "id"),
]


TARGET_DBS = [
    "anagrafica_db",
    "operativo_db",
    "percorsi_db",
    "forecast_db",
    "alerting_db",
]


def table_exists(cur, table_name: str) -> bool:
    cur.execute(
        """
        SELECT 1
        FROM information_schema.tables
        WHERE table_schema = 'public' AND table_name = %s
        LIMIT 1;
        """,
        (table_name,),
    )
    return cur.fetchone() is not None


def column_exists(cur, table_name: str, column_name: str) -> bool:
    cur.execute(
        """
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = %s AND column_name = %s
        LIMIT 1;
        """,
        (table_name, column_name),
    )
    return cur.fetchone() is not None


def fk_exists(cur, constraint_name: str) -> bool:
    cur.execute(
        """
        SELECT 1
        FROM information_schema.table_constraints
        WHERE table_schema = 'public'
          AND constraint_type = 'FOREIGN KEY'
          AND constraint_name = %s
        LIMIT 1;
        """,
        (constraint_name,),
    )
    return cur.fetchone() is not None


def orphan_count(cur, table_name: str, column_name: str, ref_table: str, ref_col: str) -> int:
    query = f"""
        SELECT COUNT(*)
        FROM {table_name} t
        LEFT JOIN {ref_table} r ON t.{column_name} = r.{ref_col}
        WHERE t.{column_name} IS NOT NULL
          AND r.{ref_col} IS NULL;
    """
    cur.execute(query)
    return int(cur.fetchone()[0])


def apply_fk(cur, constraint_name: str, table_name: str, column_name: str, ref_table: str, ref_col: str):
    query = f"""
        ALTER TABLE {table_name}
        ADD CONSTRAINT {constraint_name}
        FOREIGN KEY ({column_name})
        REFERENCES {ref_table} ({ref_col});
    """
    cur.execute(query)


def main():
    db_user = os.getenv("DB_USER", "postgres")
    db_password = os.getenv("DB_PASSWORD", "admin")
    db_host = os.getenv("DB_HOST", "host.docker.internal")

    print("Applying intra-domain foreign keys...")
    print(f"Host={db_host}, User={db_user}")

    for db_name in TARGET_DBS:
        conn = psycopg2.connect(
            dbname=db_name,
            user=db_user,
            password=db_password,
            host=db_host,
        )
        conn.autocommit = False
        cur = conn.cursor()

        created = 0
        skipped_absent = 0
        skipped_existing = 0
        skipped_orphans = 0

        print(f"\n=== {db_name} ===")

        try:
            for constraint_name, table_name, column_name, ref_table, ref_col in FK_CANDIDATES:
                if not table_exists(cur, table_name) or not table_exists(cur, ref_table):
                    skipped_absent += 1
                    continue

                if not column_exists(cur, table_name, column_name) or not column_exists(cur, ref_table, ref_col):
                    skipped_absent += 1
                    continue

                if fk_exists(cur, constraint_name):
                    skipped_existing += 1
                    continue

                missing_refs = orphan_count(cur, table_name, column_name, ref_table, ref_col)
                if missing_refs > 0:
                    skipped_orphans += 1
                    print(
                        f"SKIP orphan data: {constraint_name} ({table_name}.{column_name} -> {ref_table}.{ref_col}) missing={missing_refs}"
                    )
                    continue

                apply_fk(cur, constraint_name, table_name, column_name, ref_table, ref_col)
                created += 1
                print(f"ADD  {constraint_name} ({table_name}.{column_name} -> {ref_table}.{ref_col})")

            conn.commit()
            print(
                f"RESULT created={created}, skipped_absent={skipped_absent}, skipped_existing={skipped_existing}, skipped_orphans={skipped_orphans}"
            )
        except Exception:
            conn.rollback()
            raise
        finally:
            cur.close()
            conn.close()


if __name__ == "__main__":
    main()
