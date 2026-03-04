import requests
from app.core.database import get_connection
from app.core.config import ML_URL, SERVICE_CONFIG
from app.models.corsa import PrevisioneRequest
from fastapi import HTTPException
from datetime import timedelta

def calcola_previsione(corsa_id: str, req: PrevisioneRequest, disable_cache: bool = False):
    conn = get_connection()
    cur = conn.cursor()

    CACHE_DELTA = timedelta(minutes=SERVICE_CONFIG.cache_delta_minutes)

    try:
        # --------------------------------------------------
        # 0. Recupero corsa
        # --------------------------------------------------
        cur.execute(
            "SELECT id, orario_partenza_schedulato FROM corsa WHERE id = %s",
            (corsa_id,)
        )
        row = cur.fetchone()

        if row is None:
            raise HTTPException(status_code=404, detail="Corsa non trovata")

        corsa_id_db, orario_ts = row

        # --------------------------------------------------
        # 1. PRE-CHECK cache previsione (opzionale)
        # --------------------------------------------------
        if not disable_cache:
            cur.execute("""
                SELECT
                    id,
                    passeggeri_stimati,
                    confidenza_min,
                    confidenza_max,
                    created_at
                FROM previsione_domanda
                WHERE corsa_id = %s
                  AND created_at >= now() - interval %s
                ORDER BY created_at DESC
                LIMIT 1;
            """, (
                corsa_id_db,
                CACHE_DELTA
            ))

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
                        "cached_at": created_at.isoformat()
                    }
                }

        # --------------------------------------------------
        # 2. Chiamata servizio ML
        # --------------------------------------------------
        giorno_target = orario_ts.date().strftime("%Y-%m-%d")
        orario_str = orario_ts.strftime("%H%M")

        payload = {
            "giorno_target": giorno_target,
            "orario": orario_str,
            "biglietti_venduti_al_sample": req.biglietti_venduti_al_sample,
            "festivo": req.festivo
        }

        r = requests.post(ML_URL, json=payload, timeout=60)

        if r.status_code != 200:
            raise HTTPException(status_code=500, detail="Errore ML service")

        pred = r.json()

        micro_finale = pred["micro_finale"]
        ci_low, ci_high = pred["micro_finale_ci_95"]

        # --------------------------------------------------
        # 3. Salvataggio previsione
        # --------------------------------------------------
        cur.execute("""
            INSERT INTO previsione_domanda
                (id, corsa_id, passeggeri_stimati, confidenza_min, confidenza_max, created_at)
            VALUES
                (gen_random_uuid(), %s, %s, %s, %s, now())
            RETURNING id;
        """, (
            corsa_id_db,
            micro_finale,
            ci_low,
            ci_high
        ))

        previsione_id = cur.fetchone()[0]
        conn.commit()

        return {
            "status": "computed",
            "corsa_id": corsa_id_db,
            "previsione_id": str(previsione_id),
            "passeggeri_stimati": micro_finale,
            "dettagli": pred
        }

    except Exception:
        conn.rollback()
        raise

    finally:
        cur.close()
        conn.close()
