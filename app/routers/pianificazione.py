from fastapi import APIRouter
from typing import Dict
from app.services import ottimizzatore_service, pianificazione_service, scheduler_service
from app.models.common import (
    OttimizzatoreBatchInput, OttimizzatoreResponse, 
    RiposizionamentoBatchInput, RiposizionamentoResponse,
    AssignmentRequest, RouteAssignment,
    PercorsiCompatibiliInput, PercorsiCompatibiliResponse,
    SchedulingInput, SchedulingResponse, SchedulingByDayInput
)

router = APIRouter(prefix="", tags=["Pianificazione"])

@router.post(
    "/weather_routing/carico",
    response_model=OttimizzatoreResponse,
    summary="Weather Routing con carico (batch)",
    description="""
Calcola i percorsi ottimali considerando condizioni meteo-marine per una lista di coppie vascello-corsa.

### Ottimizzazione Multi-Obiettivo
L'algoritmo minimizza simultaneamente:
- **Tempo di percorrenza** (rispettando vincolo arrivo)
- **Consumo carburante**
- **Discomfort** (esposizione a onde/vento)

### Input Batch
```json
{
  "items": [
    {
      "corsa_id": "uuid-corsa",
      "vascello_id": "uuid-vascello",
      "eps_time": 5,
      "fake_data": true
    }
  ]
}
```

### Parametri per elemento
| Campo | Descrizione | Default |
|-------|-------------|--------|
| eps_time | Tolleranza temporale (min) | 5 |
| fake_data | Usa meteo simulato | true |
| ve_min | Velocità minima (kn) | 0.1 |
| tolerance | Tolleranza algoritmo | 1 |
| scenario_id | ID scenario meteo what-if (opzionale) | null |

### Scenari What-If
Il campo opzionale `scenario_id` permette di ottimizzare i percorsi usando dati meteo
alterati secondo uno scenario salvato nel weather_service. Ad esempio, simulare una
tempesta o mare calmo per verificare come cambiano i percorsi ottimali.
Usare `GET /weather/scenarios` per ottenere gli scenari disponibili.

### Pipeline
1. Recupero dati corsa e vascello dal DB
2. Query dati meteo (reali o simulati)
3. Ottimizzazione Pareto multi-obiettivo
4. **Inserimento automatico** percorsi nel DB
5. Restituzione UUID percorsi creati

### Note
- Chiamata batch al servizio esterno (efficienza)
- Ogni corsa può avere multipli percorsi Pareto-ottimali
    """,
    responses={
        200: {"description": "Ottimizzazione completata - percorsi inseriti"},
        404: {"description": "Corsa o vascello non trovato"},
        500: {"description": "Errore servizio ottimizzatore esterno"}
    }
)
def ottimizzatore_endpoint(data: OttimizzatoreBatchInput):
    return ottimizzatore_service.ottimizzatore(data)


@router.post(
    "/weather_routing/vuoto",
    response_model=RiposizionamentoResponse,
    summary="Stima riposizionamento a vuoto (batch)",
    description="""
Stima tempo e consumo per il trasferimento a vuoto di vascelli tra porti.

### Riposizionamento
Calcola i costi di spostamento senza carico passeggeri, utile per:
- Pianificazione turni successivi
- Ottimizzazione assegnazioni flotta
- Calcolo costi operativi

### Input Batch
```json
{
  "items": [
    {
      "porto_partenza_id": "uuid-porto-A",
      "porto_destinazione_id": "uuid-porto-B",
      "datetime_partenza": "2025-01-30T14:00:00",
      "vascello_id": "uuid-vascello"
    }
  ]
}
```

### Parametri per elemento
| Campo | Descrizione | Default |
|-------|-------------|--------|
| porto_partenza_id | UUID porto di partenza | obbligatorio |
| porto_destinazione_id | UUID porto di destinazione | obbligatorio |
| datetime_partenza | Data/ora partenza (ISO 8601) | obbligatorio |
| vascello_id | UUID del vascello | obbligatorio |
| fake_data | Usa meteo simulato | true |
| ve_min | Velocità minima (kn) | 0.1 |
| tolerance | Tolleranza algoritmo | 1 |
| graph_cache_ttl_minutes | TTL cache snap temporale (min) | null |
| scenario_id | ID scenario meteo what-if (opzionale) | null |

### Scenari What-If
Il campo opzionale `scenario_id` permette di stimare i riposizionamenti usando dati
meteo alterati secondo uno scenario salvato nel weather_service. Ad esempio, simulare
una tempesta per verificare come cambiano tempi e consumi di riposizionamento.
Usare `GET /weather/scenarios` per ottenere gli scenari disponibili.

### Output per elemento
- **tempo_riposizionamento**: tempo stimato in minuti
- **consumo_riposizionamento**: carburante stimato in litri

### Note
- Non crea percorsi nel DB (solo stima)
- Considera condizioni meteo alla data/ora specificata
- Utile per gap analysis tra corse consecutive
    """,
    responses={
        200: {"description": "Stime calcolate con successo"},
        404: {"description": "Porto o vascello non trovato"},
        500: {"description": "Errore servizio ottimizzatore"}
    }
)
def stima_riposizionamento_endpoint(data: RiposizionamentoBatchInput):
    return ottimizzatore_service.stima_riposizionamento(data)


@router.post(
    "/assegnazione/pianifica",
    response_model=Dict[str, RouteAssignment],
    summary="Pianificazione ottimale flotte",
    description="""
Calcola la pianificazione completa delle flotte su una finestra temporale.

### Pipeline completa

```
Forecast ML → Weather Routing → KPI Calculation → Ranking
```

### Input
```json
{
  "start": "2025-01-30T06:00:00",
  "end": "2025-01-30T22:00:00",
  "vessels": ["uuid-v1", "uuid-v2", "uuid-v3"],
  "eps_time": 5,
  "fake_data": true,
  "scenario_id": null
}
```

### Parametri
| Campo | Descrizione | Default |
|-------|-------------|--------|
| start | Inizio finestra temporale (ISO 8601) | obbligatorio |
| end | Fine finestra temporale (ISO 8601) | obbligatorio |
| vessels | Lista UUID vascelli disponibili | obbligatorio |
| eps_time | Tolleranza temporale (min) | obbligatorio |
| fake_data | Usa meteo simulato | obbligatorio |
| scenario_id | ID scenario meteo what-if (opzionale) | null |

### Scenari What-If
Il campo opzionale `scenario_id` viene propagato a tutte le ottimizzazioni weather routing
della pianificazione. Permette di generare piani operativi basati su condizioni meteo
alterate (es. tempesta, mare calmo) per analisi what-if e confronto tra scenari.
Usare `GET /weather/scenarios` per ottenere gli scenari disponibili.

### Elaborazione
1. **Forecast**: previsione domanda passeggeri per ogni corsa
2. **Weather Routing**: calcolo percorsi ottimali per ogni coppia vascello-corsa
3. **KPI**: calcolo metriche (consumo, comfort, tempo, capacità)
4. **Ranking**: ordinamento vascelli per ogni corsa per qualità assegnazione

### Output
Mappa `{corsa_id: RouteAssignment}` con:
- Dettagli corsa (nome, porti, orari)
- Previsione passeggeri [stimati, ci_min, ci_max]
- **KPI_assegnazione**: mappa `{vascello_id: KPI}` ordinata per ranking

### Utilizzo tipico
- Generazione piani operativi giornalieri
- Decisioni assegnazione flotta
- Analisi what-if con diversi set vascelli e scenari meteo
    """,
    responses={
        200: {"description": "Pianificazione calcolata - ranking KPI per ogni corsa"},
        400: {"description": "Finestra temporale non valida o lista vascelli vuota"},
        500: {"description": "Errore durante elaborazione pipeline"}
    }
)
def compute_assignments_endpoint(payload: AssignmentRequest):
    return pianificazione_service.compute_assignments(payload)


@router.post(
    "/pianificazione/compatibili",
    response_model=PercorsiCompatibiliResponse,
    summary="Percorsi compatibili per una corsa",
    description="""
Restituisce i percorsi di una corsa che sono compatibili con i percorsi già assegnati dall'utente.

### Caso d'uso

L'utente sta costruendo un piano operativo e ha già assegnato alcuni percorsi a dei vascelli.
Quando seleziona una nuova corsa, questo endpoint restituisce quali percorsi di quella corsa
possono essere assegnati senza conflitti con le assegnazioni esistenti.

### Logica di Compatibilità

Un percorso della corsa è **compatibile** se:
- Il suo vascello è **diverso** da tutti i vascelli dei percorsi già assegnati, OPPURE
- Se usa lo **stesso vascello**, non c'è sovrapposizione temporale (il percorso già assegnato termina prima che questo inizi, o viceversa)

### Input
```json
{
  "corsa_id": "uuid-corsa-da-assegnare",
  "percorsi_id": ["uuid-percorso-già-assegnato-1", "uuid-percorso-già-assegnato-2"]
}
```

### Output
```json
{
  "corsa_id": "uuid-corsa",
  "percorsi_compatibili": [
    {"percorso_id": "uuid", "vascello_id": "uuid", "vascello_nome": "Nave1"}
  ]
}
```

### Note
- Se `percorsi_id` è vuoto, restituisce tutti i percorsi della corsa
- Filtra solo i percorsi compatibili con **tutti** i percorsi già assegnati
    """,
    responses={
        200: {"description": "Lista percorsi compatibili"},
        404: {"description": "Corsa non trovata o senza percorsi"}
    }
)
def get_percorsi_compatibili_endpoint(payload: PercorsiCompatibiliInput):
    return pianificazione_service.get_percorsi_compatibili(payload.corsa_id, payload.percorsi_id)


@router.post(
    "/scheduling/ottimizza",
    response_model=SchedulingResponse,
    summary="Ottimizzazione scheduling flotta (Pareto multi-obiettivo)",
    description="""
Calcola le soluzioni Pareto-ottimali per lo scheduling della flotta.

### Ottimizzazione Multi-Obiettivo

L'algoritmo NAMOA* minimizza simultaneamente:
- **Costo** (consumo carburante totale)
- **Rischio** (probabilità di sovraccarico passeggeri)

### Input
```json
{
  "routes": [
    {
      "route_id": "uuid-percorso",
      "corsa_id": "uuid-corsa",
      "corsa_name": "SAL-AMA-20260205-0800",
      "vessel_id": "uuid-vascello",
      "vessel_name": "Nave A",
      "capacity": 100,
      "origin": "porto-salerno-id",
      "destination": "porto-amalfi-id",
      "start_dt": "2026-02-05T08:00:00",
      "end_dt": "2026-02-05T08:45:00",
      "consumo": 15.5,
      "comfort": 85.0,
      "pax_min": 50,
      "pax_max": 80
    }
  ],
  "vessels": [
    {"vessel_id": "uuid-vascello", "name": "Nave A", "capacity": 100}
  ],
  "max_solutions": 5,
  "include_details": true
}
```

### Output
Restituisce una lista di soluzioni Pareto-ottimali, ciascuna con:
- **cost**: costo totale (consumo)
- **risk**: rischio totale (probabilità sovraccarico)
- **plan**: piano di assegnazione `{vessel_id: [lista percorsi]}`
- **activities**: lista dettagliata con TRIP, REPOSITION, WAIT (se include_details=true)

### Nota su Scenari What-If
Questo endpoint lavora con percorsi **già calcolati**. Per ottenere scheduling basato
su scenari meteo alterati, calcolare prima i percorsi con `scenario_id` tramite
`POST /weather_routing/carico`, poi passare i percorsi risultanti a questo endpoint.

### Note
- Le soluzioni sono ordinate per costo crescente
- Ogni soluzione è Pareto-ottimale (non dominata)
- I riposizionamenti a vuoto sono calcolati automaticamente
    """,
    responses={
        200: {"description": "Soluzioni Pareto-ottimali calcolate"},
        400: {"description": "Input non valido"},
        503: {"description": "Scheduler service non disponibile"},
        504: {"description": "Scheduler service timeout"}
    }
)
def scheduling_ottimizza_endpoint(data: SchedulingInput):
    return scheduler_service.schedule_routes(data)


@router.post(
    "/scheduling/giorno",
    response_model=SchedulingResponse,
    summary="Ottimizzazione scheduling per giorno",
    description="""
Calcola lo scheduling ottimale per tutte le corse di un giorno specifico.

### Pipeline Automatica

1. **Recupero percorsi**: ottiene tutti i percorsi (già calcolati) per il giorno
2. **Recupero vascelli**: ottiene tutti i vascelli disponibili
3. **Ottimizzazione**: esegue NAMOA* per trovare soluzioni Pareto-ottimali
4. **Dettagli**: include riposizionamenti e tempi di attesa

### Input
```json
{
  "giorno": "2026-02-05",
  "solo_future": true,
  "max_solutions": 5,
  "include_details": true
}
```

### Prerequisiti
- I percorsi per le corse del giorno devono essere già stati calcolati
  (tramite `/weather_routing/carico`)
- Le previsioni passeggeri devono essere state calcolate
  (tramite `/corsa/{id}/prevedi`)

### Nota su Scenari What-If
Questo endpoint lavora con percorsi **già calcolati**. Per ottenere scheduling basato
su scenari meteo alterati, calcolare prima i percorsi con `scenario_id` tramite
`POST /weather_routing/carico`, poi usare questo endpoint sul giorno risultante.

### Output
Lista soluzioni Pareto-ottimali con:
- Piano assegnazioni per vascello
- Attività dettagliate (viaggi, riposizionamenti, attese)
- Metriche di costo e rischio

### Note
- Se `solo_future=true`, considera solo corse con partenza futura
- Restituisce lista vuota se non ci sono percorsi per il giorno
    """,
    responses={
        200: {"description": "Scheduling calcolato per il giorno"},
        400: {"description": "Formato giorno non valido"},
        503: {"description": "Scheduler service non disponibile"}
    }
)
def scheduling_giorno_endpoint(data: SchedulingByDayInput):
    return scheduler_service.schedule_by_day(data)

