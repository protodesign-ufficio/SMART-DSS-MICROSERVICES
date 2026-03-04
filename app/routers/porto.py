from fastapi import APIRouter, HTTPException
from typing import List
from app.core.database import get_connection
from app.core.anagrafica_client import delegation_enabled, get_json, post_json, AnagraficaDelegationError
from app.core.config import ENABLE_ANAGRAFICA_FALLBACK
from app.models.porto import PortoInput, Porto, PortoModificaInput, PortoDeleteInput

router = APIRouter(prefix="", tags=["Porti"])


def _handle_anagrafica_fallback(exc: Exception) -> None:
    if not ENABLE_ANAGRAFICA_FALLBACK:
        raise HTTPException(status_code=503, detail="Anagrafica service unavailable") from exc

@router.post(
    "/porto/crea",
    response_model=Porto,
    summary="Crea nuovo porto",
    description="""
Registra un nuovo porto nel sistema con le relative coordinate geografiche.

### Comportamento
- Genera automaticamente un UUID univoco per il porto
- Memorizza le coordinate come geometria PostGIS (SRID 4326 - WGS84)
- Il nome del porto deve essere univoco nel sistema

### Coordinate
- **lat**: Latitudine in gradi decimali (-90 a +90)
- **lon**: Longitudine in gradi decimali (-180 a +180)

### Esempio
```json
{
  "nome": "Salerno",
  "lat": 40.6824,
  "lon": 14.7681
}
```
    """,
    responses={
        200: {"description": "Porto creato correttamente"},
        400: {"description": "Coordinate non valide"},
        409: {"description": "Porto con lo stesso nome già esistente"}
    }
)
def crea_porto(data: PortoInput):
    if delegation_enabled():
        try:
            return post_json("/internal/porto/crea", {
                "nome": data.nome,
                "lat": data.lat,
                "lon": data.lon,
            })
        except AnagraficaDelegationError as exc:
            _handle_anagrafica_fallback(exc)

    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO porto (id, nome, coordinate_gps)
        VALUES (
            gen_random_uuid(),
            %s,
            ST_SetSRID(ST_Point(%s, %s), 4326)
        )
        RETURNING id;
    """, (data.nome, data.lon, data.lat))

    porto_id = cur.fetchone()[0]
    conn.commit()
    conn.close()

    return {"id": porto_id, "nome": data.nome, "lat": data.lat, "lon": data.lon}


@router.get(
    "/porto/lista",
    response_model=List[Porto],
    summary="Elenco porti",
    description="""
Restituisce l'elenco completo di tutti i porti registrati nel sistema.

### Ordinamento
I risultati sono ordinati alfabeticamente per nome del porto.

### Utilizzo tipico
- Popolamento dropdown/select nelle UI
- Validazione riferimenti porti
- Export anagrafica porti
    """,
    responses={
        200: {"description": "Lista porti restituita con successo"}
    }
)
def lista_porti():
    if delegation_enabled():
        try:
            return get_json("/internal/porto/lista")
        except AnagraficaDelegationError as exc:
            _handle_anagrafica_fallback(exc)

    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, nome, ST_Y(coordinate_gps), ST_X(coordinate_gps)
        FROM porto
        ORDER BY nome;
    """)
    rows = cur.fetchall()
    conn.close()

    return [{"id": r[0], "nome": r[1], "lat": r[2], "lon": r[3]} for r in rows]


@router.get(
    "/porto/{porto_id}",
    response_model=Porto,
    summary="Dettaglio porto",
    description="""
Recupera i dettagli completi di un singolo porto tramite il suo UUID.

### Path Parameters
- **porto_id**: UUID univoco del porto

### Response
Oggetto `Porto` con:
- `id`: UUID del porto
- `nome`: Nome identificativo
- `lat`: Latitudine (WGS84)
- `lon`: Longitudine (WGS84)
    """,
    responses={
        200: {"description": "Dettaglio porto restituito correttamente"},
        404: {"description": "Porto non trovato - UUID non esistente"}
    }
)
def get_porto(porto_id: str):
    if delegation_enabled():
        try:
            data = get_json(f"/internal/porto/{porto_id}")
            if data is None:
                raise HTTPException(404, "Porto non trovato")
            return data
        except AnagraficaDelegationError as exc:
            _handle_anagrafica_fallback(exc)

    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, nome, ST_Y(coordinate_gps), ST_X(coordinate_gps)
        FROM porto
        WHERE id = %s
    """, (porto_id,))
    row = cur.fetchone()
    conn.close()
    if row is None:
        raise HTTPException(404, "Porto non trovato")
    return {"id": row[0], "nome": row[1], "lat": row[2], "lon": row[3]}


@router.get(
    "/porto/by_name/{nome}",
    response_model=Porto,
    summary="Ricerca porto per nome",
    description="""
Ricerca un porto tramite il suo nome identificativo.

### Comportamento
- La ricerca è **case-insensitive** ("Salerno" = "salerno" = "SALERNO")
- Restituisce il primo match trovato
- Utile per integrazioni con sistemi esterni che usano nomi invece di UUID

### Path Parameters
- **nome**: Nome del porto da cercare
    """,
    responses={
        200: {"description": "Porto trovato"},
        404: {"description": "Nessun porto trovato con il nome specificato"}
    }
)
def get_porto_by_name(nome: str):
    if delegation_enabled():
        try:
            data = get_json(f"/internal/porto/by_name/{nome}")
            if data is None:
                raise HTTPException(status_code=404, detail=f"Nessun porto trovato con nome='{nome}'")
            return data
        except AnagraficaDelegationError as exc:
            _handle_anagrafica_fallback(exc)

    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, nome, ST_Y(coordinate_gps), ST_X(coordinate_gps)
        FROM porto
        WHERE LOWER(nome) = LOWER(%s)
        LIMIT 1;
    """, (nome,))
    row = cur.fetchone()
    conn.close()
    if row is None:
        raise HTTPException(status_code=404, detail=f"Nessun porto trovato con nome='{nome}'")
    return {"id": row[0], "nome": row[1], "lat": row[2], "lon": row[3]}


@router.post(
    "/porto/modifica",
    response_model=Porto,
    summary="Modifica porto",
    description="""
Aggiorna i dati di un porto esistente.

### Campi modificabili
- **nome**: Nuovo nome del porto
- **lat**: Nuova latitudine
- **lon**: Nuova longitudine

### Note
- Tutti i campi sono obbligatori nella richiesta
- La geometria PostGIS viene ricalcolata automaticamente
- Le tratte associate mantengono il riferimento al porto (UUID invariato)
    """,
    responses={
        200: {"description": "Porto aggiornato correttamente"},
        404: {"description": "Porto non trovato - UUID non esistente"}
    }
)
def modifica_porto(data: PortoModificaInput):
    if delegation_enabled():
        try:
            return post_json("/internal/porto/modifica", {
                "id": data.id,
                "nome": data.nome,
                "lat": data.lat,
                "lon": data.lon,
            })
        except AnagraficaDelegationError as exc:
            _handle_anagrafica_fallback(exc)

    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        UPDATE porto
        SET nome = %s, coordinate_gps = ST_SetSRID(ST_Point(%s, %s), 4326)
        WHERE id = %s
        RETURNING id, nome, ST_Y(coordinate_gps), ST_X(coordinate_gps);
    """, (data.nome, data.lon, data.lat, data.id))
    row = cur.fetchone()
    conn.commit()
    conn.close()
    if row is None:
        raise HTTPException(404, "Porto non trovato")
    return {"id": row[0], "nome": row[1], "lat": row[2], "lon": row[3]}


@router.post(
    "/porto/elimina",
    summary="Elimina porto",
    description="""
Elimina definitivamente un porto dal sistema.

### Attenzione
- L'eliminazione è **irreversibile**
- Verificare che non esistano tratte attive associate al porto
- Le tratte con riferimenti al porto potrebbero diventare inconsistenti

### Validazioni
- Il porto deve esistere nel sistema
    """,
    responses={
        200: {"description": "Porto eliminato con successo", "content": {"application/json": {"example": {"id": "uuid", "esito": "eliminato"}}}},
        404: {"description": "Porto non trovato - UUID non esistente"}
    }
)
def elimina_porto(data: PortoDeleteInput):
    if delegation_enabled():
        try:
            return post_json("/internal/porto/elimina", {"id": data.id})
        except AnagraficaDelegationError as exc:
            _handle_anagrafica_fallback(exc)

    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM porto WHERE id = %s RETURNING id;", (data.id,))
    row = cur.fetchone()
    conn.commit()
    conn.close()
    if row is None:
        raise HTTPException(404, "Porto non trovato")
    return {"id": data.id, "esito": "eliminato"}
