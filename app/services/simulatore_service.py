import json
import requests
import math
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from app.core.config import SIMULATION_URL, KAFKA_CONFIG, OPERATIVO_SERVICE_URL, PERCORSI_SERVICE_URL, ANAGRAFICA_SERVICE_URL
from fastapi import HTTPException
from datetime import datetime, timedelta
from app.models.common import SimulationBuildInput


def _get_json(base_url: str, path: str, timeout: float = 10.0):
    url = f"{base_url.rstrip('/')}{path}"
    try:
        response = requests.get(url, timeout=timeout)
    except requests.RequestException as exc:
        raise HTTPException(status_code=503, detail=f"Servizio interno non raggiungibile: {base_url}") from exc

    if response.status_code == 404:
        return None
    if response.status_code >= 400:
        raise HTTPException(status_code=503, detail=f"Errore servizio interno ({base_url}): HTTP {response.status_code}")

    try:
        return response.json()
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Risposta non valida dal servizio interno: {base_url}") from exc

def build_and_run_simulation(data: SimulationBuildInput):
    vessels_out = []
    vessels_resolved = []
    
    # Risolvi sim_speed_factor: usa config se non fornito, altrimenti aggiorna config
    if data.sim_speed_factor is not None:
        KAFKA_CONFIG["sim_speed_factor"] = data.sim_speed_factor
        effective_sim_speed_factor = data.sim_speed_factor
    else:
        effective_sim_speed_factor = KAFKA_CONFIG["sim_speed_factor"]

    try:
        for el in data.elementi:
            assegnazione = _get_json(OPERATIVO_SERVICE_URL, f"/internal/assegnazione/{el.assegnazione_id}")
            if not isinstance(assegnazione, dict):
                raise HTTPException(404, f"Assegnazione non trovata: {el.assegnazione_id}")

            percorso_id = assegnazione.get("percorso_id")
            if not percorso_id:
                raise HTTPException(404, f"Percorso non associato all'assegnazione: {el.assegnazione_id}")

            percorso = _get_json(PERCORSI_SERVICE_URL, f"/internal/percorso/{percorso_id}?include=corsa,tratta,vascello")
            if not isinstance(percorso, dict):
                raise HTTPException(404, f"Percorso non trovato: {percorso_id}")

            corsa = percorso.get("corsa") if isinstance(percorso.get("corsa"), dict) else {}
            tratta = percorso.get("tratta") if isinstance(percorso.get("tratta"), dict) else {}
            vascello = percorso.get("vascello") if isinstance(percorso.get("vascello"), dict) else {}

            tempo_percorrenza_min = percorso.get("tempo_percorrenza")
            geom_json = percorso.get("geom_rotta")
            pref_arr = percorso.get("pref")
            vref_arr = percorso.get("vref")
            orario_partenza_raw = corsa.get("orario_partenza_schedulato")
            porto_partenza_id = tratta.get("porto_partenza_id")
            porto_arrivo_id = tratta.get("porto_arrivo_id")
            vascello_id = percorso.get("vascello_id")
            virtuale = assegnazione.get("virtuale")

            if not (geom_json and orario_partenza_raw and porto_partenza_id and porto_arrivo_id and vascello_id):
                raise HTTPException(400, f"Dati percorso incompleti per assegnazione: {el.assegnazione_id}")

            orario_partenza = datetime.fromisoformat(str(orario_partenza_raw).replace("Z", "+00:00"))

            nome_vascello = vascello.get("nome")
            mmsi_vascello = vascello.get("mmsi")
            if nome_vascello is None or mmsi_vascello is None:
                vascello_full = _get_json(ANAGRAFICA_SERVICE_URL, f"/internal/vascello/{vascello_id}")
                if not isinstance(vascello_full, dict):
                    raise HTTPException(404, f"Vascello non trovato: {vascello_id}")
                nome_vascello = vascello_full.get("nome")
                mmsi_vascello = vascello_full.get("mmsi")

            porto_arrivo = _get_json(ANAGRAFICA_SERVICE_URL, f"/internal/porto/{porto_arrivo_id}")
            if not isinstance(porto_arrivo, dict):
                raise HTTPException(404, "Porto di arrivo non trovato")
            nome_porto_arrivo = porto_arrivo.get("nome")

            if el.lat_start is None or el.lon_start is None:
                porto_partenza = _get_json(ANAGRAFICA_SERVICE_URL, f"/internal/porto/{porto_partenza_id}")
                if not isinstance(porto_partenza, dict):
                    raise HTTPException(404, "Porto di partenza non trovato")
                lat_db = porto_partenza.get("lat")
                lon_db = porto_partenza.get("lon")
                lat_start = el.lat_start if el.lat_start is not None else lat_db
                lon_start = el.lon_start if el.lon_start is not None else lon_db
            else:
                lat_start = el.lat_start
                lon_start = el.lon_start

            vessels_resolved.append({
                "assegnazione_id": el.assegnazione_id,
                "lat_start": lat_start,
                "lon_start": lon_start,
                "vascello": nome_vascello
            })

            try:
                eta = orario_partenza + timedelta(minutes=float(tempo_percorrenza_min))
            except Exception:
                eta = orario_partenza

            eta_str = eta.strftime("%Y-%m-%d %H:%M")

            geom = json.loads(geom_json) if isinstance(geom_json, str) else geom_json
            coords = geom["coordinates"]

            waypoints = []
            for i, (lon, lat) in enumerate(coords):
                is_last = (i == len(coords) - 1)
                if is_last:
                    waypoints.append({
                        "lat": lat,
                        "lon": lon,
                        "type": "Stop",
                        "stop_duration": 30.0
                    })
                else:
                    wp = {
                        "lat": lat,
                        "lon": lon,
                        "type": "Walkthrough"
                    }

                    # ------------------------------------------
                    # TEMPORANEAMENTE DISABILITATO
                    # ------------------------------------------

                    # # Pa
                    if pref_arr and i < len(pref_arr) and pref_arr[i] is not None:
                         pa = float(pref_arr[i])
                         wp["Pa"] = pa
                    else:
                         pa = None

                    #Vr = [vx, vy]
                    if (
                         pa is not None and
                         vref_arr and
                         i < len(vref_arr) and
                         vref_arr[i] is not None
                    ):
                        vref = float(vref_arr[i])
                        alpha = pa  # ✅ pa è già in radianti, non serve math.radians()
                        vx = vref * math.cos(alpha)
                        vy = vref * math.sin(alpha)
                        wp["Vr"] = [vx, vy]

                    waypoints.append(wp)

            vessel_obj = {
                "destination": nome_porto_arrivo,
                # "eta": eta_str,
                "name": nome_vascello,
                "mmsi": str(mmsi_vascello),
                "lat": lat_start,
                "lon": lon_start,
                "heading": 0.0,
                "speed": 2.0,
                "mass": 1000.0,
                "drag_coeff": 5000.0,
                "max_thrust": 50000.0,
                "max_turn_rate": 0.10472,
                "turning_gain": 1.0,
                "waypoints": waypoints,
                "virtuale": virtuale if virtuale is not None else False
            }

            vessels_out.append(vessel_obj)

        payload = {
            "timestep": 0.1,
            "vessels": vessels_out,
            "sim_speed_factor": effective_sim_speed_factor
        }

        session = requests.Session()
        session.mount(
            "http://",
            HTTPAdapter(max_retries=Retry(total=0, connect=0, read=0, redirect=0, status=0))
        )

        r = session.post(
            f"{SIMULATION_URL}/start",
            json=payload,
            timeout=300
        )

        if r.status_code != 200:
            raise HTTPException(
                status_code=500,
                detail=f"Simulation error: {r.text}"
            )

        return {
            "status": "ok",
            "resolved_starts": vessels_resolved,
            "simulation_response": r.json()
        }
    finally:
        pass


def simula_piano(data):
    """
    Simula un piano operativo schedulando le simulazioni delle assegnazioni virtuali
    a partire dal momento della chiamata, mantenendo i delta temporali originali.
    
    Args:
        data: SimulaPianoInput con piano_id e delay_start_seconds
        
    Returns:
        SimulaPianoResponse con dettaglio delle simulazioni schedulate
    """
    from app.models.common import SimulaPianoInput, SimulaPianoResponse, SimulazionePianoResult
    from app.core.scheduler import schedule_simulation_job
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo
    import uuid as uuid_module
    
    # Timezone italiano
    tz_rome = ZoneInfo("Europe/Rome")
    
    if not isinstance(data, SimulaPianoInput):
        data = SimulaPianoInput(**data)
    
    # Risolvi sim_speed_factor: usa config se non fornito, altrimenti aggiorna config
    if data.sim_speed_factor is not None:
        KAFKA_CONFIG["sim_speed_factor"] = data.sim_speed_factor
        effective_sim_speed_factor = data.sim_speed_factor
    else:
        effective_sim_speed_factor = KAFKA_CONFIG["sim_speed_factor"]
    
    import os
    try:
        assegnazioni = _get_json(OPERATIVO_SERVICE_URL, f"/internal/assegnazione/by_piano/{data.piano_id}")
        if not isinstance(assegnazioni, list):
            assegnazioni = []

        rows = []
        for a in assegnazioni:
            if not isinstance(a, dict):
                continue
            if a.get("virtuale") is not True:
                continue
            if str(a.get("stato_esecuzione")) != "PIANIFICATA":
                continue
            corsa_id = a.get("id_corsa")
            if not corsa_id:
                continue
            corsa = _get_json(OPERATIVO_SERVICE_URL, f"/internal/corsa/id/{corsa_id}")
            if not isinstance(corsa, dict):
                continue
            orario_raw = corsa.get("orario_partenza_schedulato")
            if not orario_raw:
                continue
            try:
                orario_partenza = datetime.fromisoformat(str(orario_raw).replace("Z", "+00:00"))
            except Exception:
                continue
            rows.append((str(a.get("id")), orario_partenza))

        rows.sort(key=lambda item: item[1])
        
        if not rows:
            return SimulaPianoResponse(
                piano_id=data.piano_id,
                status="ok",
                assegnazioni_virtuali_trovate=0,
                simulazioni_schedulate=0,
                orario_base_simulazione=datetime.now(tz_rome).isoformat(),
                risultati=[],
                messaggio="Nessuna assegnazione virtuale pianificata trovata per questo piano"
            )
        
        # Determina l'orario base (prima partenza originale)
        prima_partenza_originale = rows[0][1]
        
        # Orario base per le simulazioni (adesso + delay) con timezone italiano
        orario_base_simulazione = datetime.now(tz_rome) + timedelta(seconds=data.delay_start_seconds)
        
        risultati = []
        simulazioni_schedulate = 0
        
        for assegnazione_id, orario_partenza_originale in rows:
            # Calcola il delta rispetto alla prima partenza originale
            delta = orario_partenza_originale - prima_partenza_originale
            delta_seconds = int(delta.total_seconds())
            
            # Scala il delta in base al sim_speed_factor
            # (se sim_speed_factor=2, un delta di 2h diventa 1h)
            scaled_delta_seconds = int(delta_seconds / effective_sim_speed_factor)
            
            # Calcola l'orario di simulazione (base + delta scalato)
            orario_simulazione = orario_base_simulazione + timedelta(seconds=scaled_delta_seconds)
            
            # Genera job_id unico
            job_id = f"sim_piano_{data.piano_id}_{assegnazione_id}_{uuid_module.uuid4().hex[:8]}"
            
            try:
                schedule_simulation_job(
                    job_id=job_id,
                    run_date=orario_simulazione,
                    assegnazione_id=str(assegnazione_id),
                    sim_speed_factor=effective_sim_speed_factor
                )
                
                risultati.append(SimulazionePianoResult(
                    assegnazione_id=str(assegnazione_id),
                    orario_originale=orario_partenza_originale.isoformat(),
                    orario_simulazione=orario_simulazione.isoformat(),
                    delta_from_first_seconds=delta_seconds,
                    job_id=job_id
                ))
                simulazioni_schedulate += 1
                
            except Exception as e:
                print(f"[simula_piano] Errore scheduling assegnazione {assegnazione_id}: {e}")
        
        # Salva i dettagli delle simulazioni schedulate in un file JSON locale
        output = {
            "piano_id": data.piano_id,
            "status": "ok",
            "assegnazioni_virtuali_trovate": len(rows),
            "simulazioni_schedulate": simulazioni_schedulate,
            "orario_base_simulazione": orario_base_simulazione.isoformat(),
            "risultati": [r.dict() if hasattr(r, 'dict') else r for r in risultati],
            "messaggio": f"Schedulate {simulazioni_schedulate} simulazioni a partire da {orario_base_simulazione.strftime('%H:%M:%S')}"
        }
        data_dir = os.path.join(os.path.dirname(__file__), '..', 'data')
        os.makedirs(data_dir, exist_ok=True)
        file_path = os.path.join(data_dir, f'simulazioni_schedulate_{data.piano_id}.json')
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(output, f, ensure_ascii=False, indent=2)

        return SimulaPianoResponse(**output)
        
    finally:
        pass

