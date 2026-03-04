from fastapi import APIRouter, HTTPException
from typing import Optional
from app.services import replanning_service
from app.models.replanning import CheckReplanningResponse
from app.core.scheduler import get_periodic_replanning_status

router = APIRouter(prefix="", tags=["Replanning"])


@router.get(
    "/check_replanning/status",
    summary="Stato job periodico replanning",
    description="""
Restituisce lo stato del job periodico di check replanning:
- intervallo configurato
- prossima esecuzione prevista
- esito e dettagli dell'ultimo ciclo eseguito
    """
)
def check_replanning_status_endpoint():
    try:
        return get_periodic_replanning_status()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/check_replanning",
    response_model=CheckReplanningResponse,
    response_model_exclude_none=True,
    summary="Verifica automatica necessità di replanning",
    description="""
Esegue il controllo di replanning sul piano operativo del giorno corrente.

### Obiettivo
Capire se lo stato operativo corrente (assegnazioni in esecuzione + vincoli temporali) richiede una ricalibrazione del piano tramite il microservizio di replanning.

### Flusso elaborativo
1. Cerca il piano con stato `IN_CORSO` riferito a oggi.
2. Recupera e raggruppa le assegnazioni per vascello.
3. Arricchisce ogni assegnazione con dettagli di percorso e corsa.
4. Mappa gli MMSI dei vascelli coinvolti.
5. Invia il payload al servizio esterno `REPLANNING_SERVICE_URL/replanning/check`.

### Response
- **success**: esito dell'operazione gateway.
- **message**: messaggio sintetico lato API Gateway.
- **piano**: dettagli del piano IN_CORSO (se trovato).
- **assegnazioni_per_vascello**: mappa `vascello_id -> assegnazioni arricchite`.
- **mmsi_per_vascello**: mappa `vascello_id -> mmsi`.
- **risposta_replanning**: risultato del servizio esterno (`needs_replanning`, motivazioni, ecc.).

### Note
- Se non esiste alcun piano IN_CORSO per oggi, la risposta è `200` con `success=false`.
- In caso di errore inatteso interno, viene restituito `500`.
    """,
    responses={
        200: {
            "description": "Verifica replanning completata",
            "content": {
                "application/json": {
                    "examples": {
                        "piano_trovato": {
                            "summary": "Piano in corso trovato",
                            "value": {
                                "success": True,
                                "message": "Piano IN_CORSO trovato con 2 assegnazioni su 1 vascelli",
                                "piano": {
                                    "id": "550e8400-e29b-41d4-a716-446655440000",
                                    "data_riferimento": "2026-02-18T00:00:00",
                                    "stato": "IN_CORSO",
                                    "versione": 2
                                },
                                "assegnazioni_per_vascello": {
                                    "vascello-1": [
                                        {
                                            "id": "asm-1",
                                            "percorso_id": "percorso-1",
                                            "stato_esecuzione": "IN_CORSO"
                                        }
                                    ]
                                },
                                "mmsi_per_vascello": {
                                    "vascello-1": "247123450"
                                },
                                "risposta_replanning": {
                                    "success": True,
                                    "needs_replanning": False
                                }
                            }
                        },
                        "nessun_piano_oggi": {
                            "summary": "Nessun piano in corso",
                            "value": {
                                "success": False,
                                "message": "Nessun piano IN_CORSO trovato per oggi",
                                "piano": None,
                                "assegnazioni_per_vascello": {},
                                "mmsi_per_vascello": {}
                            }
                        }
                    }
                }
            }
        },
        500: {
            "description": "Errore interno durante l'elaborazione",
            "content": {
                "application/json": {
                    "example": {
                        "detail": "messaggio errore"
                    }
                }
            }
        }
    }
)
def check_replanning_endpoint(
    virtuale: bool,
    piano_id: Optional[str] = None
):
    try:
        risultato = replanning_service.check_replanning(virtuale=virtuale, piano_id=piano_id)
        return risultato
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
