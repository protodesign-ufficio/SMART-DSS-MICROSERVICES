import os
from fastapi import FastAPI
import psycopg2

DB_CONN = os.getenv("TELEMETRY_DB_CONN", "dbname=telemetry_db user=postgres password=admin host=localhost")

app = FastAPI(title="Telemetry Internal Service", version="0.1.0")


def get_connection():
    return psycopg2.connect(DB_CONN)


@app.get("/health")
def health():
    return {"status": "ok", "service": "telemetry"}


@app.get("/internal/telemetry/positions/recent")
def recent_positions(limit: int = 100):
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT id, mmsi, COALESCE(speed, 0), COALESCE(course, 0), COALESCE(heading, 0), ts
            FROM posizione_ais
            ORDER BY ts DESC
            LIMIT %s
            """,
            (max(1, min(limit, 5000)),),
        )
        rows = cur.fetchall()
        return [
            {
                "id": str(r[0]),
                "mmsi": r[1],
                "speed": float(r[2]),
                "course": float(r[3]),
                "heading": float(r[4]),
                "ts": r[5].isoformat() if r[5] else None,
            }
            for r in rows
        ]
    finally:
        cur.close()
        conn.close()
