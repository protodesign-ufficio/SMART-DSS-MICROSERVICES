from fastapi import APIRouter, HTTPException
from typing import List
from datetime import timedelta
import json
from app.core.database import get_connection
from app.core.anagrafica_client import delegation_enabled, get_json, post_json, AnagraficaDelegationError
from app.core.operativo_client import get_json as operativo_get_json, OperativoDelegationError
from app.core.percorsi_client import get_json as percorsi_get_json, PercorsiDelegationError
from app.core.config import ENABLE_ANAGRAFICA_FALLBACK
from app.models.vascello import VascelloInput, Vascello, VascelloModificaInput, VascelloDeleteInput
from app.models.percorso import PercorsoAttivoResponse

router = APIRouter(prefix="", tags=["Vascelli"])


def _handle_anagrafica_fallback(exc: Exception) -> None:
    if not ENABLE_ANAGRAFICA_FALLBACK:
        raise HTTPException(status_code=503, detail="Anagrafica service unavailable") from exc


@router.post(
    "/vascello/crea",
    response_model=Vascello,
    summary="Registra nuovo vascello",
    description="""
Registra un nuovo vascello nella flotta con le relative caratteristiche tecniche.

### Identificazione
- **MMSI** (Maritime Mobile Service Identity): codice univoco a 9 cifre assegnato dall'IMO
- **Nome**: nome identificativo della nave

### Parametri operativi
- **capacita_passeggeri**: numero massimo passeggeri omologato
- **costo_orario_esercizio**: costo operativo in €/h per calcoli economici
- **velocita_max_nodi**: velocità massima in nodi per vincoli ottimizzazione
- **stato_salute_aggregato**: indice 0-100 per manutenzione predittiva

### Profilo consumo
Oggetto JSON con curve consumo parametrizzate per velocità:
```json
{"10": 45, "15": 78, "20": 125, "25": 195}
```
*Formato: {velocità_nodi: consumo_litri_ora}*
    """,
    responses={
        200: {"description": "Vascello registrato correttamente"},
        400: {"description": "Dati non validi"},
        409: {"description": "MMSI già esistente nel sistema"}
    }
)
def crea_vascello(data: VascelloInput):
    if delegation_enabled():
        try:
            return post_json("/internal/vascello/crea", {
                "mmsi": data.mmsi,
                "nome": data.nome,
                "capacita_passeggeri": data.capacita_passeggeri,
                "costo_orario_esercizio": data.costo_orario_esercizio,
                "velocita_max_nodi": data.velocita_max_nodi,
                "stato_salute_aggregato": data.stato_salute_aggregato,
                "profilo_consumo_json": data.profilo_consumo_json,
            })
        except AnagraficaDelegationError as exc:
            _handle_anagrafica_fallback(exc)

    conn = get_connection(); cur = conn.cursor()
    try:
        cur.execute("""
            INSERT INTO vascello (id, mmsi, nome, capacita_passeggeri, costo_orario_esercizio, velocita_max_nodi, stato_salute_aggregato, profilo_consumo_json, data_creazione)
            VALUES (gen_random_uuid(), %s, %s, %s, %s, %s, %s, %s, now()) RETURNING id, data_creazione;
        """, (
            data.mmsi, data.nome, data.capacita_passeggeri, data.costo_orario_esercizio, data.velocita_max_nodi, data.stato_salute_aggregato, json.dumps(data.profilo_consumo_json) if data.profilo_consumo_json else None
        ))
        new_id, data_creazione = cur.fetchone(); conn.commit()
        return {"id": new_id, "mmsi": data.mmsi, "nome": data.nome, "capacita_passeggeri": data.capacita_passeggeri, "costo_orario_esercizio": data.costo_orario_esercizio, "velocita_max_nodi": data.velocita_max_nodi, "stato_salute_aggregato": data.stato_salute_aggregato, "profilo_consumo_json": data.profilo_consumo_json, "data_creazione": data_creazione.isoformat() if data_creazione else None}
    finally:
        conn.close()


@router.get(
    "/vascello/lista",
    response_model=List[Vascello],
    summary="Elenco flotta",
    description="""
Restituisce l'elenco completo dei vascelli registrati nella flotta.

### Ordinamento
I risultati sono ordinati alfabeticamente per nome del vascello.

### Utilizzo tipico
- Selezione vascelli per pianificazione
- Dashboard stato flotta
- Export anagrafica navi
    """,
    responses={
        200: {"description": "Lista flotta restituita con successo"}
    }
)
def lista_vascelli():
    if delegation_enabled():
        try:
            return get_json("/internal/vascello/lista")
        except AnagraficaDelegationError as exc:
            _handle_anagrafica_fallback(exc)

    conn = get_connection(); cur = conn.cursor()
    cur.execute("""
        SELECT id, mmsi, nome, capacita_passeggeri, costo_orario_esercizio, velocita_max_nodi, stato_salute_aggregato, profilo_consumo_json, data_creazione FROM vascello ORDER BY nome;
    """)
    rows = cur.fetchall(); conn.close()
    return [{"id": r[0], "mmsi": r[1], "nome": r[2], "capacita_passeggeri": r[3], "costo_orario_esercizio": r[4], "velocita_max_nodi": r[5], "stato_salute_aggregato": r[6], "profilo_consumo_json": r[7], "data_creazione": r[8].isoformat() if r[8] else None} for r in rows]


@router.get(
    "/vascello/{vascello_id}",
    response_model=Vascello,
    summary="Dettaglio vascello",
    description="""
Recupera tutti i dettagli tecnici e operativi di un vascello.

### Path Parameters
- **vascello_id**: UUID univoco del vascello

### Response
Oggetto `Vascello` completo con tutti i parametri registrati.
    """,
    responses={
        200: {"description": "Dettaglio vascello restituito"},
        404: {"description": "Vascello non trovato - UUID non esistente"}
    }
)
def get_vascello(vascello_id: str):
    if delegation_enabled():
        try:
            data = get_json(f"/internal/vascello/{vascello_id}")
            if data is None:
                raise HTTPException(404, "Vascello non trovato")
            return data
        except AnagraficaDelegationError as exc:
            _handle_anagrafica_fallback(exc)

    conn = get_connection(); cur = conn.cursor()
    cur.execute("""
        SELECT id, mmsi, nome, capacita_passeggeri, costo_orario_esercizio, velocita_max_nodi, stato_salute_aggregato, profilo_consumo_json, data_creazione FROM vascello WHERE id = %s
    """, (vascello_id,))
    row = cur.fetchone(); conn.close()
    if row is None:
        raise HTTPException(404, "Vascello non trovato")
    return {"id": row[0], "mmsi": row[1], "nome": row[2], "capacita_passeggeri": row[3], "costo_orario_esercizio": row[4], "velocita_max_nodi": row[5], "stato_salute_aggregato": row[6], "profilo_consumo_json": row[7], "data_creazione": row[8].isoformat() if row[8] else None}


@router.get(
    "/vascello/by_mmsi/{mmsi}",
    response_model=Vascello,
    summary="Ricerca vascello per MMSI",
    description="""
Ricerca un vascello tramite il codice MMSI.

### MMSI (Maritime Mobile Service Identity)
Codice univoco a 9 cifre assegnato dall'IMO (International Maritime Organization)
per l'identificazione delle navi nei sistemi AIS e di comunicazione.

### Path Parameters
- **mmsi**: Codice MMSI a 9 cifre (es. "247123456")

### Utilizzo tipico
- Integrazione con sistemi AIS
- Lookup da dati di tracking esterno
    """,
    responses={
        200: {"description": "Vascello trovato"},
        404: {"description": "Nessun vascello trovato con il MMSI specificato"}
    }
)
def get_vascello_by_mmsi(mmsi: str):
    if delegation_enabled():
        try:
            data = get_json(f"/internal/vascello/by_mmsi/{mmsi}")
            if data is None:
                raise HTTPException(404, detail=f"Nessun vascello trovato con MMSI={mmsi}")
            return data
        except AnagraficaDelegationError as exc:
            _handle_anagrafica_fallback(exc)

    conn = get_connection(); cur = conn.cursor()
    cur.execute("""
        SELECT id, mmsi, nome, capacita_passeggeri, costo_orario_esercizio, velocita_max_nodi, stato_salute_aggregato, profilo_consumo_json, data_creazione FROM vascello WHERE mmsi = %s LIMIT 1;
    """, (mmsi,))
    row = cur.fetchone(); conn.close()
    if row is None:
        raise HTTPException(404, detail=f"Nessun vascello trovato con MMSI={mmsi}")
    return {"id": row[0], "mmsi": row[1], "nome": row[2], "capacita_passeggeri": row[3], "costo_orario_esercizio": row[4], "velocita_max_nodi": row[5], "stato_salute_aggregato": row[6], "profilo_consumo_json": row[7], "data_creazione": row[8].isoformat() if row[8] else None}


@router.get(
    "/vascello/{mmsi}/percorso_attivo",
    response_model=PercorsoAttivoResponse,
    summary="Percorso attivo vascello",
    description="""
Restituisce i percorsi attualmente in esecuzione per il vascello.

### Logica
1. Identifica il vascello tramite MMSI
2. Cerca tutte le assegnazioni con stato `IN_CORSO` (reali e virtuali)
3. Recupera dettagli percorso associato per ciascuna

### Response
Oggetto contenente:
- **vascello**: dati identificativi nave
- **percorsi**: lista di percorsi attivi, ciascuno con indicatore `virtuale`

### Utilizzo tipico
- Dashboard operativa real-time
- Tracking flotta
- Integrazione con simulatore (capace di vedere percorsi virtuali)
    """,
    responses={
        200: {"description": "Percorsi attivi restituiti"},
        404: {"description": "Vascello non trovato o nessun percorso attivo"}
    }
)
def get_percorso_attivo_by_mmsi(mmsi: str):
    if delegation_enabled():
        try:
            vascello = get_json(f"/internal/vascello/by_mmsi/{mmsi}")
            if vascello is None:
                raise HTTPException(404, f"Vascello con MMSI {mmsi} non trovato")

            vascello_id = str(vascello.get("id"))
            piani = operativo_get_json("/internal/piano/lista") or []

            active_assignments = []
            for piano in piani:
                for assegnazione in (piano.get("assegnazioni") or []):
                    if str(assegnazione.get("vascello_id")) == vascello_id and assegnazione.get("stato_esecuzione") == "IN_CORSO":
                        active_assignments.append(assegnazione)

            if not active_assignments:
                raise HTTPException(404, f"Nessun percorso attivo per il vascello {vascello.get('nome')}")

            percorsi_list = []
            for assegnazione in active_assignments:
                percorso_id = assegnazione.get("percorso_id")
                if not percorso_id:
                    continue

                percorso = percorsi_get_json(f"/internal/percorso/{percorso_id}")
                if not isinstance(percorso, dict):
                    continue

                corsa_id = percorso.get("corsa_id")
                corsa = operativo_get_json(f"/internal/corsa/id/{corsa_id}") if corsa_id else {}

                tempo_percorrenza = percorso.get("tempo_percorrenza")
                try:
                    tempo_percorrenza = float(tempo_percorrenza) if tempo_percorrenza is not None else 0.0
                except Exception:
                    tempo_percorrenza = 0.0

                consumo = percorso.get("consumo")
                try:
                    consumo = float(consumo) if consumo is not None else 0.0
                except Exception:
                    consumo = 0.0

                percorsi_list.append({
                    "assegnazione": {
                        "id": assegnazione.get("id"),
                        "piano_id": assegnazione.get("piano_id"),
                        "virtuale": bool(assegnazione.get("virtuale")),
                    },
                    "percorso": {
                        "id": str(percorso.get("id")),
                        "corsa_id": str(corsa_id) if corsa_id else "",
                        "orario_partenza_schedulato": corsa.get("orario_partenza_schedulato") or "",
                        "tratta_id": str(corsa.get("tratta_id")) if corsa.get("tratta_id") else "",
                        "tratta_nome": corsa.get("tratta_nome") or "",
                        "tempo_percorrenza": tempo_percorrenza,
                        "consumo": consumo,
                    }
                })

            if not percorsi_list:
                raise HTTPException(404, f"Nessun percorso attivo per il vascello {vascello.get('nome')}")

            return {
                "vascello": {
                    "id": vascello_id,
                    "mmsi": str(vascello.get("mmsi")),
                    "nome": vascello.get("nome"),
                },
                "percorsi": percorsi_list,
            }
        except (AnagraficaDelegationError, OperativoDelegationError, PercorsiDelegationError) as exc:
            if not ENABLE_ANAGRAFICA_FALLBACK:
                raise HTTPException(status_code=503, detail="Internal services unavailable") from exc

    conn = get_connection(); cur = conn.cursor()
    try:
        cur.execute("SELECT id, nome FROM vascello WHERE mmsi = %s", (mmsi,))
        rv = cur.fetchone()
        if rv is None:
            raise HTTPException(404, f"Vascello con MMSI {mmsi} non trovato")
        vascello_id, nome_vascello = rv
        cur.execute("""
            SELECT a.id, a.percorso_id, a.piano_id, a.virtuale
            FROM assegnazione a
            JOIN percorso p ON a.percorso_id = p.id
            WHERE p.vascello_id = %s AND a.stato_esecuzione = 'IN_CORSO'
        """, (vascello_id,))
        rows = cur.fetchall()
        if not rows:
            raise HTTPException(404, f"Nessun percorso attivo per il vascello {nome_vascello}")
        
        percorsi_list = []
        for ra in rows:
            assegnazione_id, percorso_id, piano_id, virtuale = ra
            cur.execute("""
                SELECT p.id, p.id_corsa, c.orario_partenza_schedulato, c.tratta_id, t.nome, p.tempo_percorrenza_min, p.consumo
                FROM percorso p
                JOIN corsa c ON c.id = p.id_corsa
                LEFT JOIN tratta t ON c.tratta_id = t.id
                WHERE p.id = %s
            """, (percorso_id,))
            rp = cur.fetchone()
            if rp:
                p_id, corsa_id, orario_partenza_schedulato, tratta_id, tratta_nome, tempo_percorrenza, consumo = rp
                if isinstance(tempo_percorrenza, timedelta):
                    tempo_percorrenza = tempo_percorrenza.total_seconds() / 60.0
                percorsi_list.append({
                    "assegnazione": {
                        "id": assegnazione_id,
                        "piano_id": piano_id,
                        "virtuale": virtuale if virtuale is not None else False
                    },
                    "percorso": {
                        "id": p_id,
                        "corsa_id": corsa_id,
                        "orario_partenza_schedulato": orario_partenza_schedulato.isoformat(),
                        "tratta_id": tratta_id,
                        "tratta_nome": tratta_nome,
                        "tempo_percorrenza": tempo_percorrenza,
                        "consumo": consumo
                    }
                })
        
        return {
            "vascello": {"id": str(vascello_id), "mmsi": mmsi, "nome": nome_vascello},
            "percorsi": percorsi_list
        }
    finally:
        conn.close()


@router.get(
    "/vascello/{mmsi}/image",
    summary="Immagine vascello",
    description="""
Restituisce l'immagine fotografica del vascello.

### Path Parameters
- **mmsi**: Codice MMSI del vascello

### Response
- **Content-Type**: `image/jpg`
- **Body**: Immagine binaria JPEG

### Note
- L'immagine è memorizzata come BLOB nel database
- Utilizzabile direttamente come src in tag `<img>`
    """,
    responses={
        200: {"description": "Immagine restituita", "content": {"image/jpg": {}}},
        404: {"description": "Immagine non trovata o vascello non esistente"}
    }
)
def get_vascello_image(mmsi: str):
    if delegation_enabled():
        import requests as _req
        from app.core.config import ANAGRAFICA_SERVICE_URL
        try:
            resp = _req.get(
                f"{ANAGRAFICA_SERVICE_URL.rstrip('/')}/internal/vascello/{mmsi}/image",
                timeout=5.0,
            )
            if resp.status_code == 404:
                raise HTTPException(404, "Immagine non trovata")
            if resp.status_code >= 400:
                raise HTTPException(resp.status_code, "Errore anagrafica service")
            from fastapi.responses import Response
            return Response(content=resp.content, media_type="image/jpg")
        except _req.RequestException as exc:
            from app.core.config import ENABLE_ANAGRAFICA_FALLBACK
            if not ENABLE_ANAGRAFICA_FALLBACK:
                raise HTTPException(503, "Anagrafica service unavailable") from exc

    conn = get_connection(); cur = conn.cursor()
    try:
        cur.execute("SELECT immagine FROM vascello WHERE mmsi = %s", (mmsi,))
        row = cur.fetchone()
        if row is None or row[0] is None:
            raise HTTPException(404, "Immagine non trovata")
        from fastapi.responses import Response
        return Response(content=row[0], media_type="image/jpg")
    finally:
        conn.close()


@router.post(
    "/vascello/modifica",
    response_model=Vascello,
    summary="Modifica vascello",
    description="""
Aggiorna i parametri tecnici e operativi di un vascello esistente.

### Campi modificabili
Tutti i campi del modello `VascelloInput` possono essere aggiornati:
- Identificazione (MMSI, nome)
- Parametri operativi (capacità, costi, velocità)
- Stato salute e profilo consumo

### Note
- L'UUID del vascello rimane invariato
- Le assegnazioni esistenti mantengono il riferimento corretto
- Aggiornare lo stato_salute_aggregato per manutenzione predittiva
    """,
    responses={
        200: {"description": "Vascello aggiornato correttamente"},
        404: {"description": "Vascello non trovato - UUID non esistente"}
    }
)
def modifica_vascello(data: VascelloModificaInput):
    if delegation_enabled():
        try:
            return post_json("/internal/vascello/modifica", {
                "id": data.id,
                "mmsi": data.mmsi,
                "nome": data.nome,
                "capacita_passeggeri": data.capacita_passeggeri,
                "costo_orario_esercizio": data.costo_orario_esercizio,
                "velocita_max_nodi": data.velocita_max_nodi,
                "stato_salute_aggregato": data.stato_salute_aggregato,
                "profilo_consumo_json": data.profilo_consumo_json,
            })
        except AnagraficaDelegationError as exc:
            _handle_anagrafica_fallback(exc)

    conn = get_connection(); cur = conn.cursor()
    cur.execute("""
        UPDATE vascello SET mmsi=%s, nome=%s, capacita_passeggeri=%s, costo_orario_esercizio=%s, velocita_max_nodi=%s, stato_salute_aggregato=%s, profilo_consumo_json=%s WHERE id=%s RETURNING id, mmsi, nome, capacita_passeggeri, costo_orario_esercizio, velocita_max_nodi, stato_salute_aggregato, profilo_consumo_json, data_creazione;
    """, (data.mmsi, data.nome, data.capacita_passeggeri, data.costo_orario_esercizio, data.velocita_max_nodi, data.stato_salute_aggregato, json.dumps(data.profilo_consumo_json) if data.profilo_consumo_json else None, data.id))
    row = cur.fetchone(); conn.commit(); conn.close()
    if row is None:
        raise HTTPException(404, "Vascello non trovato")
    return {"id": row[0], "mmsi": row[1], "nome": row[2], "capacita_passeggeri": row[3], "costo_orario_esercizio": row[4], "velocita_max_nodi": row[5], "stato_salute_aggregato": row[6], "profilo_consumo_json": row[7], "data_creazione": row[8].isoformat() if row[8] else None}


@router.post(
    "/vascello/elimina",
    summary="Elimina vascello",
    description="""
Elimina definitivamente un vascello dal sistema.

### Attenzione
- L'eliminazione è **irreversibile**
- Verificare che non esistano:
  - Percorsi associati al vascello
  - Assegnazioni attive
  - Piani operativi con riferimenti

### Prerequisiti
- Nessuna assegnazione con stato `IN_CORSO`
- Storico assegnazioni sarà mantenuto (soft reference)
    """,
    responses={
        200: {"description": "Vascello eliminato con successo", "content": {"application/json": {"example": {"id": "uuid", "esito": "eliminato"}}}},
        404: {"description": "Vascello non trovato - UUID non esistente"}
    }
)
def elimina_vascello(data: VascelloDeleteInput):
    if delegation_enabled():
        try:
            return post_json("/internal/vascello/elimina", {"id": data.id})
        except AnagraficaDelegationError as exc:
            _handle_anagrafica_fallback(exc)

    conn = get_connection(); cur = conn.cursor()
    cur.execute("DELETE FROM vascello WHERE id = %s RETURNING id;", (data.id,))
    row = cur.fetchone(); conn.commit(); conn.close()
    if row is None:
        raise HTTPException(404, "Vascello non trovato")
    return {"id": data.id, "esito": "eliminato"}
