"""
Servizio per la modifica controllata di un percorso,
applicando variazioni codificate come guasti o deviazioni.
"""
import json
import random
import math
import uuid
from typing import Dict, Any, Tuple, List
from fastapi import HTTPException
from app.core.database import get_connection
from app.models.common import VariazionePercorsoInput, VariazionePercorsoResponse


def _calcola_punto_deviato(
    lon1: float, lat1: float, 
    lon2: float, lat2: float, 
    offset_nm: float
) -> Tuple[float, float]:
    """
    Calcola un punto intermedio spostato perpendicolarmente rispetto
    alla retta tra due waypoint.
    
    Args:
        lon1, lat1: Coordinate del primo waypoint
        lon2, lat2: Coordinate del secondo waypoint
        offset_nm: Offset in miglia nautiche
        
    Returns:
        Tuple (lon, lat) del punto deviato
    """
    # Punto medio
    mid_lon = (lon1 + lon2) / 2
    mid_lat = (lat1 + lat2) / 2
    
    # Vettore direzione
    dx = lon2 - lon1
    dy = lat2 - lat1
    
    # Lunghezza vettore
    length = math.sqrt(dx * dx + dy * dy)
    if length < 1e-9:
        return mid_lon, mid_lat
    
    # Vettore perpendicolare normalizzato
    perp_x = -dy / length
    perp_y = dx / length
    
    # Conversione offset da miglia nautiche a gradi (approssimativo)
    # 1 miglio nautico ≈ 1/60 di grado di latitudine
    offset_deg = offset_nm / 60.0
    
    # Sceglie casualmente se deviare a destra o sinistra
    direction = random.choice([-1, 1])
    
    # Punto deviato
    new_lon = mid_lon + direction * perp_x * offset_deg
    new_lat = mid_lat + direction * perp_y * offset_deg
    
    return new_lon, new_lat


def applica_variazione_guasto(
    coords: List[List[float]],
    vref_arr: List[float],
    pref_arr: List[float]
) -> Dict[str, Any]:
    """
    Applica una variazione di tipo GUASTO.
    Sceglie un waypoint casuale con vref non null e divide vref per 8.
    
    Returns:
        Dizionario con coords, vref, pref modificati e dettagli della variazione
    """
    # Trova waypoint con vref valido (non null e > 0)
    candidati = [
        i for i, v in enumerate(vref_arr) 
        if v is not None and v > 0
    ]
    
    if not candidati:
        raise HTTPException(
            status_code=400,
            detail="Nessun waypoint con vref valido trovato per applicare il guasto"
        )
    
    # Sceglie un waypoint casuale
    idx_guasto = random.choice(candidati)
    vref_originale = vref_arr[idx_guasto]
    vref_nuovo = vref_originale / 8.0
    
    # Crea copie modificate
    new_vref = vref_arr.copy()
    new_vref[idx_guasto] = vref_nuovo
    
    return {
        "coords": coords,  # Non modificate
        "vref": new_vref,
        "pref": pref_arr,  # Non modificata
        "dettagli": {
            "waypoint_index": idx_guasto,
            "waypoint_coords": coords[idx_guasto] if idx_guasto < len(coords) else None,
            "vref_originale": vref_originale,
            "vref_modificato": vref_nuovo,
            "fattore_riduzione": 8
        }
    }


def applica_variazione_deviazione(
    coords: List[List[float]],
    vref_arr: List[float],
    pref_arr: List[float],
    offset_nm: float
) -> Dict[str, Any]:
    """
    Applica una variazione di tipo DEVIAZIONE.
    Inserisce un waypoint intermedio tra due waypoint consecutivi,
    spostato perpendicolarmente rispetto alla retta.
    
    Returns:
        Dizionario con coords, vref, pref modificati e dettagli della variazione
    """
    if len(coords) < 2:
        raise HTTPException(
            status_code=400,
            detail="Percorso troppo corto per applicare una deviazione (minimo 2 waypoint)"
        )
    
    # Sceglie una coppia casuale di waypoint consecutivi (esclude l'ultimo segmento)
    # per evitare di deviare proprio prima dell'arrivo
    max_idx = len(coords) - 2
    if max_idx < 0:
        max_idx = 0
    
    idx_inizio = random.randint(0, max_idx)
    
    lon1, lat1 = coords[idx_inizio]
    lon2, lat2 = coords[idx_inizio + 1]
    
    # Calcola punto deviato
    new_lon, new_lat = _calcola_punto_deviato(lon1, lat1, lon2, lat2, offset_nm)
    
    # Inserisce il nuovo waypoint
    new_coords = coords[:idx_inizio + 1] + [[new_lon, new_lat]] + coords[idx_inizio + 1:]
    
    # Interpola vref e pref per il nuovo waypoint
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
    
    new_vref = vref_arr[:idx_inizio + 1] + [new_vref_value] + vref_arr[idx_inizio + 1:]
    new_pref = pref_arr[:idx_inizio + 1] + [new_pref_value] + pref_arr[idx_inizio + 1:]
    
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
            "pref_interpolato": new_pref_value
        }
    }


def applica_variazione_percorso(data: VariazionePercorsoInput) -> VariazionePercorsoResponse:
    """
    Applica una variazione a un percorso esistente e salva una copia modificata.
    
    Tipi di variazione supportati:
    - GUASTO: Riduce la vref di un waypoint casuale dividendola per 8
    - DEVIAZIONE: Inserisce un waypoint intermedio deviato rispetto alla rotta
    
    Args:
        data: Input con ID percorso e tipo variazione
        
    Returns:
        Risposta con ID del nuovo percorso e dettagli della variazione
    """
    conn = get_connection()
    cur = conn.cursor()
    
    tipo_variazione = data.tipo_variazione.upper().strip()
    
    if tipo_variazione not in ["GUASTO", "DEVIAZIONE"]:
        raise HTTPException(
            status_code=400,
            detail=f"Tipo variazione non supportato: {data.tipo_variazione}. Valori ammessi: GUASTO, DEVIAZIONE"
        )
    
    try:
        # Recupera il percorso originale
        cur.execute("""
            SELECT 
                id,
                id_corsa,
                pref,
                vref,
                tempo_percorrenza_min,
                consumo,
                ST_AsGeoJSON(geom_rotta),
                vascello_id,
                comfort,
                distanza_nm
            FROM percorso
            WHERE id = %s
        """, (data.percorso_id,))
        
        row = cur.fetchone()
        if row is None:
            raise HTTPException(
                status_code=404,
                detail=f"Percorso non trovato: {data.percorso_id}"
            )
        
        (
            percorso_id, corsa_id, pref_arr, vref_arr,
            tempo_percorrenza, consumo, geom_json,
            vascello_id, comfort, distanza_nm
        ) = row
        
        # Parse geometria
        geom = json.loads(geom_json)
        coords = geom.get("coordinates", [])
        
        # Assicura che vref e pref siano liste
        if vref_arr is None:
            vref_arr = [None] * len(coords)
        else:
            vref_arr = list(vref_arr)
            
        if pref_arr is None:
            pref_arr = [None] * len(coords)
        else:
            pref_arr = list(pref_arr)
        
        # Applica la variazione
        if tipo_variazione == "GUASTO":
            risultato = applica_variazione_guasto(coords, vref_arr, pref_arr)
        else:  # DEVIAZIONE
            risultato = applica_variazione_deviazione(
                coords, vref_arr, pref_arr, 
                data.offset_deviazione_nm
            )
        
        # Costruisce la nuova geometria
        new_geom = {
            "type": "LineString",
            "coordinates": risultato["coords"]
        }
        new_geom_json = json.dumps(new_geom)
        
        # Genera nuovo UUID per il percorso variato
        nuovo_percorso_id = str(uuid.uuid4())
        
        # Converti vref e pref in JSON per il database (colonne jsonb)
        new_vref_json = json.dumps(risultato["vref"])
        new_pref_json = json.dumps(risultato["pref"])
        
        # Inserisce il nuovo percorso
        cur.execute("""
            INSERT INTO percorso (
                id,
                id_corsa,
                pref,
                vref,
                tempo_percorrenza_min,
                consumo,
                geom_rotta,
                vascello_id,
                comfort,
                distanza_nm
            ) VALUES (
                %s, %s, %s::jsonb, %s::jsonb, %s, %s,
                ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326),
                %s, %s, %s
            )
        """, (
            nuovo_percorso_id,
            corsa_id,
            new_pref_json,
            new_vref_json,
            tempo_percorrenza,
            consumo,
            new_geom_json,
            vascello_id,
            comfort,
            distanza_nm
        ))
        
        conn.commit()
        
        return VariazionePercorsoResponse(
            status="ok",
            percorso_originale_id=str(percorso_id),
            percorso_variato_id=nuovo_percorso_id,
            tipo_variazione=tipo_variazione,
            dettagli_variazione=risultato["dettagli"],
            messaggio=f"Variazione {tipo_variazione} applicata con successo. Nuovo percorso creato."
        )
        
    except HTTPException:
        conn.rollback()
        raise
    except Exception as e:
        conn.rollback()
        raise HTTPException(
            status_code=500,
            detail=f"Errore durante l'applicazione della variazione: {str(e)}"
        )
    finally:
        conn.close()
