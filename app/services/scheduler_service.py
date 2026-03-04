"""
Scheduler service - calls the external scheduling microservice.
"""
import requests
from datetime import datetime, timedelta
from typing import List, Dict, Any

from fastapi import HTTPException

from app.core.config import SCHEDULER_URL, OPERATIVO_SERVICE_URL, ANAGRAFICA_SERVICE_URL, PERCORSI_SERVICE_URL, FORECAST_SERVICE_URL
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
    def _get_json(base_url: str, path: str, timeout: float = 12.0):
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

    def _parse_iso(value: str | None):
        if not value:
            return None
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except Exception:
            return None

    corse = _get_json(OPERATIVO_SERVICE_URL, f"/internal/corsa/giorno?giorno={giorno}&solofuture={'true' if solo_future else 'false'}")
    if not isinstance(corse, list):
        return []

    tratta_cache: Dict[str, Dict[str, Any] | None] = {}
    vascello_cache: Dict[str, Dict[str, Any] | None] = {}
    routes: List[Dict[str, Any]] = []

    for corsa_item in corse:
        corsa_id = corsa_item.get("id") if isinstance(corsa_item, dict) else None
        if not corsa_id:
            continue

        corsa = _get_json(OPERATIVO_SERVICE_URL, f"/internal/corsa/id/{corsa_id}")
        if not isinstance(corsa, dict):
            continue

        tratta_id = str(corsa.get("tratta_id")) if corsa.get("tratta_id") else None
        if not tratta_id:
            continue

        if tratta_id not in tratta_cache:
            tratta_cache[tratta_id] = _get_json(ANAGRAFICA_SERVICE_URL, f"/internal/tratta/{tratta_id}")
        tratta = tratta_cache.get(tratta_id)
        if not isinstance(tratta, dict):
            continue

        previsione = corsa.get("previsione") if isinstance(corsa.get("previsione"), dict) else None
        if previsione is None:
            previsione = _get_json(FORECAST_SERVICE_URL, f"/internal/previsione/corsa/{corsa_id}/latest")
            if not isinstance(previsione, dict):
                previsione = None

        percorsi = _get_json(
            PERCORSI_SERVICE_URL,
            f"/internal/percorso/by_corsa/{corsa_id}?order_by=created_at&mode=DESC&limit=500",
        )
        if not isinstance(percorsi, dict):
            continue

        for p in (percorsi.get("percorsi") or []):
            if not isinstance(p, dict):
                continue
            vascello_id = p.get("vascello_id")
            if not vascello_id:
                continue

            vessel_id = str(vascello_id)
            if vessel_id not in vascello_cache:
                vascello_cache[vessel_id] = _get_json(ANAGRAFICA_SERVICE_URL, f"/internal/vascello/{vessel_id}")
            vessel = vascello_cache.get(vessel_id)
            if not isinstance(vessel, dict):
                continue

            start_dt = _parse_iso(corsa.get("orario_partenza_schedulato") or p.get("orario_partenza_schedulato"))
            end_dt = _parse_iso(p.get("orario_arrivo_previsto"))
            if end_dt is None and start_dt is not None and p.get("tempo_percorrenza") is not None:
                try:
                    end_dt = start_dt + timedelta(minutes=float(p.get("tempo_percorrenza")))
                except Exception:
                    end_dt = None

            routes.append({
                "route_id": str(p.get("id") or p.get("percorso_id")),
                "corsa_id": str(corsa_id),
                "corsa_name": corsa.get("nome"),
                "vessel_id": vessel_id,
                "vessel_name": vessel.get("nome"),
                "capacity": float(vessel.get("capacita_passeggeri") or 100.0),
                "origin": str(tratta.get("porto_partenza_id")),
                "destination": str(tratta.get("porto_arrivo_id")),
                "start_dt": start_dt.isoformat() if start_dt else None,
                "end_dt": end_dt.isoformat() if end_dt else None,
                "consumo": float(p.get("consumo") or 0.0),
                "comfort": float(p.get("comfort") or 0.0),
                "pax_min": float((previsione or {}).get("confidenza_min") or 0.0),
                "pax_max": float((previsione or {}).get("confidenza_max") or 0.0),
            })

    return routes


def get_all_vessels() -> List[Dict[str, Any]]:
    """
    Get all available vessels from the database.
    """
    try:
        response = requests.get(f"{ANAGRAFICA_SERVICE_URL.rstrip('/')}/internal/vascello/lista", timeout=10)
    except requests.RequestException as exc:
        raise HTTPException(503, "Anagrafica service unavailable") from exc

    if response.status_code >= 400:
        raise HTTPException(503, f"Anagrafica service error: HTTP {response.status_code}")

    try:
        rows = response.json()
    except Exception as exc:
        raise HTTPException(502, "Invalid response from Anagrafica service") from exc

    if not isinstance(rows, list):
        return []

    vessels = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        vessel_id = row.get("id")
        if not vessel_id:
            continue
        vessels.append({
            "vessel_id": str(vessel_id),
            "name": row.get("nome"),
            "capacity": float(row.get("capacita_passeggeri") or 100.0),
        })

    return vessels


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
