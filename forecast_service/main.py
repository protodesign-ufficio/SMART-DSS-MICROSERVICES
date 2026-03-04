import os
from datetime import datetime, timedelta
import requests
from fastapi import FastAPI, HTTPException, Query
import psycopg2

DB_CONN = os.getenv("FORECAST_DB_CONN", "dbname=forecast_db user=postgres password=admin host=localhost")
ML_URL = os.getenv("ML_URL", "http://service:8000/predict")
OPERATIVO_SERVICE_URL = os.getenv("OPERATIVO_SERVICE_URL", "http://operativo:8072")
CACHE_MINUTES = int(os.getenv("FORECAST_CACHE_MINUTES", "120"))

app = FastAPI(title="Forecast Internal Service", version="0.1.0")


def get_connection():
    return psycopg2.connect(DB_CONN)


@app.get("/health")
def health():
    return {"status": "ok", "service": "forecast"}


@app.post("/internal/previsione/corsa/{corsa_id}/calcola")
def calcola_previsione(
    corsa_id: str,
    req: dict,
    disable_cache: bool = Query(False, description="Se true forza il ricalcolo senza usare cache"),
):
    conn = get_connection()
    cur = conn.cursor()
    cache_delta = timedelta(minutes=CACHE_MINUTES)

    try:
        try:
            corsa_resp = requests.get(
                f"{OPERATIVO_SERVICE_URL.rstrip('/')}/internal/corsa/id/{corsa_id}",
                timeout=8,
            )
        except requests.RequestException as exc:
            raise HTTPException(status_code=503, detail="Operativo service unavailable") from exc

        if corsa_resp.status_code == 404:
            raise HTTPException(status_code=404, detail="Corsa non trovata")
        if corsa_resp.status_code >= 400:
            raise HTTPException(status_code=503, detail="Operativo service unavailable")

        corsa_data = corsa_resp.json()
        corsa_id_db = corsa_data.get("id")
        orario_iso = corsa_data.get("orario_partenza_schedulato")
        if corsa_id_db is None or orario_iso is None:
            raise HTTPException(status_code=502, detail="Invalid operativo response")
        orario_ts = datetime.fromisoformat(orario_iso)

        if not disable_cache:
            cur.execute(
                """
                SELECT id, passeggeri_stimati, confidenza_min, confidenza_max, created_at
                FROM previsione_domanda
                WHERE corsa_id = %s
                  AND created_at >= now() - interval %s
                ORDER BY created_at DESC
                LIMIT 1;
                """,
                (corsa_id_db, cache_delta),
            )
            cached = cur.fetchone()

            if cached:
                previsione_id, stimati, ci_min, ci_max, created_at = cached
                return {
                    "status": "cached",
                    "corsa_id": corsa_id_db,
                    "previsione_id": str(previsione_id),
                    "passeggeri_stimati": stimati,
                    "dettagli": {
                        "micro_finale": stimati,
                        "micro_finale_ci_95": [ci_min, ci_max],
                        "cached_at": created_at.isoformat(),
                    },
                }

        giorno_target = orario_ts.date().strftime("%Y-%m-%d")
        orario_str = orario_ts.strftime("%H%M")

        payload = {
            "giorno_target": giorno_target,
            "orario": orario_str,
            "biglietti_venduti_al_sample": req.get("biglietti_venduti_al_sample"),
            "festivo": req.get("festivo"),
        }

        r = requests.post(ML_URL, json=payload, timeout=60)
        if r.status_code != 200:
            raise HTTPException(status_code=500, detail="Errore ML service")

        pred = r.json()
        micro_finale = pred["micro_finale"]
        ci_low, ci_high = pred["micro_finale_ci_95"]

        cur.execute(
            """
            INSERT INTO previsione_domanda
                (id, corsa_id, passeggeri_stimati, confidenza_min, confidenza_max, created_at)
            VALUES
                (gen_random_uuid(), %s, %s, %s, %s, now())
            RETURNING id;
            """,
            (corsa_id_db, micro_finale, ci_low, ci_high),
        )

        previsione_id = cur.fetchone()[0]
        conn.commit()

        return {
            "status": "computed",
            "corsa_id": corsa_id_db,
            "previsione_id": str(previsione_id),
            "passeggeri_stimati": micro_finale,
            "dettagli": pred,
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()


@app.get("/internal/previsione/{previsione_id}")
def get_previsione(previsione_id: str):
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT id, corsa_id, passeggeri_stimati, confidenza_min, confidenza_max, created_at
            FROM previsione_domanda
            WHERE id = %s
            LIMIT 1;
            """,
            (previsione_id,),
        )
        row = cur.fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Previsione non trovata")

        return {
            "id": str(row[0]),
            "corsa_id": str(row[1]) if row[1] else None,
            "passeggeri_stimati": row[2],
            "confidenza_min": row[3],
            "confidenza_max": row[4],
            "created_at": row[5].isoformat() if row[5] else None,
        }
    finally:
        cur.close()
        conn.close()
