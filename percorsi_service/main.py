import os
import json
import random
import math
import uuid
from datetime import datetime, timedelta
from fastapi import FastAPI, HTTPException, Query, Path
import psycopg2
import requests

DB_CONN = os.getenv("PERCORSI_DB_CONN", "dbname=percorsi_db user=postgres password=admin host=localhost")
OPERATIVO_SERVICE_URL = os.getenv("OPERATIVO_SERVICE_URL", "http://operativo:8072")
ANAGRAFICA_SERVICE_URL = os.getenv("ANAGRAFICA_SERVICE_URL", "http://anagrafica:8070")

app = FastAPI(title="Percorsi Internal Service", version="0.1.0")

ALLOWED_ORDER_BY = {"tempo_percorrenza_min", "consumo", "created_at", "pref", "vref", "comfort", "distanza_nm"}
ALLOWED_INCLUDES = {"corsa", "tratta", "vascello"}


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


def _parse_iso_datetime(value: str | None):
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


@app.get("/health")
def health():
    return {"status": "ok", "service": "percorsi"}


@app.get("/internal/percorso/{percorso_id}")
def get_percorso(percorso_id: str, include: str | None = Query(None)):
    includes = set(s.strip() for s in include.split(",")) if include else set()
    invalid = includes - ALLOWED_INCLUDES
    if invalid:
        raise HTTPException(400, f"include non valido: {sorted(invalid)}. Ammessi: {sorted(ALLOWED_INCLUDES)}")

    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT p.id, p.id_corsa, p.pref, p.vref,
                   EXTRACT(EPOCH FROM p.tempo_percorrenza_min)/60.0 AS tempo_percorrenza_min,
                   p.consumo, ST_AsGeoJSON(p.geom_rotta), p.vascello_id, p.comfort, p.distanza_nm
            FROM percorso p
            WHERE p.id = %s
            LIMIT 1;
            """,
            (percorso_id,),
        )
        row = cur.fetchone()
        if row is None:
            raise HTTPException(404, f"Percorso non trovato: {percorso_id}")

        pid, corsa_id, pref, vref, tempo_perc_min, consumo, geom_rotta, vascello_id, comfort, distanza_nm = row
        response = {
            "percorso_id": str(pid),
            "corsa_id": str(corsa_id),
            "vascello_id": str(vascello_id) if vascello_id else None,
            "pref": pref,
            "vref": vref,
            "tempo_percorrenza": tempo_perc_min,
            "consumo": consumo,
            "geom_rotta": geom_rotta,
            "comfort": comfort,
            "distanza_nm": distanza_nm,
        }

        tratta_id = None
        corsa_data = None
        if includes & {"corsa", "tratta"}:
            corsa_data = _get_json(OPERATIVO_SERVICE_URL, f"/internal/corsa/id/{corsa_id}")
            if corsa_data:
                tratta_id = corsa_data.get("tratta_id")
                previsione_data = corsa_data.get("previsione")
                previsione_obj = None
                if previsione_data:
                    previsione_obj = {
                        "id": previsione_data.get("id"),
                        "passeggeri_stimati": previsione_data.get("passeggeri_stimati"),
                        "confidenza_min": previsione_data.get("confidenza_min"),
                        "confidenza_max": previsione_data.get("confidenza_max"),
                        "created_at": None,
                    }
                if "corsa" in includes:
                    response["corsa"] = {
                        "id": corsa_data.get("id"),
                        "nome": corsa_data.get("nome"),
                        "tratta_id": corsa_data.get("tratta_id"),
                        "tratta_nome": corsa_data.get("tratta_nome"),
                        "orario_partenza_schedulato": corsa_data.get("orario_partenza_schedulato"),
                        "orario_arrivo_max": corsa_data.get("orario_arrivo_max"),
                        "previsione_domanda_id": corsa_data.get("previsione_domanda_id"),
                        "previsione": previsione_obj,
                    }

        if "vascello" in includes and vascello_id:
            v = _get_json(ANAGRAFICA_SERVICE_URL, f"/internal/vascello/{vascello_id}")
            if v:
                response["vascello"] = {
                    "id": v.get("id"),
                    "mmsi": v.get("mmsi"),
                    "nome": v.get("nome"),
                    "capacita_passeggeri": v.get("capacita_passeggeri"),
                    "costo_orario_esercizio": v.get("costo_orario_esercizio"),
                    "velocita_max_nodi": v.get("velocita_max_nodi"),
                    "stato_salute_aggregato": v.get("stato_salute_aggregato"),
                    "profilo_consumo_json": v.get("profilo_consumo_json"),
                    "data_creazione": v.get("data_creazione"),
                }

        if "tratta" in includes and tratta_id:
            t = _get_json(ANAGRAFICA_SERVICE_URL, f"/internal/tratta/{tratta_id}")
            if t:
                response["tratta"] = {
                    "id": t.get("id"),
                    "nome": t.get("nome"),
                    "porto_partenza_id": t.get("porto_partenza_id"),
                    "porto_arrivo_id": t.get("porto_arrivo_id"),
                    "distanza_miglia": t.get("distanza_miglia"),
                    "porti_intermedi": t.get("porti_intermedi"),
                    "tratta_multiporto": t.get("tratta_multiporto"),
                    "geometry": t.get("geometry"),
                }

        return response
    finally:
        cur.close()
        conn.close()


@app.get("/internal/percorso/by_corsa/{corsa_id}")
def get_percorsi_by_corsa(
    corsa_id: str = Path(...),
    order_by: str = Query("tempo_percorrenza_min"),
    mode: str = Query("ASC"),
    limit: int = Query(100, ge=1),
    vascello_id: str | None = Query(None),
    include: str | None = Query(None),
):
    if order_by not in ALLOWED_ORDER_BY:
        raise HTTPException(400, detail=f"order_by non valido. Valori ammessi: {sorted(ALLOWED_ORDER_BY)}")
    includes = set(s.strip() for s in include.split(",")) if include else set()
    invalid = includes - ALLOWED_INCLUDES
    if invalid:
        raise HTTPException(400, f"include non valido: {sorted(invalid)}. Ammessi: {sorted(ALLOWED_INCLUDES)}")

    conn = get_connection()
    cur = conn.cursor()
    try:
        where_clauses = ["id_corsa = %s"]
        params = [corsa_id]
        if vascello_id is not None:
            where_clauses.append("vascello_id = %s")
            params.append(vascello_id)
        params.append(limit)

        query = f"""
            SELECT p.id, p.id_corsa, p.pref, p.vref, EXTRACT(EPOCH FROM p.tempo_percorrenza_min)/60.0 AS tempo_percorrenza_min,
                   p.consumo, ST_AsGeoJSON(p.geom_rotta), p.created_at,
                   p.vascello_id, p.comfort, p.distanza_nm
            FROM percorso p
            WHERE {' AND '.join(where_clauses)}
            ORDER BY {order_by} {mode}
            LIMIT %s;
        """
        cur.execute(query, params)
        rows = cur.fetchall()

        if not rows:
            raise HTTPException(404, detail=f"Nessun percorso trovato per corsa_id: {corsa_id}")

        corsa_data = _get_json(OPERATIVO_SERVICE_URL, f"/internal/corsa/id/{corsa_id}")
        orario_partenza_schedulato = _parse_iso_datetime(corsa_data.get("orario_partenza_schedulato") if corsa_data else None)
        previsione = corsa_data.get("previsione") if corsa_data else None

        vascelli_cache = {}
        percorsi = []
        for r in rows:
            (
                pid, cid, pref, vref, tempo_perc_min, consumo, geom_rotta,
                created_at, vessel_id, comfort, distanza_nm,
            ) = r

            capacita_passeggeri = None
            if vessel_id:
                vessel_key = str(vessel_id)
                if vessel_key not in vascelli_cache:
                    v_data = _get_json(ANAGRAFICA_SERVICE_URL, f"/internal/vascello/{vessel_key}")
                    vascelli_cache[vessel_key] = v_data
                v_data = vascelli_cache[vessel_key]
                if v_data:
                    capacita_passeggeri = v_data.get("capacita_passeggeri")

            previsione_previsti = previsione.get("passeggeri_stimati") if previsione else None
            confidenza_min = previsione.get("confidenza_min") if previsione else None
            confidenza_max = previsione.get("confidenza_max") if previsione else None
            previsione_data = None

            orario_arrivo_previsto = None
            if orario_partenza_schedulato is not None and tempo_perc_min is not None:
                try:
                    orario_arrivo_previsto = (orario_partenza_schedulato + timedelta(minutes=float(tempo_perc_min))).isoformat()
                except Exception:
                    orario_arrivo_previsto = None

            item = {
                "id": str(pid),
                "corsa_id": str(cid),
                "vascello_id": str(vessel_id) if vessel_id else None,
                "created_at": created_at.isoformat() if created_at else None,
                "orario_partenza_schedulato": orario_partenza_schedulato.isoformat() if orario_partenza_schedulato else None,
                "tempo_percorrenza": tempo_perc_min,
                "orario_arrivo_previsto": orario_arrivo_previsto,
                "passeggeri": {
                    "capacita_vascello": capacita_passeggeri,
                    "previsione_confidenza_min": confidenza_min,
                    "previsione_confidenza_max": confidenza_max,
                    "previsti": previsione_previsti,
                    "data_previsione": previsione_data.isoformat() if previsione_data is not None else None,
                },
                "consumo": consumo,
                "comfort": comfort,
                "distanza_nm": distanza_nm,
                "pref": pref,
                "vref": vref,
                "geom_rotta": geom_rotta,
            }
            percorsi.append(item)

        return {"corsa_id": corsa_id, "percorsi": percorsi}
    finally:
        cur.close()
        conn.close()


@app.post("/internal/percorso/elimina")
def elimina_percorso(payload: dict):
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT id FROM percorso WHERE id = %s", (payload.get("id"),))
        row = cur.fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail=f"Percorso non trovato: {payload.get('id')}")
        cur.execute("DELETE FROM percorso WHERE id = %s", (payload.get("id"),))
        conn.commit()
        return {"status": "ok", "percorso_id": payload.get("id")}
    finally:
        cur.close()
        conn.close()


@app.post("/internal/percorso/crea_batch")
def crea_percorsi_batch(payload: dict):
    items = payload.get("items") if isinstance(payload, dict) else None
    if not isinstance(items, list) or not items:
        raise HTTPException(status_code=400, detail="Payload non valido: 'items' deve essere una lista non vuota")

    conn = get_connection()
    cur = conn.cursor()
    inserted_ids = []
    try:
        for item in items:
            required = {"id_corsa", "vascello_id", "pref", "vref", "tempo_percorrenza_min", "tempo_riposizionamento_min", "consumo", "geom_rotta", "consumo_riposizionamento", "distanza_nm", "comfort"}
            if not isinstance(item, dict) or not required.issubset(item.keys()):
                raise HTTPException(status_code=400, detail="Item percorso incompleto nel batch")

            cur.execute(
                """
                INSERT INTO percorso (
                    id_corsa, pref, vref,
                    tempo_percorrenza_min, tempo_riposizionamento_min,
                    consumo, geom_rotta, vascello_id,
                    consumo_riposizionamento, distanza_nm, comfort
                )
                VALUES (
                    %s, %s::jsonb, %s::jsonb,
                    (%s * interval '1 minute'),
                    (%s * interval '1 minute'),
                    %s,
                    ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326),
                    %s, %s, %s, %s
                )
                RETURNING id;
                """,
                (
                    item["id_corsa"],
                    json.dumps(item["pref"]),
                    json.dumps(item["vref"]),
                    float(item["tempo_percorrenza_min"]),
                    float(item["tempo_riposizionamento_min"]),
                    float(item["consumo"]),
                    json.dumps(item["geom_rotta"]),
                    item["vascello_id"],
                    float(item["consumo_riposizionamento"]),
                    float(item["distanza_nm"]),
                    float(item["comfort"]),
                ),
            )
            inserted_ids.append(str(cur.fetchone()[0]))

        conn.commit()
        return {"status": "ok", "percorsi_inseriti": inserted_ids}
    except HTTPException:
        conn.rollback()
        raise
    except Exception as exc:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"Errore inserimento percorsi batch: {str(exc)}")
    finally:
        cur.close()
        conn.close()


def _calcola_punto_deviato(lon1: float, lat1: float, lon2: float, lat2: float, offset_nm: float):
    mid_lon = (lon1 + lon2) / 2
    mid_lat = (lat1 + lat2) / 2
    dx = lon2 - lon1
    dy = lat2 - lat1
    length = math.sqrt(dx * dx + dy * dy)
    if length < 1e-9:
        return mid_lon, mid_lat
    perp_x = -dy / length
    perp_y = dx / length
    offset_deg = offset_nm / 60.0
    direction = random.choice([-1, 1])
    new_lon = mid_lon + direction * perp_x * offset_deg
    new_lat = mid_lat + direction * perp_y * offset_deg
    return new_lon, new_lat


def _applica_variazione_guasto(coords, vref_arr, pref_arr):
    candidati = [i for i, v in enumerate(vref_arr) if v is not None and v > 0]
    if not candidati:
        raise HTTPException(status_code=400, detail="Nessun waypoint con vref valido trovato per applicare il guasto")
    idx_guasto = random.choice(candidati)
    vref_originale = vref_arr[idx_guasto]
    vref_nuovo = vref_originale / 8.0
    new_vref = vref_arr.copy()
    new_vref[idx_guasto] = vref_nuovo
    return {
        "coords": coords,
        "vref": new_vref,
        "pref": pref_arr,
        "dettagli": {
            "waypoint_index": idx_guasto,
            "waypoint_coords": coords[idx_guasto] if idx_guasto < len(coords) else None,
            "vref_originale": vref_originale,
            "vref_modificato": vref_nuovo,
            "fattore_riduzione": 8,
        },
    }


def _applica_variazione_deviazione(coords, vref_arr, pref_arr, offset_nm: float):
    if len(coords) < 2:
        raise HTTPException(status_code=400, detail="Percorso troppo corto per applicare una deviazione (minimo 2 waypoint)")
    max_idx = len(coords) - 2
    if max_idx < 0:
        max_idx = 0
    idx_inizio = random.randint(0, max_idx)
    lon1, lat1 = coords[idx_inizio]
    lon2, lat2 = coords[idx_inizio + 1]
    new_lon, new_lat = _calcola_punto_deviato(lon1, lat1, lon2, lat2, offset_nm)
    new_coords = coords[: idx_inizio + 1] + [[new_lon, new_lat]] + coords[idx_inizio + 1 :]

    vref1 = vref_arr[idx_inizio] if idx_inizio < len(vref_arr) and vref_arr[idx_inizio] is not None else None
    vref2 = vref_arr[idx_inizio + 1] if idx_inizio + 1 < len(vref_arr) and vref_arr[idx_inizio + 1] is not None else None
    if vref1 is not None and vref2 is not None:
        new_vref_value = (vref1 + vref2) / 2
    elif vref1 is not None:
        new_vref_value = vref1
    elif vref2 is not None:
        new_vref_value = vref2
    else:
        new_vref_value = None

    pref1 = pref_arr[idx_inizio] if idx_inizio < len(pref_arr) and pref_arr[idx_inizio] is not None else None
    pref2 = pref_arr[idx_inizio + 1] if idx_inizio + 1 < len(pref_arr) and pref_arr[idx_inizio + 1] is not None else None
    if pref1 is not None and pref2 is not None:
        new_pref_value = (pref1 + pref2) / 2
    elif pref1 is not None:
        new_pref_value = pref1
    elif pref2 is not None:
        new_pref_value = pref2
    else:
        new_pref_value = None

    new_vref = vref_arr[: idx_inizio + 1] + [new_vref_value] + vref_arr[idx_inizio + 1 :]
    new_pref = pref_arr[: idx_inizio + 1] + [new_pref_value] + pref_arr[idx_inizio + 1 :]

    return {
        "coords": new_coords,
        "vref": new_vref,
        "pref": new_pref,
        "dettagli": {
            "segmento_iniziale_index": idx_inizio,
            "waypoint_originale_1": [lon1, lat1],
            "waypoint_originale_2": [lon2, lat2],
            "waypoint_inserito": [new_lon, new_lat],
            "offset_nm": offset_nm,
            "vref_interpolato": new_vref_value,
            "pref_interpolato": new_pref_value,
        },
    }


@app.post("/internal/percorso/applica_variazione")
def applica_variazione_percorso(data: dict):
    conn = get_connection()
    cur = conn.cursor()
    tipo_variazione = str(data.get("tipo_variazione", "")).upper().strip()
    if tipo_variazione not in ["GUASTO", "DEVIAZIONE"]:
        raise HTTPException(status_code=400, detail=f"Tipo variazione non supportato: {data.get('tipo_variazione')}. Valori ammessi: GUASTO, DEVIAZIONE")

    try:
        cur.execute(
            """
            SELECT id, id_corsa, pref, vref, tempo_percorrenza_min, consumo,
                   ST_AsGeoJSON(geom_rotta), vascello_id, comfort, distanza_nm
            FROM percorso
            WHERE id = %s
            """,
            (data.get("percorso_id"),),
        )
        row = cur.fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail=f"Percorso non trovato: {data.get('percorso_id')}")

        percorso_id, corsa_id, pref_arr, vref_arr, tempo_percorrenza, consumo, geom_json, vascello_id, comfort, distanza_nm = row
        geom = json.loads(geom_json)
        coords = geom.get("coordinates", [])

        if vref_arr is None:
            vref_arr = [None] * len(coords)
        else:
            vref_arr = list(vref_arr)

        if pref_arr is None:
            pref_arr = [None] * len(coords)
        else:
            pref_arr = list(pref_arr)

        if tipo_variazione == "GUASTO":
            risultato = _applica_variazione_guasto(coords, vref_arr, pref_arr)
        else:
            risultato = _applica_variazione_deviazione(coords, vref_arr, pref_arr, float(data.get("offset_deviazione_nm", 0.5)))

        new_geom = {"type": "LineString", "coordinates": risultato["coords"]}
        new_geom_json = json.dumps(new_geom)
        nuovo_percorso_id = str(uuid.uuid4())
        new_vref_json = json.dumps(risultato["vref"])
        new_pref_json = json.dumps(risultato["pref"])

        cur.execute(
            """
            INSERT INTO percorso (
                id, id_corsa, pref, vref, tempo_percorrenza_min, consumo, geom_rotta,
                vascello_id, comfort, distanza_nm
            ) VALUES (
                %s, %s, %s::jsonb, %s::jsonb, %s, %s,
                ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326),
                %s, %s, %s
            )
            """,
            (
                nuovo_percorso_id,
                corsa_id,
                new_pref_json,
                new_vref_json,
                tempo_percorrenza,
                consumo,
                new_geom_json,
                vascello_id,
                comfort,
                distanza_nm,
            ),
        )

        conn.commit()
        return {
            "status": "ok",
            "percorso_originale_id": str(percorso_id),
            "percorso_variato_id": nuovo_percorso_id,
            "tipo_variazione": tipo_variazione,
            "dettagli_variazione": risultato["dettagli"],
            "messaggio": f"Variazione {tipo_variazione} applicata con successo. Nuovo percorso creato.",
        }
    except HTTPException:
        conn.rollback()
        raise
    except Exception as exc:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"Errore durante l'applicazione della variazione: {str(exc)}")
    finally:
        cur.close()
        conn.close()
