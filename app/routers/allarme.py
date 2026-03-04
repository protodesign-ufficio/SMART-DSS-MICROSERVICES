from typing import List
from fastapi import APIRouter, Query, HTTPException
from app.core.database import get_connection
from app.core.config import ENABLE_ALERTING_FALLBACK
from app.core.alerting_client import (
    delegation_enabled as alerting_delegation_enabled,
    get_json as alerting_get_json,
    AlertingDelegationError,
)
from app.models.allarme import AllarmeResponse

router = APIRouter(prefix="", tags=["Alerting"])


@router.get(
    "/allarme/lista",
    response_model=List[AllarmeResponse],
    summary="Lista allarmi",
    description="Restituisce gli ultimi allarmi operativi ordinati per data decrescente.",
    response_description="Lista allarmi operativi con id, utente assegnatario, testo e timestamp creazione.",
)
def lista_allarmi(
    limit: int = Query(
        200,
        ge=1,
        le=2000,
        description="Numero massimo di allarmi da restituire (default 200, massimo 2000).",
    )
):
    if alerting_delegation_enabled():
        try:
            return alerting_get_json(f"/internal/allarme/lista?limit={limit}")
        except AlertingDelegationError as exc:
            if not ENABLE_ALERTING_FALLBACK:
                raise HTTPException(status_code=503, detail="Alerting service unavailable") from exc
            pass

    if not ENABLE_ALERTING_FALLBACK and alerting_delegation_enabled():
        raise HTTPException(status_code=503, detail="Alerting service unavailable")

    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT
                id,
                utente_assegnatario_id AS utente_id,
                descrizione AS testo,
                created_at AS data_creazione
            FROM allarme
            ORDER BY created_at DESC
            LIMIT %s;
            """,
            (limit,),
        )
        rows = cur.fetchall()
        return [
            {
                "id": str(r[0]),
                "utente_id": str(r[1]) if r[1] else None,
                "testo": r[2],
                "data_creazione": r[3].isoformat() if r[3] else None,
            }
            for r in rows
        ]
    finally:
        cur.close()
        conn.close()
