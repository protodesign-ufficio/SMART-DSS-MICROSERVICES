from app.core.database import get_connection
from app.models.common import AssignmentRequest
from app.models.corsa import PrevisioneRequest
from app.services import previsione_service, ottimizzatore_service
from app.models.piano import PianoCreateInput, PianoUpdateInput, PianoDeleteInput
from app.core.config import PERCORSI_SERVICE_URL
from app.core.operativo_client import (
    delegation_enabled as operativo_delegation_enabled,
    get_json as operativo_get_json,
    post_json as operativo_post_json,
    OperativoDelegationError,
)
from datetime import datetime, timedelta, date
from fastapi import HTTPException
import psycopg2
import json
import requests

def compute_assignments(data: dict):
    inp = AssignmentRequest(**data) if not isinstance(data, AssignmentRequest) else data
    conn = get_connection(); cur = conn.cursor()
    try:
        # retrieve routes in window
        cur.execute("""
            SELECT c.id, c.nome, c.tratta_id, c.orario_partenza_schedulato FROM corsa c WHERE c.orario_partenza_schedulato >= %s AND c.orario_partenza_schedulato <= %s ORDER BY c.orario_partenza_schedulato;
        """, (inp.start, inp.end))
        routes_rows = cur.fetchall()

        # vascelli filter by id
        cur.execute("SELECT id, nome, capacita_passeggeri FROM vascello")
        v_rows = cur.fetchall()
        vessels_all = [{"id": str(r[0]), "nome": r[1], "capacita_passeggeri": r[2]} for r in v_rows]
        vessels_data = [v for v in vessels_all if v["id"] in inp.vessels]
        if not vessels_data:
            raise HTTPException(400, "Nessun vascello trovato corrispondente alla lista fornita")

        # ports and legs lookup
        cur.execute("SELECT id, nome FROM porto")
        ports = {str(r[0]): r[1] for r in cur.fetchall()}
        cur.execute("SELECT id, porto_partenza_id, porto_arrivo_id FROM tratta")
        legs = {str(r[0]): {"porto_partenza_id": str(r[1]), "porto_arrivo_id": str(r[2])} for r in cur.fetchall()}

        routes_output = {}
        
        # Costruisci la lista di tutti gli input per l'ottimizzatore
        opt_items = []
        opt_items_mapping = []  # per mappare risultati a (route_id, vessel)

        for r in routes_rows:
            route_id = str(r[0])
            nome_corsa = r[1]
            tratta_id = str(r[2])
            orario_partenza = r[3]
            if tratta_id not in legs:
                continue
            leg = legs[tratta_id]
            porto_partenza_id = leg["porto_partenza_id"]
            porto_arrivo_id = leg["porto_arrivo_id"]

            routes_output[route_id] = {"nome_corsa": nome_corsa, "porto_partenza": ports.get(porto_partenza_id, "Unknown"), "porto_arrivo": ports.get(porto_arrivo_id, "Unknown"), "porto_partenza_id": porto_partenza_id, "porto_arrivo_id": porto_arrivo_id, "orario_partenza_schedulato": orario_partenza.isoformat(), "passeggeri_previsti": None, "KPI_assegnazione": {}}

            # forecast
            try:
                forecast_req = PrevisioneRequest(biglietti_venduti_al_sample=10, festivo=False)
                forecast = previsione_service.calcola_previsione(route_id, forecast_req)
                ci = [forecast["dettagli"]["micro_finale_ci_95"][0], forecast["dettagli"]["micro_finale_ci_95"][1]]
                routes_output[route_id]["passeggeri_previsti"] = ci
            except Exception:
                routes_output[route_id]["passeggeri_previsti"] = [0.0, 0.0]

            # Prepara input per ogni vessel
            for vessel in vessels_data:
                vessel_id = vessel["id"]
                opt_items.append({
                    "corsa_id": route_id,
                    "vascello_id": vessel_id,
                    "eps_time": inp.eps_time,
                    "fake_data": inp.fake_data,
                    "ve_min": 0.1,
                    "tolerance": 1
                })
                opt_items_mapping.append((route_id, vessel))

        # Chiamata unica all'ottimizzatore con tutti gli items
        if opt_items:
            from app.models.common import OttimizzatoreBatchInput, OttimizzatoreInput
            batch_input = OttimizzatoreBatchInput(items=[OttimizzatoreInput(**item) for item in opt_items])
            try:
                ottimizzatore_service.ottimizzatore(batch_input)
            except Exception:
                raise

        # Recupera i KPI dai percorsi calcolati
        for route_id, vessel in opt_items_mapping:
            vessel_id = vessel["id"]
            vessel_nome = vessel["nome"]
            vessel_cap = vessel.get("capacita_passeggeri")
            
            cur.execute("SELECT id, tempo_percorrenza_min, consumo, comfort FROM percorso WHERE id_corsa = %s AND vascello_id = %s ORDER BY created_at DESC LIMIT 1", (route_id, vessel_id))
            per = cur.fetchone()
            if not per:
                continue
            percorso_id, tempo_percorrenza_obj, consumo, comfort = per
            orario_arrivo_previsto = datetime.fromisoformat(routes_output[route_id]["orario_partenza_schedulato"]) + tempo_percorrenza_obj
            routes_output[route_id]["KPI_assegnazione"][vessel_id] = {"nome_vascello": vessel_nome, "consumo": consumo, "comfort": comfort, "tempo_percorrenza_sec": tempo_percorrenza_obj.total_seconds(), "orario_arrivo_previsto": orario_arrivo_previsto.isoformat(), "capacita_passeggeri": vessel_cap}

        return routes_output
    finally:
        cur.close(); conn.close()


def crea_piano(data: dict):
    inp = PianoCreateInput(**data) if not isinstance(data, PianoCreateInput) else data
    conn = get_connection(); cur = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO piano_operativo (data_riferimento, stato, kpi_profitto_stimato, kpi_robustezza, versione) VALUES (%s, %s, %s, %s, %s) RETURNING id;
        """, (inp.data_riferimento, inp.stato, inp.kpi_profitto_stimato, inp.kpi_robustezza, inp.versione))
        piano_id = cur.fetchone()[0]
        conn.commit()
        return {"id": piano_id, "data_riferimento": inp.data_riferimento, "stato": inp.stato, "kpi_profitto_stimato": inp.kpi_profitto_stimato, "kpi_robustezza": inp.kpi_robustezza, "versione": inp.versione}
    except psycopg2.errors.UniqueViolation:
        conn.rollback(); raise HTTPException(status_code=409, detail="Piano operativo già esistente")
    finally:
        conn.close()


def modifica_piano(data: dict):
    inp = PianoUpdateInput(**data) if not isinstance(data, PianoUpdateInput) else data
    conn = get_connection(); cur = conn.cursor()
    try:
        updates = []
        params = []
        if inp.data_riferimento is not None:
            updates.append("data_riferimento = %s"); params.append(inp.data_riferimento)
        if inp.stato is not None:
            updates.append("stato = %s"); params.append(inp.stato)
        if inp.kpi_profitto_stimato is not None:
            updates.append("kpi_profitto_stimato = %s"); params.append(inp.kpi_profitto_stimato)
        if inp.kpi_robustezza is not None:
            updates.append("kpi_robustezza = %s"); params.append(inp.kpi_robustezza)
        if inp.versione is not None:
            updates.append("versione = %s"); params.append(inp.versione)

        if not updates:
            raise HTTPException(status_code=400, detail="Nessun campo da aggiornare")

        params.append(inp.id)
        sql = "UPDATE piano_operativo SET " + ", ".join(updates) + " WHERE id = %s RETURNING id, data_riferimento, stato, kpi_profitto_stimato, kpi_robustezza, versione;"
        cur.execute(sql, tuple(params))
        row = cur.fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Piano operativo non trovato")
        conn.commit()
        return {"id": row[0], "data_riferimento": row[1], "stato": row[2], "kpi_profitto_stimato": row[3], "kpi_robustezza": row[4], "versione": row[5]}
    except psycopg2.errors.UniqueViolation:
        conn.rollback(); raise HTTPException(status_code=409, detail="Conflitto durante aggiornamento piano operativo")
    finally:
        conn.close()


def elimina_piano(data: dict):
    inp = PianoDeleteInput(**data) if not isinstance(data, PianoDeleteInput) else data
    conn = get_connection(); cur = conn.cursor()
    try:
        cur.execute("DELETE FROM piano_operativo WHERE id = %s RETURNING id;", (inp.id,))
        row = cur.fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Piano operativo non trovato")
        conn.commit()
        return {"id": row[0]}
    finally:
        conn.close()


def get_piano_by_id(piano_id: str):
    conn = get_connection(); cur = conn.cursor()
    try:
        cur.execute("SELECT id, data_riferimento, stato, kpi_profitto_stimato, kpi_robustezza, versione FROM piano_operativo WHERE id = %s;", (piano_id,))
        r = cur.fetchone()
        if not r:
            return None
        return {
            "id": str(r[0]),
            "data_riferimento": r[1],
            "stato": r[2],
            "kpi_profitto_stimato": r[3],
            "kpi_robustezza": r[4],
            "versione": r[5],
            "assegnazioni": []
        }
    finally:
        conn.close()


def lista_piani(data_riferimento: date = None):
    conn = get_connection(); cur = conn.cursor()
    try:
        if data_riferimento is not None:
            cur.execute("SELECT id, data_riferimento, stato, kpi_profitto_stimato, kpi_robustezza, versione FROM piano_operativo WHERE data_riferimento = %s ORDER BY data_riferimento DESC;", (data_riferimento,))
        else:
            cur.execute("SELECT id, data_riferimento, stato, kpi_profitto_stimato, kpi_robustezza, versione FROM piano_operativo ORDER BY data_riferimento DESC;")
        rows = cur.fetchall()
        result = []
        for r in rows:
            piano_id = r[0]
            # fetch assignments for this piano
            cur.execute("""
                SELECT a.id, a.piano_id, p.vascello_id, a.percorso_id, a.stato_esecuzione, a.virtuale, p.id_corsa
                FROM assegnazione a
                LEFT JOIN percorso p ON a.percorso_id = p.id
                WHERE a.piano_id = %s;
            """, (piano_id,))
            ass_rows = cur.fetchall()
            assegnazioni = []
            for a in ass_rows:
                assegnazioni.append({
                    "id": str(a[0]),
                    "piano_id": str(a[1]) if a[1] is not None else None,
                    "vascello_id": str(a[2]) if a[2] is not None else None,
                    "percorso_id": str(a[3]),
                    "id_corsa": str(a[6]) if a[6] is not None else None,
                    "stato_esecuzione": a[4],
                    "virtuale": a[5]
                })

            result.append({
                "id": str(piano_id),
                "data_riferimento": r[1],
                "stato": r[2],
                "kpi_profitto_stimato": r[3],
                "kpi_robustezza": r[4],
                "versione": r[5],
                "assegnazioni": assegnazioni
            })
        return result
    finally:
        cur.close(); conn.close()


def get_percorsi_compatibili(corsa_id: str, percorsi_id: list):
    """Restituisce i percorsi della corsa compatibili con tutti i percorsi già assegnati."""
    def _get_json(path: str, timeout: float = 8.0):
        url = f"{PERCORSI_SERVICE_URL.rstrip('/')}{path}"
        try:
            response = requests.get(url, timeout=timeout)
        except requests.RequestException as exc:
            raise HTTPException(status_code=503, detail="Percorsi service non raggiungibile") from exc

        if response.status_code == 404:
            return None
        if response.status_code >= 400:
            raise HTTPException(status_code=503, detail=f"Errore Percorsi service: HTTP {response.status_code}")

        try:
            return response.json()
        except Exception as exc:
            raise HTTPException(status_code=502, detail="Risposta non valida dal Percorsi service") from exc

    def _parse_iso_datetime(value: str | None):
        if not value:
            return None
        normalized = value.replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(normalized)
        except Exception:
            return None

    def _build_percorso_response(item: dict):
        percorso_id = item.get("id") or item.get("percorso_id")
        vascello_id = item.get("vascello_id")
        orario_partenza = _parse_iso_datetime(item.get("orario_partenza_schedulato"))
        orario_arrivo = _parse_iso_datetime(item.get("orario_arrivo_previsto"))

        tempo_percorrenza_min = item.get("tempo_percorrenza")
        if tempo_percorrenza_min is None:
            tempo_percorrenza_min = item.get("tempo_percorrenza_min")

        return {
            "percorso_id": str(percorso_id),
            "tempo_percorrenza_min": float(tempo_percorrenza_min) if tempo_percorrenza_min is not None else None,
            "consumo": item.get("consumo"),
            "comfort": item.get("comfort"),
            "vascello_id": str(vascello_id) if vascello_id else None,
            "vascello_nome": item.get("vascello_nome"),
            "orario_partenza_schedulato": orario_partenza.isoformat() if orario_partenza else None,
            "orario_arrivo_calcolato": orario_arrivo.isoformat() if orario_arrivo else None,
        }

    percorsi_id_set = {str(pid) for pid in (percorsi_id or [])}

    percorsi_target_resp = _get_json(
        f"/internal/percorso/by_corsa/{corsa_id}?order_by=created_at&mode=DESC&limit=500"
    )
    if not isinstance(percorsi_target_resp, dict):
        raise HTTPException(status_code=404, detail=f"Nessun percorso trovato per la corsa {corsa_id}")

    percorsi_corsa = percorsi_target_resp.get("percorsi", [])
    if not isinstance(percorsi_corsa, list) or not percorsi_corsa:
        raise HTTPException(status_code=404, detail=f"Nessun percorso trovato per la corsa {corsa_id}")

    if not percorsi_id_set:
        return {
            "corsa_id": corsa_id,
            "percorsi_compatibili": [_build_percorso_response(pc) for pc in percorsi_corsa],
        }

    percorsi_assegnati_list = []
    percorsi_mancanti = []

    for percorso_id in sorted(percorsi_id_set):
        pa = _get_json(f"/internal/percorso/{percorso_id}?include=corsa")
        if not isinstance(pa, dict):
            percorsi_mancanti.append(percorso_id)
            continue

        corsa_obj = pa.get("corsa") if isinstance(pa.get("corsa"), dict) else {}
        pa_start = _parse_iso_datetime(corsa_obj.get("orario_partenza_schedulato") or pa.get("orario_partenza_schedulato"))
        pa_end = _parse_iso_datetime(pa.get("orario_arrivo_previsto"))
        if pa_end is None and pa_start is not None and pa.get("tempo_percorrenza") is not None:
            try:
                pa_end = pa_start + timedelta(minutes=float(pa.get("tempo_percorrenza")))
            except Exception:
                pa_end = None

        percorsi_assegnati_list.append(
            {
                "id": str(pa.get("percorso_id") or pa.get("id") or percorso_id),
                "vascello_id": str(pa.get("vascello_id")) if pa.get("vascello_id") else None,
                "orario_partenza": pa_start,
                "orario_arrivo_calcolato": pa_end,
                "corsa_id": str(pa.get("corsa_id")) if pa.get("corsa_id") else None,
            }
        )

    if percorsi_mancanti:
        raise HTTPException(
            status_code=404,
            detail=f"Percorsi assegnati non trovati: {', '.join(percorsi_mancanti)}",
        )

    corse_gia_assegnate = {p["corsa_id"] for p in percorsi_assegnati_list if p.get("corsa_id")}
    if corsa_id in corse_gia_assegnate:
        return {
            "corsa_id": corsa_id,
            "percorsi_compatibili": [],
        }

    percorsi_compatibili = []

    for pc in percorsi_corsa:
        pc_id = str(pc.get("id") or pc.get("percorso_id"))
        if pc_id in percorsi_id_set:
            continue

        pc_vascello_id = str(pc.get("vascello_id")) if pc.get("vascello_id") else None
        pc_orario_partenza = _parse_iso_datetime(pc.get("orario_partenza_schedulato"))
        pc_orario_arrivo_calcolato = _parse_iso_datetime(pc.get("orario_arrivo_previsto"))
        if pc_orario_arrivo_calcolato is None and pc_orario_partenza is not None and pc.get("tempo_percorrenza") is not None:
            try:
                pc_orario_arrivo_calcolato = pc_orario_partenza + timedelta(minutes=float(pc.get("tempo_percorrenza")))
            except Exception:
                pc_orario_arrivo_calcolato = None

        compatibile_con_tutti = True
        for pa in percorsi_assegnati_list:
            if pc_vascello_id != pa["vascello_id"]:
                continue

            pa_finisce_prima = pa["orario_arrivo_calcolato"] and pc_orario_partenza and pa["orario_arrivo_calcolato"] < pc_orario_partenza
            pc_finisce_prima = pc_orario_arrivo_calcolato and pa["orario_partenza"] and pc_orario_arrivo_calcolato < pa["orario_partenza"]

            if not (pa_finisce_prima or pc_finisce_prima):
                compatibile_con_tutti = False
                break

        if compatibile_con_tutti:
            percorsi_compatibili.append(_build_percorso_response(pc))

    return {
        "corsa_id": corsa_id,
        "percorsi_compatibili": percorsi_compatibili,
    }


def check_validita_percorsi(percorso_1_id: str, percorso_2_id: str):
    conn = get_connection(); cur = conn.cursor()
    try:
        # Retrieve both routes with their corsa and vascello info
        cur.execute("""
            SELECT p.id, p.id_corsa, p.vascello_id, c.orario_partenza_schedulato, c.orario_arrivo_max, c.nome
            FROM percorso p
            JOIN corsa c ON p.id_corsa = c.id
            WHERE p.id IN (%s, %s);
        """, (percorso_1_id, percorso_2_id))
        
        rows = cur.fetchall()
        if len(rows) < 2:
            raise HTTPException(status_code=404, detail="Uno o entrambi i percorsi non trovati")
        
        percorso_1 = rows[0]
        percorso_2 = rows[1]
        
        # Check 1: I percorsi non devono essere della stessa corsa
        if percorso_1[1] == percorso_2[1]:
            return {
                "valido": False,
                "percorso_1": {
                    "id": percorso_1[0],
                    "corsa_id": percorso_1[1],
                    "vascello_id": percorso_1[2],
                    "orario_partenza_schedulato": percorso_1[3].isoformat() if percorso_1[3] else None,
                    "orario_arrivo_max": percorso_1[4].isoformat() if percorso_1[4] else None,
                    "nome_corsa": percorso_1[5]
                },
                "percorso_2": {
                    "id": percorso_2[0],
                    "corsa_id": percorso_2[1],
                    "vascello_id": percorso_2[2],
                    "orario_partenza_schedulato": percorso_2[3].isoformat() if percorso_2[3] else None,
                    "orario_arrivo_max": percorso_2[4].isoformat() if percorso_2[4] else None,
                    "nome_corsa": percorso_2[5]
                },
                "messaggio": "Invalidità: i due percorsi appartengono alla stessa corsa"
            }
        
        # Check 2: I vascelli devono essere uguali (se diversi è valido a priori)
        if percorso_1[2] != percorso_2[2]:
            return {
                "valido": True,
                "percorso_1": {
                    "id": percorso_1[0],
                    "corsa_id": percorso_1[1],
                    "vascello_id": percorso_1[2],
                    "orario_partenza_schedulato": percorso_1[3].isoformat() if percorso_1[3] else None,
                    "orario_arrivo_max": percorso_1[4].isoformat() if percorso_1[4] else None,
                    "nome_corsa": percorso_1[5]
                },
                "percorso_2": {
                    "id": percorso_2[0],
                    "corsa_id": percorso_2[1],
                    "vascello_id": percorso_2[2],
                    "orario_partenza_schedulato": percorso_2[3].isoformat() if percorso_2[3] else None,
                    "orario_arrivo_max": percorso_2[4].isoformat() if percorso_2[4] else None,
                    "nome_corsa": percorso_2[5]
                },
                "messaggio": "Validità a priori: i vascelli sono diversi - assegnazione sempre valida"
            }
        
        # Ordina i percorsi per orario_partenza_schedulato per il check temporale
        if percorso_1[3] > percorso_2[3]:
            percorso_1, percorso_2 = percorso_2, percorso_1
        
        # Check 3: Validità temporale - arrival_max of first < departure of second
        valido = percorso_1[4] < percorso_2[3]
        messaggio = "Validità verificata: la prima corsa termina prima che inizi la seconda" if valido else "Validità fallita: la prima corsa non termina prima dell'inizio della seconda"
        
        return {
            "valido": valido,
            "percorso_1": {
                "id": percorso_1[0],
                "corsa_id": percorso_1[1],
                "vascello_id": percorso_1[2],
                "orario_partenza_schedulato": percorso_1[3].isoformat() if percorso_1[3] else None,
                "orario_arrivo_max": percorso_1[4].isoformat() if percorso_1[4] else None,
                "nome_corsa": percorso_1[5]
            },
            "percorso_2": {
                "id": percorso_2[0],
                "corsa_id": percorso_2[1],
                "vascello_id": percorso_2[2],
                "orario_partenza_schedulato": percorso_2[3].isoformat() if percorso_2[3] else None,
                "orario_arrivo_max": percorso_2[4].isoformat() if percorso_2[4] else None,
                "nome_corsa": percorso_2[5]
            },
            "messaggio": messaggio
        }
    finally:
        conn.close()


def valida_piano(piano_id: str):
    """
    Valida un piano operativo:
    1. Verifica che non ci siano altri piani con stato VALIDATO nello stesso giorno
    2. Verifica che ci siano assegnazioni PIANIFICATE per tutte le corse del giorno
    3. Se le condizioni sono verificate, imposta lo stato del piano a VALIDATO
    4. Schedula le simulazioni per le assegnazioni virtuali del piano
    
    Args:
        piano_id: UUID del piano da validare
        
    Returns:
        PianoValidaResponse con dettaglio dell'operazione
    """
    from app.models.piano import PianoValidaInput, PianoValidaResponse, SimulazioneSchedulataItem
    from app.core.scheduler import schedule_simulation_job
    from zoneinfo import ZoneInfo
    import uuid as uuid_module
    
    tz_rome = ZoneInfo("Europe/Rome")

    if operativo_delegation_enabled():
        def _percorsi_get_json(path: str, timeout: float = 8.0):
            url = f"{PERCORSI_SERVICE_URL.rstrip('/')}{path}"
            try:
                response = requests.get(url, timeout=timeout)
            except requests.RequestException as exc:
                raise HTTPException(status_code=503, detail="Percorsi service non raggiungibile") from exc

            if response.status_code == 404:
                return None
            if response.status_code >= 400:
                raise HTTPException(status_code=503, detail=f"Errore Percorsi service: HTTP {response.status_code}")

            try:
                return response.json()
            except Exception as exc:
                raise HTTPException(status_code=502, detail="Risposta non valida dal Percorsi service") from exc

        def _parse_iso_datetime(value):
            if value is None:
                return None
            if isinstance(value, datetime):
                return value
            text = str(value).replace("Z", "+00:00")
            try:
                return datetime.fromisoformat(text)
            except Exception:
                return None

        try:
            try:
                piano = operativo_get_json(f"/internal/piano/{piano_id}")
            except OperativoDelegationError as exc:
                raise HTTPException(status_code=503, detail="Operativo service non raggiungibile") from exc

            if not isinstance(piano, dict):
                raise HTTPException(status_code=404, detail="Piano operativo non trovato")

            piano_stato_attuale = piano.get("stato")
            piano_data_riferimento = piano.get("data_riferimento")
            dt_riferimento = _parse_iso_datetime(piano_data_riferimento)
            if dt_riferimento is None:
                raise HTTPException(status_code=500, detail="data_riferimento non valida nel piano operativo")
            giorno_piano = dt_riferimento.date()

            try:
                piani_giorno = operativo_get_json(f"/internal/piano/lista?data_riferimento={giorno_piano.isoformat()}")
            except OperativoDelegationError as exc:
                raise HTTPException(status_code=503, detail="Operativo service non raggiungibile") from exc

            if not isinstance(piani_giorno, list):
                piani_giorno = []

            piani_validato = [
                p for p in piani_giorno
                if isinstance(p, dict)
                and str(p.get("id")) != str(piano_id)
                and p.get("stato") == "VALIDATO"
            ]
            if piani_validato:
                return {
                    "piano_id": str(piano_id),
                    "stato": piano_stato_attuale,
                    "validato": False,
                    "messaggio": f"Validazione fallita: esistono altri piani con stato VALIDATO per il giorno {giorno_piano}",
                    "corse_giorno": 0,
                    "assegnazioni_pianificate": 0,
                    "simulazioni_schedulate": 0,
                    "dettaglio_simulazioni": None,
                }

            try:
                corse_giorno = operativo_get_json(
                    f"/internal/corsa/giorno?giorno={giorno_piano.isoformat()}&solofuture=false"
                )
            except OperativoDelegationError as exc:
                raise HTTPException(status_code=503, detail="Operativo service non raggiungibile") from exc

            if not isinstance(corse_giorno, list):
                corse_giorno = []
            corse_ids = [str(c.get("id")) for c in corse_giorno if isinstance(c, dict) and c.get("id")]
            num_corse_giorno = len(corse_ids)

            if num_corse_giorno == 0:
                return {
                    "piano_id": str(piano_id),
                    "stato": piano_stato_attuale,
                    "validato": False,
                    "messaggio": f"Validazione fallita: nessuna corsa trovata per il giorno {giorno_piano}",
                    "corse_giorno": 0,
                    "assegnazioni_pianificate": 0,
                    "simulazioni_schedulate": 0,
                    "dettaglio_simulazioni": None,
                }

            try:
                assegnazioni = operativo_get_json(f"/internal/assegnazione/by_piano/{piano_id}")
            except OperativoDelegationError as exc:
                raise HTTPException(status_code=503, detail="Operativo service non raggiungibile") from exc

            if not isinstance(assegnazioni, list):
                assegnazioni = []

            assegnazioni_pianificate = [
                a for a in assegnazioni
                if isinstance(a, dict) and a.get("stato_esecuzione") == "PIANIFICATA"
            ]

            corse_con_assegnazione_ids = set()
            assegnazioni_virtuali = []
            corsa_cache = {}

            for a in assegnazioni_pianificate:
                percorso_id = a.get("percorso_id")
                if not percorso_id:
                    continue
                percorso = _percorsi_get_json(f"/internal/percorso/{percorso_id}")
                if not isinstance(percorso, dict):
                    continue
                corsa_id = percorso.get("corsa_id")
                if not corsa_id:
                    continue
                corsa_id = str(corsa_id)
                corse_con_assegnazione_ids.add(corsa_id)

                if a.get("virtuale") is True:
                    if corsa_id not in corsa_cache:
                        try:
                            corsa_cache[corsa_id] = operativo_get_json(f"/internal/corsa/id/{corsa_id}")
                        except OperativoDelegationError as exc:
                            raise HTTPException(status_code=503, detail="Operativo service non raggiungibile") from exc
                    corsa_item = corsa_cache.get(corsa_id)
                    if isinstance(corsa_item, dict):
                        orario_partenza = _parse_iso_datetime(corsa_item.get("orario_partenza_schedulato"))
                        if orario_partenza is not None:
                            assegnazioni_virtuali.append((str(a.get("id")), orario_partenza))

            corse_mancanti = [cid for cid in corse_ids if cid not in corse_con_assegnazione_ids]
            if corse_mancanti:
                return {
                    "piano_id": str(piano_id),
                    "stato": piano_stato_attuale,
                    "validato": False,
                    "messaggio": f"Validazione fallita: {len(corse_mancanti)} corse senza assegnazione PIANIFICATA",
                    "corse_giorno": num_corse_giorno,
                    "assegnazioni_pianificate": len(corse_con_assegnazione_ids),
                    "simulazioni_schedulate": 0,
                    "dettaglio_simulazioni": None,
                }

            try:
                operativo_post_json("/internal/piano/modifica", {"id": str(piano_id), "stato": "VALIDATO"})
            except OperativoDelegationError as exc:
                raise HTTPException(status_code=503, detail="Operativo service non raggiungibile") from exc

            simulazioni_schedulate = 0
            dettaglio_simulazioni = []

            for assegnazione_id, orario_partenza in sorted(assegnazioni_virtuali, key=lambda x: x[1]):
                job_id = f"sim_valida_{piano_id}_{assegnazione_id}_{uuid_module.uuid4().hex[:8]}"
                try:
                    schedule_simulation_job(
                        job_id=job_id,
                        run_date=orario_partenza,
                        assegnazione_id=str(assegnazione_id),
                    )
                    dettaglio_simulazioni.append({
                        "assegnazione_id": str(assegnazione_id),
                        "orario_simulazione": orario_partenza.isoformat(),
                        "job_id": job_id,
                    })
                    simulazioni_schedulate += 1
                except Exception as e:
                    print(f"[valida_piano] Errore scheduling assegnazione {assegnazione_id}: {e}")

            return {
                "piano_id": str(piano_id),
                "stato": "VALIDATO",
                "validato": True,
                "messaggio": f"Piano validato con successo. Stato aggiornato a VALIDATO. Schedulate {simulazioni_schedulate} simulazioni.",
                "corse_giorno": num_corse_giorno,
                "assegnazioni_pianificate": len(corse_con_assegnazione_ids),
                "simulazioni_schedulate": simulazioni_schedulate,
                "dettaglio_simulazioni": dettaglio_simulazioni if dettaglio_simulazioni else None,
            }

        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Errore durante la validazione del piano: {str(e)}")
    
    conn = get_connection()
    cur = conn.cursor()
    
    try:
        # Recupera il piano operativo
        cur.execute("""
            SELECT id, data_riferimento, stato 
            FROM piano_operativo 
            WHERE id = %s
        """, (piano_id,))
        
        piano_row = cur.fetchone()
        if piano_row is None:
            raise HTTPException(status_code=404, detail="Piano operativo non trovato")
        
        piano_data_riferimento = piano_row[1]
        piano_stato_attuale = piano_row[2]
        
        # Estrai solo la data (senza l'orario) per il confronto
        giorno_piano = piano_data_riferimento.date() if hasattr(piano_data_riferimento, 'date') else piano_data_riferimento
        
        # 1. Verifica che non ci siano altri piani con stato VALIDATO nello stesso giorno
        cur.execute("""
            SELECT id, stato 
            FROM piano_operativo 
            WHERE DATE(data_riferimento) = %s 
              AND stato = 'VALIDATO'
              AND id != %s
        """, (giorno_piano, piano_id))
        
        piani_validato = cur.fetchall()
        if piani_validato:
            return {
                "piano_id": str(piano_id),
                "stato": piano_stato_attuale,
                "validato": False,
                "messaggio": f"Validazione fallita: esistono altri piani con stato VALIDATO per il giorno {giorno_piano}",
                "corse_giorno": 0,
                "assegnazioni_pianificate": 0,
                "simulazioni_schedulate": 0,
                "dettaglio_simulazioni": None
            }
        
        # 2. Recupera tutte le corse del giorno del piano
        cur.execute("""
            SELECT id 
            FROM corsa 
            WHERE DATE(orario_partenza_schedulato) = %s
        """, (giorno_piano,))
        
        corse_giorno = cur.fetchall()
        corse_ids = [str(c[0]) for c in corse_giorno]
        num_corse_giorno = len(corse_ids)
        
        if num_corse_giorno == 0:
            return {
                "piano_id": str(piano_id),
                "stato": piano_stato_attuale,
                "validato": False,
                "messaggio": f"Validazione fallita: nessuna corsa trovata per il giorno {giorno_piano}",
                "corse_giorno": 0,
                "assegnazioni_pianificate": 0,
                "simulazioni_schedulate": 0,
                "dettaglio_simulazioni": None
            }
        
        # 3. Verifica che ci siano assegnazioni PIANIFICATE per tutte le corse del giorno
        # Recupera le corse che hanno almeno un'assegnazione PIANIFICATA
        cur.execute("""
            SELECT DISTINCT p.id_corsa
            FROM assegnazione a
            JOIN percorso p ON p.id = a.percorso_id
            WHERE a.stato_esecuzione = 'PIANIFICATA'
              AND DATE(
                  (SELECT c.orario_partenza_schedulato FROM corsa c WHERE c.id = p.id_corsa)
              ) = %s
        """, (giorno_piano,))
        
        corse_con_assegnazione = cur.fetchall()
        corse_con_assegnazione_ids = set(str(c[0]) for c in corse_con_assegnazione)
        
        # Verifica se tutte le corse del giorno hanno un'assegnazione
        corse_mancanti = [cid for cid in corse_ids if cid not in corse_con_assegnazione_ids]
        
        if corse_mancanti:
            return {
                "piano_id": str(piano_id),
                "stato": piano_stato_attuale,
                "validato": False,
                "messaggio": f"Validazione fallita: {len(corse_mancanti)} corse senza assegnazione PIANIFICATA",
                "corse_giorno": num_corse_giorno,
                "assegnazioni_pianificate": len(corse_con_assegnazione_ids),
                "simulazioni_schedulate": 0,
                "dettaglio_simulazioni": None
            }
        
        # 4. Tutte le verifiche sono passate - Aggiorna lo stato del piano a VALIDATO
        cur.execute("""
            UPDATE piano_operativo 
            SET stato = 'VALIDATO' 
            WHERE id = %s
        """, (piano_id,))
        
        # 5. Recupera TUTTE le assegnazioni del piano con virtuale = true per schedulare le simulazioni
        cur.execute("""
            SELECT 
                a.id as assegnazione_id,
                c.orario_partenza_schedulato
            FROM assegnazione a
            JOIN percorso p ON p.id = a.percorso_id
            JOIN corsa c ON c.id = p.id_corsa
            WHERE a.piano_id = %s 
              AND a.virtuale = true
              AND a.stato_esecuzione = 'PIANIFICATA'
            ORDER BY c.orario_partenza_schedulato ASC
        """, (piano_id,))
        
        assegnazioni_virtuali = cur.fetchall()
        
        simulazioni_schedulate = 0
        dettaglio_simulazioni = []
        
        for assegnazione_id, orario_partenza in assegnazioni_virtuali:
            job_id = f"sim_valida_{piano_id}_{assegnazione_id}_{uuid_module.uuid4().hex[:8]}"
            
            try:
                schedule_simulation_job(
                    job_id=job_id,
                    run_date=orario_partenza,
                    assegnazione_id=str(assegnazione_id)
                )
                
                dettaglio_simulazioni.append({
                    "assegnazione_id": str(assegnazione_id),
                    "orario_simulazione": orario_partenza.isoformat(),
                    "job_id": job_id
                })
                simulazioni_schedulate += 1
                
            except Exception as e:
                print(f"[valida_piano] Errore scheduling assegnazione {assegnazione_id}: {e}")
        
        conn.commit()
        
        return {
            "piano_id": str(piano_id),
            "stato": "VALIDATO",
            "validato": True,
            "messaggio": f"Piano validato con successo. Stato aggiornato a VALIDATO. Schedulate {simulazioni_schedulate} simulazioni.",
            "corse_giorno": num_corse_giorno,
            "assegnazioni_pianificate": len(corse_con_assegnazione_ids),
            "simulazioni_schedulate": simulazioni_schedulate,
            "dettaglio_simulazioni": dettaglio_simulazioni if dettaglio_simulazioni else None
        }
        
    except HTTPException:
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"Errore durante la validazione del piano: {str(e)}")
    finally:
        cur.close()
        conn.close()
