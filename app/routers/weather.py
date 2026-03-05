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


class WeatherScenarioModifier(BaseModel):
    """Modificatore what-if per generare scenari meteo sintetici.

    Altera i dati reali Copernicus applicando un fattore moltiplicativo
    globale e/o una funzione di modulazione spaziale.
    Effetto combinato: total_factor = multiplier × function(lat, lon).
    """
    multiplier: float | None = Field(
        None,
        description=(
            "Fattore moltiplicativo globale applicato a tutte le grandezze. "
            "Es. 2.0 = raddoppia intensità, 0.5 = dimezza."
        ),
    )
    function: str | None = Field(
        None,
        pattern="^(sinusoidal|linear_ramp|gaussian_peak)$",
        description=(
            "Funzione di modulazione spaziale: "
            "'sinusoidal' (onda sin lungo un asse), "
            "'linear_ramp' (rampa lineare da un estremo all'altro), "
            "'gaussian_peak' (picco gaussiano localizzato)."
        ),
    )
    function_params: dict | None = Field(
        None,
        description=(
            "Parametri della funzione di modulazione.\n"
            "sinusoidal  → amplitude (0-1, def 0.5), frequency (cicli, def 1), "
            "axis ('lon'|'lat', def 'lon'), phase (rad, def 0).\n"
            "linear_ramp → start_factor (def 0.5), end_factor (def 2.0), "
            "axis ('lon'|'lat', def 'lon').\n"
            "gaussian_peak → center_lat, center_lon, radius_deg (def 0.1), "
            "peak_factor (def 3.0)."
        ),
    )
    variables: list[str] | None = Field(
        None,
        description=(
            "Variabili su cui applicare la modifica. "
            "Correnti: 'u','v'. Onde: 'height','period','dir'. "
            "Se omesso modifica tutte le grandezze di intensità."
        ),
    )


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
    scenario: WeatherScenarioModifier | None = Field(
        None,
        description=(
            "Modificatore di scenario what-if. Se presente, i dati reali vengono "
            "alterati secondo i parametri specificati (moltiplicatore e/o funzione "
            "spaziale). La cache viene saltata automaticamente quando uno scenario è attivo. "
            "Usare GET /weather/scenarios per ottenere i preset disponibili."
        ),
    )
    scenario_id: int | None = Field(
        None,
        description=(
            "ID di uno scenario salvato nel database. Se specificato, il campo 'scenario' "
            "viene ignorato e si usa lo scenario persistente. "
            "Usare POST /weather/scenarios per crearne uno nuovo, "
            "o GET /weather/scenarios per vedere quelli disponibili."
        ),
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


def _get_weather(path: str, timeout: float = 20.0):
    """Proxy GET generico verso il weather service."""
    url = f"{WEATHER_SERVICE_URL.rstrip('/')}{path}"
    try:
        response = requests.get(url, timeout=timeout)
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


@router.get(
    "/weather/scenarios",
    summary="Lista scenari meteo (preset + salvati)",
    description=(
        "Restituisce tutti gli scenari meteo disponibili: i preset built-in e quelli "
        "salvati nel database dall'utente.\n\n"
        "**Preset built-in:** calm_sea, rough_sea, storm, current_gradient_ew, wave_swell.\n\n"
        "Gli scenari salvati includono un campo `id` utilizzabile come `scenario_id` "
        "nella richiesta POST `/weather/layer`.\n\n"
        "Per creare un nuovo scenario personalizzato usare POST `/weather/scenarios`."
    ),
)
def weather_scenarios():
    """Proxy GET verso /internal/weather/scenarios del weather service."""
    return _get_weather("/internal/weather/scenarios")


@router.post(
    "/weather/layer",
    summary="Dati meteo layer dashboard (con supporto scenari what-if)",
    description=(
        "Proxy verso il weather micro-service per ottenere i dati meteo (correnti o onde) "
        "formattati per la visualizzazione su mappa.\n\n"
        "**Parametri principali:**\n"
        "- `layer_type`: 'currents' (correnti marine) o 'waves' (moto ondoso)\n"
        "- `bounds`: bounding-box geografico opzionale\n"
        "- `timestamp`: timestamp ISO-8601 richiesto\n"
        "- `use_cache`, `save_cache`, `force_refresh`, `max_age_minutes`: gestione cache\n\n"
        "**Scenari what-if:**\n"
        "Il campo opzionale `scenario` permette di generare scenari meteo sintetici "
        "alterando i dati reali Copernicus. Si può specificare:\n"
        "- `multiplier`: fattore moltiplicativo globale (es. 2.0 = raddoppia)\n"
        "- `function`: modulazione spaziale (sinusoidal, linear_ramp, gaussian_peak)\n"
        "- `function_params`: parametri della funzione\n"
        "- `variables`: variabili target (es. ['u','v'] o ['height'])\n\n"
        "Quando uno scenario è attivo la cache viene saltata e la risposta include "
        "`source: 'copernicus+scenario'` con i dettagli dello scenario applicato.\n\n"
        "Usare `GET /weather/scenarios` per ottenere i preset pronti all'uso."
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


# ── Scenari CRUD ──────────────────────────────────────────────

class WeatherScenarioCreate(BaseModel):
    """Body per la creazione/aggiornamento di uno scenario persistente."""
    name: str = Field(..., min_length=1, max_length=100, description="Nome univoco dello scenario.")
    label: str | None = Field(None, max_length=200, description="Etichetta breve human-friendly.")
    description: str | None = Field(None, max_length=1000, description="Descrizione testuale dello scenario.")
    scenario: WeatherScenarioModifier = Field(..., description="Parametri del modificatore what-if.")


@router.post(
    "/weather/scenarios",
    summary="Crea scenario meteo personalizzato",
    description=(
        "Salva un nuovo scenario what-if nel database. Lo scenario creato riceve un `id` "
        "univoco che potr\u00e0 essere usato come `scenario_id` nella richiesta "
        "POST `/weather/layer`, senza dover ripetere i parametri ogni volta.\n\n"
        "Il campo `name` deve essere univoco: se esiste gi\u00e0 uno scenario con lo "
        "stesso nome viene restituito errore 409."
    ),
)
def create_scenario(body: WeatherScenarioCreate):
    """Proxy POST verso /internal/weather/scenarios."""
    return _post_weather("/internal/weather/scenarios", body.model_dump(exclude_none=True))


@router.get(
    "/weather/scenarios/{scenario_id}",
    summary="Dettaglio scenario salvato",
    description="Restituisce il dettaglio di uno scenario salvato identificato dal suo ID numerico.",
)
def get_scenario(scenario_id: int):
    """Proxy GET verso /internal/weather/scenarios/{id}."""
    return _get_weather(f"/internal/weather/scenarios/{scenario_id}")


@router.put(
    "/weather/scenarios/{scenario_id}",
    summary="Aggiorna scenario salvato",
    description="Aggiorna i parametri di uno scenario esistente identificato dal suo ID.",
)
def update_scenario(scenario_id: int, body: WeatherScenarioCreate):
    """Proxy PUT verso /internal/weather/scenarios/{id}."""
    url = f"{WEATHER_SERVICE_URL.rstrip('/')}/internal/weather/scenarios/{scenario_id}"
    try:
        response = requests.put(url, json=body.model_dump(exclude_none=True), timeout=20)
    except requests.RequestException as exc:
        raise HTTPException(status_code=503, detail="Weather service unavailable") from exc
    if response.status_code >= 400:
        detail = "Weather service error"
        try:
            b = response.json()
            if isinstance(b, dict) and b.get("detail"):
                detail = b["detail"]
        except Exception:
            pass
        raise HTTPException(status_code=response.status_code, detail=detail)
    try:
        return response.json()
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Invalid response from weather service") from exc


@router.delete(
    "/weather/scenarios/{scenario_id}",
    summary="Elimina scenario salvato",
    description="Elimina uno scenario dal database. L'operazione \u00e8 irreversibile.",
)
def delete_scenario(scenario_id: int):
    """Proxy DELETE verso /internal/weather/scenarios/{id}."""
    url = f"{WEATHER_SERVICE_URL.rstrip('/')}/internal/weather/scenarios/{scenario_id}"
    try:
        response = requests.delete(url, timeout=20)
    except requests.RequestException as exc:
        raise HTTPException(status_code=503, detail="Weather service unavailable") from exc
    if response.status_code >= 400:
        detail = "Weather service error"
        try:
            b = response.json()
            if isinstance(b, dict) and b.get("detail"):
                detail = b["detail"]
        except Exception:
            pass
        raise HTTPException(status_code=response.status_code, detail=detail)
    try:
        return response.json()
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Invalid response from weather service") from exc
