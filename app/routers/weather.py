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
    north: float | None = Field(40.76, description="Latitudine nord (gradi decimali)")
    south: float | None = Field(40.50, description="Latitudine sud (gradi decimali)")
    east: float | None = Field(14.90, description="Longitudine est (gradi decimali)")
    west: float | None = Field(14.30, description="Longitudine ovest (gradi decimali)")


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
    description="""
Verifica la raggiungibilità del microservizio meteo dedicato e lo stato
della sua connessione al database `weather_db`.

### Output
```json
{
  "status": "ok",
  "service": "weather_service",
  "db": "connected"
}
```

### Codici di errore
| Codice | Significato |
|--------|-------------|
| 503 | Weather service non raggiungibile |
    """,
    responses={
        200: {"description": "Weather service attivo e connesso al DB"},
        503: {"description": "Weather service non raggiungibile"},
    },
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
    description="""
Restituisce tutti gli scenari meteo disponibili, suddivisi in due categorie:

### Preset built-in
Scenari predefiniti sempre disponibili:

| Nome | Label | Descrizione |
|------|-------|-------------|
| calm_sea | Mare calmo | Riduce correnti e onde al 30% |
| rough_sea | Mare mosso | Raddoppia intensità correnti e onde |
| storm | Tempesta | Triplica intensità + picco gaussiano |
| current_gradient_ew | Gradiente correnti W→E | Rampa lineare 0.5×→2.5× |
| wave_swell | Onda lunga sinusoidale | Modulazione sinusoidale altezza onda |

### Scenari salvati
Scenari personalizzati creati dall'utente tramite `POST /weather/scenarios`.
Ogni scenario salvato include un campo `id` numerico utilizzabile come
`scenario_id` in:
- `POST /weather/layer`
- `POST /weather_routing/carico`
- `POST /weather_routing/vuoto`
- `POST /assegnazione/pianifica`

### Output
```json
{
  "presets": { "calm_sea": {...}, ... },
  "saved": [ { "id": 1, "name": "...", "scenario": {...} }, ... ]
}
```
    """,
    responses={
        200: {"description": "Lista completa scenari (preset + salvati)"},
        503: {"description": "Weather service non raggiungibile"},
    },
)
def weather_scenarios():
    """Proxy GET verso /internal/weather/scenarios del weather service."""
    return _get_weather("/internal/weather/scenarios")


@router.post(
    "/weather/layer",
    summary="Dati meteo layer dashboard (con supporto scenari what-if)",
    description="""
Ottiene i dati meteo (correnti marine o moto ondoso) formattati per la
visualizzazione su mappa Leaflet, con supporto completo per scenari what-if.

### Parametri principali
| Campo | Tipo | Descrizione | Default |
|-------|------|-------------|--------|
| layer_type | string | `currents` (correnti) o `waves` (onde) | obbligatorio |
| bounds | object | Bounding-box {north, south, east, west} | area default |
| timestamp | string | Timestamp ISO-8601 richiesto | più vicino disponibile |
| use_cache | bool | Tenta recupero da cache DB | true |
| save_cache | bool | Salva risposta in cache DB | true |
| force_refresh | bool | Ignora cache, forza fetch Copernicus | false |
| max_age_minutes | int | Età massima cache (min) | default servizio |

### Scenari What-If
Due modalità alternative per applicare uno scenario:

**1. `scenario_id`** (consigliato) — ID numerico di uno scenario salvato nel DB.
Usare `GET /weather/scenarios` per vedere gli ID disponibili.

**2. `scenario`** (inline) — Oggetto con parametri what-if:
- `multiplier`: fattore moltiplicativo globale (es. 2.0 = raddoppia)
- `function`: modulazione spaziale (`sinusoidal`, `linear_ramp`, `gaussian_peak`)
- `function_params`: parametri della funzione (vedi `POST /weather/scenarios`)
- `variables`: variabili target (correnti: `u`,`v` — onde: `height`,`period`,`dir`)

Se entrambi sono specificati, `scenario_id` ha priorità.
Quando uno scenario è attivo la risposta include `source: 'copernicus+scenario'`.

### Output
```json
{
  "layer_type": "currents",
  "timestamp": "2026-03-05T12:00:00",
  "source": "copernicus" | "db_cache" | "copernicus+scenario",
  "items": [ {"lat": ..., "lon": ..., "u": ..., "v": ...} ]
}
```
    """,
    responses={
        200: {"description": "Dati layer meteo restituiti con successo"},
        503: {"description": "Weather service non raggiungibile"},
    },
)
def weather_layer(payload: WeatherLayerRequest):
    """Proxy POST verso /internal/weather/layer del weather service."""
    return _post_weather("/internal/weather/layer", payload.model_dump(exclude_none=True), timeout=90.0)


@router.get(
    "/weather/cache/layer",
    summary="Lista cache layer meteo",
    description="""
Restituisce l'elenco delle entry salvate nella cache dei layer meteo,
ordinate per data di creazione decrescente.

### Query parameters
| Parametro | Tipo | Descrizione | Default |
|-----------|------|-------------|--------|
| layer_type | string | Filtra per `currents` o `waves` | tutti |
| limit | int | Max entry da restituire (1-200) | 20 |

### Output
Lista di entry con: `cache_key`, `layer_type`, `timestamp`, `source`, `created_at`.
    """,
    responses={
        200: {"description": "Lista entry cache"},
        503: {"description": "Weather service non raggiungibile"},
    },
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
    summary="Dettaglio cache layer meteo",
    description="""
Recupera il payload meteo completo salvato in cache, identificato dalla
`cache_key` SHA-256.

### Path parameter
| Parametro | Tipo | Descrizione |
|-----------|------|-------------|
| cache_key | string | Hash SHA-256 della cache entry |

### Output
Payload completo con `items`, `range`, `timestamp`, `layer_type`, `source`.
    """,
    responses={
        200: {"description": "Payload cache completo"},
        404: {"description": "Cache key non trovata"},
        503: {"description": "Weather service non raggiungibile"},
    },
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
    description="""
Salva un nuovo scenario what-if nel database. Lo scenario creato riceve un `id`
numerico univoco utilizzabile come `scenario_id` in:
- `POST /weather/layer`
- `POST /weather_routing/carico`
- `POST /weather_routing/vuoto`
- `POST /assegnazione/pianifica`

Il campo `name` deve essere univoco (errore 409 se già esistente).

### Input
```json
{
  "name": "mio_scenario",
  "label": "Etichetta leggibile",
  "description": "Descrizione testuale",
  "scenario": {
    "multiplier": 2.0,
    "function": "gaussian_peak",
    "function_params": { "radius_deg": 0.15, "peak_factor": 3.0 },
    "variables": ["height"]
  }
}
```

### Parametri scenario
| Campo | Tipo | Descrizione | Default |
|-------|------|-------------|--------|
| multiplier | float | Fattore moltiplicativo globale (es. 2.0 = raddoppia, 0.3 = riduce al 30%) | null (nessun fattore) |
| function | string | Funzione di modulazione spaziale (vedi sotto) | null (nessuna modulazione) |
| function_params | object | Parametri specifici della funzione scelta | {} |
| variables | list[str] | Variabili target — Correnti: `u`, `v` — Onde: `height`, `period`, `dir` | tutte |

### Funzioni di modulazione spaziale disponibili

**`sinusoidal`** — Onda sinusoidale lungo un asse geografico.
| Parametro | Tipo | Descrizione | Default |
|-----------|------|-------------|--------|
| amplitude | float | Ampiezza dell'onda (0-1) | 0.5 |
| frequency | float | Numero di cicli completi nell'area | 1 |
| axis | string | Asse di variazione: `lon` o `lat` | `lon` |
| phase | float | Sfasamento in radianti | 0 |

**`linear_ramp`** — Rampa lineare crescente/decrescente da un estremo all'altro.
| Parametro | Tipo | Descrizione | Default |
|-----------|------|-------------|--------|
| start_factor | float | Fattore moltiplicativo all'inizio dell'asse | 0.5 |
| end_factor | float | Fattore moltiplicativo alla fine dell'asse | 2.0 |
| axis | string | Asse di variazione: `lon` o `lat` | `lon` |

**`gaussian_peak`** — Picco gaussiano localizzato su un punto.
| Parametro | Tipo | Descrizione | Default |
|-----------|------|-------------|--------|
| center_lat | float | Latitudine del centro del picco | centro area |
| center_lon | float | Longitudine del centro del picco | centro area |
| radius_deg | float | Raggio della gaussiana in gradi | 0.1 |
| peak_factor | float | Fattore moltiplicativo al centro del picco | 3.0 |

### Formula di applicazione
```
valore_modificato = valore_reale × multiplier × function(lat, lon)
```
Se `multiplier` è null vale 1.0. Se `function` è null vale 1.0.

### Output
```json
{
  "id": 9,
  "name": "mio_scenario",
  "label": "Etichetta leggibile",
  "scenario": { ... },
  "created_at": "2026-03-05T12:00:00+01:00"
}
```
    """,
    responses={
        200: {"description": "Scenario creato con successo"},
        409: {"description": "Scenario con lo stesso nome già esistente"},
        503: {"description": "Weather service non raggiungibile"},
    },
)
def create_scenario(body: WeatherScenarioCreate):
    """Proxy POST verso /internal/weather/scenarios."""
    return _post_weather("/internal/weather/scenarios", body.model_dump(exclude_none=True))


@router.get(
    "/weather/scenarios/{scenario_id}",
    summary="Dettaglio scenario salvato",
    description="""
Restituisce il dettaglio completo di uno scenario salvato, identificato dal suo ID numerico.

### Path parameter
| Parametro | Tipo | Descrizione |
|-----------|------|-------------|
| scenario_id | int | ID numerico dello scenario |

### Output
```json
{
  "id": 2,
  "name": "tempesta_forte",
  "label": "Tempesta forte",
  "description": "Scenario con onde x3",
  "scenario": { "multiplier": 2.5, "function": "gaussian_peak", ... },
  "created_at": "...",
  "updated_at": "..."
}
```
    """,
    responses={
        200: {"description": "Dettaglio scenario"},
        404: {"description": "Scenario non trovato"},
        503: {"description": "Weather service non raggiungibile"},
    },
)
def get_scenario(scenario_id: int):
    """Proxy GET verso /internal/weather/scenarios/{id}."""
    return _get_weather(f"/internal/weather/scenarios/{scenario_id}")


@router.put(
    "/weather/scenarios/{scenario_id}",
    summary="Aggiorna scenario salvato",
    description="""
Aggiorna i parametri di uno scenario esistente identificato dal suo ID.

### Path parameter
| Parametro | Tipo | Descrizione |
|-----------|------|-------------|
| scenario_id | int | ID numerico dello scenario da aggiornare |

### Body
Stesso formato di `POST /weather/scenarios` (name, label, description, scenario).
Tutti i campi vengono sovrascritti.

### Note
- Il campo `updated_at` viene aggiornato automaticamente.
- Il `name` deve restare univoco (errore 409 se conflitto con altro scenario).
    """,
    responses={
        200: {"description": "Scenario aggiornato con successo"},
        404: {"description": "Scenario non trovato"},
        409: {"description": "Nome già in uso da un altro scenario"},
        503: {"description": "Weather service non raggiungibile"},
    },
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
    description="""
Elimina uno scenario dal database. **L'operazione è irreversibile.**

### Path parameter
| Parametro | Tipo | Descrizione |
|-----------|------|-------------|
| scenario_id | int | ID numerico dello scenario da eliminare |

### Note
- Eventuali chiamate successive con questo `scenario_id` restituiranno 404.
- I percorsi già calcolati con questo scenario non vengono alterati.
    """,
    responses={
        200: {"description": "Scenario eliminato con successo"},
        404: {"description": "Scenario non trovato"},
        503: {"description": "Weather service non raggiungibile"},
    },
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
