from fastapi import APIRouter, HTTPException
from app.services.simulatore_service import build_and_run_simulation, simula_piano
from app.core.operativo_client import get_json as operativo_get_json, OperativoDelegationError
import os
import glob
import json
from app.models.common import *

router = APIRouter(prefix="", tags=["Simulazione"])

@router.post(
    "/simulation/build_and_run",
    summary="Avvia simulazione navigazione",
    description="""
Costruisce e avvia una simulazione fisica completa di navigazione per uno o più vascelli.

### Simulatore Fisico
Modello di navigazione che considera:
- Dinamica del vascello (inerzia, resistenza)
- Condizioni meteo-marine
- Rotta pianificata dal percorso

### Input
```json
{
  "elementi": [
    {
      "assegnazione_id": "uuid-assegnazione",
      "lat_start": 40.68,
      "lon_start": 14.76
    }
  ],
  "sim_speed_factor": 1.0
}
```

### Parametri
- **elementi**: Lista di vascelli da simulare con coordinate opzionali
- **sim_speed_factor**: Fattore di accelerazione simulazione (se omesso usa valore da configurazione Kafka, altrimenti aggiorna anche la configurazione Kafka)

### Coordinate iniziali
- **Se fornite**: usa le coordinate specificate (override)
- **Se omesse**: recupera automaticamente dal porto di partenza

### Processo
1. Risoluzione coordinate di partenza
2. Recupero dati percorso e assegnazione
3. Costruzione configurazione simulatore
4. Invio al servizio simulatore esterno
5. Restituzione risultati simulazione

### Response
- **resolved_starts**: coordinate effettivamente utilizzate
- **simulation_response**: output del simulatore esterno

### Utilizzo tipico
- Validazione scenari pianificati
- Training operatori
- Analisi what-if
- Demo e visualizzazioni
    """,
    responses={
        200: {"description": "Simulazione avviata con successo"},
        404: {"description": "Assegnazione o percorso non trovato"},
        500: {"description": "Errore comunicazione con simulatore esterno"}
    }
)
def build_and_run(data: SimulationBuildInput):
    return build_and_run_simulation(data)


@router.post(
    "/simulation/simula_piano",
    response_model=SimulaPianoResponse,
    summary="Simula piano operativo anticipato",
    description="""
Esegue una simulazione anticipata di un piano operativo schedulato per una data futura,
avviando le simulazioni a partire dal momento della chiamata.

### Funzionalità
- Recupera tutte le assegnazioni **virtuali** (virtuale=True) del piano
- Filtra solo quelle in stato **PIANIFICATA**
- Le ordina per orario di partenza schedulato
- Calcola i delta temporali relativi rispetto alla prima partenza
- Scala i delta in base a `sim_speed_factor` (es. factor=2 dimezza i tempi)
- Schedula le simulazioni mantenendo i delta scalati, a partire da "adesso"

### Esempio d'uso
Se un piano ha 3 corse virtuali alle ore 08:00, 08:30 e 09:15,
e la chiamata viene fatta alle 14:00 con `sim_speed_factor=2`, le simulazioni verranno schedulate:
- Prima corsa: 14:00 + delay_start_seconds
- Seconda corsa: 14:15 + delay_start_seconds (15 min dopo, scalato da 30 min)
- Terza corsa: 14:37:30 + delay_start_seconds (37.5 min dopo, scalato da 1h15m)

### Input
```json
{
  "piano_id": "uuid-piano-operativo",
  "delay_start_seconds": 5,
  "sim_speed_factor": 1.0
}
```

### Parametri
- **piano_id**: UUID del piano operativo da simulare
- **delay_start_seconds**: ritardo iniziale in secondi prima della prima simulazione (default: 5)
- **sim_speed_factor**: fattore di accelerazione (se omesso usa valore da configurazione Kafka). I delta temporali tra le simulazioni vengono scalati. Aggiorna anche la configurazione Kafka quando fornito.

### Output
Restituisce il dettaglio di tutte le simulazioni schedulate con:
- Orari originali e nuovi orari di simulazione
- Delta temporali calcolati
- Job ID per il tracking
    """,
    responses={
        200: {"description": "Simulazioni schedulate con successo"},
        404: {"description": "Piano non trovato"},
        400: {"description": "Nessuna assegnazione virtuale trovata"}
    }
)
def simula_piano_endpoint(data: SimulaPianoInput):
    return simula_piano(data)


@router.get(
  "/simulation/schedulate",
  summary="Recupera simulazioni schedulate",
  description="""
Recupera i file JSON delle simulazioni schedulate salvati localmente.

### Filtro assegnazioni
Vengono restituiti **solo** i piani che hanno almeno un'assegnazione con stato:
- `PIANIFICATA`
- `IN_CORSO`

Se un piano è presente su file ma non ha assegnazioni in questi stati, viene escluso dalla risposta.

### Parametri
- **piano_id** (query, opzionale): filtra il recupero su uno specifico piano.

### Campi aggiunti in output
- **stato_assegnazione**: stato principale del piano (`IN_CORSO` se presente, altrimenti `PIANIFICATA`)
- **stati_assegnazione**: lista degli stati validi trovati per il piano
  """,
  responses={
    200: {
      "description": "Lista delle simulazioni schedulate filtrate per assegnazioni PIANIFICATA/IN_CORSO"
    },
    404: {
      "description": "Nessun file trovato o nessuna simulazione con assegnazioni PIANIFICATA/IN_CORSO"
    }
  }
)
def get_schedulate_simulations(piano_id: str = None):
  data_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data')
  pattern = f"simulazioni_schedulate_{piano_id}.json" if piano_id else "simulazioni_schedulate_*.json"
  files = glob.glob(os.path.join(data_dir, pattern))
  if not files:
    raise HTTPException(status_code=404, detail="Nessun file di simulazioni schedulate trovato")

  file_contents = []
  for file_path in files:
    with open(file_path, 'r', encoding='utf-8') as f:
      try:
        payload = json.load(f)
        if isinstance(payload, dict) and payload.get("piano_id"):
          file_contents.append(payload)
      except Exception as e:
        file_contents.append({"file": file_path, "error": str(e)})

  candidates = [item for item in file_contents if isinstance(item, dict) and item.get("piano_id")]
  if not candidates:
    raise HTTPException(status_code=404, detail="Nessuna simulazione valida trovata")

  results = []
  for item in candidates:
    pid = item["piano_id"]
    try:
      assegnazioni = operativo_get_json(f"/internal/assegnazione/by_piano/{pid}")
    except OperativoDelegationError as exc:
      raise HTTPException(status_code=503, detail="Operativo service unavailable") from exc

    stati_validi = sorted(
      {a.get("stato_esecuzione") for a in assegnazioni if a.get("stato_esecuzione") in {"PIANIFICATA", "IN_CORSO"}},
      key=lambda s: 0 if s == "IN_CORSO" else 1,
    )
    if not stati_validi:
      continue

    enriched = dict(item)
    enriched["stati_assegnazione"] = stati_validi
    enriched["stato_assegnazione"] = "IN_CORSO" if "IN_CORSO" in stati_validi else "PIANIFICATA"
    results.append(enriched)

  if not results:
    raise HTTPException(
      status_code=404,
      detail="Nessuna simulazione schedulata con assegnazioni in stato PIANIFICATA o IN_CORSO"
    )

  return results