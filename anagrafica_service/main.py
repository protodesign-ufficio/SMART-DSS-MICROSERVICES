import os
import json
import uuid
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
import psycopg2
import requests

DB_CONN = os.getenv("ANAGRAFICA_DB_CONN", "dbname=anagrafica_db user=postgres password=admin host=localhost")
OPERATIVO_SERVICE_URL = os.getenv("OPERATIVO_SERVICE_URL", "http://operativo:8072")

app = FastAPI(title="Anagrafica Internal Service", version="0.1.0")


def get_connection():
    return psycopg2.connect(DB_CONN)


def _post_json(base_url: str, path: str, payload: dict, timeout: float = 6.0):
    url = f"{base_url.rstrip('/')}{path}"
    try:
        response = requests.post(url, json=payload, timeout=timeout)
    except requests.RequestException:
        return None  # fallback silenzioso: il cascade è best-effort
    if response.status_code >= 400:
        return None
    try:
        return response.json()
    except Exception:
        return None


@app.get("/health")
def health():
    return {"status": "ok", "service": "anagrafica"}


@app.get("/internal/porto/lista")
def lista_porti():
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT id, nome, ST_Y(coordinate_gps), ST_X(coordinate_gps)
            FROM porto
            ORDER BY nome;
        """)
        rows = cur.fetchall()
        return [{"id": r[0], "nome": r[1], "lat": r[2], "lon": r[3]} for r in rows]
    finally:
        cur.close()
        conn.close()


@app.get("/internal/porto/{porto_id}")
def get_porto(porto_id: str):
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT id, nome, ST_Y(coordinate_gps), ST_X(coordinate_gps)
            FROM porto
            WHERE id = %s
        """, (porto_id,))
        row = cur.fetchone()
        if row is None:
            raise HTTPException(404, "Porto non trovato")
        return {"id": row[0], "nome": row[1], "lat": row[2], "lon": row[3]}
    finally:
        cur.close()
        conn.close()


@app.get("/internal/porto/by_name/{nome}")
def get_porto_by_name(nome: str):
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT id, nome, ST_Y(coordinate_gps), ST_X(coordinate_gps)
            FROM porto
            WHERE LOWER(nome) = LOWER(%s)
            LIMIT 1;
        """, (nome,))
        row = cur.fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail=f"Nessun porto trovato con nome='{nome}'")
        return {"id": row[0], "nome": row[1], "lat": row[2], "lon": row[3]}
    finally:
        cur.close()
        conn.close()


@app.post("/internal/porto/crea")
def crea_porto(data: dict):
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO porto (id, nome, coordinate_gps)
            VALUES (
                gen_random_uuid(),
                %s,
                ST_SetSRID(ST_Point(%s, %s), 4326)
            )
            RETURNING id;
        """, (data.get("nome"), data.get("lon"), data.get("lat")))
        porto_id = cur.fetchone()[0]
        conn.commit()
        return {
            "id": porto_id,
            "nome": data.get("nome"),
            "lat": data.get("lat"),
            "lon": data.get("lon")
        }
    finally:
        cur.close()
        conn.close()


@app.post("/internal/porto/modifica")
def modifica_porto(data: dict):
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            UPDATE porto
            SET nome = %s, coordinate_gps = ST_SetSRID(ST_Point(%s, %s), 4326)
            WHERE id = %s
            RETURNING id, nome, ST_Y(coordinate_gps), ST_X(coordinate_gps);
        """, (data.get("nome"), data.get("lon"), data.get("lat"), data.get("id")))
        row = cur.fetchone()
        conn.commit()
        if row is None:
            raise HTTPException(404, "Porto non trovato")
        return {"id": row[0], "nome": row[1], "lat": row[2], "lon": row[3]}
    finally:
        cur.close()
        conn.close()


@app.post("/internal/porto/elimina")
def elimina_porto(data: dict):
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("DELETE FROM porto WHERE id = %s RETURNING id;", (data.get("id"),))
        row = cur.fetchone()
        conn.commit()
        if row is None:
            raise HTTPException(404, "Porto non trovato")
        return {"id": data.get("id"), "esito": "eliminato"}
    finally:
        cur.close()
        conn.close()


@app.get("/internal/tratta/lista")
def lista_tratte():
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT id, nome, porto_partenza_id, porto_arrivo_id, porti_intermedi, tratta_multiporto
            FROM tratta
            ORDER BY nome ASC;
        """)
        rows = cur.fetchall()
        return [
            {
                "id": str(r[0]),
                "nome": r[1],
                "porto_partenza_id": str(r[2]),
                "porto_arrivo_id": str(r[3]),
                "porti_intermedi": r[4],
                "tratta_multiporto": r[5]
            }
            for r in rows
        ]
    finally:
        cur.close()
        conn.close()


@app.get("/internal/tratta/{tratta_id}")
def get_tratta(tratta_id: str):
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT id, nome, porto_partenza_id, porto_arrivo_id, distanza_miglia, porti_intermedi, tratta_multiporto, ST_AsGeoJSON(geom_rotta_standard)
            FROM tratta
            WHERE id = %s
        """, (tratta_id,))
        row = cur.fetchone()
        if row is None:
            raise HTTPException(404, "Tratta non trovata")
        return {
            "id": str(row[0]),
            "nome": row[1],
            "porto_partenza_id": str(row[2]),
            "porto_arrivo_id": str(row[3]),
            "distanza_miglia": row[4],
            "porti_intermedi": row[5],
            "tratta_multiporto": row[6],
            "geometry": row[7]
        }
    finally:
        cur.close()
        conn.close()


@app.post("/internal/tratta/crea")
def crea_tratta(data: dict):
    conn = get_connection()
    cur = conn.cursor()
    try:
        porto_partenza_id = data.get("porto_partenza_id")
        porto_arrivo_id = data.get("porto_arrivo_id")

        cur.execute("SELECT nome, ST_X(coordinate_gps), ST_Y(coordinate_gps) FROM porto WHERE id = %s", (porto_partenza_id,))
        p1 = cur.fetchone()
        if p1 is None:
            raise HTTPException(404, f"Porto di partenza non trovato: {porto_partenza_id}")
        nome_p1, lon1, lat1 = p1

        cur.execute("SELECT nome, ST_X(coordinate_gps), ST_Y(coordinate_gps) FROM porto WHERE id = %s", (porto_arrivo_id,))
        p2 = cur.fetchone()
        if p2 is None:
            raise HTTPException(404, f"Porto di arrivo non trovato: {porto_arrivo_id}")
        nome_p2, lon2, lat2 = p2

        cur.execute(
            "SELECT id FROM tratta WHERE porto_partenza_id = %s AND porto_arrivo_id = %s AND tratta_multiporto = false LIMIT 1",
            (porto_partenza_id, porto_arrivo_id)
        )
        if cur.fetchone() is not None:
            raise HTTPException(409, detail=f"Esiste già una tratta diretta tra {nome_p1} e {nome_p2}.")

        nome_tratta = f"{nome_p1[:3].upper()}-{nome_p2[:3].upper()}"
        tratta_uuid = data.get("id") if data.get("id") else str(uuid.uuid4())

        cur.execute("""
            INSERT INTO tratta (id, nome, porto_partenza_id, porto_arrivo_id, geom_rotta_standard, tratta_multiporto)
            VALUES (%s, %s, %s, %s, ST_SetSRID(ST_MakeLine(ST_Point(%s, %s), ST_Point(%s, %s)), 4326), false)
            RETURNING id;
        """, (tratta_uuid, nome_tratta, porto_partenza_id, porto_arrivo_id, lon1, lat1, lon2, lat2))
        tratta_id = cur.fetchone()[0]
        conn.commit()

        cur.execute("SELECT ST_AsGeoJSON(geom_rotta_standard) FROM tratta WHERE id = %s", (tratta_id,))
        geom_json = cur.fetchone()[0]

        return {
            "id": str(tratta_id),
            "nome": nome_tratta,
            "porto_partenza_id": str(porto_partenza_id),
            "porto_arrivo_id": str(porto_arrivo_id),
            "porto_partenza": nome_p1,
            "porto_arrivo": nome_p2,
            "distanza_miglia": None,
            "geometry": geom_json
        }
    finally:
        cur.close()
        conn.close()


@app.post("/internal/tratta/crea_multi")
def crea_tratta_multiporto(data: dict):
    porti_ids = data.get("porti_ids") or []
    if len(porti_ids) < 2:
        raise HTTPException(400, "Servono almeno due porti.")

    conn = get_connection()
    cur = conn.cursor()
    try:
        punti = []
        nomi_porti = []

        for porto_id in porti_ids:
            cur.execute("SELECT nome, ST_X(coordinate_gps), ST_Y(coordinate_gps) FROM porto WHERE id = %s", (porto_id,))
            row = cur.fetchone()
            if not row:
                raise HTTPException(404, f"Porto non trovato: {porto_id}")
            nome, lon, lat = row
            nomi_porti.append(nome)
            punti.append((lon, lat))

        porto_partenza_id = porti_ids[0]
        porto_arrivo_id = porti_ids[-1]
        ids_intermedi = [str(uid) for uid in porti_ids[1:-1]]
        has_intermedi = len(ids_intermedi) > 0
        nomi_intermedi = nomi_porti[1:-1] if has_intermedi else None

        nome_tratta = f"{nomi_porti[0][:3].upper()}-{nomi_porti[-1][:3].upper()}"
        punti_sql = ",".join([f"ST_Point({lon},{lat})" for lon, lat in punti])
        json_intermedi_db = json.dumps(ids_intermedi) if has_intermedi else None
        tratta_uuid = data.get("id") if data.get("id") else str(uuid.uuid4())

        cur.execute(f"""
            INSERT INTO tratta (id, nome, porto_partenza_id, porto_arrivo_id, porti_intermedi, tratta_multiporto, geom_rotta_standard)
            VALUES (%s, %s, %s, %s, %s, %s, ST_SetSRID(ST_MakeLine(ARRAY[{punti_sql}]), 4326))
            RETURNING id;
        """, (tratta_uuid, nome_tratta, porto_partenza_id, porto_arrivo_id, json_intermedi_db, has_intermedi))

        tratta_id = cur.fetchone()[0]
        conn.commit()
        cur.execute("SELECT ST_AsGeoJSON(geom_rotta_standard) FROM tratta WHERE id = %s", (tratta_id,))
        geom_json = cur.fetchone()[0]

        return {
            "id": str(tratta_id),
            "porti": nomi_porti,
            "distanza_miglia": None,
            "porti_intermedi": nomi_intermedi,
            "tratta_multiporto": has_intermedi,
            "geometry": geom_json
        }
    finally:
        cur.close()
        conn.close()


@app.post("/internal/tratta/modifica")
def modifica_tratta(data: dict):
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT nome, ST_X(coordinate_gps), ST_Y(coordinate_gps) FROM porto WHERE id = %s", (data.get("porto_partenza_id"),))
        p1 = cur.fetchone()
        if p1 is None:
            raise HTTPException(404, f"Porto di partenza non trovato: {data.get('porto_partenza_id')}")
        nome_p1, lon1, lat1 = p1

        cur.execute("SELECT nome, ST_X(coordinate_gps), ST_Y(coordinate_gps) FROM porto WHERE id = %s", (data.get("porto_arrivo_id"),))
        p2 = cur.fetchone()
        if p2 is None:
            raise HTTPException(404, f"Porto di arrivo non trovato: {data.get('porto_arrivo_id')}")
        nome_p2, lon2, lat2 = p2

        nuovo_nome = f"{nome_p1[:3].upper()}-{nome_p2[:3].upper()}"
        cur.execute("""
            UPDATE tratta
            SET nome = %s, porto_partenza_id = %s, porto_arrivo_id = %s,
                geom_rotta_standard = ST_SetSRID(ST_MakeLine(ST_Point(%s,%s), ST_Point(%s,%s)), 4326)
            WHERE id = %s
            RETURNING id, ST_AsGeoJSON(geom_rotta_standard);
        """, (nuovo_nome, data.get("porto_partenza_id"), data.get("porto_arrivo_id"), lon1, lat1, lon2, lat2, data.get("id")))
        row = cur.fetchone()
        conn.commit()
        if row is None:
            raise HTTPException(404, "Tratta non trovata per la modifica")
        return {
            "id": str(row[0]),
            "porto_partenza": nome_p1,
            "porto_arrivo": nome_p2,
            "distanza_miglia": None,
            "geometry": row[1]
        }
    finally:
        cur.close()
        conn.close()


@app.post("/internal/tratta/elimina")
def elimina_tratta(data: dict):
    # cascade: elimina corse (e percorsi) nel servizio operativo
    _post_json(OPERATIVO_SERVICE_URL, "/internal/corsa/elimina_by_tratta", {"tratta_id": data.get("id")})
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("DELETE FROM tratta WHERE id = %s RETURNING id;", (data.get("id"),))
        row = cur.fetchone()
        conn.commit()
        if row is None:
            raise HTTPException(404, "Tratta non trovata")
        return {"id": data.get("id"), "esito": "eliminato"}
    finally:
        cur.close()
        conn.close()


@app.get("/internal/vascello/lista")
def lista_vascelli():
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT id, mmsi, nome, capacita_passeggeri, costo_orario_esercizio, velocita_max_nodi, lunghezza_m, stato_salute_aggregato, profilo_consumo_json, data_creazione
            FROM vascello
            ORDER BY nome;
        """)
        rows = cur.fetchall()
        return [
            {
                "id": r[0],
                "mmsi": r[1],
                "nome": r[2],
                "capacita_passeggeri": r[3],
                "costo_orario_esercizio": r[4],
                "velocita_max_nodi": r[5],
                "lunghezza_m": r[6],
                "stato_salute_aggregato": r[7],
                "profilo_consumo_json": r[8],
                "data_creazione": r[9].isoformat() if r[9] else None
            }
            for r in rows
        ]
    finally:
        cur.close()
        conn.close()


@app.get("/internal/vascello/{vascello_id}")
def get_vascello(vascello_id: str):
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT id, mmsi, nome, capacita_passeggeri, costo_orario_esercizio, velocita_max_nodi, lunghezza_m, stato_salute_aggregato, profilo_consumo_json, data_creazione
            FROM vascello
            WHERE id = %s
        """, (vascello_id,))
        row = cur.fetchone()
        if row is None:
            raise HTTPException(404, "Vascello non trovato")
        return {
            "id": row[0],
            "mmsi": row[1],
            "nome": row[2],
            "capacita_passeggeri": row[3],
            "costo_orario_esercizio": row[4],
            "velocita_max_nodi": row[5],
            "lunghezza_m": row[6],
            "stato_salute_aggregato": row[7],
            "profilo_consumo_json": row[8],
            "data_creazione": row[9].isoformat() if row[9] else None
        }
    finally:
        cur.close()
        conn.close()


@app.get("/internal/vascello/by_mmsi/{mmsi}")
def get_vascello_by_mmsi(mmsi: str):
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT id, mmsi, nome, capacita_passeggeri, costo_orario_esercizio, velocita_max_nodi, lunghezza_m, stato_salute_aggregato, profilo_consumo_json, data_creazione
            FROM vascello
            WHERE mmsi = %s
            LIMIT 1;
        """, (mmsi,))
        row = cur.fetchone()
        if row is None:
            raise HTTPException(404, detail=f"Nessun vascello trovato con MMSI={mmsi}")
        return {
            "id": row[0],
            "mmsi": row[1],
            "nome": row[2],
            "capacita_passeggeri": row[3],
            "costo_orario_esercizio": row[4],
            "velocita_max_nodi": row[5],
            "lunghezza_m": row[6],
            "stato_salute_aggregato": row[7],
            "profilo_consumo_json": row[8],
            "data_creazione": row[9].isoformat() if row[9] else None
        }
    finally:
        cur.close()
        conn.close()


@app.post("/internal/vascello/crea")
def crea_vascello(data: dict):
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO vascello (id, mmsi, nome, capacita_passeggeri, costo_orario_esercizio, velocita_max_nodi, stato_salute_aggregato, profilo_consumo_json, data_creazione)
            VALUES (gen_random_uuid(), %s, %s, %s, %s, %s, %s, %s, now())
            RETURNING id, data_creazione;
        """, (
            data.get("mmsi"),
            data.get("nome"),
            data.get("capacita_passeggeri"),
            data.get("costo_orario_esercizio"),
            data.get("velocita_max_nodi"),
            data.get("stato_salute_aggregato"),
            json.dumps(data.get("profilo_consumo_json")) if data.get("profilo_consumo_json") else None,
        ))
        new_id, data_creazione = cur.fetchone()
        conn.commit()
        return {
            "id": new_id,
            "mmsi": data.get("mmsi"),
            "nome": data.get("nome"),
            "capacita_passeggeri": data.get("capacita_passeggeri"),
            "costo_orario_esercizio": data.get("costo_orario_esercizio"),
            "velocita_max_nodi": data.get("velocita_max_nodi"),
            "stato_salute_aggregato": data.get("stato_salute_aggregato"),
            "profilo_consumo_json": data.get("profilo_consumo_json"),
            "data_creazione": data_creazione.isoformat() if data_creazione else None,
        }
    finally:
        cur.close()
        conn.close()


@app.post("/internal/vascello/modifica")
def modifica_vascello(data: dict):
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            UPDATE vascello
            SET mmsi=%s, nome=%s, capacita_passeggeri=%s, costo_orario_esercizio=%s, velocita_max_nodi=%s, stato_salute_aggregato=%s, profilo_consumo_json=%s
            WHERE id=%s
            RETURNING id, mmsi, nome, capacita_passeggeri, costo_orario_esercizio, velocita_max_nodi, stato_salute_aggregato, profilo_consumo_json, data_creazione;
        """, (
            data.get("mmsi"),
            data.get("nome"),
            data.get("capacita_passeggeri"),
            data.get("costo_orario_esercizio"),
            data.get("velocita_max_nodi"),
            data.get("stato_salute_aggregato"),
            json.dumps(data.get("profilo_consumo_json")) if data.get("profilo_consumo_json") else None,
            data.get("id"),
        ))
        row = cur.fetchone()
        conn.commit()
        if row is None:
            raise HTTPException(404, "Vascello non trovato")
        return {
            "id": row[0],
            "mmsi": row[1],
            "nome": row[2],
            "capacita_passeggeri": row[3],
            "costo_orario_esercizio": row[4],
            "velocita_max_nodi": row[5],
            "stato_salute_aggregato": row[6],
            "profilo_consumo_json": row[7],
            "data_creazione": row[8].isoformat() if row[8] else None,
        }
    finally:
        cur.close()
        conn.close()


@app.post("/internal/vascello/elimina")
def elimina_vascello(data: dict):
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("DELETE FROM vascello WHERE id = %s RETURNING id;", (data.get("id"),))
        row = cur.fetchone()
        conn.commit()
        if row is None:
            raise HTTPException(404, "Vascello non trovato")
        return {"id": data.get("id"), "esito": "eliminato"}
    finally:
        cur.close()
        conn.close()


@app.post("/internal/componente/crea")
def crea_componente(data: dict):
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO componente (
                id,
                vascello_id,
                nome_componente,
                sottosistema,
                ore_utilizzo_totali,
                soglia_manutenzione,
                modello_guasto_json
            )
            VALUES (gen_random_uuid(), %s, %s, %s, %s, %s, %s)
            RETURNING id, vascello_id, nome_componente, sottosistema, ore_utilizzo_totali, soglia_manutenzione, modello_guasto_json;
        """, (
            data.get("vascello_id"),
            data.get("nome_componente"),
            data.get("sottosistema"),
            data.get("ore_utilizzo_totali"),
            data.get("soglia_manutenzione"),
            json.dumps(data.get("modello_guasto_json")) if data.get("modello_guasto_json") is not None else None,
        ))
        row = cur.fetchone()
        conn.commit()
        return {
            "id": row[0],
            "vascello_id": str(row[1]) if row[1] else None,
            "nome_componente": row[2],
            "sottosistema": row[3],
            "ore_utilizzo_totali": float(row[4]) if row[4] is not None else None,
            "soglia_manutenzione": float(row[5]) if row[5] is not None else None,
            "modello_guasto_json": row[6],
        }
    finally:
        cur.close()
        conn.close()


@app.get("/internal/componente/lista")
def lista_componenti():
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT id, vascello_id, nome_componente, sottosistema, ore_utilizzo_totali, soglia_manutenzione, modello_guasto_json
            FROM componente
            ORDER BY nome_componente;
        """)
        rows = cur.fetchall()
        return [
            {
                "id": r[0],
                "vascello_id": str(r[1]) if r[1] else None,
                "nome_componente": r[2],
                "sottosistema": r[3],
                "ore_utilizzo_totali": float(r[4]) if r[4] is not None else None,
                "soglia_manutenzione": float(r[5]) if r[5] is not None else None,
                "modello_guasto_json": r[6],
            }
            for r in rows
        ]
    finally:
        cur.close()
        conn.close()


@app.get("/internal/componente/{vascello_id}")
def lista_componenti_by_vascello(vascello_id: str):
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT id, vascello_id, nome_componente, sottosistema, ore_utilizzo_totali, soglia_manutenzione, modello_guasto_json
            FROM componente
            WHERE vascello_id = %s
            ORDER BY nome_componente;
        """, (vascello_id,))
        rows = cur.fetchall()
        return [
            {
                "id": r[0],
                "vascello_id": str(r[1]) if r[1] else None,
                "nome_componente": r[2],
                "sottosistema": r[3],
                "ore_utilizzo_totali": float(r[4]) if r[4] is not None else None,
                "soglia_manutenzione": float(r[5]) if r[5] is not None else None,
                "modello_guasto_json": r[6],
            }
            for r in rows
        ]
    finally:
        cur.close()
        conn.close()


@app.get("/internal/componente/by_mmsi/{mmsi}")
def lista_componenti_by_mmsi(mmsi: str):
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT c.id, c.vascello_id, c.nome_componente, c.sottosistema, c.ore_utilizzo_totali, c.soglia_manutenzione, c.modello_guasto_json
            FROM componente c
            JOIN vascello v ON v.id = c.vascello_id
            WHERE v.mmsi = %s
            ORDER BY c.nome_componente;
        """, (mmsi,))
        rows = cur.fetchall()
        return [
            {
                "id": r[0],
                "vascello_id": str(r[1]) if r[1] else None,
                "nome_componente": r[2],
                "sottosistema": r[3],
                "ore_utilizzo_totali": float(r[4]) if r[4] is not None else None,
                "soglia_manutenzione": float(r[5]) if r[5] is not None else None,
                "modello_guasto_json": r[6],
            }
            for r in rows
        ]
    finally:
        cur.close()
        conn.close()


@app.post("/internal/componente/modifica")
def modifica_componente(data: dict):
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            UPDATE componente
            SET
                vascello_id = %s,
                nome_componente = %s,
                sottosistema = %s,
                ore_utilizzo_totali = %s,
                soglia_manutenzione = %s,
                modello_guasto_json = %s
            WHERE id = %s
            RETURNING id, vascello_id, nome_componente, sottosistema, ore_utilizzo_totali, soglia_manutenzione, modello_guasto_json;
        """, (
            data.get("vascello_id"),
            data.get("nome_componente"),
            data.get("sottosistema"),
            data.get("ore_utilizzo_totali"),
            data.get("soglia_manutenzione"),
            json.dumps(data.get("modello_guasto_json")) if data.get("modello_guasto_json") is not None else None,
            data.get("id"),
        ))
        row = cur.fetchone()
        conn.commit()
        if row is None:
            raise HTTPException(404, "Componente non trovato")
        return {
            "id": row[0],
            "vascello_id": str(row[1]) if row[1] else None,
            "nome_componente": row[2],
            "sottosistema": row[3],
            "ore_utilizzo_totali": float(row[4]) if row[4] is not None else None,
            "soglia_manutenzione": float(row[5]) if row[5] is not None else None,
            "modello_guasto_json": row[6],
        }
    finally:
        cur.close()
        conn.close()


@app.post("/internal/componente/elimina")
def elimina_componente(data: dict):
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("DELETE FROM componente WHERE id = %s RETURNING id;", (data.get("id"),))
        row = cur.fetchone()
        conn.commit()
        if row is None:
            raise HTTPException(404, "Componente non trovato")
        return {"id": data.get("id"), "esito": "eliminato"}
    finally:
        cur.close()
        conn.close()


@app.get("/internal/vascello/{mmsi}/image")
def get_vascello_image(mmsi: str):
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT immagine FROM vascello WHERE mmsi = %s", (mmsi,))
        row = cur.fetchone()
        if row is None or row[0] is None:
            raise HTTPException(404, "Immagine non trovata")
        image_bytes = bytes(row[0])
        return Response(content=image_bytes, media_type="image/jpg")
    finally:
        cur.close()
        conn.close()
