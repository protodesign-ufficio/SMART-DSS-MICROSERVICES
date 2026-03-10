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
    summary="Leggi configurazione runtime del servizio",
    description="""
Restituisce l'intera configurazione runtime del servizio API Gateway così come è **attiva in questo momento**.
Tutti i valori sono modificabili senza riavvio tramite `POST /config`.

### Parametri restituiti

| Campo | Default | Descrizione |
|-------|---------|-------------|
| `cache_delta_minutes` | 120 | Durata in minuti della cache risultati ottimizzazione weather routing. Scaduta la cache, il prossimo ciclo esegue un ricalcolo completo. |
| `replanning_check_interval_seconds` | 300 | Cadenza in secondi del job periodico che verifica automaticamente se il piano operativo necessita di replanning. |
| `replanning_theta_min` | 10.0 | Soglia θ_min (min): ritardo oltre cui una corsa è considerata *in ritardo*. Alimenta il contatore M. |
| `replanning_theta_critical_min` | 30.0 | Soglia θ_critical (min): ritardo oltre cui una corsa è *critica*. Alimenta il contatore M_c. Deve essere > theta_min. |
| `replanning_max_late` | 2 | Numero massimo di corse *in ritardo* (M > theta_min) tollerato nell'orizzonte prima di attivare il replanning. |
| `replanning_max_critical` | 1 | Numero massimo di corse *critiche* (M_c > theta_critical_min) tollerato. Anche una singola corsa critica oltre soglia attiva il replanning. |
| `replanning_total_delay_max` | 60.0 | Ritardo cumulativo massimo (D_tot, min): somma di tutti i ritardi nell'orizzonte. Superato questo valore il replanning scatta indipendentemente da M e M_c. |
| `replanning_single_delay_max` | 40.0 | Ritardo massimo su una singola corsa (D_max, min). Se anche solo una corsa supera questo valore il replanning scatta immediatamente. |
| `replanning_horizon_minutes` | 120 | Ampiezza in minuti della finestra temporale futura analizzata. Solo le corse con partenza/arrivo entro questo orizzonte vengono incluse nell'analisi. |
| `replanning_cooldown_minutes` | 30 | Periodo di silenzio (min) dopo un trigger: nuovi trigger non vengono generati né notificati su Kafka per evitare oscillazioni. |
| `replanning_freeze_window_minutes` | 15 | Finestra di freeze operativo (min) prima della partenza di una corsa. Le corse imminenti entro questa finestra sono escluse dal replanning. |
    """
)
def get_config():
    # restituisce lo stato runtime reale
    return ServiceConfig(**SERVICE_CONFIG.model_dump())

@router.post(
    "/config",
    response_model=ServiceConfig,
    summary="Aggiorna configurazione runtime del servizio",
    description="""
Modifica uno o più parametri della configurazione runtime del servizio API Gateway.
Tutti i campi sono **opzionali**: invia solo quelli che vuoi cambiare, gli altri restano invariati.
Le modifiche sono applicate **immediatamente** senza riavvio del servizio (hot reload).

### Parametri modificabili

| Campo | Range | Effetto della modifica |
|-------|-------|------------------------|
| `cache_delta_minutes` | 1–1440 min | Durata cache ottimizzazione. Ridurre = risultati più freschi ma più ricalcoli. |
| `replanning_check_interval_seconds` | 5–86400 sec | Cadenza del job periodico; la modifica rischedula il job immediatamente. |
| `replanning_theta_min` | ≥ 0 min | Soglia θ_min ritardo minimo. Abbassare = più corse contate come *in ritardo*. |
| `replanning_theta_critical_min` | ≥ 0 min | Soglia θ_critical ritardo critico. Impostare sempre > theta_min. |
| `replanning_max_late` | ≥ 0 | Tolleranza corse in ritardo (M). 0 = trigger al primo ritardo rilevato. |
| `replanning_max_critical` | ≥ 0 | Tolleranza corse critiche (M_c). 0 = trigger alla prima corsa critica. |
| `replanning_total_delay_max` | ≥ 0 min | Soglia ritardo cumulativo (D_tot). Ridurre = più sensibile a ritardi distribuiti. |
| `replanning_single_delay_max` | ≥ 0 min | Soglia ritardo singola corsa (D_max). Ridurre = più sensibile ai picchi di ritardo. |
| `replanning_horizon_minutes` | ≥ 1 min | Orizzonte analisi. Aumentare = più corse analizzate ma segnali più diluiti. |
| `replanning_cooldown_minutes` | ≥ 0 min | Cooldown post-trigger. 0 = disabilita il cooldown, ogni ciclo può generare trigger. |
| `replanning_freeze_window_minutes` | ≥ 0 min | Freeze operativo pre-partenza. 0 = nessun freeze, anche le corse imminenti sono incluse. |

### Note operative
- I parametri di replanning vengono inoltrati al microservizio a ogni chiamata `POST /replanning/check`.
- La modifica di `replanning_check_interval_seconds` rischedula il job automatico senza perdere il ciclo corrente.
- La cache ottimizzazione è separata dai parametri replanning e non viene invalidata dalla modifica di questi ultimi.
    """
)
def update_config(data: ServiceConfigUpdate):
    # aggiorna LO STESSO oggetto usato dall'ottimizzatore
    if data.cache_delta_minutes is not None:
        SERVICE_CONFIG.cache_delta_minutes = data.cache_delta_minutes

    if data.replanning_check_interval_seconds is not None:
        SERVICE_CONFIG.replanning_check_interval_seconds = data.replanning_check_interval_seconds
        ensure_periodic_replanning_job()

    if data.replanning_theta_min is not None:
        SERVICE_CONFIG.replanning_theta_min = data.replanning_theta_min
    if data.replanning_theta_critical_min is not None:
        SERVICE_CONFIG.replanning_theta_critical_min = data.replanning_theta_critical_min
    if data.replanning_max_late is not None:
        SERVICE_CONFIG.replanning_max_late = data.replanning_max_late
    if data.replanning_max_critical is not None:
        SERVICE_CONFIG.replanning_max_critical = data.replanning_max_critical
    if data.replanning_total_delay_max is not None:
        SERVICE_CONFIG.replanning_total_delay_max = data.replanning_total_delay_max
    if data.replanning_single_delay_max is not None:
        SERVICE_CONFIG.replanning_single_delay_max = data.replanning_single_delay_max
    if data.replanning_horizon_minutes is not None:
        SERVICE_CONFIG.replanning_horizon_minutes = data.replanning_horizon_minutes
    if data.replanning_cooldown_minutes is not None:
        SERVICE_CONFIG.replanning_cooldown_minutes = data.replanning_cooldown_minutes
    if data.replanning_freeze_window_minutes is not None:
        SERVICE_CONFIG.replanning_freeze_window_minutes = data.replanning_freeze_window_minutes

    return ServiceConfig(**SERVICE_CONFIG.model_dump())
