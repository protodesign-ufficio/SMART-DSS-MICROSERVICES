import psycopg2
from pathlib import Path

DB_CONN = "dbname=operativo_db user=postgres password=admin host=localhost"

SQL = Path(__file__).resolve().parent.joinpath("operativo_service", "sql", "piano_status_legacy_trigger.sql").read_text(encoding="utf-8")


def main():
    conn = psycopg2.connect(DB_CONN)
    try:
        conn.autocommit = False
        with conn.cursor() as cur:
            cur.execute(SQL)
        conn.commit()
        print("OK: funzione/trigger stato piano allineati al legacy su operativo_db")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
