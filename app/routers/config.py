from fastapi import APIRouter, HTTPException
from app.core.config import KAFKA_CONFIG, now_iso, SERVICE_CONFIG
from app.models.kafka import KafkaSettingsInput, KafkaSettingsResponse
from app.models.common import ServiceConfig, ServiceConfigUpdate
from app.core.scheduler import ensure_periodic_replanning_job

router = APIRouter(prefix="", tags=["Configurazione"])


@router.get(
    "/api/config/kafka-settings",
    response_model=KafkaSettingsResponse,
    summary="Configurazione Kafka corrente",
    description="""
Restituisce la configurazione Kafka attualmente attiva nel sistema.

### Parametri restituiti
| Campo | Descrizione | Unità |
|-------|-------------|-------|
| window_future | Finestra temporale futura per eventi | minuti |
| publish_interval | Intervallo pubblicazione | minuti |
| publish_interval_sec | Intervallo fine | secondi |
| sim_speed_factor | Fattore accelerazione simulazione | adimensionale |
| last_update | Timestamp ultima modifica | Unix |

### Utilizzo tipico
- Verifica configurazione corrente
- Debug integrazione Kafka
- Monitoring parametri runtime
    """
)
def get_kafka_settings():
    return KafkaSettingsResponse(
        window_future=KAFKA_CONFIG["window_future"],
        publish_interval=KAFKA_CONFIG["publish_interval"],
        publish_interval_sec=KAFKA_CONFIG["publish_interval_sec"],
        sim_speed_factor=KAFKA_CONFIG["sim_speed_factor"],
        last_update=KAFKA_CONFIG["last_update"],
        timestamp=now_iso()
    )


@router.post(
    "/api/config/kafka-settings",
    summary="Aggiorna configurazione Kafka",
    description="""
Aggiorna dinamicamente la configurazione Kafka **senza riavvio** del servizio.

### Hot Reload
Le modifiche sono applicate **immediatamente** a tutti i componenti che utilizzano la configurazione.

### Parametri
| Campo | Descrizione | Range |
|-------|-------------|-------|
| window_future | Finestra eventi futuri | 1-1440 min |
| publish_interval | Intervallo pubblicazione | 1-1440 min |
| publish_interval_sec | Intervallo fine | 1-3600 sec |
| sim_speed_factor | Fattore accelerazione simulazione (opzionale) | 0.1-100.0 |

### Validazioni
- Tutti i valori devono essere > 0
- Valori fuori range generano errore 400

### Note
- Il timestamp `last_update` viene aggiornato automaticamente
- `sim_speed_factor` viene usato dalle simulazioni se non specificato nella chiamata
- Le simulazioni possono anche aggiornare `sim_speed_factor` passandolo come parametro
- Usare con cautela in produzione
    """,
    responses={
        200: {"description": "Configurazione aggiornata con successo"},
        400: {"description": "Valori non validi (devono essere > 0)"}
    }
)
def update_kafka_settings(settings: KafkaSettingsInput):
    if settings.window_future <= 0 or settings.publish_interval <= 0 or settings.publish_interval_sec <= 0:
        raise HTTPException(400, "Valori numerici devono essere > 0")
    import time
    KAFKA_CONFIG["window_future"] = settings.window_future
    KAFKA_CONFIG["publish_interval"] = settings.publish_interval
    KAFKA_CONFIG["publish_interval_sec"] = settings.publish_interval_sec
    if settings.sim_speed_factor is not None:
        KAFKA_CONFIG["sim_speed_factor"] = settings.sim_speed_factor
    KAFKA_CONFIG["last_update"] = time.time()
    return {"status": "success", "updated_at": now_iso(), "settings": KAFKA_CONFIG}




@router.get(
    "/config",
    response_model=ServiceConfig,
    summary="Configurazione servizio",
    description="""
Restituisce la configurazione runtime del servizio API Gateway.

### Parametri
- **cache_delta_minutes**: durata validità cache per risultati ottimizzazione (minuti)
- **replanning_check_interval_seconds**: intervallo del check automatico replanning (secondi)

### Utilizzo
La cache evita ricalcoli costosi quando i dati meteo non sono cambiati significativamente.
    """
)
def get_config():
    # restituisce lo stato runtime reale
    return ServiceConfig(**SERVICE_CONFIG.model_dump())

@router.post(
    "/config",
    response_model=ServiceConfig,
    summary="Aggiorna configurazione servizio",
    description="""
Modifica la configurazione runtime del servizio API Gateway.

### Parametri modificabili
- **cache_delta_minutes**: nuova durata cache (1-1440 minuti)
- **replanning_check_interval_seconds**: nuovo intervallo check automatico replanning (5-86400 secondi)

### Hot Reload
Le modifiche sono applicate immediatamente senza riavvio.

### Note
- Valori bassi = dati più freschi ma più chiamate all'ottimizzatore
- Valori alti = meno chiamate ma possibile uso dati obsoleti
    """
)
def update_config(data: ServiceConfigUpdate):
    # aggiorna LO STESSO oggetto usato dall'ottimizzatore
    if data.cache_delta_minutes is not None:
        SERVICE_CONFIG.cache_delta_minutes = data.cache_delta_minutes

    if data.replanning_check_interval_seconds is not None:
        SERVICE_CONFIG.replanning_check_interval_seconds = data.replanning_check_interval_seconds
        ensure_periodic_replanning_job()

    return ServiceConfig(**SERVICE_CONFIG.model_dump())
