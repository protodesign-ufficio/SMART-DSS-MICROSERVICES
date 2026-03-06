import json
from typing import List
from fastapi import APIRouter, HTTPException
from app.core.database import get_connection
from app.core.anagrafica_client import delegation_enabled, get_json, post_json, AnagraficaDelegationError
from app.core.config import ENABLE_ANAGRAFICA_FALLBACK
from app.models.componente import ComponenteInput, ComponenteModificaInput, Componente, ComponenteDeleteInput

router = APIRouter(prefix="", tags=["Componenti"])


def _handle_anagrafica_fallback(exc: Exception) -> None:
    if not ENABLE_ANAGRAFICA_FALLBACK:
        raise HTTPException(status_code=503, detail="Anagrafica service unavailable") from exc


@router.post(
    "/componente/crea",
    response_model=Componente,
    summary="Crea nuovo componente",
)
def crea_componente(data: ComponenteInput):
    if delegation_enabled():
        try:
            return post_json("/internal/componente/crea", {
                "vascello_id": data.vascello_id,
                "nome_componente": data.nome_componente,
                "sottosistema": data.sottosistema,
                "ore_utilizzo_totali": data.ore_utilizzo_totali,
                "soglia_manutenzione": data.soglia_manutenzione,
                "modello_guasto_json": data.modello_guasto_json,
            })
        except AnagraficaDelegationError as exc:
            _handle_anagrafica_fallback(exc)

    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            """
            INSERT INTO componente (
                id,
                vascello_id,
                nome_componente,
                sottosistema,
                ore_utilizzo_totali,
                soglia_manutenzione,
                modello_guasto_json
            )
            VALUES (gen_random_uuid(), %s, %s, %s, %s, %s, %s)
            RETURNING id, vascello_id, nome_componente, sottosistema, ore_utilizzo_totali, soglia_manutenzione, modello_guasto_json;
            """,
            (
                data.vascello_id,
                data.nome_componente,
                data.sottosistema,
                data.ore_utilizzo_totali,
                data.soglia_manutenzione,
                json.dumps(data.modello_guasto_json) if data.modello_guasto_json is not None else None,
            ),
        )
        row = cur.fetchone()
        conn.commit()
        return {
            "id": row[0],
            "vascello_id": str(row[1]) if row[1] else None,
            "nome_componente": row[2],
            "sottosistema": row[3],
            "ore_utilizzo_totali": float(row[4]) if row[4] is not None else None,
            "soglia_manutenzione": float(row[5]) if row[5] is not None else None,
            "modello_guasto_json": row[6],
        }
    finally:
        conn.close()


@router.get(
    "/componente/lista",
    response_model=List[Componente],
    summary="Elenco componenti",
)
def lista_componenti():
    if delegation_enabled():
        try:
            return get_json("/internal/componente/lista")
        except AnagraficaDelegationError as exc:
            _handle_anagrafica_fallback(exc)

    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT id, vascello_id, nome_componente, sottosistema, ore_utilizzo_totali, soglia_manutenzione, modello_guasto_json
            FROM componente
            ORDER BY nome_componente;
            """
        )
        rows = cur.fetchall()
        return [
            {
                "id": r[0],
                "vascello_id": str(r[1]) if r[1] else None,
                "nome_componente": r[2],
                "sottosistema": r[3],
                "ore_utilizzo_totali": float(r[4]) if r[4] is not None else None,
                "soglia_manutenzione": float(r[5]) if r[5] is not None else None,
                "modello_guasto_json": r[6],
            }
            for r in rows
        ]
    finally:
        conn.close()


@router.get(
    "/componente/{vascello_id}",
    response_model=List[Componente],
    summary="Elenco componenti per vascello",
)
def lista_componenti_by_vascello(vascello_id: str):
    if delegation_enabled():
        try:
            return get_json(f"/internal/componente/{vascello_id}")
        except AnagraficaDelegationError as exc:
            _handle_anagrafica_fallback(exc)

    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT id, vascello_id, nome_componente, sottosistema, ore_utilizzo_totali, soglia_manutenzione, modello_guasto_json
            FROM componente
            WHERE vascello_id = %s
            ORDER BY nome_componente;
            """,
            (vascello_id,),
        )
        rows = cur.fetchall()
        return [
            {
                "id": r[0],
                "vascello_id": str(r[1]) if r[1] else None,
                "nome_componente": r[2],
                "sottosistema": r[3],
                "ore_utilizzo_totali": float(r[4]) if r[4] is not None else None,
                "soglia_manutenzione": float(r[5]) if r[5] is not None else None,
                "modello_guasto_json": r[6],
            }
            for r in rows
        ]
    finally:
        conn.close()


@router.post(
    "/componente/modifica",
    response_model=Componente,
    summary="Modifica componente",
)
def modifica_componente(data: ComponenteModificaInput):
    if delegation_enabled():
        try:
            return post_json("/internal/componente/modifica", {
                "id": data.id,
                "vascello_id": data.vascello_id,
                "nome_componente": data.nome_componente,
                "sottosistema": data.sottosistema,
                "ore_utilizzo_totali": data.ore_utilizzo_totali,
                "soglia_manutenzione": data.soglia_manutenzione,
                "modello_guasto_json": data.modello_guasto_json,
            })
        except AnagraficaDelegationError as exc:
            _handle_anagrafica_fallback(exc)

    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            """
            UPDATE componente
            SET vascello_id = %s,
                nome_componente = %s,
                sottosistema = %s,
                ore_utilizzo_totali = %s,
                soglia_manutenzione = %s,
                modello_guasto_json = %s
            WHERE id = %s
            RETURNING id, vascello_id, nome_componente, sottosistema, ore_utilizzo_totali, soglia_manutenzione, modello_guasto_json;
            """,
            (
                data.vascello_id,
                data.nome_componente,
                data.sottosistema,
                data.ore_utilizzo_totali,
                data.soglia_manutenzione,
                json.dumps(data.modello_guasto_json) if data.modello_guasto_json is not None else None,
                data.id,
            ),
        )
        row = cur.fetchone()
        conn.commit()
        if row is None:
            raise HTTPException(404, "Componente non trovato")
        return {
            "id": row[0],
            "vascello_id": str(row[1]) if row[1] else None,
            "nome_componente": row[2],
            "sottosistema": row[3],
            "ore_utilizzo_totali": float(row[4]) if row[4] is not None else None,
            "soglia_manutenzione": float(row[5]) if row[5] is not None else None,
            "modello_guasto_json": row[6],
        }
    finally:
        conn.close()


@router.post(
    "/componente/elimina",
    summary="Elimina componente",
    responses={
        200: {"description": "Componente eliminato con successo", "content": {"application/json": {"example": {"id": "uuid", "esito": "eliminato"}}}},
        404: {"description": "Componente non trovato - UUID non esistente"}
    }
)
def elimina_componente(data: ComponenteDeleteInput):
    if delegation_enabled():
        try:
            return post_json("/internal/componente/elimina", {"id": data.id})
        except AnagraficaDelegationError as exc:
            _handle_anagrafica_fallback(exc)

    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("DELETE FROM componente WHERE id = %s RETURNING id;", (data.id,))
        row = cur.fetchone()
        conn.commit()
        if row is None:
            raise HTTPException(404, "Componente non trovato")
        return {"id": data.id, "esito": "eliminato"}
    finally:
        conn.close()
