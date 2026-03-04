"""
Scheduler service - calls the external scheduling microservice.
"""
import requests
from datetime import datetime
from typing import List, Dict, Any

from fastapi import HTTPException

from app.core.database import get_connection
from app.core.config import SCHEDULER_URL
from app.models.common import (
    SchedulingInput,
    SchedulingResponse,
    SchedulingByDayInput,
    SchedulingRouteInput,
    SchedulingVesselInput
)


def call_scheduler(data: SchedulingInput) -> SchedulingResponse:
    """
    Call the external scheduler microservice with routes and vessels.
    Returns Pareto-optimal scheduling solutions.
    """
    payload = {
        "routes": [r.model_dump() for r in data.routes],
        "vessels": [v.model_dump() for v in data.vessels],
        "max_solutions": data.max_solutions,
        "include_details": data.include_details
    }
    
    try:
        response = requests.post(SCHEDULER_URL, json=payload, timeout=300)
        response.raise_for_status()
        result = response.json()
        return SchedulingResponse(**result)
    except requests.exceptions.Timeout:
        raise HTTPException(504, "Scheduler service timeout")
    except requests.exceptions.ConnectionError:
        raise HTTPException(503, "Scheduler service unavailable")
    except requests.exceptions.HTTPError as e:
        raise HTTPException(500, f"Scheduler service error: {e.response.text}")


def get_routes_for_day(giorno: str, solo_future: bool = True) -> List[Dict[str, Any]]:
    """
    Get all routes (percorsi) for a given day.
    Returns route data including corsa, vessel, and timing info.
    """
    conn = get_connection()
    cur = conn.cursor()
    
    try:
        # Build the query based on solo_future flag
        if solo_future:
            query = """
                SELECT 
                    p.id as percorso_id,
                    p.id_corsa as corsa_id,
                    c.nome as corsa_name,
                    p.vascello_id,
                    v.nome as vessel_name,
                    v.capacita_passeggeri as capacity,
                    t.porto_partenza_id as origin,
                    t.porto_arrivo_id as destination,
                    c.orario_partenza_schedulato as start_dt,
                    c.orario_partenza_schedulato + p.tempo_percorrenza_min as end_dt,
                    p.consumo,
                    p.comfort,
                    COALESCE(pv.confidenza_min, 0) as pax_min,
                    COALESCE(pv.confidenza_max, 0) as pax_max
                FROM percorso p
                JOIN corsa c ON c.id = p.id_corsa
                JOIN tratta t ON t.id = c.tratta_id
                JOIN vascello v ON v.id = p.vascello_id
                LEFT JOIN previsione_domanda pv ON pv.id = c.previsione_domanda_id
                WHERE DATE(c.orario_partenza_schedulato) = %s
                  AND c.orario_partenza_schedulato > NOW()
                ORDER BY c.orario_partenza_schedulato
            """
        else:
            query = """
                SELECT 
                    p.id as percorso_id,
                    p.id_corsa as corsa_id,
                    c.nome as corsa_name,
                    p.vascello_id,
                    v.nome as vessel_name,
                    v.capacita_passeggeri as capacity,
                    t.porto_partenza_id as origin,
                    t.porto_arrivo_id as destination,
                    c.orario_partenza_schedulato as start_dt,
                    c.orario_partenza_schedulato + p.tempo_percorrenza_min as end_dt,
                    p.consumo,
                    p.comfort,
                    COALESCE(pv.confidenza_min, 0) as pax_min,
                    COALESCE(pv.confidenza_max, 0) as pax_max
                FROM percorso p
                JOIN corsa c ON c.id = p.id_corsa
                JOIN tratta t ON t.id = c.tratta_id
                JOIN vascello v ON v.id = p.vascello_id
                LEFT JOIN previsione_domanda pv ON pv.id = c.previsione_domanda_id
                WHERE DATE(c.orario_partenza_schedulato) = %s
                ORDER BY c.orario_partenza_schedulato
            """
        
        cur.execute(query, (giorno,))
        rows = cur.fetchall()
        
        routes = []
        for row in rows:
            (percorso_id, corsa_id, corsa_name, vascello_id, vessel_name,
             capacity, origin, destination, start_dt, end_dt,
             consumo, comfort, pax_min, pax_max) = row
            
            routes.append({
                "route_id": str(percorso_id),
                "corsa_id": str(corsa_id),
                "corsa_name": corsa_name,
                "vessel_id": str(vascello_id),
                "vessel_name": vessel_name,
                "capacity": float(capacity) if capacity else 100.0,
                "origin": str(origin),
                "destination": str(destination),
                "start_dt": start_dt.isoformat() if start_dt else None,
                "end_dt": end_dt.isoformat() if end_dt else None,
                "consumo": float(consumo) if consumo else 0.0,
                "comfort": float(comfort) if comfort else 0.0,
                "pax_min": float(pax_min) if pax_min else 0.0,
                "pax_max": float(pax_max) if pax_max else 0.0
            })
        
        return routes
        
    finally:
        cur.close()
        conn.close()


def get_all_vessels() -> List[Dict[str, Any]]:
    """
    Get all available vessels from the database.
    """
    conn = get_connection()
    cur = conn.cursor()
    
    try:
        cur.execute("""
            SELECT id, nome, capacita_passeggeri
            FROM vascello
            ORDER BY nome
        """)
        rows = cur.fetchall()
        
        vessels = []
        for row in rows:
            vessel_id, name, capacity = row
            vessels.append({
                "vessel_id": str(vessel_id),
                "name": name,
                "capacity": float(capacity) if capacity else 100.0
            })
        
        return vessels
        
    finally:
        cur.close()
        conn.close()


def schedule_by_day(data: SchedulingByDayInput) -> SchedulingResponse:
    """
    Perform scheduling optimization for all routes on a given day.
    
    1. Fetch all routes (percorsi) for the day
    2. Fetch all vessels
    3. Call the scheduler microservice
    4. Return Pareto-optimal solutions
    """
    # Get routes for the day
    routes_data = get_routes_for_day(data.giorno, data.solo_future)
    
    if not routes_data:
        return SchedulingResponse(
            status="ok",
            solutions=[],
            message=f"No routes found for day {data.giorno}"
        )
    
    # Get all vessels
    vessels_data = get_all_vessels()
    
    if not vessels_data:
        return SchedulingResponse(
            status="ok",
            solutions=[],
            message="No vessels available"
        )
    
    # Build scheduling input
    routes = [SchedulingRouteInput(**r) for r in routes_data]
    vessels = [SchedulingVesselInput(**v) for v in vessels_data]
    
    scheduling_input = SchedulingInput(
        routes=routes,
        vessels=vessels,
        max_solutions=data.max_solutions,
        include_details=data.include_details
    )
    
    # Call the scheduler
    return call_scheduler(scheduling_input)


def schedule_routes(data: SchedulingInput) -> SchedulingResponse:
    """
    Perform scheduling optimization with provided routes and vessels.
    This is the direct endpoint for custom scheduling.
    """
    return call_scheduler(data)
