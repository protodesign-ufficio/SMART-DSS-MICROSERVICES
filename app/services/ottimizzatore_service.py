import requests
import json
from datetime import datetime, timedelta
from app.core.config import OPT_URL, OPERATIVO_SERVICE_URL, ANAGRAFICA_SERVICE_URL, PERCORSI_SERVICE_URL, SERVICE_CONFIG, WEATHER_SERVICE_URL
from app.models.common import OttimizzatoreInput, OttimizzatoreBatchInput, RiposizionamentoInput
from fastapi import HTTPException
import psycopg2
from typing import List


def _parse_iso_datetime(value: str | None):
    if not value:
        return None
    normalized = value.replace("Z", "+00:00")
    return datetime.fromisoformat(normalized)


def _is_within_cache_window(created_at: str | None, cache_delta: timedelta) -> bool:
    dt = _parse_iso_datetime(created_at)
    if dt is None:
        return False
    now = datetime.now(dt.tzinfo) if dt.tzinfo else datetime.now()
    return dt >= (now - cache_delta)


def _get_json(base_url: str, path: str, timeout: float = 10.0):
    url = f"{base_url.rstrip('/')}{path}"
    try:
        response = requests.get(url, timeout=timeout)
    except requests.RequestException as exc:
        raise HTTPException(503, f"Servizio interno non raggiungibile: {base_url}") from exc

    if response.status_code == 404:
        return None
    if response.status_code >= 400:
        raise HTTPException(503, f"Errore servizio interno ({base_url}): HTTP {response.status_code}")

    try:
        return response.json()
    except Exception as exc:
        raise HTTPException(502, f"Risposta non valida dal servizio interno: {base_url}") from exc


def _post_json(base_url: str, path: str, payload, timeout: float = 30.0):
    url = f"{base_url.rstrip('/')}{path}"
    try:
        response = requests.post(url, json=payload, timeout=timeout)
    except requests.RequestException as exc:
        raise HTTPException(503, f"Servizio interno non raggiungibile: {base_url}") from exc

    if response.status_code >= 400:
        detail = f"HTTP {response.status_code}"
        try:
            body = response.json()
            if isinstance(body, dict) and "detail" in body:
                detail = body["detail"]
        except Exception:
            pass
        raise HTTPException(response.status_code, f"Errore servizio interno ({base_url}): {detail}")

    try:
        return response.json() if response.content else None
    except Exception as exc:
        raise HTTPException(502, f"Risposta non valida dal servizio interno: {base_url}") from exc


def ottimizzatore(data: OttimizzatoreBatchInput):
    """
    Calcola il weather routing per una lista di coppie corsa/vascello.
    Costruisce i payload dal DB e fa un'unica chiamata al servizio esterno.
    """
    items = data.items if isinstance(data, OttimizzatoreBatchInput) else [OttimizzatoreInput(**d) for d in data]
    
    results = []
    payloads_to_compute = []  # lista di (inp, payload, corsa_data)
    
    try:
        cache_delta = timedelta(minutes=SERVICE_CONFIG.cache_delta_minutes)
        # Prima fase: raccolta dati da microservizi per ogni item
        for inp in items:
            cached = _get_json(
                PERCORSI_SERVICE_URL,
                f"/internal/percorso/by_corsa/{inp.corsa_id}?order_by=created_at&mode=DESC&limit=200&vascello_id={inp.vascello_id}",
                timeout=10.0,
            )
            if isinstance(cached, dict):
                cached_percorsi = cached.get("percorsi", [])
                recent_ids = [
                    str(p.get("id"))
                    for p in cached_percorsi
                    if p.get("id") and _is_within_cache_window(p.get("created_at"), cache_delta)
                ]
                if recent_ids:
                    results.append(
                        {
                            "status": "cached",
                            "corsa_id": inp.corsa_id,
                            "vascello_id": inp.vascello_id,
                            "percorsi_inseriti": recent_ids,
                        }
                    )
                    continue

            corsa = _get_json(OPERATIVO_SERVICE_URL, f"/internal/corsa/id/{inp.corsa_id}")
            if corsa is None:
                raise HTTPException(404, f"Corsa {inp.corsa_id} non trovata")

            tratta_id = corsa.get("tratta_id")
            tratta = _get_json(ANAGRAFICA_SERVICE_URL, f"/internal/tratta/{tratta_id}") if tratta_id else None
            if tratta is None:
                raise HTTPException(404, f"Tratta {tratta_id} non trovata per corsa {inp.corsa_id}")

            porto_partenza_id = tratta.get("porto_partenza_id")
            porto_arrivo_id = tratta.get("porto_arrivo_id")
            porto_partenza = _get_json(ANAGRAFICA_SERVICE_URL, f"/internal/porto/{porto_partenza_id}") if porto_partenza_id else None
            porto_arrivo = _get_json(ANAGRAFICA_SERVICE_URL, f"/internal/porto/{porto_arrivo_id}") if porto_arrivo_id else None
            if porto_partenza is None:
                raise HTTPException(404, f"Porto partenza {porto_partenza_id} non trovato")
            if porto_arrivo is None:
                raise HTTPException(404, f"Porto arrivo {porto_arrivo_id} non trovato")

            lat_start = porto_partenza.get("lat")
            lon_start = porto_partenza.get("lon")
            lat_end = porto_arrivo.get("lat")
            lon_end = porto_arrivo.get("lon")

            vascello = _get_json(ANAGRAFICA_SERVICE_URL, f"/internal/vascello/{inp.vascello_id}")
            if vascello is None:
                raise HTTPException(404, f"Vascello {inp.vascello_id} non trovato")
            vascello_id = str(vascello.get("id"))
            vascello_nome = vascello.get("nome")
            vmax_knots = float(vascello.get("velocita_max_nodi")) if vascello.get("velocita_max_nodi") is not None else None
            length_raw = vascello.get("lunghezza_m")
            length_m = float(length_raw) if length_raw is not None else 30.0
            
            # Calcola time_max
            orario_partenza_schedulato = _parse_iso_datetime(corsa.get("orario_partenza_schedulato"))
            if orario_partenza_schedulato is None:
                raise HTTPException(400, f"orario_partenza_schedulato mancante/non valido per corsa {inp.corsa_id}")

            orario_arrivo_max = _parse_iso_datetime(corsa.get("orario_arrivo_max"))

            start_time_utc = orario_partenza_schedulato.isoformat()
            if orario_arrivo_max is not None:
                delta = orario_arrivo_max - orario_partenza_schedulato
                time_max_seconds = int(delta.total_seconds())
                if time_max_seconds <= 0:
                    raise HTTPException(400, f"orario_arrivo_max <= orario_partenza_schedulato per corsa {inp.corsa_id}")
            else:
                time_max_seconds = 3600
            
            # Costruisci payload per servizio esterno
            payload = {
                "vessel": {
                    "id": vascello_id,
                    "name": vascello_nome,
                    "length_m": length_m,
                    "vmax_knots": vmax_knots
                },
                "start": {"lat": float(lat_start), "lon": float(lon_start)},
                "goal": {"lat": float(lat_end), "lon": float(lon_end)},
                "params": {
                    "start_time_utc": start_time_utc,
                    "time_max": time_max_seconds,
                    "vel_vect_knots": [2, 4, 6, 8, 10]
                },
                "optimization_id": f"{inp.corsa_id}_{inp.vascello_id}",
                "ve_min": inp.ve_min,
                "eps_time": inp.eps_time,
                "empty": False,
                "fake_data": inp.fake_data,
                "tollerance": inp.tolerance
            }

            # Risolvi scenario_id → scenario params dal weather service
            if inp.scenario_id is not None:
                scenario_data = _get_json(WEATHER_SERVICE_URL, f"/internal/weather/scenarios/{inp.scenario_id}", timeout=10.0)
                if scenario_data is None:
                    raise HTTPException(404, f"Scenario {inp.scenario_id} non trovato nel weather service")
                payload["scenario"] = scenario_data.get("scenario", {})
            
            corsa_data = {
                "corsa_id": inp.corsa_id,
                "vascello_id": vascello_id,
                "orario_partenza_schedulato": orario_partenza_schedulato,
                "orario_arrivo_max": orario_arrivo_max
            }
            payloads_to_compute.append((inp, payload, corsa_data))
        
        # Se non ci sono payload da calcolare, ritorna i risultati correnti
        if not payloads_to_compute:
            return {"results": results}
        
        # Seconda fase: chiamata unica al servizio esterno con lista di payload
        all_payloads = [p[1] for p in payloads_to_compute]
        
        r = requests.post(OPT_URL, json=all_payloads, timeout=600)
        if r.status_code != 200:
            raise HTTPException(500, f"Optimizer error: {r.text}")
        
        resp_list = r.json()
        if not isinstance(resp_list, list):
            # Se la risposta è un singolo oggetto, wrappalo in lista
            resp_list = [resp_list]
        
        # Terza fase: elaborazione risposte e inserimento via microservizio percorsi
        for idx, (inp, payload, corsa_data) in enumerate(payloads_to_compute):
            if idx >= len(resp_list):
                results.append({
                    "status": "error",
                    "corsa_id": corsa_data["corsa_id"],
                    "vascello_id": corsa_data["vascello_id"],
                    "percorsi_inseriti": []
                })
                continue
            
            resp = resp_list[idx]
            
            if not isinstance(resp, dict) or "percorsi" not in resp:
                results.append({
                    "status": "error",
                    "corsa_id": corsa_data["corsa_id"],
                    "vascello_id": corsa_data["vascello_id"],
                    "percorsi_inseriti": []
                })
                continue
            
            percorsi = resp["percorsi"]
            tempo_riposizionamento_min = float(resp.get("tempo_riposizionamento", 0.0)) if resp.get("tempo_riposizionamento") is not None else 0.0

            insert_items = []
            for p in percorsi:
                required_keys = ["tempo_percorrenza", "geom_rotta", "pref", "vref", "consumo_pieno_carico", "consumo_vuoto", "distanza_nm", "comfort"]
                if not all(k in p for k in required_keys):
                    continue
                
                tempo_percorrenza_min = float(p["tempo_percorrenza"])
                
                if corsa_data["orario_arrivo_max"] is not None:
                    orario_arrivo_stimato = corsa_data["orario_partenza_schedulato"] + timedelta(minutes=tempo_percorrenza_min)
                    if orario_arrivo_stimato > corsa_data["orario_arrivo_max"]:
                        continue
                
                consumo = float(p["consumo_pieno_carico"]) if p.get("consumo_pieno_carico") is not None else float(p.get("consumo", 0))
                consumo_riposizionamento = float(p.get("consumo_vuoto", 0))
                geojson = {"type": "LineString", "coordinates": [[c[1], c[0]] for c in p["geom_rotta"]]}

                insert_items.append({
                    "id_corsa": corsa_data["corsa_id"],
                    "vascello_id": corsa_data["vascello_id"],
                    "pref": p["pref"],
                    "vref": p["vref"],
                    "tempo_percorrenza_min": tempo_percorrenza_min,
                    "tempo_riposizionamento_min": tempo_riposizionamento_min,
                    "consumo": consumo,
                    "geom_rotta": geojson,
                    "consumo_riposizionamento": consumo_riposizionamento,
                    "distanza_nm": float(p.get("distanza_nm", 0)),
                    "comfort": float(p.get("comfort", 0)),
                })

            inserted_ids = []
            if insert_items:
                insert_resp = _post_json(PERCORSI_SERVICE_URL, "/internal/percorso/crea_batch", {"items": insert_items}, timeout=40.0)
                if isinstance(insert_resp, dict) and isinstance(insert_resp.get("percorsi_inseriti"), list):
                    inserted_ids = [str(x) for x in insert_resp.get("percorsi_inseriti", [])]
            
            results.append({
                "status": "computed",
                "corsa_id": corsa_data["corsa_id"],
                "vascello_id": corsa_data["vascello_id"],
                "percorsi_inseriti": inserted_ids
            })
        
        return {"results": results}
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Errore interno: {str(e)}")


def stima_riposizionamento(data):
    """
    Stima tempo e consumo per il riposizionamento a vuoto di una lista di vascelli.
    Costruisce i payload dal DB e fa un'unica chiamata al servizio esterno.
    """
    from app.models.common import RiposizionamentoBatchInput, RiposizionamentoInput
    
    if isinstance(data, RiposizionamentoBatchInput):
        items = data.items
    elif isinstance(data, list):
        items = [RiposizionamentoInput(**d) if isinstance(d, dict) else d for d in data]
    else:
        items = [RiposizionamentoInput(**data) if isinstance(data, dict) else data]
    
    results = []
    payloads_to_compute = []  # lista di (inp, payload)
    
    try:
        # Prima fase: raccolta dati da microservizi per ogni item
        for inp in items:
            porto_partenza = _get_json(ANAGRAFICA_SERVICE_URL, f"/internal/porto/{inp.porto_partenza_id}")
            if porto_partenza is None:
                raise HTTPException(404, f"Porto di partenza {inp.porto_partenza_id} non trovato")
            lat_start = porto_partenza.get("lat")
            lon_start = porto_partenza.get("lon")
            if lat_start is None or lon_start is None:
                raise HTTPException(400, f"Coordinate mancanti per porto di partenza {inp.porto_partenza_id}")
            
            porto_destinazione = _get_json(ANAGRAFICA_SERVICE_URL, f"/internal/porto/{inp.porto_destinazione_id}")
            if porto_destinazione is None:
                raise HTTPException(404, f"Porto di destinazione {inp.porto_destinazione_id} non trovato")
            lat_end = porto_destinazione.get("lat")
            lon_end = porto_destinazione.get("lon")
            if lat_end is None or lon_end is None:
                raise HTTPException(400, f"Coordinate mancanti per porto di destinazione {inp.porto_destinazione_id}")
            
            vascello = _get_json(ANAGRAFICA_SERVICE_URL, f"/internal/vascello/{inp.vascello_id}")
            if vascello is None:
                raise HTTPException(404, f"Vascello {inp.vascello_id} non trovato")
            vascello_id_db = str(vascello.get("id"))
            vascello_nome = vascello.get("nome")
            vmax_knots_db = vascello.get("velocita_max_nodi")
            vmax_knots = float(vmax_knots_db) if vmax_knots_db is not None else None
            lunghezza_m = vascello.get("lunghezza_m")
            length_m = float(lunghezza_m) if lunghezza_m is not None else 30.0
            
            if vmax_knots is None:
                raise HTTPException(400, f"velocita_max_nodi (vmax_knots) mancante per il vascello {inp.vascello_id}")
            
            start_time_utc = inp.datetime_partenza
            if inp.graph_cache_ttl_minutes and inp.graph_cache_ttl_minutes > 0:
                # Snap temporale basato su timestamp
                ttl_seconds = inp.graph_cache_ttl_minutes * 60
                ts = start_time_utc.timestamp()
                snapped_ts = (ts // ttl_seconds) * ttl_seconds
                # Ricostruisci datetime mantenendo la timezone originale (o None)
                start_time_utc = datetime.fromtimestamp(snapped_ts, tz=start_time_utc.tzinfo)
            
            start_time_iso = start_time_utc.isoformat()
            time_max_seconds = 6 * 3600
            
            # Costruisci payload per servizio esterno
            payload = {
                "vessel": {
                    "id": str(vascello_id_db),
                    "name": vascello_nome,
                    "length_m": length_m,
                    "vmax_knots": vmax_knots
                },
                "start": {"lat": float(lat_start), "lon": float(lon_start)},
                "goal": {"lat": float(lat_end), "lon": float(lon_end)},
                "params": {
                    "start_time_utc": start_time_iso,
                    "time_max": time_max_seconds,
                    "vel_vect_knots": [2, 4, 6, 8, 10]
                },
                "optimization_id": f"{inp.porto_partenza_id}_{inp.porto_destinazione_id}_{inp.vascello_id}",
                "ve_min": inp.ve_min,
                "eps_time": 5.0,
                "empty": True,
                "fake_data": inp.fake_data,
                "tollerance": inp.tolerance
            }

            # Risolvi scenario_id → scenario params dal weather service
            if inp.scenario_id is not None:
                scenario_data = _get_json(WEATHER_SERVICE_URL, f"/internal/weather/scenarios/{inp.scenario_id}", timeout=10.0)
                if scenario_data is None:
                    raise HTTPException(404, f"Scenario {inp.scenario_id} non trovato nel weather service")
                payload["scenario"] = scenario_data.get("scenario", {})

            payloads_to_compute.append((inp, payload))
        
        # Seconda fase: chiamata unica al servizio esterno con lista di payload
        all_payloads = [p[1] for p in payloads_to_compute]
        
        r = requests.post(OPT_URL, json=all_payloads, timeout=600)
        if r.status_code != 200:
            raise HTTPException(500, f"Optimizer error: {r.text}")
        
        resp_list = r.json()
        if not isinstance(resp_list, list):
            # Se la risposta è un singolo oggetto, wrappalo in lista
            resp_list = [resp_list]
        
        # Terza fase: elaborazione risposte
        for idx, (inp, payload) in enumerate(payloads_to_compute):
            if idx >= len(resp_list):
                results.append({
                    "porto_partenza_id": inp.porto_partenza_id,
                    "porto_destinazione_id": inp.porto_destinazione_id,
                    "vascello_id": inp.vascello_id,
                    "tempo_riposizionamento": 0.0,
                    "consumo_riposizionamento": 0.0
                })
                continue
            
            resp = resp_list[idx]
            tempo_ripos_min = None
            consumo_ripos = None
            
            if isinstance(resp, dict):
                if "tempo_riposizionamento" in resp:
                    tempo_ripos_min = resp.get("tempo_riposizionamento")
                if "percorsi" in resp and isinstance(resp["percorsi"], list) and resp["percorsi"]:
                    p0 = resp["percorsi"][0]
                    if isinstance(p0, dict):
                        consumo_ripos = p0.get("consumo_vuoto") or p0.get("consumo_riposizionamento") or p0.get("consumo")
            
            if tempo_ripos_min is None or consumo_ripos is None:
                raise HTTPException(500, f"Unexpected optimizer response for item {idx}, missing fields. resp={resp}")
            
            results.append({
                "porto_partenza_id": inp.porto_partenza_id,
                "porto_destinazione_id": inp.porto_destinazione_id,
                "vascello_id": inp.vascello_id,
                "tempo_riposizionamento": float(tempo_ripos_min),
                "consumo_riposizionamento": float(consumo_ripos)
            })
        
        return {"results": results}
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"Errore interno: {str(e)}")
