from fastapi import APIRouter, HTTPException, Query
from typing import Dict, List, Optional
from app.services import assegnazione_service, pianificazione_service
from app.core.operativo_client import delegation_enabled as operativo_delegation_enabled, get_json as operativo_get_json, post_json as operativo_post_json, patch_json as operativo_patch_json, OperativoDelegationError
from app.core.percorsi_client import get_json as percorsi_get_json, PercorsiDelegationError
from app.core.anagrafica_client import get_json as anagrafica_get_json, AnagraficaDelegationError
from app.core.config import ENABLE_OPERATIVO_FALLBACK
from app.models.common import (
    CheckValiditaInput, CheckValiditaResponse,
    CreaAssegnazioniBulkInput, CreaAssegnazioniBulkResponse
)
from app.models.assegnazione import *

router = APIRouter(prefix="", tags=["Assegnazione"])
ALLOWED_INCLUDES_ASSEGNAZIONE = {"piano", "percorso", "corsa", "vascello"}


def _handle_operativo_fallback(exc: Exception) -> None:
    if not ENABLE_OPERATIVO_FALLBACK:
        raise HTTPException(status_code=503, detail="Operativo service unavailable") from exc


@router.get(
    "/assegnazione/{assegnazione_id}",
    response_model=AssegnazioneAPI,
    response_model_exclude_none=True,
    summary="Dettaglio assegnazione",
    description="""
Restituisce il dettaglio di una singola assegnazione.

Per impostazione predefinita l'endpoint restituisce solo i dati dell'assegnazione.

È possibile espandere dinamicamente le relazioni tramite il parametro query `include`.

Entità espandibili:
- `piano`: dettagli del piano operativo associato
- `percorso`: dettagli del percorso associato
- `corsa`: dettagli della corsa associata al percorso
- `vascello`: dettagli del vascello associato al percorso
    """,
    responses={
        200: {"description": "Dettaglio assegnazione restituito"},
        404: {"description": "Assegnazione non trovata"},
        400: {"description": "Parametro include non valido"},
    }
)
def get_assegnazione(
    assegnazione_id: str,
    include: Optional[str] = Query(None),
):
    includes = set(s.strip() for s in include.split(",") if s.strip()) if include else set()
    invalid = includes - ALLOWED_INCLUDES_ASSEGNAZIONE
    if invalid:
        raise HTTPException(
            400,
            f"include non valido: {sorted(invalid)}. Ammessi: {sorted(ALLOWED_INCLUDES_ASSEGNAZIONE)}"
        )

    if operativo_delegation_enabled():
        try:
            base = operativo_get_json(f"/internal/assegnazione/{assegnazione_id}")
            response = dict(base)

            piano_id = response.get("piano_id")
            percorso_id = response.get("percorso_id")
            id_corsa = response.get("id_corsa")
            vascello_id = response.get("vascello_id")

            if "piano" in includes and piano_id:
                response["piano"] = operativo_get_json(f"/internal/piano/{piano_id}")

            percorso_obj = None
            if includes & {"percorso", "corsa", "vascello"} and percorso_id:
                percorso_obj = percorsi_get_json(f"/internal/percorso/{percorso_id}")
                if "percorso" in includes:
                    response["percorso"] = percorso_obj
                if not id_corsa and isinstance(percorso_obj, dict):
                    id_corsa = percorso_obj.get("corsa_id")
                if not vascello_id and isinstance(percorso_obj, dict):
                    vascello_id = percorso_obj.get("vascello_id")

            if "corsa" in includes and id_corsa:
                response["corsa"] = operativo_get_json(f"/internal/corsa/id/{id_corsa}")

            if "vascello" in includes and vascello_id:
                response["vascello"] = anagrafica_get_json(f"/internal/vascello/{vascello_id}")

            return response
        except (OperativoDelegationError, PercorsiDelegationError, AnagraficaDelegationError) as exc:
            _handle_operativo_fallback(exc)

    try:
        return operativo_get_json(f"/internal/assegnazione/{assegnazione_id}")
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Operativo service unavailable") from exc


@router.post(
    "/assegnazione/crea",
    response_model=AssegnazioneResponse,
    summary="Crea assegnazione operativa",
    description="""
Crea una nuova assegnazione operativa tra un vascello e un percorso.

### Assegnazione
Collega un **percorso** (rotta ottimizzata) a un **piano operativo**, permettendo il tracking dell'esecuzione.

### Input
```json
{
  "piano_id": "uuid-piano",
  "percorso_id": "uuid-percorso",
  "stato_esecuzione": "PIANIFICATA",
  "virtuale": false
}
```

### Stati iniziali consigliati
- `PIANIFICATA`: assegnazione standard per piano operativo
- `IN_CORSO`: se il vascello sta già eseguendo il percorso

### Flag virtuale
- `true`: assegnazione di test/simulazione (non influenza operatività reale)
- `false`: assegnazione operativa reale

### Logica
1. Recupera il vascello_id dal percorso associato
2. Verifica univocità assegnazione (no duplicati percorso)
3. Crea record con timestamp

### Vincolo operativo:
- Un vascello può avere **una sola assegnazione con stato = IN_CORSO**. Il vincolo è applicato a livello database (trigger) e può causare errore 409.

    """,
    responses={
        200: {"description": "Assegnazione creata con successo"},
        404: {"description": "Percorso o piano non trovato"},
        409: {"description": "Assegnazione già esistente per questo percorso"}
    }
)
def crea_assegnazione_endpoint(data: AssegnazioneCreateInput):
    if operativo_delegation_enabled():
        try:
            return operativo_post_json("/internal/assegnazione/crea", {
                "piano_id": data.piano_id,
                "percorso_id": data.percorso_id,
                "stato_esecuzione": data.stato_esecuzione.value,
                "virtuale": data.virtuale,
            })
        except OperativoDelegationError as exc:
            _handle_operativo_fallback(exc)

    return assegnazione_service.crea_assegnazione(data)


@router.patch(
    "/assegnazione/{assegnazione_id}/stato",
    response_model=AssegnazioneResponse,
    summary="Aggiorna stato assegnazione",
    description="""
Aggiorna lo stato operativo di un'assegnazione esistente.

### Ciclo di vita assegnazione

```
PIANIFICATA → IN_CORSO → COMPLETATA
     ↓              ↓
     └─────────────┘ → CANCELLATA
```

### Stati
| Stato | Descrizione |
|-------|-------------|
| `PIANIFICATA` | Assegnazione creata, in attesa di esecuzione |
| `IN_CORSO` | Vascello sta eseguendo il percorso |
| `COMPLETATA` | Percorso terminato con successo |
| `CANCELLATA` | Assegnazione annullata |

### Path Parameter
- **assegnazione_id**: UUID dell'assegnazione

### Body
```json
{"stato_esecuzione": "IN_CORSO"}
```

### Utilizzo tipico
- Avvio corsa: `PIANIFICATA` → `IN_CORSO`
- Fine corsa: `IN_CORSO` → `COMPLETATA`
- Annullamento: `*` → `CANCELLATA`


### Vincolo operativo:
- Un vascello può avere **una sola assegnazione con stato = IN_CORSO**. Il vincolo è applicato a livello database (trigger) e può causare errore 409.

    """,
    responses={
        200: {"description": "Stato aggiornato con successo"},
        404: {"description": "Assegnazione non trovata"}
    }
)
def aggiorna_stato_assegnazione(assegnazione_id: str, data: AssegnazioneUpdateStatoInput):
    if operativo_delegation_enabled():
        try:
            return operativo_patch_json(f"/internal/assegnazione/{assegnazione_id}/stato", {
                "stato_esecuzione": data.stato_esecuzione.value,
            })
        except OperativoDelegationError as exc:
            _handle_operativo_fallback(exc)

    return assegnazione_service.aggiorna_stato_assegnazione(assegnazione_id, data)


@router.get(
    "/assegnazione/by_piano/{piano_id}",
    response_model=List[AssegnazioneResponse],
    summary="Lista assegnazioni per piano",
    description="""
Restituisce tutte le assegnazioni associate a un piano operativo.

### Path Parameter
- **piano_id**: UUID del piano operativo

### Ordinamento
Risultati ordinati per data di creazione (prima le più vecchie).

### Response
Lista di `AssegnazioneResponse` con:
- ID assegnazione
- Riferimenti a vascello, percorso, corsa
- Stato esecuzione corrente
- Flag virtuale

### Utilizzo tipico
- Visualizzazione piano operativo completo
- Monitoring esecuzione giornata
- Export assegnazioni
    """,
    responses={
        200: {"description": "Lista assegnazioni recuperata (vuota se nessuna assegnazione)"}
    }
)
def lista_assegnazioni_by_piano_endpoint(piano_id: str):
    if operativo_delegation_enabled():
        try:
            return operativo_get_json(f"/internal/assegnazione/by_piano/{piano_id}", timeout=60.0)
        except OperativoDelegationError as exc:
            _handle_operativo_fallback(exc)

    return assegnazione_service.lista_assegnazioni_by_piano(piano_id)


@router.post(
    "/assegnazione/check_validita",
    response_model=CheckValiditaResponse,
    summary="Verifica sequenzialità percorsi",
    description="""
Verifica se due percorsi possono essere eseguiti **in sequenza** dallo stesso vascello.

### Vincolo temporale
Controlla che:
```
orario_arrivo_max(percorso_1) < orario_partenza(percorso_2)
```

### Input
```json
{
  "percorso_1_id": "uuid-percorso-A",
  "percorso_2_id": "uuid-percorso-B"
}
```

### Logica
1. Recupera i dati di entrambi i percorsi
2. **Ordina automaticamente** per orario partenza
3. Verifica il gap temporale
4. Considera eventuale riposizionamento tra porti

### Response
```json
{
  "valido": true,
  "percorso_1": {"...": "dettagli primo per orario"},
  "percorso_2": {"...": "dettagli secondo per orario"},
  "messaggio": "Sequenza valida: 45 min di margine"
}
```

### Utilizzo tipico
- Validazione manuale assegnazioni
- Pre-check prima di creare sequenze
- Debug pianificazione
    """,
    responses={
        200: {"description": "Validità verificata"},
        404: {"description": "Uno o entrambi i percorsi non trovati"}
    }
)
def check_validita_percorsi_endpoint(data: CheckValiditaInput):
    return pianificazione_service.check_validita_percorsi(data.percorso_1_id, data.percorso_2_id)


@router.post(
    "/assegnazione/bulk",
    response_model=CreaAssegnazioniBulkResponse,
    summary="Crea assegnazioni bulk",
    description="""
Crea multiple assegnazioni per un piano operativo in un'unica operazione.

### Operazione bulk
Permette di creare più assegnazioni contemporaneamente, associando percorsi a un piano operativo.

### Flag virtuale
- `virtuale=true`: assegnazione di simulazione/what-if
- `virtuale=false`: assegnazione operativa reale

### Input
```json
{
  "piano_id": "uuid-piano-operativo",
  "percorsi": [
    {"percorso_id": "uuid-percorso-1", "virtuale": false},
    {"percorso_id": "uuid-percorso-2", "virtuale": true}
  ]
}
```

### Logica
1. Per ogni percorso nella lista:
   - Crea un'assegnazione con stato `PIANIFICATA`
2. Commit transazionale di tutte le assegnazioni

### Response
```json
{
  "piano_id": "uuid-piano",
  "assegnazioni_create": 2,
  "risultati": [
    {
      "assegnazione_id": "uuid-assegnazione-1",
      "percorso_id": "uuid-percorso-1",
      "virtuale": false
    },
    {
      "assegnazione_id": "uuid-assegnazione-2",
      "percorso_id": "uuid-percorso-2",
      "virtuale": true
    }
  ]
}
```

### Utilizzo tipico
- Creazione massiva assegnazioni da interfaccia piano operativo
- Setup scenari what-if
- Batch import assegnazioni
    """,
    responses={
        200: {"description": "Assegnazioni create con successo"},
        404: {"description": "Piano o percorso non trovato"},
        409: {"description": "Una o più assegnazioni già esistenti"}
    }
)
def crea_assegnazioni_bulk_endpoint(data: CreaAssegnazioniBulkInput):
    if operativo_delegation_enabled():
        try:
            return operativo_post_json("/internal/assegnazione/bulk", {
                "piano_id": data.piano_id,
                "percorsi": [
                    {"percorso_id": item.percorso_id, "virtuale": item.virtuale}
                    for item in data.percorsi
                ],
            }, timeout=60.0)
        except OperativoDelegationError as exc:
            _handle_operativo_fallback(exc)

    return assegnazione_service.crea_assegnazioni_bulk(data)


@router.post(
    "/assegnazione/in_corso2cancellata",
    summary="Cancella assegnazioni virtuali in corso",
    description="""
Modifica tutte le assegnazioni che hanno:
- `virtuale = true`
- `stato = IN_CORSO`
impostando il loro stato a `CANCELLATA`.

Utile per resettare scenari di simulazione o test rimasti appesi.
    """
)
def cancella_assegnazioni_virtuali_in_corso():
    if operativo_delegation_enabled():
        try:
            return operativo_post_json("/internal/assegnazione/in_corso2cancellata", {})
        except OperativoDelegationError as exc:
            _handle_operativo_fallback(exc)

    return assegnazione_service.cancella_assegnazioni_virtuali_in_corso()
