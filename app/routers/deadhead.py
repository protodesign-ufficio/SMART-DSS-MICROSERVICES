from fastapi import APIRouter, Query, HTTPException
from typing import List, Optional
from app.services import deadhead_service
from app.core.operativo_client import delegation_enabled as operativo_delegation_enabled, get_json as operativo_get_json, post_json as operativo_post_json, OperativoDelegationError
from app.core.config import ENABLE_OPERATIVO_FALLBACK
from app.models.deadhead import (
    DeadheadCreateInput, DeadheadUpdateInput, DeadheadDeleteInput, DeadheadResponse
)

router = APIRouter(prefix="", tags=["Deadhead Trips"])


def _handle_operativo_fallback(exc: Exception) -> None:
    if not ENABLE_OPERATIVO_FALLBACK:
        raise HTTPException(status_code=503, detail="Operativo service unavailable") from exc


@router.post(
    "/deadhead/crea",
    response_model=DeadheadResponse,
    summary="Crea deadhead trip",
    description="""
Crea un nuovo deadhead trip (viaggio a vuoto / riposizionamento) nel sistema.

### Deadhead Trip
Rappresenta uno spostamento non produttivo di un vascello tra due porti,
senza trasporto passeggeri. Tipicamente utilizzato per:
- Riposizionamento flotta tra corse operative
- Periodi di attesa (idle) in porto
- Trasferimenti a vuoto per manutenzione

### Input
```json
{
  "orario_partenza_schedulato": "2025-01-30T08:00:00",
  "porto_partenza_id": "uuid-porto-partenza",
  "porto_arrivo_id": "uuid-porto-arrivo",
  "idle": false,
  "non_productive_time_min": 30.0,
  "consumo": 150.0,
  "vascello_id": "uuid-vascello",
  "piano_id": "uuid-piano"
}
```

### Campi principali
- **idle**: `true` se il vascello è fermo in porto (nessun movimento)
- **non_productive_time_min**: durata del tempo non produttivo in minuti
- **consumo**: carburante consumato per il riposizionamento
    """,
    responses={
        200: {"description": "Deadhead trip creato con successo"},
        400: {"description": "Porto, vascello o piano non trovato"}
    }
)
def crea_deadhead_endpoint(data: DeadheadCreateInput):
    if operativo_delegation_enabled():
        try:
            return operativo_post_json("/internal/deadhead/crea", {
                "orario_partenza_schedulato": data.orario_partenza_schedulato.isoformat(),
                "porto_partenza_id": data.porto_partenza_id,
                "porto_arrivo_id": data.porto_arrivo_id,
                "idle": data.idle,
                "non_productive_time_min": data.non_productive_time_min,
                "consumo": data.consumo,
                "vascello_id": data.vascello_id,
                "piano_id": data.piano_id,
            })
        except OperativoDelegationError as exc:
            _handle_operativo_fallback(exc)

    return deadhead_service.crea_deadhead(data)


@router.post(
    "/deadhead/modifica",
    response_model=DeadheadResponse,
    summary="Modifica deadhead trip",
    description="""
Aggiorna un deadhead trip esistente.

### Campi modificabili
- **orario_partenza_schedulato**: nuovo orario di partenza
- **porto_partenza_id** / **porto_arrivo_id**: nuovi porti
- **idle**: nuovo stato idle
- **non_productive_time_min**: nuovo tempo non produttivo
- **consumo**: nuovo consumo
- **vascello_id**: nuovo vascello
- **piano_id**: nuovo piano operativo

### Note
- Richiede `id` del deadhead trip + almeno un campo da aggiornare
    """,
    responses={
        200: {"description": "Deadhead trip aggiornato"},
        400: {"description": "Nessun campo da aggiornare o FK non valida"},
        404: {"description": "Deadhead trip non trovato"}
    }
)
def modifica_deadhead_endpoint(data: DeadheadUpdateInput):
    if operativo_delegation_enabled():
        try:
            return operativo_post_json("/internal/deadhead/modifica", {
                "id": data.id,
                "orario_partenza_schedulato": data.orario_partenza_schedulato.isoformat() if data.orario_partenza_schedulato else None,
                "porto_partenza_id": data.porto_partenza_id,
                "porto_arrivo_id": data.porto_arrivo_id,
                "idle": data.idle,
                "non_productive_time_min": data.non_productive_time_min,
                "consumo": data.consumo,
                "vascello_id": data.vascello_id,
                "piano_id": data.piano_id,
            })
        except OperativoDelegationError as exc:
            _handle_operativo_fallback(exc)

    return deadhead_service.modifica_deadhead(data)


@router.post(
    "/deadhead/elimina",
    summary="Elimina deadhead trip",
    description="""
Elimina definitivamente un deadhead trip dal sistema.

### Attenzione
- L'eliminazione è **irreversibile**
    """,
    responses={
        200: {"description": "Deadhead trip eliminato", "content": {"application/json": {"example": {"id": "uuid", "esito": "eliminato"}}}},
        404: {"description": "Deadhead trip non trovato"}
    }
)
def elimina_deadhead_endpoint(data: DeadheadDeleteInput):
    if operativo_delegation_enabled():
        try:
            return operativo_post_json("/internal/deadhead/elimina", {"id": data.id})
        except OperativoDelegationError as exc:
            _handle_operativo_fallback(exc)

    return deadhead_service.elimina_deadhead(data)


@router.get(
    "/deadhead/lista",
    response_model=List[DeadheadResponse],
    summary="Lista deadhead trips",
    description="""
Restituisce l'elenco dei deadhead trips registrati nel sistema.

### Ordinamento
Risultati ordinati per `orario_partenza_schedulato` crescente.

### Query Parameters (opzionali)
- **piano_id**: filtra per piano operativo
- **vascello_id**: filtra per vascello

### Esempi
- `/deadhead/lista` → tutti i deadhead trips
- `/deadhead/lista?piano_id=uuid` → solo deadhead del piano specificato
- `/deadhead/lista?vascello_id=uuid` → solo deadhead del vascello specificato
    """,
    responses={
        200: {"description": "Lista deadhead trips restituita con successo"}
    }
)
def lista_deadhead_endpoint(
    piano_id: Optional[str] = Query(None, description="Filtro per piano operativo"),
    vascello_id: Optional[str] = Query(None, description="Filtro per vascello")
):
    if operativo_delegation_enabled():
        try:
            query = []
            if piano_id:
                query.append(f"piano_id={piano_id}")
            if vascello_id:
                query.append(f"vascello_id={vascello_id}")
            suffix = f"?{'&'.join(query)}" if query else ""
            return operativo_get_json(f"/internal/deadhead/lista{suffix}")
        except OperativoDelegationError as exc:
            _handle_operativo_fallback(exc)

    return deadhead_service.lista_deadhead(piano_id, vascello_id)
