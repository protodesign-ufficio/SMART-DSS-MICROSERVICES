import os
from datetime import datetime
from fastapi import FastAPI, HTTPException, Query
import psycopg2
import requests

DB_CONN = os.getenv("OPERATIVO_DB_CONN", "dbname=operativo_db user=postgres password=admin host=localhost")
ANAGRAFICA_SERVICE_URL = os.getenv("ANAGRAFICA_SERVICE_URL", "http://anagrafica:8070")
FORECAST_SERVICE_URL = os.getenv("FORECAST_SERVICE_URL", "http://forecast:8074")
PERCORSI_SERVICE_URL = os.getenv("PERCORSI_SERVICE_URL", "http://percorsi:8073")

app = FastAPI(title="Operativo Internal Service", version="0.1.0")


def get_connection():
    return psycopg2.connect(DB_CONN)


def _get_json(base_url: str, path: str, timeout: float = 6.0):
    url = f"{base_url.rstrip('/')}{path}"
    try:
        response = requests.get(url, timeout=timeout)
    except requests.RequestException as exc:
        raise HTTPException(status_code=503, detail=f"Internal dependency unavailable: {base_url}") from exc

    if response.status_code == 404:
        return None
    if response.status_code >= 400:
        raise HTTPException(status_code=503, detail=f"Internal dependency error: {base_url}")

    try:
        return response.json()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Invalid internal response from {base_url}") from exc


def _tratta_nome(tratta_id: str) -> str | None:
    tratta = _get_json(ANAGRAFICA_SERVICE_URL, f"/internal/tratta/{tratta_id}")
    if not tratta:
        return None
    return tratta.get("nome")


def _previsione(previsione_id: str | None):
    if not previsione_id:
        return None
    return _get_json(FORECAST_SERVICE_URL, f"/internal/previsione/{previsione_id}")


def _percorso_meta(percorso_id: str | None):
    if not percorso_id:
        return {"vascello_id": None, "id_corsa": None}
    percorso = _get_json(PERCORSI_SERVICE_URL, f"/internal/percorso/{percorso_id}")
    if not percorso:
        return {"vascello_id": None, "id_corsa": None}
    return {
        "vascello_id": percorso.get("vascello_id"),
        "id_corsa": percorso.get("corsa_id"),
    }


@app.get("/health")
def health():
    return {"status": "ok", "service": "operativo"}


@app.get("/internal/corsa/lista")
def lista_corse():
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT c.id, c.nome, c.tratta_id, c.orario_partenza_schedulato, c.previsione_domanda_id, c.orario_arrivo_max
            FROM corsa c
            WHERE c.orario_partenza_schedulato > NOW()
            ORDER BY c.orario_partenza_schedulato;
        """)
        rows = cur.fetchall()
        out = []
        for r in rows:
            tratta_nome = _tratta_nome(str(r[2]))
            prev = _previsione(str(r[4])) if r[4] else None
            corsa_obj = {
                "id": str(r[0]),
                "nome": r[1],
                "tratta_id": str(r[2]),
                "tratta_nome": tratta_nome,
                "orario_partenza_schedulato": r[3].isoformat(),
                "previsione_domanda_id": str(r[4]) if r[4] else None,
                "orario_arrivo_max": r[5].isoformat() if r[5] else None,
                "previsione": None,
            }
            if prev:
                corsa_obj["previsione"] = {
                    "id": prev.get("id"),
                    "passeggeri_stimati": prev.get("passeggeri_stimati"),
                    "confidenza_min": prev.get("confidenza_min"),
                    "confidenza_max": prev.get("confidenza_max"),
                    "created_at": prev.get("created_at"),
                }
            out.append(corsa_obj)
        return out
    finally:
        cur.close()
        conn.close()


@app.get("/internal/corsa/id/{corsa_id}")
def get_corsa(corsa_id: str):
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT c.id, c.nome, c.tratta_id, c.orario_partenza_schedulato, c.previsione_domanda_id, c.orario_arrivo_max
            FROM corsa c
            WHERE c.id = %s
            """,
            (corsa_id,),
        )
        row = cur.fetchone()
        if row is None:
            raise HTTPException(404, "Corsa non trovata")

        tratta_nome = _tratta_nome(str(row[2]))
        prev = _previsione(str(row[4])) if row[4] else None

        corsa = {
            "id": str(row[0]),
            "nome": row[1],
            "tratta_id": str(row[2]),
            "tratta_nome": tratta_nome,
            "orario_partenza_schedulato": row[3].isoformat(),
            "previsione_domanda_id": str(row[4]) if row[4] else None,
            "orario_arrivo_max": row[5].isoformat() if row[5] else None,
            "previsione": None,
        }
        if prev:
            corsa["previsione"] = {
                "id": prev.get("id"),
                "passeggeri_stimati": prev.get("passeggeri_stimati"),
                "confidenza_min": prev.get("confidenza_min"),
                "confidenza_max": prev.get("confidenza_max"),
            }
        return corsa
    finally:
        cur.close()
        conn.close()


@app.get("/internal/corsa/orari/{tratta_id}")
def get_orari(tratta_id: str, data: str = Query(..., description="YYYY-MM-DD")):
    """Orari partenza distinti per una tratta in un giorno."""
    try:
        giorno = datetime.strptime(data, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail="Formato data non valido")
    nome_tratta = _tratta_nome(tratta_id)
    if not nome_tratta:
        raise HTTPException(404, "Tratta non trovata")
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT DISTINCT orario_partenza_schedulato::time
            FROM corsa
            WHERE tratta_id = %s AND orario_partenza_schedulato::date = %s
            ORDER BY orario_partenza_schedulato::time;
        """, (tratta_id, giorno))
        orari = [r[0].strftime("%H:%M") for r in cur.fetchall()]
        return {"tratta_id": tratta_id, "tratta_nome": nome_tratta, "orari": orari}
    finally:
        cur.close()
        conn.close()


@app.get("/internal/corsa/giorno")
def get_corse_by_giorno(
    giorno: str = Query(..., description="YYYY-MM-DD"),
    solofuture: bool = Query(False),
):
    giorno_date = datetime.strptime(giorno, "%Y-%m-%d").date()
    conn = get_connection()
    cur = conn.cursor()
    try:
        query = """
            SELECT c.id, c.orario_partenza_schedulato::time, c.tratta_id, c.nome, c.orario_arrivo_max::time, c.previsione_domanda_id
            FROM corsa c
            WHERE c.orario_partenza_schedulato::date = %s
        """
        if solofuture:
            query += " AND c.orario_partenza_schedulato > NOW()"
        query += " ORDER BY c.orario_partenza_schedulato;"
        cur.execute(query, (giorno_date,))
        rows = cur.fetchall()

        results = []
        for r in rows:
            item = {
                "id": str(r[0]),
                "tratta": _tratta_nome(str(r[2])),
                "orario": r[1].strftime("%H:%M"),
                "tratta_id": str(r[2]),
                "nome": str(r[3]),
                "orario_arrivo_max": r[4].strftime("%H:%M") if r[4] else None,
                "previsione": None,
            }
            if r[5]:
                prev = _previsione(str(r[5]))
                if prev:
                    item["previsione"] = {
                        "id": prev.get("id"),
                        "passeggeri_stimati": prev.get("passeggeri_stimati"),
                        "confidenza_min": prev.get("confidenza_min"),
                        "confidenza_max": prev.get("confidenza_max"),
                        "created_at": prev.get("created_at"),
                    }
            results.append(item)
        return results
    finally:
        cur.close()
        conn.close()


@app.get("/internal/piano/lista")
def lista_piani(data_riferimento: str | None = None):
    conn = get_connection()
    cur = conn.cursor()
    try:
        if data_riferimento is not None:
            cur.execute(
                "SELECT id, data_riferimento, stato, kpi_profitto_stimato, kpi_robustezza, versione FROM piano_operativo WHERE data_riferimento::date = %s ORDER BY data_riferimento DESC;",
                (data_riferimento,),
            )
        else:
            cur.execute(
                "SELECT id, data_riferimento, stato, kpi_profitto_stimato, kpi_robustezza, versione FROM piano_operativo ORDER BY data_riferimento DESC;"
            )
        rows = cur.fetchall()
        result = []
        for r in rows:
            piano_id = r[0]
            cur.execute(
                """
                SELECT a.id, a.piano_id, a.percorso_id, a.stato_esecuzione, a.virtuale
                FROM assegnazione a
                WHERE a.piano_id = %s;
                """,
                (piano_id,),
            )
            ass_rows = cur.fetchall()
            assegnazioni = []
            for a in ass_rows:
                meta = _percorso_meta(str(a[2]))
                assegnazioni.append(
                    {
                        "id": str(a[0]),
                        "piano_id": str(a[1]) if a[1] is not None else None,
                        "vascello_id": meta.get("vascello_id"),
                        "percorso_id": str(a[2]),
                        "id_corsa": meta.get("id_corsa"),
                        "stato_esecuzione": a[3],
                        "virtuale": a[4],
                    }
                )

            result.append(
                {
                    "id": str(piano_id),
                    "data_riferimento": r[1],
                    "stato": r[2],
                    "kpi_profitto_stimato": r[3],
                    "kpi_robustezza": r[4],
                    "versione": r[5],
                    "assegnazioni": assegnazioni,
                }
            )
        return result
    finally:
        cur.close()
        conn.close()


@app.get("/internal/piano/{piano_id}")
def get_piano_by_id(piano_id: str):
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT id, data_riferimento, stato, kpi_profitto_stimato, kpi_robustezza, versione FROM piano_operativo WHERE id = %s;",
            (piano_id,),
        )
        r = cur.fetchone()
        if not r:
            raise HTTPException(status_code=404, detail="Piano operativo non trovato")
        return {
            "id": str(r[0]),
            "data_riferimento": r[1],
            "stato": r[2],
            "kpi_profitto_stimato": r[3],
            "kpi_robustezza": r[4],
            "versione": r[5],
            "assegnazioni": [],
        }
    finally:
        cur.close()
        conn.close()


@app.get("/internal/assegnazione/by_piano/{piano_id}")
def lista_assegnazioni_by_piano(piano_id: str):
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT a.id, a.piano_id, a.percorso_id, a.stato_esecuzione, a.virtuale, a.orario_completamento
            FROM assegnazione a
            WHERE a.piano_id = %s ORDER BY a.id;
            """,
            (piano_id,),
        )
        rows = cur.fetchall()
        result = []
        for r in rows:
            meta = _percorso_meta(str(r[2]))
            result.append(
                {
                    "id": r[0],
                    "piano_id": r[1],
                    "vascello_id": meta.get("vascello_id"),
                    "percorso_id": r[2],
                    "id_corsa": meta.get("id_corsa"),
                    "stato_esecuzione": r[3],
                    "virtuale": r[4],
                    "orario_completamento": r[5].isoformat() if r[5] else None,
                }
            )
        return result
    finally:
        cur.close()
        conn.close()


@app.get("/internal/assegnazione/{assegnazione_id}")
def get_assegnazione_by_id(assegnazione_id: str):
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT a.id, a.piano_id, a.percorso_id, a.stato_esecuzione, a.virtuale, a.orario_completamento
            FROM assegnazione a
            WHERE a.id = %s
            LIMIT 1;
            """,
            (assegnazione_id,),
        )
        row = cur.fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail=f"Assegnazione non trovata: {assegnazione_id}")

        meta = _percorso_meta(str(row[2]))
        return {
            "id": row[0],
            "piano_id": row[1],
            "vascello_id": meta.get("vascello_id"),
            "percorso_id": row[2],
            "id_corsa": meta.get("id_corsa"),
            "stato_esecuzione": row[3],
            "virtuale": row[4],
            "orario_completamento": row[5].isoformat() if row[5] else None,
        }
    finally:
        cur.close()
        conn.close()


@app.get("/internal/deadhead/lista")
def lista_deadhead(
    piano_id: str | None = Query(None),
    vascello_id: str | None = Query(None),
):
    conn = get_connection()
    cur = conn.cursor()
    try:
        conditions = []
        params = []
        if piano_id:
            conditions.append("piano_id = %s")
            params.append(piano_id)
        if vascello_id:
            conditions.append("vascello_id = %s")
            params.append(vascello_id)

        where_clause = " WHERE " + " AND ".join(conditions) if conditions else ""
        cur.execute(
            "SELECT id, orario_partenza_schedulato, porto_partenza_id, porto_arrivo_id, idle, non_productive_time_min, consumo, vascello_id, piano_id FROM deadhead_trips"
            + where_clause
            + " ORDER BY orario_partenza_schedulato;",
            tuple(params),
        )
        rows = cur.fetchall()
        return [
            {
                "id": str(row[0]),
                "orario_partenza_schedulato": row[1],
                "porto_partenza_id": str(row[2]),
                "porto_arrivo_id": str(row[3]),
                "idle": row[4],
                "non_productive_time_min": float(row[5]) if row[5] is not None else None,
                "consumo": float(row[6]) if row[6] is not None else None,
                "vascello_id": str(row[7]),
                "piano_id": str(row[8]) if row[8] is not None else None,
            }
            for row in rows
        ]
    finally:
        cur.close()
        conn.close()


@app.post("/internal/corsa/crea")
def crea_corsa(data: dict):
    try:
        dt = datetime.strptime(data.get("data"), "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail="Formato data non valido (YYYY-MM-DD)")

    orario_str = str(data.get("orario", "")).strip()
    if ":" in orario_str:
        hhmm = datetime.strptime(orario_str, "%H:%M").strftime("%H%M")
    elif len(orario_str) == 4 and orario_str.isdigit():
        hhmm = orario_str
    else:
        raise HTTPException(status_code=400, detail="Formato orario non valido (HH:MM o HHMM)")

    orario_ts = datetime.strptime(f"{dt.strftime('%Y-%m-%d')} {hhmm}", "%Y-%m-%d %H%M")
    orario_arrivo_ts = None
    if data.get("orario_arrivo_max"):
        arr_str = str(data.get("orario_arrivo_max")).strip()
        if ":" in arr_str:
            arr_hhmm = datetime.strptime(arr_str, "%H:%M").strftime("%H%M")
        elif len(arr_str) == 4 and arr_str.isdigit():
            arr_hhmm = arr_str
        else:
            raise HTTPException(status_code=400, detail="Formato orario_arrivo_max non valido")
        orario_arrivo_ts = datetime.strptime(f"{dt.strftime('%Y-%m-%d')} {arr_hhmm}", "%Y-%m-%d %H%M")

    conn = get_connection()
    cur = conn.cursor()
    try:
        tratta_info = _get_json(ANAGRAFICA_SERVICE_URL, f"/internal/tratta/{data.get('tratta_id')}")
        if tratta_info is None:
            raise HTTPException(status_code=404, detail=f"Tratta non trovata: {data.get('tratta_id')}")
        nome_tratta = tratta_info.get("nome")
        corsa_nome_str = f"{nome_tratta}-{dt.strftime('%Y%m%d')}-{hhmm}"

        cur.execute(
            """
            INSERT INTO corsa (nome, tratta_id, orario_partenza_schedulato, orario_arrivo_max)
            VALUES (%s, %s, %s, %s) RETURNING id;
            """,
            (corsa_nome_str, data.get("tratta_id"), orario_ts, orario_arrivo_ts),
        )
        new_uuid = cur.fetchone()[0]
        conn.commit()
        return {
            "id": str(new_uuid),
            "nome": corsa_nome_str,
            "tratta_id": data.get("tratta_id"),
            "tratta_nome": nome_tratta,
            "data": dt.strftime("%Y-%m-%d"),
            "orario": orario_ts.strftime("%H:%M"),
            "orario_partenza_schedulato": orario_ts.isoformat(),
            "orario_arrivo_max": orario_arrivo_ts.isoformat() if orario_arrivo_ts else None,
        }
    except psycopg2.errors.UniqueViolation:
        conn.rollback()
        raise HTTPException(status_code=409, detail="Corsa già esistente")
    finally:
        cur.close()
        conn.close()


@app.post("/internal/corsa/modifica")
def modifica_corsa(data: dict):
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT tratta_id, orario_partenza_schedulato, orario_arrivo_max
            FROM corsa
            WHERE id = %s
            """,
            (data.get("id"),),
        )
        row_current = cur.fetchone()
        if row_current is None:
            raise HTTPException(404, "Corsa non trovata")

        current_tratta_id, current_ts, current_arr_max = row_current
        final_tratta_id = data.get("tratta_id") if data.get("tratta_id") else str(current_tratta_id)

        if data.get("data"):
            try:
                final_date_obj = datetime.strptime(data.get("data"), "%Y-%m-%d").date()
            except ValueError:
                raise HTTPException(400, "Formato data non valido (usa YYYY-MM-DD)")
        else:
            final_date_obj = current_ts.date()

        if data.get("orario"):
            raw_time = str(data.get("orario")).strip()
            if ":" in raw_time:
                try:
                    final_hhmm = datetime.strptime(raw_time, "%H:%M").strftime("%H%M")
                except ValueError:
                    raise HTTPException(400, "Formato orario non valido")
            elif len(raw_time) == 4 and raw_time.isdigit():
                final_hhmm = raw_time
            else:
                raise HTTPException(400, "Formato orario non valido (usa HH:MM o HHMM)")
        else:
            final_hhmm = current_ts.strftime("%H%M")

        final_ts = datetime.strptime(f"{final_date_obj.strftime('%Y-%m-%d')} {final_hhmm}", "%Y-%m-%d %H%M")

        if data.get("orario_arrivo_max"):
            raw_arr = str(data.get("orario_arrivo_max")).strip()
            if ":" in raw_arr:
                arr_hhmm = datetime.strptime(raw_arr, "%H:%M").strftime("%H%M")
            elif len(raw_arr) == 4 and raw_arr.isdigit():
                arr_hhmm = raw_arr
            else:
                raise HTTPException(400, "Formato orario arrivo non valido")
            final_arr_ts = datetime.strptime(f"{final_date_obj.strftime('%Y-%m-%d')} {arr_hhmm}", "%Y-%m-%d %H%M")
        else:
            final_arr_ts = current_arr_max

        tratta_info = _get_json(ANAGRAFICA_SERVICE_URL, f"/internal/tratta/{final_tratta_id}")
        if not tratta_info:
            raise HTTPException(404, f"Tratta non trovata: {final_tratta_id}")
        nome_tratta = tratta_info.get("nome")

        nuovo_nome_corsa = f"{nome_tratta}-{final_date_obj.strftime('%Y%m%d')}-{final_hhmm}"

        cur.execute(
            """
            UPDATE corsa
            SET nome = %s, tratta_id = %s, orario_partenza_schedulato = %s, orario_arrivo_max = %s
            WHERE id = %s
            RETURNING id;
            """,
            (nuovo_nome_corsa, final_tratta_id, final_ts, final_arr_ts, data.get("id")),
        )
        row = cur.fetchone()
        conn.commit()

        if row is None:
            raise HTTPException(404, "Corsa non trovata durante l'aggiornamento")

        return {
            "id": data.get("id"),
            "nome": nuovo_nome_corsa,
            "tratta_id": final_tratta_id,
            "tratta_nome": nome_tratta,
            "data": final_date_obj.strftime("%Y-%m-%d"),
            "orario": final_hhmm[:2] + ":" + final_hhmm[2:],
            "orario_partenza_schedulato": final_ts.isoformat(),
            "orario_arrivo_max": final_arr_ts.isoformat() if final_arr_ts else None,
        }
    except psycopg2.Error as exc:
        conn.rollback()
        raise HTTPException(500, f"Errore Database: {exc}")
    finally:
        cur.close()
        conn.close()


@app.post("/internal/corsa/elimina")
def elimina_corsa(data: dict):
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("DELETE FROM corsa WHERE id = %s RETURNING id;", (data.get("id"),))
        row = cur.fetchone()
        conn.commit()
        if row is None:
            raise HTTPException(404, "Corsa non trovata")
        return {"id": data.get("id"), "esito": "eliminato"}
    finally:
        cur.close()
        conn.close()


@app.post("/internal/piano/crea")
def crea_piano(data: dict):
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            """
            INSERT INTO piano_operativo (data_riferimento, stato, kpi_profitto_stimato, kpi_robustezza, versione)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING id;
            """,
            (data.get("data_riferimento"), data.get("stato"), data.get("kpi_profitto_stimato"), data.get("kpi_robustezza"), data.get("versione")),
        )
        piano_id = cur.fetchone()[0]
        conn.commit()
        return {
            "id": piano_id,
            "data_riferimento": data.get("data_riferimento"),
            "stato": data.get("stato"),
            "kpi_profitto_stimato": data.get("kpi_profitto_stimato"),
            "kpi_robustezza": data.get("kpi_robustezza"),
            "versione": data.get("versione"),
        }
    except psycopg2.errors.UniqueViolation:
        conn.rollback()
        raise HTTPException(status_code=409, detail="Piano operativo già esistente")
    finally:
        cur.close()
        conn.close()


@app.post("/internal/piano/modifica")
def modifica_piano(data: dict):
    conn = get_connection()
    cur = conn.cursor()
    try:
        updates = []
        params = []
        if data.get("data_riferimento") is not None:
            updates.append("data_riferimento = %s")
            params.append(data.get("data_riferimento"))
        if data.get("stato") is not None:
            updates.append("stato = %s")
            params.append(data.get("stato"))
        if data.get("kpi_profitto_stimato") is not None:
            updates.append("kpi_profitto_stimato = %s")
            params.append(data.get("kpi_profitto_stimato"))
        if data.get("kpi_robustezza") is not None:
            updates.append("kpi_robustezza = %s")
            params.append(data.get("kpi_robustezza"))
        if data.get("versione") is not None:
            updates.append("versione = %s")
            params.append(data.get("versione"))

        if not updates:
            raise HTTPException(status_code=400, detail="Nessun campo da aggiornare")

        params.append(data.get("id"))
        sql = "UPDATE piano_operativo SET " + ", ".join(updates) + " WHERE id = %s RETURNING id, data_riferimento, stato, kpi_profitto_stimato, kpi_robustezza, versione;"
        cur.execute(sql, tuple(params))
        row = cur.fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Piano operativo non trovato")
        conn.commit()
        return {
            "id": row[0],
            "data_riferimento": row[1],
            "stato": row[2],
            "kpi_profitto_stimato": row[3],
            "kpi_robustezza": row[4],
            "versione": row[5],
        }
    except psycopg2.errors.UniqueViolation:
        conn.rollback()
        raise HTTPException(status_code=409, detail="Conflitto durante aggiornamento piano operativo")
    finally:
        cur.close()
        conn.close()


@app.post("/internal/piano/elimina")
def elimina_piano(data: dict):
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("DELETE FROM piano_operativo WHERE id = %s RETURNING id;", (data.get("id"),))
        row = cur.fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Piano operativo non trovato")
        conn.commit()
        return {"id": row[0]}
    finally:
        cur.close()
        conn.close()


@app.post("/internal/assegnazione/crea")
def crea_assegnazione(data: dict):
    conn = get_connection()
    cur = conn.cursor()
    try:
        virtuale_val = data.get("virtuale") if data.get("virtuale") is not None else False
        cur.execute(
            """
            INSERT INTO assegnazione (piano_id, percorso_id, stato_esecuzione, virtuale)
            VALUES (%s, %s, %s, %s)
            RETURNING id;
            """,
            (data.get("piano_id"), data.get("percorso_id"), data.get("stato_esecuzione"), virtuale_val),
        )
        assegnazione_id = cur.fetchone()[0]

        conn.commit()

        cur.execute(
            """
            SELECT a.id, a.piano_id, a.percorso_id, a.stato_esecuzione, a.virtuale, a.orario_completamento
            FROM assegnazione a
            WHERE a.id = %s;
            """,
            (assegnazione_id,),
        )
        row = cur.fetchone()
        meta = _percorso_meta(str(row[2])) if row else {"vascello_id": None, "id_corsa": None}
        return {
            "id": row[0],
            "piano_id": row[1],
            "vascello_id": meta.get("vascello_id"),
            "percorso_id": row[2],
            "id_corsa": meta.get("id_corsa"),
            "stato_esecuzione": row[3],
            "virtuale": row[4],
            "orario_completamento": row[5].isoformat() if row[5] else None,
        }
    except psycopg2.errors.UniqueViolation:
        conn.rollback()
        raise HTTPException(status_code=409, detail="Esiste già un'assegnazione IN_CORSO per questo vascello")
    finally:
        cur.close()
        conn.close()


@app.patch("/internal/assegnazione/{assegnazione_id}/stato")
def aggiorna_stato_assegnazione(assegnazione_id: str, data: dict):
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            """
            UPDATE assegnazione SET stato_esecuzione = %s WHERE id = %s;
            SELECT a.id, a.piano_id, a.percorso_id, a.stato_esecuzione, a.virtuale, a.orario_completamento
            FROM assegnazione a
            WHERE a.id = %s;
            """,
            (data.get("stato_esecuzione"), assegnazione_id, assegnazione_id),
        )
        conn.commit()
        row = cur.fetchone()
        if row is None:
            raise HTTPException(404, "Assegnazione non trovata")
        meta = _percorso_meta(str(row[2]))
        return {
            "id": row[0],
            "piano_id": row[1],
            "vascello_id": meta.get("vascello_id"),
            "percorso_id": row[2],
            "id_corsa": meta.get("id_corsa"),
            "stato_esecuzione": row[3],
            "virtuale": row[4],
            "orario_completamento": row[5].isoformat() if row[5] else None,
        }
    except psycopg2.errors.UniqueViolation:
        conn.rollback()
        raise HTTPException(status_code=409, detail="Un'altra assegnazione IN_CORSO esiste già per questo vascello")
    finally:
        cur.close()
        conn.close()


@app.post("/internal/assegnazione/bulk")
def crea_assegnazioni_bulk(data: dict):
    conn = get_connection()
    cur = conn.cursor()
    risultati = []
    try:
        for item in data.get("percorsi", []):
            cur.execute(
                """
                INSERT INTO assegnazione (piano_id, percorso_id, stato_esecuzione, virtuale)
                VALUES (%s, %s, %s, %s)
                RETURNING id;
                """,
                (data.get("piano_id"), item.get("percorso_id"), "PIANIFICATA", item.get("virtuale")),
            )
            assegnazione_id = cur.fetchone()[0]
            risultati.append(
                {
                    "assegnazione_id": str(assegnazione_id),
                    "percorso_id": item.get("percorso_id"),
                    "virtuale": item.get("virtuale"),
                }
            )

        conn.commit()
        return {
            "piano_id": data.get("piano_id"),
            "assegnazioni_create": len(risultati),
            "risultati": risultati,
        }
    except psycopg2.errors.UniqueViolation:
        conn.rollback()
        raise HTTPException(status_code=409, detail="Una o più assegnazioni esistono già per i percorsi specificati")
    finally:
        cur.close()
        conn.close()


@app.post("/internal/assegnazione/in_corso2cancellata")
def cancella_assegnazioni_virtuali_in_corso():
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            """
            UPDATE assegnazione
            SET stato_esecuzione = %s
            WHERE stato_esecuzione = %s AND virtuale = true;
            """,
            ("CANCELLATA", "IN_CORSO"),
        )
        count = cur.rowcount
        conn.commit()
        return {"messaggio": f"Aggiornate {count} assegnazioni", "updated_count": count}
    finally:
        cur.close()
        conn.close()


def _deadhead_row_to_dict(row):
    return {
        "id": str(row[0]),
        "orario_partenza_schedulato": row[1],
        "porto_partenza_id": str(row[2]),
        "porto_arrivo_id": str(row[3]),
        "idle": row[4],
        "non_productive_time_min": float(row[5]) if row[5] is not None else None,
        "consumo": float(row[6]) if row[6] is not None else None,
        "vascello_id": str(row[7]),
        "piano_id": str(row[8]) if row[8] is not None else None,
    }


@app.post("/internal/deadhead/crea")
def crea_deadhead(data: dict):
    conn = get_connection()
    cur = conn.cursor()
    try:
        idle_val = data.get("idle") if data.get("idle") is not None else False
        cur.execute(
            """
            INSERT INTO deadhead_trips (
                orario_partenza_schedulato, porto_partenza_id, porto_arrivo_id,
                idle, non_productive_time_min, consumo, vascello_id, piano_id
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id, orario_partenza_schedulato, porto_partenza_id, porto_arrivo_id,
                      idle, non_productive_time_min, consumo, vascello_id, piano_id;
            """,
            (
                data.get("orario_partenza_schedulato"),
                data.get("porto_partenza_id"),
                data.get("porto_arrivo_id"),
                idle_val,
                data.get("non_productive_time_min"),
                data.get("consumo"),
                data.get("vascello_id"),
                data.get("piano_id"),
            ),
        )
        row = cur.fetchone()
        conn.commit()
        return _deadhead_row_to_dict(row)
    except psycopg2.errors.ForeignKeyViolation:
        conn.rollback()
        raise HTTPException(status_code=400, detail="Porto, vascello o piano operativo non trovato")
    finally:
        cur.close()
        conn.close()


@app.post("/internal/deadhead/modifica")
def modifica_deadhead(data: dict):
    conn = get_connection()
    cur = conn.cursor()
    try:
        updates = []
        params = []
        if data.get("orario_partenza_schedulato") is not None:
            updates.append("orario_partenza_schedulato = %s")
            params.append(data.get("orario_partenza_schedulato"))
        if data.get("porto_partenza_id") is not None:
            updates.append("porto_partenza_id = %s")
            params.append(data.get("porto_partenza_id"))
        if data.get("porto_arrivo_id") is not None:
            updates.append("porto_arrivo_id = %s")
            params.append(data.get("porto_arrivo_id"))
        if data.get("idle") is not None:
            updates.append("idle = %s")
            params.append(data.get("idle"))
        if data.get("non_productive_time_min") is not None:
            updates.append("non_productive_time_min = %s")
            params.append(data.get("non_productive_time_min"))
        if data.get("consumo") is not None:
            updates.append("consumo = %s")
            params.append(data.get("consumo"))
        if data.get("vascello_id") is not None:
            updates.append("vascello_id = %s")
            params.append(data.get("vascello_id"))
        if data.get("piano_id") is not None:
            updates.append("piano_id = %s")
            params.append(data.get("piano_id"))

        if not updates:
            raise HTTPException(status_code=400, detail="Nessun campo da aggiornare")

        params.append(data.get("id"))
        sql = (
            "UPDATE deadhead_trips SET "
            + ", ".join(updates)
            + " WHERE id = %s RETURNING id, orario_partenza_schedulato, porto_partenza_id, porto_arrivo_id,"
            + " idle, non_productive_time_min, consumo, vascello_id, piano_id;"
        )
        cur.execute(sql, tuple(params))
        row = cur.fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Deadhead trip non trovato")
        conn.commit()
        return _deadhead_row_to_dict(row)
    except psycopg2.errors.ForeignKeyViolation:
        conn.rollback()
        raise HTTPException(status_code=400, detail="Porto, vascello o piano operativo non trovato")
    finally:
        cur.close()
        conn.close()


@app.post("/internal/deadhead/elimina")
def elimina_deadhead(data: dict):
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("DELETE FROM deadhead_trips WHERE id = %s RETURNING id;", (data.get("id"),))
        row = cur.fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Deadhead trip non trovato")
        conn.commit()
        return {"id": str(row[0]), "esito": "eliminato"}
    finally:
        cur.close()
        conn.close()
