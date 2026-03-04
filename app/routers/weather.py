import requests
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.core.config import WEATHER_SERVICE_URL

router = APIRouter(
    prefix="",
    tags=["Weather"],
    responses={
        503: {"description": "Weather micro-service non raggiungibile"},
        502: {"description": "Risposta non valida dal weather micro-service"},
    },
)


class WeatherBoundsRequest(BaseModel):
    north: float | None = Field(None, description="Latitudine nord (gradi decimali)")
    south: float | None = Field(None, description="Latitudine sud (gradi decimali)")
    east: float | None = Field(None, description="Longitudine est (gradi decimali)")
    west: float | None = Field(None, description="Longitudine ovest (gradi decimali)")


class WeatherLayerRequest(BaseModel):
    layer_type: str = Field(
        ...,
        pattern="^(currents|waves)$",
        description="Tipo layer meteo: 'currents' oppure 'waves'.",
    )
    bounds: WeatherBoundsRequest | None = Field(
        None,
        description="Bounding-box geografico opzionale. Se omesso usa area default.",
    )
    timestamp: str | None = Field(
        None,
        description="Timestamp ISO-8601 richiesto (es. 2026-03-04T12:00:00). Se omesso usa il più vicino disponibile.",
    )
    use_cache: bool = Field(
        True,
        description="Se true tenta prima il recupero da cache DB.",
    )
    save_cache: bool = Field(
        True,
        description="Se true salva in cache DB la risposta ottenuta da Copernicus.",
    )
    force_refresh: bool = Field(
        False,
        description="Se true ignora la cache e forza un nuovo fetch remoto.",
    )
    max_age_minutes: int | None = Field(
        None,
        ge=1,
        description="Età massima cache in minuti. Se omesso usa default lato servizio.",
    )


def _post_weather(path: str, payload: dict, timeout: float = 60.0):
    url = f"{WEATHER_SERVICE_URL.rstrip('/')}{path}"
    try:
        response = requests.post(url, json=payload, timeout=timeout)
    except requests.RequestException as exc:
        raise HTTPException(status_code=503, detail="Weather service unavailable") from exc

    if response.status_code >= 400:
        detail = response.text
        try:
            body = response.json()
            if isinstance(body, dict):
                detail = body.get("detail", detail)
        except Exception:
            pass
        raise HTTPException(status_code=response.status_code, detail=f"Weather service error: {detail}")

    try:
        return response.json() if response.content else {}
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Invalid response from weather service") from exc


@router.get(
    "/weather/health",
    summary="Health check weather service",
    description=(
        "Verifica la raggiungibilità del microservizio meteo dedicato e lo stato "
        "della sua connessione al database weather_db. "
        "Restituisce {status, service, db}."
    ),
)
def weather_health():
    """Proxy GET verso /health del weather service."""
    url = f"{WEATHER_SERVICE_URL.rstrip('/')}/health"
    try:
        response = requests.get(url, timeout=8)
    except requests.RequestException as exc:
        raise HTTPException(status_code=503, detail="Weather service unavailable") from exc

    if response.status_code >= 400:
        raise HTTPException(status_code=response.status_code, detail="Weather service unhealthy")

    try:
        return response.json()
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Invalid response from weather service") from exc


@router.post(
    "/weather/layer",
    summary="Dati meteo layer dashboard",
    description=(
        "Proxy verso il weather micro-service per ottenere i dati meteo (correnti o onde) "
        "formattati per la visualizzazione su mappa. Accetta un oggetto LayerRequest con: "
        "layer_type ('currents'|'waves'), bounds opzionali, timestamp, e parametri di cache "
        "(use_cache, save_cache, force_refresh, max_age_minutes). "
        "Restituisce items geolocalizzati, range e metadati di provenienza."
    ),
)
def weather_layer(payload: WeatherLayerRequest):
    """Proxy POST verso /internal/weather/layer del weather service."""
    return _post_weather("/internal/weather/layer", payload.model_dump(exclude_none=True), timeout=90.0)


@router.get(
    "/weather/cache/layer",
    summary="Lista cache layer weather",
    description=(
        "Restituisce l'elenco delle entry salvate nella cache dei layer meteo del weather "
        "service, ordinate per data di creazione decrescente. "
        "Filtrabile per tipo di layer e con limite configurabile."
    ),
)
def weather_layer_cache_list(
    layer_type: str | None = Query(
        default=None,
        pattern="^(currents|waves)$",
        description="Filtra per tipo di layer: 'currents' o 'waves'. Se omesso restituisce entrambi.",
    ),
    limit: int = Query(
        default=20,
        ge=1,
        le=200,
        description="Numero massimo di entry da restituire (1-200, default 20).",
    ),
):
    query = f"?limit={limit}"
    if layer_type:
        query += f"&layer_type={layer_type}"
    url = f"{WEATHER_SERVICE_URL.rstrip('/')}/internal/weather/cache/layer{query}"
    try:
        response = requests.get(url, timeout=20)
    except requests.RequestException as exc:
        raise HTTPException(status_code=503, detail="Weather service unavailable") from exc

    if response.status_code >= 400:
        raise HTTPException(status_code=response.status_code, detail="Weather service error")
    try:
        return response.json()
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Invalid response from weather service") from exc


@router.get(
    "/weather/cache/layer/{cache_key}",
    summary="Dettaglio cache layer weather",
    description=(
        "Recupera il payload meteo completo (items, range, timestamp) salvato in cache, "
        "identificato dalla cache_key SHA-256. Restituisce 404 se la chiave non esiste."
    ),
)
def weather_layer_cache_get(cache_key: str):
    """Proxy GET verso /internal/weather/cache/layer/{cache_key}."""
    url = f"{WEATHER_SERVICE_URL.rstrip('/')}/internal/weather/cache/layer/{cache_key}"
    try:
        response = requests.get(url, timeout=20)
    except requests.RequestException as exc:
        raise HTTPException(status_code=503, detail="Weather service unavailable") from exc

    if response.status_code >= 400:
        detail = "Weather service error"
        try:
            body = response.json()
            if isinstance(body, dict) and body.get("detail"):
                detail = body["detail"]
        except Exception:
            pass
        raise HTTPException(status_code=response.status_code, detail=detail)
    try:
        return response.json()
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Invalid response from weather service") from exc
