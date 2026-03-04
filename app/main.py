from fastapi import FastAPI
from contextlib import asynccontextmanager
import subprocess
from datetime import datetime
from zoneinfo import ZoneInfo
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.middleware.cors import CORSMiddleware
from app.routers import (
    porto, tratta, corsa, vascello, percorso,
    pianificazione, piano_operativo, simulazione, config as config_router,
    assegnazione, deadhead, replanning, allarme, weather
)
from app.core.config import TAGS_METADATA
from app.core.scheduler import start_scheduler, shutdown_scheduler

# Timestamp di avvio dell'applicazione (fuso orario italiano)
STARTUP_TIME = datetime.now(ZoneInfo("Europe/Rome")).strftime("%d/%m/%Y ORE %H:%M")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Gestisce il ciclo di vita dell'applicazione (startup/shutdown)."""
    # Startup: avvia lo scheduler
    start_scheduler()
    print("[Scheduler] Avviato")
    yield
    # Shutdown: arresta lo scheduler
    shutdown_scheduler()
    print("[Scheduler] Arrestato")


app = FastAPI(
    lifespan=lifespan,
    title="SMART Maritime API Gateway",
    description=f"""
## Sistema di Gestione Trasporto Marittimo Intelligente

API Gateway centralizzato per la gestione operativa e l'ottimizzazione delle flotte marittime.

---

### Funzionalità principali

| Modulo | Descrizione |
|--------|-------------|
| **Anagrafica** | Gestione porti, tratte, vascelli e corse programmate |
| **Previsione ML** | Stima domanda passeggeri con modelli di Machine Learning |
| **Weather Routing** | Ottimizzazione percorsi considerando condizioni meteo-marine |
| **Pianificazione** | Assegnazione ottimale flotte su orizzonte temporale |
| **Deadhead Trips** | Gestione viaggi a vuoto e riposizionamenti flotta |
| **Simulazione** | Simulatore fisico di navigazione in tempo reale |
| **Configurazione** | Gestione parametri runtime e integrazione Kafka |

---

### Architettura

Il sistema è basato su architettura a **microservizi** con:
- **PostgreSQL + PostGIS** per dati geospaziali
- **Integrazione ML** per previsioni domanda
- **Ottimizzatore esterno** per weather routing multi-obiettivo
- **Simulatore fisico** per validazione scenari

---
<details>
<summary><strong>Schema di Esecuzione - Casi d'Uso Complessi (Clicca per espandere)</strong></summary>

#### Caso 1: Simulazione singola assegnazione
*Tipico caso d'uso per testare e visualizzare il funzionamento del simulatore*

| Step | Endpoint | Descrizione |
|------|----------|-------------|
| 1 | `POST /porto/crea` | Crea il porto |
| 2 | `POST /vascello/crea` | Crea il vascello |
| 3 | `POST /tratta/crea` | Crea la tratta |
| 4 | `POST /corsa/crea` | Crea la corsa |
| 5 | `POST /weather_routing/carico` | Genera i percorsi tramite l'ottimizzatore per la corsa e il vascello selezionati |
| 6 | `POST /piano/crea` | Crea il piano operativo |
| 7 | `POST /assegnazione/crea` | Associa un percorso al piano *(impostare stato: `IN_CORSO` per avviare la simulazione)* |
| 8 | `POST /simulation/build_and_run` | Avvia la simulazione |

#### Caso 2: Piano operativo completo con schedulazione automatica
*Workflow completo per creare un piano operativo giornaliero con simulazioni automatiche*

| Step | Endpoint | Descrizione |
|------|----------|-------------|
| 1 | `POST /porto/crea` | Crea i porti *(se non esistenti)* |
| 2 | `POST /vascello/crea` | Crea i vascelli della flotta *(se non esistenti)* |
| 3 | `POST /tratta/crea` | Crea le tratte *(se non esistenti)* |
| 4 | `POST /corsa/crea` | Crea tutte le corse del giorno |
| 5 | `POST /corsa/{id}/prevedi` | Calcola previsione ML passeggeri per ogni corsa |
| 6 | `POST /weather_routing/carico` | Genera i percorsi ottimali per tutte le coppie corsa-vascello |
| 7 | `POST /scheduling/giorno` | Calcola soluzioni Pareto-ottimali (NAMOA*) per lo scheduling |
| 8 | `POST /piano/crea` | Crea il piano operativo per la giornata |
| 9 | `POST /assegnazione/bulk` | Crea le assegnazioni in blocco *(con `virtuale: true` per schedulare simulazioni)* |
| 10 | *Automatico* | Le simulazioni partono automaticamente agli orari schedulati |

> **Nota**: Lo step 9 con `virtuale: true` schedula automaticamente un job che avvierà la simulazione
> all'`orario_partenza_schedulato` di ogni corsa. Le simulazioni vengono eseguite in background.

#### Caso 3: Simulazione Anticipata Piano ("Accelerata")
*Permette di simulare immediatamente un piano operativo previsto per il futuro*

| Step | Endpoint | Descrizione |
|------|----------|-------------|
| 1 | `POST /piano/crea` | Crea il piano operativo (o usa esistente) |
| 2 | `POST /assegnazione/bulk` | Crea assegnazioni con `virtuale: true` per il piano |
| 3 | `POST /simulation/simula_piano` | Avvia **subito** le simulazioni scalate nel tempo (es. partendo tra 5s) invece di attendere l'orario reale |

#### Caso 4: Gestione Variazioni e Guasti
*Creazione di scenari alternativi (guasti motore, deviazioni) per training o test*

| Step | Endpoint | Descrizione |
|------|----------|-------------|
| 1 | `GET /percorso/{id}` | Recupera l'ID di un percorso esistente |
| 2 | `POST /percorso/applica_variazione` | Crea una variante (es. `type: "GUASTO"`) che riduce la velocità (simula avaria) |
| 3 | `POST /assegnazione/crea` | Assegna il **nuovo percorso variato** al piano |
| 4 | `POST /simulation/build_and_run` | Simula con il percorso guasto per misurare l'impatto (es. ritardi) |

</details>

---

   *Ultimo aggiornamento documentazione: {STARTUP_TIME}*
    """,
    version="2.1.0",
    swagger_ui_parameters={
        "defaultModelsExpandDepth": -1,
        "docExpansion": "none",
        "filter": True,
        "showExtensions": True,
        "showCommonExtensions": True
    },
    openapi_tags=TAGS_METADATA,
    docs_url=None
)

@app.get("/docs", include_in_schema=False)
async def custom_swagger_ui_html():
    html = get_swagger_ui_html(
        openapi_url=app.openapi_url,
        title=app.title + " - Docs",
        oauth2_redirect_url=app.swagger_ui_oauth2_redirect_url,
        swagger_ui_parameters=app.swagger_ui_parameters
    )
    custom_css = """
    <style>
        .swagger-ui .opblock-tag-section {
            display: block;
            margin-bottom: 5px;
            background: #fff;
            padding: 5px 10px;
            box-shadow: 0 1px 2px 0 rgba(0,0,0,0.05);
            border-radius: 4px;
            border: 1px solid #e2e8f0;
        }
        
        .swagger-ui .opblock-tag {
            border-bottom: 1px solid #e2e8f0 !important;
            margin: 0 0 2px 0 !important;
            padding-bottom: 2px !important;
            display: flex;
            flex-wrap: wrap;
            align-items: center;
            justify-content: space-between;
        }

        .swagger-ui .opblock-tag a {
            font-size: 0.95em !important;
            font-weight: 700 !important;
            color: #1e293b !important;
            font-family: 'Segoe UI', system-ui, sans-serif;
            flex: 1;
            letter-spacing: -0.01em;
        }

        .swagger-ui .opblock-tag small {
            width: 100%;
            order: 1;
            font-size: 0.7em !important;
            font-weight: 400 !important;
            color: #475569 !important;
            text-align: left;
            padding: 2px 0 0 0 !important;
            line-height: 1.2;
        }

        .swagger-ui .opblock-tag small ul {
            margin: 2px 0 0 0;
            padding-left: 12px;
        }

        .swagger-ui .opblock-tag small li {
            margin-bottom: 0px;
        }
        
        .swagger-ui .opblock-tag button {
            margin: 0 !important;
            opacity: 0.6;
            flex: 0 0 auto;
            transform: scale(0.85);
        }
    </style>
    """
    html_content = html.body.decode('utf-8')
    html_content = html_content.replace('</body>', f'{custom_css}</body>')
    return HTMLResponse(content=html_content)

@app.get("/health", tags=["Sistema"], summary="Health check del gateway",
         description="Verifica che il gateway API sia operativo.")
async def health():
    return {"status": "ok", "service": "gateway"}


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# include routers
app.include_router(porto.router)
app.include_router(tratta.router)
app.include_router(corsa.router)
app.include_router(vascello.router)
app.include_router(percorso.router)
app.include_router(pianificazione.router)
app.include_router(assegnazione.router)
app.include_router(piano_operativo.router)
app.include_router(simulazione.router)
app.include_router(config_router.router)
app.include_router(deadhead.router)
app.include_router(replanning.router)
app.include_router(allarme.router)
app.include_router(weather.router)


