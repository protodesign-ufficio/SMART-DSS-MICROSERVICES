from fastapi import APIRouter, HTTPException
from typing import List
from app.core.database import get_connection
from app.core.anagrafica_client import delegation_enabled, get_json, post_json, AnagraficaDelegationError
from app.core.config import ENABLE_ANAGRAFICA_FALLBACK
from app.models.tratta import (
    TrattaInputById, TrattaMultiInputById, TrattaCreated,
    TrattaMultiCreated, TrattaListItem, TrattaDetail, TrattaModificaInput, TrattaDeleteInput
)
import json
import uuid

router = APIRouter(prefix="", tags=["Tratte"])


def _handle_anagrafica_fallback(exc: Exception) -> None:
    if not ENABLE_ANAGRAFICA_FALLBACK:
        raise HTTPException(status_code=503, detail="Anagrafica service unavailable") from exc


@router.post(
    "/tratta/crea",
    response_model=TrattaCreated,
    summary="Crea tratta diretta",
    description="""
Crea una nuova tratta diretta (point-to-point) tra due porti.

### Comportamento
- Verifica l'esistenza di entrambi i porti
- Previene duplicazioni: una sola tratta diretta per coppia di porti
- Genera automaticamente:
  - **UUID** univoco (o usa quello fornito)
  - **Nome** nel formato `XXX-YYY` (prime 3 lettere maiuscole dei porti)
  - **Geometria** come LineString PostGIS (SRID 4326)

### Naming Convention
`PARTENZA[:3]-ARRIVO[:3]` → es. `SAL-AMA` (Salerno → Amalfi)

### Note
- Per tratte con scali intermedi usare `/tratta/crea_multi`
- La distanza viene calcolata al primo utilizzo o su richiesta
    """,
    responses={
        200: {"description": "Tratta creata con successo"},
        404: {"description": "Porto partenza o arrivo non trovato"},
        409: {"description": "Tratta diretta già esistente tra questi porti"}
    }
)
def crea_tratta(data: TrattaInputById):
    if delegation_enabled():
        try:
            return post_json("/internal/tratta/crea", {
                "id": str(data.id) if data.id else None,
                "porto_partenza_id": str(data.porto_partenza_id),
                "porto_arrivo_id": str(data.porto_arrivo_id),
            })
        except AnagraficaDelegationError as exc:
            _handle_anagrafica_fallback(exc)

    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT nome, ST_X(coordinate_gps), ST_Y(coordinate_gps) FROM porto WHERE id = %s", (str(data.porto_partenza_id),))
        p1 = cur.fetchone()
        if p1 is None:
            raise HTTPException(404, f"Porto di partenza non trovato: {data.porto_partenza_id}")
        nome_p1, lon1, lat1 = p1

        cur.execute("SELECT nome, ST_X(coordinate_gps), ST_Y(coordinate_gps) FROM porto WHERE id = %s", (str(data.porto_arrivo_id),))
        p2 = cur.fetchone()
        if p2 is None:
            raise HTTPException(404, f"Porto di arrivo non trovato: {data.porto_arrivo_id}")
        nome_p2, lon2, lat2 = p2

        cur.execute("SELECT id FROM tratta WHERE porto_partenza_id = %s AND porto_arrivo_id = %s AND tratta_multiporto = false LIMIT 1", (str(data.porto_partenza_id), str(data.porto_arrivo_id)))
        if cur.fetchone() is not None:
            raise HTTPException(409, detail=f"Esiste già una tratta diretta tra {nome_p1} e {nome_p2}.")

        nome_tratta = f"{nome_p1[:3].upper()}-{nome_p2[:3].upper()}"
        tratta_uuid = data.id if data.id else uuid.uuid4()

        cur.execute("""
            INSERT INTO tratta (id, nome, porto_partenza_id, porto_arrivo_id, geom_rotta_standard, tratta_multiporto)
            VALUES (%s, %s, %s, %s, ST_SetSRID(ST_MakeLine(ST_Point(%s, %s), ST_Point(%s, %s)), 4326), false)
            RETURNING id;
        """, (str(tratta_uuid), nome_tratta, str(data.porto_partenza_id), str(data.porto_arrivo_id), lon1, lat1, lon2, lat2))

        tratta_id = cur.fetchone()[0]
        conn.commit()

        cur.execute("SELECT ST_AsGeoJSON(geom_rotta_standard) FROM tratta WHERE id = %s", (tratta_id,))
        geom_json = cur.fetchone()[0]

        return {"id": str(tratta_id), "nome": nome_tratta, "porto_partenza_id": str(data.porto_partenza_id), "porto_arrivo_id": str(data.porto_arrivo_id), "porto_partenza": nome_p1, "porto_arrivo": nome_p2, "distanza_miglia": None, "geometry": geom_json}
    finally:
        cur.close()
        conn.close()


@router.post(
    "/tratta/crea_multi",
    response_model=TrattaMultiCreated,
    summary="Crea tratta multiporto",
    description="""
Crea una tratta con uno o più porti intermedi (scali).

### Input
- **porti_ids**: lista ordinata di UUID porti [partenza, ...intermedi..., arrivo]
- Minimo 2 porti richiesti

### Comportamento
- Verifica esistenza di tutti i porti nella lista
- La geometria viene generata come LineString passante per tutti i punti
- I porti intermedi vengono salvati in un array JSON

### Esempio
```json
{
  "porti_ids": ["uuid-salerno", "uuid-positano", "uuid-amalfi"]
}
```
*Risultato: tratta SAL-AMA con scalo a Positano*

### Response
Include:
- Lista completa nomi porti in ordine
- Geometria GeoJSON dell'intero percorso
- Flag `tratta_multiporto: true`
    """,
    responses={
        200: {"description": "Tratta multiporto creata con successo"},
        400: {"description": "Lista porti insufficiente (minimo 2)"},
        404: {"description": "Uno o più porti non trovati"}
    }
)
def crea_tratta_multiporto(data: TrattaMultiInputById):
    if delegation_enabled():
        try:
            return post_json("/internal/tratta/crea_multi", {
                "id": str(data.id) if data.id else None,
                "porti_ids": [str(porto_id) for porto_id in data.porti_ids],
            })
        except AnagraficaDelegationError as exc:
            _handle_anagrafica_fallback(exc)

    if len(data.porti_ids) < 2:
        raise HTTPException(400, "Servono almeno due porti.")
    conn = get_connection()
    cur = conn.cursor()
    try:
        punti = []
        nomi_porti = []
        for p_id in data.porti_ids:
            cur.execute("SELECT nome, ST_X(coordinate_gps), ST_Y(coordinate_gps) FROM porto WHERE id = %s", (str(p_id),))
            row = cur.fetchone()
            if not row:
                raise HTTPException(404, f"Porto non trovato: {p_id}")
            nome, lon, lat = row
            nomi_porti.append(nome)
            punti.append((lon, lat))

        porto_partenza_id = data.porti_ids[0]
        porto_arrivo_id = data.porti_ids[-1]
        ids_intermedi = [str(uid) for uid in data.porti_ids[1:-1]]
        has_intermedi = len(ids_intermedi) > 0
        nomi_intermedi = nomi_porti[1:-1] if has_intermedi else None

        nome_tratta = f"{nomi_porti[0][:3].upper()}-{nomi_porti[-1][:3].upper()}"
        punti_sql = ",".join([f"ST_Point({lon},{lat})" for lon, lat in punti])
        json_intermedi_db = json.dumps(ids_intermedi) if has_intermedi else None
        tratta_uuid = data.id if data.id else uuid.uuid4()

        cur.execute(f"""
            INSERT INTO tratta (id, nome, porto_partenza_id, porto_arrivo_id, porti_intermedi, tratta_multiporto, geom_rotta_standard)
            VALUES (%s, %s, %s, %s, %s, %s, ST_SetSRID(ST_MakeLine(ARRAY[{punti_sql}]), 4326))
            RETURNING id;
        """, (str(tratta_uuid), nome_tratta, str(porto_partenza_id), str(porto_arrivo_id), json_intermedi_db, has_intermedi))

        tratta_id = cur.fetchone()[0]
        conn.commit()
        cur.execute("SELECT ST_AsGeoJSON(geom_rotta_standard) FROM tratta WHERE id = %s", (tratta_id,))
        geom_json = cur.fetchone()[0]

        return {"id": str(tratta_id), "porti": nomi_porti, "distanza_miglia": None, "porti_intermedi": nomi_intermedi, "tratta_multiporto": has_intermedi, "geometry": geom_json}
    finally:
        cur.close()
        conn.close()


@router.get(
    "/tratta/lista",
    response_model=List[TrattaListItem],
    summary="Elenco tratte",
    description="""
Restituisce l'elenco completo di tutte le tratte definite nel sistema.

### Ordinamento
Risultati ordinati alfabeticamente per nome tratta.

### Response
Per ogni tratta:
- Identificativi (UUID, nome)
- Riferimenti porti (partenza, arrivo, intermedi)
- Flag `tratta_multiporto` per distinguere tipologia

### Note
- Non include la geometria (per ottimizzare payload)
- Per geometria usare endpoint dettaglio `/tratta/{id}`
    """,
    responses={
        200: {"description": "Lista tratte restituita con successo"}
    }
)
def lista_tratte():
    if delegation_enabled():
        try:
            return get_json("/internal/tratta/lista")
        except AnagraficaDelegationError as exc:
            _handle_anagrafica_fallback(exc)

    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT id, nome, porto_partenza_id, porto_arrivo_id, porti_intermedi, tratta_multiporto FROM tratta ORDER BY nome ASC;")
        rows = cur.fetchall()
        return [{"id": str(r[0]), "nome": r[1], "porto_partenza_id": str(r[2]), "porto_arrivo_id": str(r[3]), "porti_intermedi": r[4], "tratta_multiporto": r[5]} for r in rows]
    finally:
        cur.close(); conn.close()


@router.get(
    "/tratta/{tratta_id}",
    response_model=TrattaDetail,
    response_model_exclude_none=True,
    summary="Dettaglio tratta",
    description="""
Restituisce i dettagli completi di una tratta, inclusa la geometria.

### Path Parameters
- **tratta_id**: UUID della tratta

### Response
- Identificativi e riferimenti porti
- Distanza in miglia nautiche (se calcolata)
- **geometry**: GeoJSON LineString della rotta standard
- Lista porti intermedi (se multiporto)

### Utilizzo tipico
- Visualizzazione su mappa
- Export dati geografici
- Calcolo distanze
    """,
    responses={
        200: {"description": "Dettaglio tratta con geometria"},
        404: {"description": "Tratta non trovata - UUID non esistente"}
    }
)
def get_tratta(tratta_id: str):
    if delegation_enabled():
        try:
            data = get_json(f"/internal/tratta/{tratta_id}")
            if data is None:
                raise HTTPException(404, "Tratta non trovata")
            return data
        except AnagraficaDelegationError as exc:
            _handle_anagrafica_fallback(exc)

    conn = get_connection(); cur = conn.cursor()
    try:
        cur.execute("""
            SELECT id, nome, porto_partenza_id, porto_arrivo_id, distanza_miglia, porti_intermedi, tratta_multiporto, ST_AsGeoJSON(geom_rotta_standard)
            FROM tratta WHERE id = %s
        """, (tratta_id,))
        row = cur.fetchone()
        if row is None:
            raise HTTPException(404, "Tratta non trovata")
        return {"id": str(row[0]), "nome": row[1], "porto_partenza_id": str(row[2]), "porto_arrivo_id": str(row[3]), "distanza_miglia": row[4], "porti_intermedi": row[5], "tratta_multiporto": row[6], "geometry": row[7]}
    finally:
        cur.close(); conn.close()


@router.post(
    "/tratta/modifica",
    response_model=TrattaCreated,
    summary="Modifica tratta",
    description="""
Aggiorna una tratta esistente con nuovi porti di partenza e/o arrivo.

### Comportamento automatico
- Ricalcola il **nome** basandosi sui nuovi porti
- Rigenera la **geometria** LineString tra i nuovi punti
- Mantiene l'**UUID** originale (referenze preservate)

### Input richiesti
- **id**: UUID della tratta da modificare
- **porto_partenza_id**: nuovo UUID porto partenza
- **porto_arrivo_id**: nuovo UUID porto arrivo

### Note
- Le corse associate mantengono il riferimento alla tratta
- I percorsi calcolati sulla vecchia geometria restano invariati
- Per modifiche su tratte multiporto, eliminare e ricreare
    """,
    responses={
        200: {"description": "Tratta aggiornata con nuova geometria"},
        404: {"description": "Tratta o porto non trovato"}
    }
)
def modifica_tratta(data: TrattaModificaInput):
    if delegation_enabled():
        try:
            return post_json("/internal/tratta/modifica", {
                "id": data.id,
                "porto_partenza_id": data.porto_partenza_id,
                "porto_arrivo_id": data.porto_arrivo_id,
            })
        except AnagraficaDelegationError as exc:
            _handle_anagrafica_fallback(exc)

    conn = get_connection(); cur = conn.cursor()
    try:
        cur.execute("SELECT nome, ST_X(coordinate_gps), ST_Y(coordinate_gps) FROM porto WHERE id = %s", (data.porto_partenza_id,))
        p1 = cur.fetchone()
        if p1 is None:
            raise HTTPException(404, f"Porto di partenza non trovato: {data.porto_partenza_id}")
        nome_p1, lon1, lat1 = p1

        cur.execute("SELECT nome, ST_X(coordinate_gps), ST_Y(coordinate_gps) FROM porto WHERE id = %s", (data.porto_arrivo_id,))
        p2 = cur.fetchone()
        if p2 is None:
            raise HTTPException(404, f"Porto di arrivo non trovato: {data.porto_arrivo_id}")
        nome_p2, lon2, lat2 = p2

        nuovo_nome = f"{nome_p1[:3].upper()}-{nome_p2[:3].upper()}"
        cur.execute("""
            UPDATE tratta SET nome = %s, porto_partenza_id = %s, porto_arrivo_id = %s, geom_rotta_standard = ST_SetSRID(ST_MakeLine(ST_Point(%s,%s), ST_Point(%s,%s)), 4326)
            WHERE id = %s RETURNING id, ST_AsGeoJSON(geom_rotta_standard);
        """, (nuovo_nome, data.porto_partenza_id, data.porto_arrivo_id, lon1, lat1, lon2, lat2, data.id))
        row = cur.fetchone(); conn.commit()
        if row is None:
            raise HTTPException(404, "Tratta non trovata per la modifica")
        return {"id": str(row[0]), "porto_partenza": nome_p1, "porto_arrivo": nome_p2, "distanza_miglia": None, "geometry": row[1]}
    finally:
        cur.close(); conn.close()


@router.post(
    "/tratta/elimina",
    summary="Elimina tratta",
    description="""
Elimina definitivamente una tratta dal sistema con eliminazione **a cascata**.

### Comportamento a cascata
L'operazione elimina in sequenza:
1. Tutte le **assegnazioni** legate ai percorsi delle corse della tratta
2. Tutti i **percorsi** associati alle corse della tratta
3. Tutte le **corse** associate alla tratta
4. La **tratta** stessa

I **piani operativi** non vengono eliminati: rimangono nel sistema privi delle assegnazioni rimosse.

In modalità monolitica le eliminazioni avvengono in una singola transazione DB.
In modalità microservizi viene coordinato il cascade tra `anagrafica_service` → `operativo_service` → `percorsi_service`.

### Attenzione
- L'eliminazione è **irreversibile**
- Non è necessario eliminare manualmente corse, percorsi o assegnazioni prima di chiamare questo endpoint

### Input
```json
{"id": "uuid-tratta"}
```
    """,
    responses={
        200: {"description": "Tratta eliminata con successo", "content": {"application/json": {"example": {"id": "uuid", "esito": "eliminato"}}}},
        404: {"description": "Tratta non trovata - UUID non esistente"}
    }
)
def elimina_tratta(data: TrattaDeleteInput):
    if delegation_enabled():
        try:
            # In microservices mode this operation can take longer due to cascades across services.
            return post_json("/internal/tratta/elimina", data.model_dump(), timeout=30.0)
        except AnagraficaDelegationError as exc:
            _handle_anagrafica_fallback(exc)

    conn = get_connection(); cur = conn.cursor()
    try:
        cur.execute(
            "DELETE FROM assegnazione WHERE percorso_id IN (SELECT id FROM percorso WHERE id_corsa IN (SELECT id FROM corsa WHERE tratta_id = %s));",
            (data.id,)
        )
        cur.execute(
            "DELETE FROM percorso WHERE id_corsa IN (SELECT id FROM corsa WHERE tratta_id = %s);",
            (data.id,)
        )
        cur.execute("DELETE FROM corsa WHERE tratta_id = %s;", (data.id,))
        cur.execute("DELETE FROM tratta WHERE id = %s RETURNING id;", (data.id,))
        row = cur.fetchone()
        if row is None:
            conn.rollback()
            raise HTTPException(404, "Tratta non trovata")
        conn.commit()
        return {"id": data.id, "esito": "eliminato"}
    except HTTPException:
        raise
    except Exception:
        conn.rollback(); raise
    finally:
        cur.close(); conn.close()
