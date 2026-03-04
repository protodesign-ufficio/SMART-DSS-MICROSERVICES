# SMART-DSS

**Sistema di Supporto Decisionale per la Navigazione Marittima**

Sistema di ottimizzazione e simulazione per la pianificazione di rotte marittime, con previsione biglietti tramite ensemble ML, weather routing multi-obiettivo (NAMOA\*), scheduling Pareto-ottimale e simulazione fisica della navigazione.

## Architettura

Il sistema è composto da microservizi orchestrati via Docker Compose:

| Servizio | Porta (interna → host) | Framework | DB dedicato | Descrizione |
|----------|------------------------|-----------|-------------|-------------|
| **backend** | 15080 → 25080 | FastAPI | — | API Gateway centralizzato — coordina tutti i servizi |
| **anagrafica** | 8070 → 18070 | FastAPI | `anagrafica_db` | Dominio anagrafica: porti, tratte, vascelli |
| **operativo** | 8072 → 18072 | FastAPI | `operativo_db` | Dominio operativo: piani, corse, assegnazioni, deadhead |
| **percorsi** | 8073 → 18073 | FastAPI | `percorsi_db` | Dominio percorsi: rotte ottimizzate, variazioni |
| **forecast** | 8074 → 18074 | FastAPI | `forecast_db` | Dominio previsioni: calcolo domanda passeggeri ML |
| **alerting** | 8075 → 18075 | FastAPI | `alerting_db` | Dominio allarmi: gestione allarmi operativi |
| **telemetry** | 8071 → 18071 | FastAPI | `telemetry_db` | Dominio telemetria: posizioni AIS recenti |
| **weather** | 8076 → 18076 | FastAPI | `weather_db` | Fetch e cache persistente dati meteo-marini Copernicus (subset NetCDF + layer dashboard) |
| **service** | 8000 → 18000 | FastAPI | — | Previsione biglietti con ensemble ML a 3 modelli |
| **ottimizzatore** | 8090 → 18090 | Flask | — | Weather routing multi-obiettivo (NAMOA\*, dati Copernicus) |
| **scheduler** | 8091 → 18091 | Flask | — | Scheduling flotta Pareto-ottimale |
| **simulator** | 5001 → 15001 | Flask | — | Simulazione fisica di navigazione in tempo reale |
| **replanning** | 8001 → 18001 | FastAPI | — | Trigger adattivo replanning su ritardi operativi (Kafka analytics) |

Dipendenza esterna: **PostgreSQL 18 + PostGIS** (raggiunto via `host.docker.internal`).
Database dedicati: `anagrafica_db`, `operativo_db`, `percorsi_db`, `forecast_db`, `alerting_db`, `telemetry_db`, `weather_db` (+ legacy `travelmar_db`).

```
┌──────────────────────────────────────────────────────────────────────────┐
│                        Backend :15080 (host :25080)                      │
│              (API Gateway FastAPI + APScheduler + /health)               │
└──┬──────┬──────┬──────┬──────┬──────┬──────┬──────┬──────┬──────┬───────┘
   │      │      │      │      │      │      │      │      │      │
   ▼      ▼      ▼      ▼      ▼      ▼      ▼      ▼      ▼      ▼
┌──────┐┌──────┐┌──────┐┌──────┐┌──────┐┌──────┐┌──────┐┌──────┐┌──────┐┌──────────┐
│Anag. ││Oper. ││Perc. ││Forec.││Alert.││Telem.││Weath.││ Svc  ││Simul.││Ottimizz. │
│ :8070││ :8072││ :8073││ :8074││ :8075││ :8071││ :8076││ :8000││ :5001││   :8090  │
└──┬───┘└──┬───┘└──┬───┘└──┬───┘└──┬───┘└──┬───┘└──┬───┘└──────┘└──────┘└────┬─────┘
   │       │       │       │       │       │       │                           │
   ▼       ▼       ▼       ▼       ▼       ▼       ▼                           ▼
┌────────────────────────────────────────────────────────┐          ┌──────────────┐
│     PostgreSQL 18 + PostGIS  (host.docker.internal)    │          │copernicus-data│
│  anagrafica_db │ operativo_db │ percorsi_db            │          │   (volume)    │
│  forecast_db   │ alerting_db  │ telemetry_db           │          └──────────────┘
│  weather_db    │ travelmar_db (legacy)                 │
└────────────────────────────────────────────────────────┘
                                         ┌──────────┐  ┌────────────┐
                                         │Scheduler │  │ Replanning │
                                         │  :8091   │  │   :8001    │
                                         └──────────┘  └─────┬──────┘
                                                             │
                                                       ┌─────▼──────┐
                                                       │Kafka topic │
                                                       │analytics   │
                                                       └────────────┘
```

## Quickstart

```bash
# Avvia tutti i servizi
docker compose up --build -d

# Verifica stato
docker compose ps

# Visualizza logs
docker compose logs -f backend
```

Documentazione Swagger: `http://localhost:15080/docs`

## Struttura del progetto

```
SMART-DSS/
├── docker-compose.yml          # Orchestrazione microservizi
├── Dockerfile.*                # Dockerfile per ogni servizio
├── requirements.txt            # Dipendenze Python (ML + Backend)
├── service.py                  # Servizio ML prediction (ensemble 3 modelli)
├── mod_macro.json              # Modello macro (passeggeri giornalieri)
├── mod_micro_step1.json        # Modello micro base (per-corsa)
├── mod_micro_step2.json        # Modello micro adjustment
├── config_modelli.json         # Configurazione modelli ML
├── app/                        # Backend API Gateway
│   ├── main.py                 # Entrypoint FastAPI + lifespan scheduler + /health
│   ├── requirements.txt        # Dipendenze minime backend
│   ├── core/                   # Config, database, scheduler APScheduler, client HTTP
│   ├── models/                 # Modelli Pydantic (11 moduli)
│   ├── routers/                # Endpoint API (14 router)
│   ├── services/               # Logica business (10 servizi)
│   └── utils/                  # Utility (geo, time, validation)
├── routing_service/            # Servizio ottimizzatore (Flask)
│   ├── app_server.py           # Server Flask (:8090)
│   ├── NAMOA.py                # Algoritmo NAMOA* multi-obiettivo
│   ├── routing.py              # Logica routing con correnti marine
│   ├── optimizer_service.py    # Servizio ottimizzazione
│   ├── graphs_cell.py          # Gestione grafi per navigazione
│   ├── Api_Copernicus.py       # Client API Copernicus Marine
│   ├── waypoint.py             # Modello waypoint
│   └── copernicus-data/        # Dati oceanografici NetCDF
├── weather_service/            # Servizio meteo Copernicus (FastAPI)
│   ├── main.py                 # API meteo interne (/health, /internal/weather/*)
│   └── requirements.txt        # Dipendenze servizio weather
├── anagrafica_service/         # Microservizio anagrafica (FastAPI :8070)
│   ├── main.py                 # API interne porti, tratte, vascelli
│   └── requirements.txt
├── operativo_service/          # Microservizio operativo (FastAPI :8072)
│   ├── main.py                 # API interne corse, piani, assegnazioni, deadhead
│   └── requirements.txt
├── percorsi_service/           # Microservizio percorsi (FastAPI :8073)
│   ├── main.py                 # API interne percorsi + include expansion
│   └── requirements.txt
├── forecast_service/           # Microservizio previsioni (FastAPI :8074)
│   ├── main.py                 # API interne previsioni + calcolo ML
│   └── requirements.txt
├── alerting_service/           # Microservizio allarmi (FastAPI :8075)
│   ├── main.py                 # API interne allarmi operativi
│   └── requirements.txt
├── telemetry_service/          # Microservizio telemetria (FastAPI :8071)
│   ├── main.py                 # API interne posizioni AIS
│   └── requirements.txt
├── simulator_service/          # Servizio simulazione (Flask)
│   ├── sim_server.py           # Server Flask (:5001)
│   ├── simulation_service.py   # Engine simulazione (RAFLAC physics)
│   ├── vessel.py               # Modello vessel fisico
│   ├── ais_generator.py        # Generatore dati AIS
│   ├── Api_Copernicus.py       # Client API Copernicus
│   ├── waypoint.py             # Gestione waypoint
│   └── constants.py            # Costanti fisiche
├── scheduling_service/         # Servizio scheduling (Flask)
│   ├── app_server.py           # Server Flask (:8091)
│   ├── solver.py               # Solver Pareto-ottimale (NAMOA*)
│   └── models.py               # Modelli dati scheduling
├── SMART_replanning_service/   # Servizio replanning (FastAPI)
│   ├── replanning_service/
│   │   ├── main.py             # API /health e /replanning/check (:8001)
│   │   ├── config.py           # Soglie trigger + configurazione Kafka
│   │   └── requirements.txt    # Dipendenze servizio replanning
│   └── specifiche.md           # Specifiche propagazione ritardi e trigger
└── docs/                       # Documentazione
    ├── README.md               # Indice documentazione
    ├── docker-overview.md      # Panoramica Docker Compose
    ├── runbook.md              # Runbook operativo
    ├── env-reference.md        # Variabili d'ambiente
    ├── diagrams/               # Diagrammi architettura
    └── services/               # Documentazione per servizio
```

## Prerequisiti

- Docker Desktop con Docker Compose v2
- PostgreSQL 18 + PostGIS esterno con 8 database dedicati (vedi sezione Configurazione)
- Credenziali Copernicus Marine (per dati oceanografici real-time)

## Configurazione

Le variabili d'ambiente principali sono definite in `docker-compose.yml`:

| Variabile | Servizio | Descrizione |
|-----------|----------|-------------|
| `DB_CONN` | backend, microservizi | Connessione PostgreSQL (legacy fallback — disattivato in strict mode) |
| `ANAGRAFICA_DB_CONN` | anagrafica | Connessione DB dedicato `anagrafica_db` |
| `OPERATIVO_DB_CONN` | operativo | Connessione DB dedicato `operativo_db` |
| `PERCORSI_DB_CONN` | percorsi | Connessione DB dedicato `percorsi_db` |
| `FORECAST_DB_CONN` | forecast | Connessione DB dedicato `forecast_db` |
| `ALERTING_DB_CONN` | alerting | Connessione DB dedicato `alerting_db` |
| `TELEMETRY_DB_CONN` | telemetry | Connessione DB dedicato `telemetry_db` |
| `WEATHER_DB_CONN` | weather | Connessione DB dedicato `weather_db` |
| `ANAGRAFICA_SERVICE_URL` | backend, operativo, percorsi | Endpoint servizio anagrafica (`http://anagrafica:8070`) |
| `OPERATIVO_SERVICE_URL` | backend, percorsi | Endpoint servizio operativo (`http://operativo:8072`) |
| `PERCORSI_SERVICE_URL` | backend, operativo | Endpoint servizio percorsi (`http://percorsi:8073`) |
| `FORECAST_SERVICE_URL` | backend, operativo | Endpoint servizio forecast (`http://forecast:8074`) |
| `ALERTING_SERVICE_URL` | backend | Endpoint servizio alerting (`http://alerting:8075`) |
| `WEATHER_SERVICE_URL` | backend, ottimizzatore | Endpoint servizio weather (`http://weather:8076`) |
| `ENABLE_ANAGRAFICA_DELEGATION` | backend | Delega richieste anagrafica al microservizio (default: `true`) |
| `ENABLE_ANAGRAFICA_FALLBACK` | backend | Fallback legacy su `travelmar_db` (default: `false`) |
| `ENABLE_OPERATIVO_DELEGATION` | backend | Delega richieste operativo al microservizio (default: `true`) |
| `ENABLE_OPERATIVO_FALLBACK` | backend | Fallback legacy su `travelmar_db` (default: `false`) |
| `ENABLE_PERCORSI_DELEGATION` | backend | Delega richieste percorsi al microservizio (default: `true`) |
| `ENABLE_PERCORSI_FALLBACK` | backend | Fallback legacy su `travelmar_db` (default: `false`) |
| `ENABLE_FORECAST_DELEGATION` | backend | Delega richieste forecast al microservizio (default: `true`) |
| `ENABLE_FORECAST_FALLBACK` | backend | Fallback legacy su `travelmar_db` (default: `false`) |
| `ENABLE_ALERTING_DELEGATION` | backend | Delega richieste alerting al microservizio (default: `true`) |
| `ENABLE_ALERTING_FALLBACK` | backend | Fallback legacy su `travelmar_db` (default: `false`) |
| `ML_URL` | backend, forecast | Endpoint servizio ML (`http://service:8000/predict`) |
| `SIMULATION_URL` | backend | Endpoint simulatore (`http://simulator:5001/simulate`) |
| `OPT_URL` | backend | Endpoint ottimizzatore (`http://ottimizzatore:8090/optimize/list`) |
| `SCHEDULER_URL` | backend | Endpoint scheduler (`http://scheduler:8091/schedule`) |
| `REPLANNING_SERVICE_URL` | backend | Endpoint servizio replanning (`http://replanning:8001`) |
| `WINDOW_FUTURE_MIN` | backend | Finestra temporale Kafka (default: `30`) |
| `PUBLISH_INTERVAL` | backend | Intervallo pubblicazione Kafka (default: `30`) |
| `SIM_SPEED_FACTOR` | backend | Fattore accelerazione simulazione (default: `1.0`) |
| `COPERNICUSMARINE_SERVICE_USERNAME` | weather | Username Copernicus Marine |
| `COPERNICUSMARINE_SERVICE_PASSWORD` | weather | Password Copernicus Marine |
| `WEATHER_DATA_DIR` | weather | Cartella output NetCDF condivisa (`/app/copernicus-data`) |
| `WEATHER_DB_CONN` | weather | Connessione DB dedicata meteo (`weather_db`) |
| `WEATHER_LAYER_CACHE_TTL_MIN` | weather | TTL cache layer meteo in minuti (default `120`) |
| `HDF5_USE_FILE_LOCKING` | ottimizzatore | Disabilita file locking HDF5 (`FALSE`) |
| `KAFKA_BOOTSTRAP_SERVERS` | replanning | Bootstrap servers Kafka (default compose: `host.docker.internal:9092`) |
| `KAFKA_ANALYTICS_TOPIC` | replanning | Topic analytics AIS (default compose: `analytics_ais.raw`) |
| `REPLANNING_THETA_MIN` | replanning | Soglia ritardo minimo (minuti) |
| `REPLANNING_THETA_CRITICAL_MIN` | replanning | Soglia ritardo critico (minuti) |

> ⚠️ **Nota:** le credenziali sono attualmente hardcoded nel compose. Per produzione, utilizzare file `.env` o Docker secrets.

## Comandi utili

```bash
# Avvio completo
docker compose up --build -d

# Stop servizi
docker compose down

# Rebuild singolo servizio
docker compose build --no-cache <servizio>
docker compose up -d <servizio>

# Logs real-time
docker compose logs -f <servizio>

# Shell nel container
docker compose exec <servizio> sh

# Pulizia completa
docker compose down
docker image prune -f
docker volume prune -f
```

## API Endpoints

### Backend — API Gateway (porta 15080)

Il backend espone **14 gruppi di endpoint** organizzati per dominio funzionale:

| Gruppo | Prefisso | Metodi | Descrizione |
|--------|----------|--------|-------------|
| **Sistema** | `/health` | 1 | Health check del gateway |
| **Porti** | `/porto/` | 6 | CRUD anagrafica porti con coordinate WGS84/PostGIS |
| **Vascelli** | `/vascello/` | 8 | Gestione flotta (MMSI, capacità, consumi, immagini) |
| **Tratte** | `/tratta/` | 6 | Rotte geografiche dirette e multiporto con LineString PostGIS |
| **Corse** | `/corsa/` | 9 | Programmazione oraria con previsione domanda ML |
| **Percorsi** | `/percorso/` | 4 | Rotte ottimizzate da weather routing (GeoJSON + KPI) |
| **Pianificazione** | `/weather_routing/`, `/scheduling/` | 6 | Weather routing batch, riposizionamento, scheduling Pareto |
| **Assegnazione** | `/assegnazione/` | 6 | Ciclo di vita assegnazioni (PIANIFICATA→IN_CORSO→COMPLETATA) |
| **Piano Operativo** | `/piano/` | 6 | Piani giornalieri con validazione e KPI aggregati |
| **Simulazione** | `/simulation/` | 2 | Simulazione fisica navigazione e piani anticipati |
| **Deadhead Trips** | `/deadhead/` | 4 | Riposizionamenti a vuoto e idle in porto |
| **Allarmi** | `/allarme/` | 1 | Lista allarmi operativi (delegato ad alerting_service) |
| **Weather** | `/weather/` | 4 | Dati meteo-marini: layer dashboard, cache layer, health |
| **Replanning** | `/check_replanning` | 2 | Verifica automatica necessità di replanning + status |
| **Configurazione** | `/api/config/`, `/config` | 4 | Parametri runtime Kafka e cache (hot-reload) |

### Service ML (porta 8000)

| Metodo | Endpoint | Descrizione |
|--------|----------|-------------|
| `POST` | `/predict` | Previsione domanda passeggeri (ensemble 3 modelli + bootstrap CI 95%) |

### Ottimizzatore (porta 8090)

| Metodo | Endpoint | Descrizione |
|--------|----------|-------------|
| `POST` | `/optimize` | Ottimizzazione singola rotta |
| `POST` | `/optimize/list` | Ottimizzazione rotte in batch |
| `POST` | `/set_current_box` | Imposta bounding box correnti marine |
| `POST` | `/clear_current_box` | Reset bounding box |
| `POST` | `/graphs/precompute` | Pre-calcolo grafi NAMOA\* |

### Weather (porta 8076)

| Metodo | Endpoint | Descrizione |
|--------|----------|-------------|
| `GET` | `/health` | Health check servizio meteo |
| `POST` | `/internal/weather/subset/download` | Download subset Copernicus in formato NetCDF |
| `POST` | `/internal/weather/layer` | Dati correnti/onde per dashboard (timestamp, items, range) |
| `GET` | `/internal/weather/cache/layer` | Lista cache persistita dei layer meteo |
| `GET` | `/internal/weather/cache/layer/{cache_key}` | Recupero payload meteo da cache persistita |

### Database dedicato Weather

Il microservizio `weather` usa un database dedicato `weather_db` (PostgreSQL) per persistere:
- cache layer (`weather_layer_cache`) con payload completo riutilizzabile
- storico download subset NetCDF (`weather_subset_downloads`)

Le tabelle vengono create automaticamente al bootstrap del servizio.

Se il database non esiste ancora, crearlo una sola volta su PostgreSQL:

```sql
CREATE DATABASE weather_db;
```

### Scheduler (porta 8091)

| Metodo | Endpoint | Descrizione |
|--------|----------|-------------|
| `POST` | `/schedule` | Ottimizzazione scheduling flotta (Pareto) |
| `POST` | `/schedule/validate` | Validazione input scheduling |
| `GET` | `/health` | Health check |

### Simulator (porta 5001)

| Metodo | Endpoint | Descrizione |
|--------|----------|-------------|
| `POST` | `/simulate/start` | Avvia simulazione navigazione |
| `GET` | `/simulate/status` | Stato simulazione (singola o tutte) |
| `POST` | `/simulate/stop` | Arresta simulazione |
| `GET` | `/simulate/list` | Lista simulazioni attive |
| `POST` | `/vessel/<name>/disturbance` | Imposta disturbo su vascello (speed decay, correnti esterne) |

### Replanning (porta 8001)

| Metodo | Endpoint | Descrizione |
|--------|----------|-------------|
| `GET` | `/health` | Health check servizio replanning |
| `POST` | `/replanning/check` | Propagazione ritardi + indicatori globali + trigger/cooldown |

Documentazione Swagger interattiva disponibile su: `http://localhost:25080/docs` (porta host) oppure `http://localhost:15080/docs` (porta interna container).

## Documentazione

Documentazione dettagliata disponibile in [docs/](docs/README.md):

- [Docker Overview](docs/docker-overview.md) — Panoramica Docker Compose
- [Runbook](docs/runbook.md) — Guida operativa
- [Env Reference](docs/env-reference.md) — Variabili d'ambiente
- [Architettura](docs/diagrams/architecture.md) — Diagrammi Mermaid
- Servizi:
       - [Backend](docs/services/backend.md) — API Gateway (FastAPI)
       - [Service ML](docs/services/service.md) — Previsione biglietti (FastAPI)
       - [Simulator](docs/services/simulator.md) — Simulazione navigazione (Flask)
       - [Ottimizzatore](docs/services/ottimizzatore.md) — Weather routing (Flask)
       - [Scheduler](docs/services/scheduler.md) — Scheduling flotta (Flask)
       - [Replanning](docs/services/replanning.md) — Trigger adattivo su ritardi operativi (FastAPI)

## Licenza

Progetto SMART - Sistema Marittimo Avanzato per Rotte e Trasporti
