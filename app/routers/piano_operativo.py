from fastapi import APIRouter, Query, HTTPException
from app.services import pianificazione_service
from app.models.piano import PianoCreateInput, PianoResponse, PianoUpdateInput, PianoDeleteInput, PianoValidaInput, PianoValidaResponse
from app.core.operativo_client import delegation_enabled as operativo_delegation_enabled, get_json as operativo_get_json, post_json as operativo_post_json, OperativoDelegationError
from app.core.config import ENABLE_OPERATIVO_FALLBACK
from typing import List, Optional
from datetime import date

router = APIRouter(prefix="", tags=["Piano Operativo"])


def _handle_operativo_fallback(exc: Exception) -> None:
    if not ENABLE_OPERATIVO_FALLBACK:
        raise HTTPException(status_code=503, detail="Operativo service unavailable") from exc


@router.post(
    "/piano/crea",
    response_model=PianoResponse,
    summary="Crea piano operativo",
    description="""
Crea un nuovo piano operativo per la gestione della flotta.

### Piano Operativo
Contenitore per le assegnazioni vascello-percorso di una giornata operativa.

### Stati del ciclo di vita
| Stato | Descrizione |
|-------|-------------|
| `CREATO` | Piano appena creato, non ancora elaborato |
| `IN_OTTIMIZZAZIONE` | Elaborazione in corso |
| `PRONTO` | Ottimizzazione completata, pronto per attivazione |
| `ATTIVO` | Piano correntemente in esecuzione |
| `ARCHIVIATO` | Piano storicizzato |
| `ERRORE` | Errore durante elaborazione |

### Input
```json
{
  "data_riferimento": "2025-01-30T00:00:00",
  "stato": "CREATO",
  "kpi_profitto_stimato": 15000.50,
  "kpi_robustezza": 87.5,
  "versione": 1
}
```

### KPI opzionali
- **kpi_profitto_stimato**: profitto atteso in EUR
- **kpi_robustezza**: indice 0-100 di resilienza a variazioni
    """,
    responses={
        200: {"description": "Piano operativo creato con successo"},
        409: {"description": "Piano già esistente per la data specificata"}
    }
)
def crea_piano_endpoint(data: PianoCreateInput):
    if operativo_delegation_enabled():
        try:
            return operativo_post_json("/internal/piano/crea", {
                "data_riferimento": data.data_riferimento.isoformat(),
                "stato": data.stato,
                "kpi_profitto_stimato": data.kpi_profitto_stimato,
                "kpi_robustezza": data.kpi_robustezza,
                "versione": data.versione,
            })
        except OperativoDelegationError as exc:
            _handle_operativo_fallback(exc)

    return pianificazione_service.crea_piano(data)


@router.post(
    "/piano/modifica",
    response_model=PianoResponse,
    summary="Modifica piano operativo",
    description="""
Aggiorna un piano operativo esistente.

### Campi modificabili
- **data_riferimento**: nuova data di riferimento
- **stato**: nuovo stato del piano (vedi ciclo di vita)
- **kpi_profitto_stimato**: aggiornamento KPI profitto
- **kpi_robustezza**: aggiornamento KPI robustezza
- **versione**: incremento manuale versione

### Note
- Richiede `id` del piano + almeno un campo da aggiornare
- Le assegnazioni associate non vengono modificate
- Usare transizione stati coerente con il ciclo di vita
    """,
    responses={
        200: {"description": "Piano operativo aggiornato"},
        400: {"description": "Nessun campo da aggiornare specificato"},
        404: {"description": "Piano non trovato"},
        409: {"description": "Conflitto: transizione stato non valida"}
    }
)
def modifica_piano_endpoint(data: PianoUpdateInput):
    if operativo_delegation_enabled():
        try:
            return operativo_post_json("/internal/piano/modifica", {
                "id": data.id,
                "data_riferimento": data.data_riferimento.isoformat() if data.data_riferimento else None,
                "stato": data.stato,
                "kpi_profitto_stimato": data.kpi_profitto_stimato,
                "kpi_robustezza": data.kpi_robustezza,
                "versione": data.versione,
            })
        except OperativoDelegationError as exc:
            _handle_operativo_fallback(exc)

    return pianificazione_service.modifica_piano(data)


@router.post(
    "/piano/elimina",
    summary="Elimina piano operativo",
    description="""
Elimina definitivamente un piano operativo dal sistema.

### Attenzione
- L'eliminazione è **irreversibile**
- Le assegnazioni associate verranno eliminate a cascata

### Prerequisiti
- Piano non deve essere in stato `ATTIVO`
- Nessuna assegnazione con stato `IN_CORSO`

### Alternativa consigliata
Usare stato `ARCHIVIATO` per mantenere lo storico.
    """,
    responses={
        200: {"description": "Piano operativo eliminato"},
        404: {"description": "Piano non trovato"},
        409: {"description": "Impossibile eliminare: piano attivo o assegnazioni in corso"}
    }
)
def elimina_piano_endpoint(data: PianoDeleteInput):
    if operativo_delegation_enabled():
        try:
            return operativo_post_json("/internal/piano/elimina", {"id": data.id})
        except OperativoDelegationError as exc:
            _handle_operativo_fallback(exc)

    return pianificazione_service.elimina_piano(data)


@router.get(
    "/piano/lista",
    response_model=List[PianoResponse],
    summary="Lista piani operativi",
    description="""
Restituisce l'elenco dei piani operativi registrati nel sistema.

### Ordinamento
Risultati ordinati per `data_riferimento` decrescente (più recenti prima).

### Query Parameters (opzionali)
- **data_riferimento**: filtra per data specifica (formato YYYY-MM-DD)

### Esempi
- `/piano/lista` → tutti i piani
- `/piano/lista?data_riferimento=2025-01-30` → solo piani del 30/01/2025

### Utilizzo tipico
- Selezione piano per visualizzazione/modifica
- Storico pianificazioni
- Dashboard piani operativi
    """,
    responses={
        200: {"description": "Lista piani restituita con successo"}
    }
)
def lista_piano_endpoint(data_riferimento: Optional[date] = Query(None, description="Filtro per data_riferimento (YYYY-MM-DD)")):
    if operativo_delegation_enabled():
        try:
            if data_riferimento is None:
                return operativo_get_json("/internal/piano/lista", timeout=60.0)
            return operativo_get_json(f"/internal/piano/lista?data_riferimento={data_riferimento.isoformat()}", timeout=60.0)
        except OperativoDelegationError as exc:
            _handle_operativo_fallback(exc)

    return pianificazione_service.lista_piani(data_riferimento)


@router.post(
    "/piano/valida",
    response_model=PianoValidaResponse,
    summary="Valida piano operativo",
    description="""
Valida un piano operativo verificando le condizioni necessarie per passare allo stato VALIDATO.

### Verifiche eseguite
1. **Unicità stato VALIDATO**: verifica che non esistano altri piani con stato `VALIDATO` per lo stesso giorno
2. **Copertura corse**: verifica che tutte le corse del giorno abbiano almeno un'assegnazione con stato `PIANIFICATA`

### Azioni in caso di successo
- Aggiorna lo stato del piano a `VALIDATO`
- Schedula le simulazioni per tutte le assegnazioni **virtuali** (`virtuale=true`) del piano

### Input
```json
{
  "piano_id": "uuid-piano-operativo"
}
```

### Response
- **validato**: `true` se il piano è stato validato con successo
- **stato**: nuovo stato del piano (`VALIDATO` se validato)
- **corse_giorno**: numero totale di corse nel giorno del piano
- **assegnazioni_pianificate**: numero di corse con assegnazione PIANIFICATA
- **simulazioni_schedulate**: numero di simulazioni schedulate per assegnazioni virtuali
- **dettaglio_simulazioni**: lista con dettaglio di ogni simulazione schedulata

### Utilizzo tipico
- Finalizzazione pianificazione giornaliera
- Attivazione simulazioni anticipate
- Passaggio da fase di pianificazione a operatività
    """,
    responses={
        200: {"description": "Risultato validazione piano"},
        404: {"description": "Piano non trovato"},
        500: {"description": "Errore durante la validazione"}
    }
)
def valida_piano_endpoint(data: PianoValidaInput):
    return pianificazione_service.valida_piano(data.piano_id)


@router.get(
    "/piano/{piano_id}",
    response_model=PianoResponse,
    summary="Recupera piano operativo per ID",
    description="""
Restituisce i dettagli di un piano operativo specificato dal suo ID.
Non include le assegnazioni dei vascelli.
    """,
    responses={
        200: {"description": "Dettagli del piano operativo"},
        404: {"description": "Piano operativo non trovato"}
    }
)
def get_piano_by_id_endpoint(piano_id: str):
    if operativo_delegation_enabled():
        try:
            return operativo_get_json(f"/internal/piano/{piano_id}")
        except OperativoDelegationError as exc:
            _handle_operativo_fallback(exc)

    piano = pianificazione_service.get_piano_by_id(piano_id)
    if not piano:
        raise HTTPException(status_code=404, detail="Piano operativo non trovato")
    return piano
