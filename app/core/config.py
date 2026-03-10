import os
from datetime import datetime
from pydantic import BaseModel

TAGS_METADATA = [
    {
        "name": "Porti",
        "description": """**Gestione anagrafica porti**
        
CRUD completo per la gestione dei porti nel sistema. Ogni porto è identificato da coordinate GPS (WGS84) e memorizzato con geometria PostGIS.

*Operazioni disponibili:* creazione, modifica, eliminazione, ricerca per ID o nome."""
    },
    {
        "name": "Vascelli",
        "description": """**Gestione flotta navale**
        
Anagrafica completa dei vascelli con caratteristiche tecniche e operative:
- Identificazione MMSI (Maritime Mobile Service Identity)
- Capacità passeggeri e parametri di consumo
- Stato di salute aggregato per manutenzione predittiva
- Profilo di consumo carburante parametrizzato

*Supporta:* ricerca per MMSI, recupero percorso attivo, immagine nave."""
    },
    {
        "name": "Componenti",
        "description": """**Gestione componenti di bordo**

Anagrafica dei componenti associabili ai vascelli:
- Riferimento opzionale al vascello proprietario
- Dati di utilizzo cumulativo e soglia manutentiva
- Parametri modello guasto in JSONB per manutenzione predittiva

*Operazioni disponibili:* creazione e modifica."""
    },
    {
        "name": "Tratte",
        "description": """**Gestione rotte geografiche**
        
Definizione delle tratte marittime tra porti:
- **Tratte dirette**: collegamento punto-punto tra due porti
- **Tratte multiporto**: percorsi con scali intermedi

La geometria viene calcolata automaticamente come LineString PostGIS."""
    },
    {
        "name": "Corse",
        "description": """**Programmazione oraria servizi**
        
Gestione delle corse programmate con:
- Associazione a tratta di riferimento
- Orari di partenza e arrivo massimo schedulati
- Integrazione con previsioni domanda passeggeri ML

*Naming convention:* `TRATTA-YYYYMMDD-HHMM` (es. SAL-AMA-20250125-0930)"""
    },
    {
        "name": "Percorsi",
        "description": """**Rotte ottimizzate calcolate**
        
Percorsi risultanti dall'ottimizzazione weather routing:
- Geometria rotta ottimale (GeoJSON)
- KPI: tempo percorrenza, consumo carburante, comfort
- Velocità di riferimento (Vref) e pressione (Pref)
- Distanza nautica in miglia

*Supporta espansione dinamica:* `?include=corsa,tratta,vascello`"""
    },
    {
        "name": "Pianificazione",
        "description": """**Ottimizzazione, Weather Routing e Scheduling**
        
Algoritmi avanzati per:
- **Weather routing con carico**: ottimizzazione multi-obiettivo (tempo/consumo/comfort) via NAMOA\* con dati Copernicus
- **Riposizionamento a vuoto**: stima tempi e consumi per trasferimenti non produttivi
- **Assegnazione ottimale**: matching vascelli-corse con ranking KPI
- **Scheduling Pareto-ottimale**: assegnazione flotta per giornata con soluzioni multi-obiettivo
- **Percorsi compatibili**: ricerca percorsi assegnabili per vincoli temporali

*Pipeline completa:* Forecast ML → Weather Routing → KPI Calculation → Scheduling → Ranking"""
    },
    {
        "name": "Assegnazione",
        "description": """**Gestione operativa assegnazioni**
        
Gestione del ciclo di vita delle assegnazioni vascello-percorso:
- Stati: `PIANIFICATA` → `IN_CORSO` → `COMPLETATA` | `CANCELLATA`
- Validazione vincoli temporali tra percorsi sequenziali
- Associazione a piano operativo di riferimento"""
    },
    {
        "name": "Piano Operativo",
        "description": """**Piani operativi giornalieri**
        
Gestione dei piani operativi con ciclo di vita:
- Stati: `CREATO` → `IN_OTTIMIZZAZIONE` → `PRONTO` → `ATTIVO` → `ARCHIVIATO`
- KPI aggregati: profitto stimato, robustezza pianificazione
- Versionamento per storico modifiche"""
    },
    {
        "name": "Simulazione",
        "description": """**Simulatore fisico di navigazione**
        
Simulazione realistica della navigazione con motore fisico RAFLAC:
- Modello fisico con timestep configurabile
- Coordinate di partenza automatiche o personalizzate
- Integrazione con servizio simulatore esterno (Flask :5001)
- Accelerazione simulazione tramite `sim_speed_factor`
- Simulazione anticipata di piani operativi completi (`simula_piano`)
- Supporto disturbi runtime (speed decay, correnti esterne)

*Utilizzo:* validazione scenari, training operatori, analisi what-if."""
    },
    {
        "name": "Deadhead Trips",
        "description": """**Gestione viaggi a vuoto e riposizionamenti**
        
Gestione dei deadhead trips (spostamenti non produttivi) della flotta:
- Riposizionamento vascelli tra porti senza trasporto passeggeri
- Periodi di attesa (idle) in porto
- Tracciamento tempi non produttivi e consumi associati
- Associazione a piano operativo e vascello

*Operazioni disponibili:* creazione, modifica, eliminazione, lista con filtri per piano/vascello."""
    },
    {
        "name": "Replanning",
        "description": """**Controllo adattivo del piano operativo**
        
Endpoint dedicati alla verifica della necessità di replanning in tempo quasi reale:
- Ricerca del piano `IN_CORSO` per la giornata attiva
- Aggregazione assegnazioni per vascello con arricchimento dati percorso/corsa
- Mappatura `vascello_id -> MMSI` per interoperabilità servizi esterni
- Invocazione del microservizio di replanning per valutare criticità operative

*Output principale:* esito check, contesto operativo corrente e risposta dettagliata del servizio di replanning."""
    },
    {
        "name": "Alerting",
        "description": """**Monitoraggio allarmi operativi**

Raccolta e consultazione degli allarmi generati dal sistema:
- Lista allarmi ordinata per data di creazione decrescente
- Integrazione con microservizio dedicato `alerting_service`
- Fallback su database locale gateway quando configurato

*Obiettivo:* fornire visibilità immediata sugli eventi critici operativi."""
    },
    {
        "name": "Weather",
        "description": """**Integrazione meteo-oceanografica (Copernicus)**

Endpoint proxy verso il microservizio weather per:
- Health check del servizio meteo e del database `weather_db`
- Dati layer correnti/onde per dashboard geospaziale
- Consultazione cache layer con filtro e dettaglio per `cache_key`

*Supporta cache controllata* con parametri TTL e refresh per bilanciare latenza e accuratezza."""
    },
    {
        "name": "Configurazione",
        "description": """**Parametri runtime e integrazione**
        
Configurazione dinamica senza riavvio (hot-reload):
- **Kafka**: finestra temporale (`window_future`), intervalli di pubblicazione, `sim_speed_factor`
- **Cache**: durata validità dati ottimizzazione (`cache_delta_minutes`, default 120 min)

*Endpoint:* `GET/POST /api/config/kafka-settings` e `GET/POST /config`"""
    },
]

# Environment-backed configuration
DB_CONN = os.getenv("DB_CONN", "dbname=__forbidden_travelmar_test__ user=postgres password=admin host=localhost")
ML_URL = os.getenv("ML_URL", "http://localhost:8000/predict")
OPT_URL = os.getenv("OPT_URL", "http://192.168.1.250:8090/optimize")
SIMULATION_URL = os.getenv("SIMULATION_URL", "http://192.168.1.224:5001/simulate")
SCHEDULER_URL = os.getenv("SCHEDULER_URL", "http://localhost:8091/schedule")
REPLANNING_SERVICE_URL = os.getenv("REPLANNING_SERVICE_URL", "http://localhost:8001")
ANAGRAFICA_SERVICE_URL = os.getenv("ANAGRAFICA_SERVICE_URL", "http://localhost:8070")
ENABLE_ANAGRAFICA_DELEGATION = os.getenv("ENABLE_ANAGRAFICA_DELEGATION", "false").lower() in {"1", "true", "yes", "on"}
ENABLE_ANAGRAFICA_FALLBACK = os.getenv("ENABLE_ANAGRAFICA_FALLBACK", "true").lower() in {"1", "true", "yes", "on"}
OPERATIVO_SERVICE_URL = os.getenv("OPERATIVO_SERVICE_URL", "http://operativo:8072")
ENABLE_OPERATIVO_DELEGATION = os.getenv("ENABLE_OPERATIVO_DELEGATION", "false").lower() in {"1", "true", "yes", "on"}
ENABLE_OPERATIVO_FALLBACK = os.getenv("ENABLE_OPERATIVO_FALLBACK", "true").lower() in {"1", "true", "yes", "on"}
PERCORSI_SERVICE_URL = os.getenv("PERCORSI_SERVICE_URL", "http://percorsi:8073")
ENABLE_PERCORSI_DELEGATION = os.getenv("ENABLE_PERCORSI_DELEGATION", "false").lower() in {"1", "true", "yes", "on"}
ENABLE_PERCORSI_FALLBACK = os.getenv("ENABLE_PERCORSI_FALLBACK", "true").lower() in {"1", "true", "yes", "on"}
FORECAST_SERVICE_URL = os.getenv("FORECAST_SERVICE_URL", "http://forecast:8074")
ENABLE_FORECAST_DELEGATION = os.getenv("ENABLE_FORECAST_DELEGATION", "false").lower() in {"1", "true", "yes", "on"}
ENABLE_FORECAST_FALLBACK = os.getenv("ENABLE_FORECAST_FALLBACK", "true").lower() in {"1", "true", "yes", "on"}
ALERTING_SERVICE_URL = os.getenv("ALERTING_SERVICE_URL", "http://alerting:8075")
ENABLE_ALERTING_DELEGATION = os.getenv("ENABLE_ALERTING_DELEGATION", "false").lower() in {"1", "true", "yes", "on"}
ENABLE_ALERTING_FALLBACK = os.getenv("ENABLE_ALERTING_FALLBACK", "true").lower() in {"1", "true", "yes", "on"}
WEATHER_SERVICE_URL = os.getenv("WEATHER_SERVICE_URL", "http://weather:8076")

import time
KAFKA_CONFIG_TIMESTAMP = time.time()
KAFKA_CONFIG = {
    "window_future": int(os.getenv("WINDOW_FUTURE_MIN", "30")),
    "publish_interval": int(os.getenv("PUBLISH_INTERVAL", "30")),
    "publish_interval_sec": int(os.getenv("PUBLISH_INTERVAL_SEC", "30")),
    "sim_speed_factor": float(os.getenv("SIM_SPEED_FACTOR", "1.0")),
    "last_update": KAFKA_CONFIG_TIMESTAMP
}

def now_iso():
    return datetime.now().isoformat()


class _ServiceCfg(BaseModel):
    cache_delta_minutes: int = 120
    replanning_check_interval_seconds: int = 300
    replanning_theta_min: float = float(os.getenv("REPLANNING_THETA_MIN", "10"))
    replanning_theta_critical_min: float = float(os.getenv("REPLANNING_THETA_CRITICAL_MIN", "30"))
    replanning_max_late: int = int(os.getenv("REPLANNING_MAX_LATE", "2"))
    replanning_max_critical: int = int(os.getenv("REPLANNING_MAX_CRITICAL", "1"))
    replanning_total_delay_max: float = float(os.getenv("REPLANNING_TOTAL_DELAY_MAX", "60"))
    replanning_single_delay_max: float = float(os.getenv("REPLANNING_SINGLE_DELAY_MAX", "40"))
    replanning_horizon_minutes: int = int(os.getenv("REPLANNING_HORIZON_MINUTES", "120"))
    replanning_cooldown_minutes: int = int(os.getenv("REPLANNING_COOLDOWN_MINUTES", "30"))
    replanning_freeze_window_minutes: int = int(os.getenv("REPLANNING_FREEZE_WINDOW_MINUTES", "15"))

SERVICE_CONFIG = _ServiceCfg()