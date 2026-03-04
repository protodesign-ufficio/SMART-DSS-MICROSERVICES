# SMART-DSS

**Sistema di Supporto Decisionale per la Navigazione Marittima**

Sistema di ottimizzazione e simulazione per la pianificazione di rotte marittime, con previsione biglietti tramite ensemble ML, weather routing multi-obiettivo (NAMOA\*), scheduling Pareto-ottimale e simulazione fisica della navigazione.

## Architettura

Il sistema è composto da 6 microservizi orchestrati via Docker Compose:

| Servizio | Porta | Framework | Descrizione |
|----------|-------|-----------|-------------|
| **backend** | 15080 | FastAPI | API Gateway centralizzato — coordina tutti i servizi |
| **service** | 8000 | FastAPI | Previsione biglietti con ensemble ML a 3 modelli |
| **ottimizzatore** | 8090 | Flask | Weather routing multi-obiettivo (NAMOA\*, dati Copernicus) |
| **scheduler** | 8091 | Flask | Scheduling flotta Pareto-ottimale |
| **simulator** | 5001 | Flask | Simulazione fisica di navigazione in tempo reale |
| **replanning** | 8001 | FastAPI | Trigger adattivo replanning su ritardi operativi (Kafka analytics) |

Dipendenza esterna: **PostgreSQL + PostGIS** (raggiunto via `host.docker.internal`).

```
┌──────────────────────────────────────────────────────────────┐
│                     Backend :15080                            │
│           (API Gateway FastAPI + APScheduler)                │
└──────┬──────────────┬───────────────┬───────────────┬────────────┬────────┘
       │              │               │               │            │
       ▼              ▼               ▼               ▼            ▼
┌──────────┐   ┌──────────┐   ┌──────────────┐  ┌──────────┐  ┌──────────┐
│ Service  │   │Simulator │   │Ottimizzatore │  │Scheduler │  │Replanning│
│  :8000   │   │  :5001   │   │    :8090     │  │  :8091   │  │  :8001   │
│(ML/Fast) │   │ (Flask)  │   │   (Flask)    │  │ (Flask)  │  │ (FastAPI)│
└──────────┘   └──────────┘   └──────┬───────┘  └──────────┘  └─────┬────┘
                                     │                               │
                              ┌──────▼───────┐                ┌──────▼─────┐
                              │copernicus-data│                │Kafka topic │
                              │   (volume)    │                │analytics   │
                              └──────────────┘                └────────────┘
                                     
       ┌─────────────────────────────────────────┐
       │   PostgreSQL + PostGIS (esterno)         │
       │   host.docker.internal                   │
       └─────────────────────────────────────────┘
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
├── docker-compose.yml          # Orchestrazione 6 servizi
├── Dockerfile.*                # Dockerfile per ogni servizio
├── requirements.txt            # Dipendenze Python (ML + Backend)
├── service.py                  # Servizio ML prediction (ensemble 3 modelli)
├── mod_macro.json              # Modello macro (passeggeri giornalieri)
├── mod_micro_step1.json        # Modello micro base (per-corsa)
├── mod_micro_step2.json        # Modello micro adjustment
├── config_modelli.json         # Configurazione modelli ML
├── app/                        # Backend API Gateway
│   ├── main.py                 # Entrypoint FastAPI + lifespan scheduler
│   ├── requirements.txt        # Dipendenze minime backend
│   ├── core/                   # Config, database, scheduler APScheduler
│   ├── models/                 # Modelli Pydantic (11 moduli)
│   ├── routers/                # Endpoint API (12 router)
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
- PostgreSQL + PostGIS esterno (configurato in `DB_CONN`)
- Credenziali Copernicus Marine (per dati oceanografici real-time)

## Configurazione

Le variabili d'ambiente principali sono definite in `docker-compose.yml`:

| Variabile | Servizio | Descrizione |
|-----------|----------|-------------|
| `DB_CONN` | backend | Connessione PostgreSQL |
| `ML_URL` | backend | Endpoint servizio ML (`http://service:8000/predict`) |
| `SIMULATION_URL` | backend | Endpoint simulatore (`http://simulator:5001/simulate`) |
| `OPT_URL` | backend | Endpoint ottimizzatore (`http://ottimizzatore:8090/optimize/list`) |
| `SCHEDULER_URL` | backend | Endpoint scheduler (`http://scheduler:8091/schedule`) |
| `REPLANNING_SERVICE_URL` | backend | Endpoint servizio replanning (`http://replanning:8001`) |
| `WINDOW_FUTURE_MIN` | backend | Finestra temporale Kafka (default: `30`) |
| `PUBLISH_INTERVAL` | backend | Intervallo pubblicazione Kafka (default: `30`) |
| `SIM_SPEED_FACTOR` | backend | Fattore accelerazione simulazione (default: `1.0`) |
| `COPERNICUSMARINE_SERVICE_USERNAME` | ottimizzatore | Username Copernicus Marine |
| `COPERNICUSMARINE_SERVICE_PASSWORD` | ottimizzatore | Password Copernicus Marine |
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

Il backend espone **12 gruppi di endpoint** organizzati per dominio funzionale:

| Gruppo | Prefisso | Metodi | Descrizione |
|--------|----------|--------|-------------|
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
| **Replanning** | `/check_replanning` | 1 | Verifica automatica necessità di replanning |
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

Documentazione Swagger interattiva disponibile su: `http://localhost:15080/docs`

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
