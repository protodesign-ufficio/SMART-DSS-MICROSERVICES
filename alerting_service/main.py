import os
from fastapi import FastAPI
import psycopg2

DB_CONN = os.getenv("ALERTING_DB_CONN", "dbname=alerting_db user=postgres password=admin host=localhost")

app = FastAPI(
    title="Alerting Internal Service",
    version="0.1.0",
    description=(
        "Microservizio interno per la consultazione degli allarmi operativi. "
        "Espone endpoint di health e lista allarmi, leggendo i dati dal database alerting_db."
    ),
)


def get_connection():
    return psycopg2.connect(DB_CONN)


@app.get("/health")
def health():
    return {"status": "ok", "service": "alerting"}


@app.get("/internal/allarme/lista")
def lista_allarmi(limit: int = 200):
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT
                id,
                utente_assegnatario_id AS utente_id,
                descrizione AS testo,
                created_at AS data_creazione
            FROM allarme
            ORDER BY created_at DESC
            LIMIT %s;
            """,
            (limit,),
        )
        rows = cur.fetchall()
        return [
            {
                "id": str(r[0]),
                "utente_id": str(r[1]) if r[1] else None,
                "testo": r[2],
                "data_creazione": r[3].isoformat() if r[3] else None,
            }
            for r in rows
        ]
    finally:
        cur.close()
        conn.close()
