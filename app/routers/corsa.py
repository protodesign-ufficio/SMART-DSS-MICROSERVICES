from fastapi import APIRouter, HTTPException, Query, Path
from typing import List, Optional
from app.core.database import get_connection
from app.core.operativo_client import delegation_enabled as operativo_delegation_enabled, get_json as operativo_get_json, post_json as operativo_post_json, OperativoDelegationError
from app.core.forecast_client import delegation_enabled as forecast_delegation_enabled, post_json as forecast_post_json, ForecastDelegationError
from app.core.config import ENABLE_FORECAST_FALLBACK, ENABLE_OPERATIVO_FALLBACK
from app.models.corsa import (
    PrevisioneRequest, PrevisioneResponse, CorsaInput, CorsaCreated,
    OrariResponse, CorsaWithPrevisione, CorsaGiornoItem, DashboardCorsaItem, CorsaAPI
)
from app.services import previsione_service, corsa_service

router = APIRouter(prefix="", tags=["Corse"])
ALLOWED_INCLUDES_CORSA = {"tratta", "percorsi"}


def _handle_operativo_fallback(exc: Exception) -> None:
    if not ENABLE_OPERATIVO_FALLBACK:
        raise HTTPException(status_code=503, detail="Operativo service unavailable") from exc


@router.post(
    "/corsa/{corsa_id}/prevedi",
    response_model=PrevisioneResponse,
    summary="Calcola previsione domanda passeggeri",
    description="""
    Calcola la previsione di domanda passeggeri per una specifica corsa.

    ### Flusso:
    1. Recupero corsa dal DB
    2. Chiamata microservizio ML
    3. Salvataggio previsione
    4. Restituzione stima + confidenza

    ### Output:
    - Passeggeri stimati
    - Intervallo di confidenza 95%
    - Dettaglio predizione ML

        ### Parametri opzionali
        - `disable_cache` (query, default `false`):
            se `true`, ignora eventuali previsioni recenti in cache e forza sempre
            una nuova chiamata al microservizio ML.

        ### Esempio
        - `/corsa/{id}/prevedi?disable_cache=true`
    """,
    responses={
        200: {"description": "Previsione calcolata correttamente"},
        404: {"description": "Corsa non trovata"},
        500: {"description": "Errore servizio ML"}
    }
)
def previsione_endpoint(
    corsa_id: str,
    req: PrevisioneRequest,
    disable_cache: bool = Query(False, description="Se true forza il ricalcolo senza usare cache")
):
    if forecast_delegation_enabled():
        try:
            disable_cache_q = "true" if disable_cache else "false"
            return forecast_post_json(f"/internal/previsione/corsa/{corsa_id}/calcola?disable_cache={disable_cache_q}", {
                "biglietti_venduti_al_sample": req.biglietti_venduti_al_sample,
                "festivo": req.festivo,
            })
        except ForecastDelegationError as exc:
            if not ENABLE_FORECAST_FALLBACK:
                raise HTTPException(status_code=503, detail="Forecast service unavailable") from exc
            pass

    if not ENABLE_FORECAST_FALLBACK and forecast_delegation_enabled():
        raise HTTPException(status_code=503, detail="Forecast service unavailable")

    return previsione_service.calcola_previsione(corsa_id, req, disable_cache=disable_cache)


@router.post(
    "/corsa/crea",
    response_model=CorsaCreated,
    summary="Crea una nuova corsa",
    description="""
    Crea una nuova corsa associata a una tratta.

    Il sistema genera automaticamente:
    - UUID corsa
    - Nome leggibile nel formato: TRATTA-YYYYMMDD-HHMM

    ### Esempio nome:
    SAL-AMA-20250125-0930

    ### Validazioni:
    - Formato data: YYYY-MM-DD
    - Formato orario: HH:MM o HHMM
    """,
    responses={
        200: {"description": "Corsa creata correttamente"},
        400: {"description": "Formato data/orario non valido"},
        404: {"description": "Tratta non trovata"},
        409: {"description": "Corsa già esistente"}
    }
)
def crea_corsa_endpoint(data: CorsaInput):
    if operativo_delegation_enabled():
        try:
            return operativo_post_json("/internal/corsa/crea", {
                "tratta_id": data.tratta_id,
                "data": data.data,
                "orario": data.orario,
                "orario_arrivo_max": data.orario_arrivo_max,
            })
        except OperativoDelegationError as exc:
            _handle_operativo_fallback(exc)

    return corsa_service.crea_corsa(data)


@router.get(
    "/corsa/orari/{tratta_id}",
    response_model=OrariResponse,
    summary="Elenco orari per tratta",
    description="""
    Restituisce tutti gli orari programmati per una specifica tratta e data.
    """,
    responses={
        200: {"description": "Orari restituiti correttamente"},
        400: {"description": "Formato data non valido"},
        404: {"description": "Tratta non trovata"}
    }
)
def get_orari(tratta_id: str, data: str):
    if operativo_delegation_enabled():
        try:
            return operativo_get_json(f"/internal/corsa/orari/{tratta_id}?data={data}")
        except OperativoDelegationError as exc:
            _handle_operativo_fallback(exc)

    return corsa_service.get_orari(tratta_id, data)


@router.get(
    "/corsa/lista",
    response_model=List[CorsaWithPrevisione],
    tags=["Corse"],
    summary="Elenco corse future",
    description="""
    Restituisce tutte le corse future (orario > NOW).

    Include:
    - Info tratta
    - Previsione domanda se disponibile
    """,
    responses={
        200: {"description": "Lista corse restituita correttamente"}
    }
)
def lista_corse():
    if operativo_delegation_enabled():
        try:
            return operativo_get_json("/internal/corsa/lista")
        except OperativoDelegationError as exc:
            _handle_operativo_fallback(exc)

    return corsa_service.lista_corse()


@router.get(
    "/corsa/giorno",
    response_model=List[CorsaGiornoItem],
    tags=["Corse"],
    summary="Elenco corse per giorno",
    description="""
    Restituisce tutte le corse pianificate in una data specifica.
    """,
    responses={
        200: {"description": "Elenco corse restituito"},
        400: {"description": "Formato data non valido"}
    }
)
def get_corse_by_giorno(
    giorno: str = Query(..., description="YYYY-MM-DD"),
    solofuture: bool = Query(False, description="Se True, restituisce solo le corse non ancora partite")
):
    if operativo_delegation_enabled():
        try:
            query_solofuture = "true" if solofuture else "false"
            return operativo_get_json(f"/internal/corsa/giorno?giorno={giorno}&solofuture={query_solofuture}")
        except OperativoDelegationError as exc:
            _handle_operativo_fallback(exc)

    return corsa_service.get_corse_by_giorno(giorno, solofuture)

@router.get(
    "/corsa/{corsa_id}",
    response_model=CorsaAPI,
    response_model_exclude_none=True,
    tags=["Corse"],
    summary="Dettaglio corsa",
    description="""
    Restituisce il dettaglio di una corsa.

    Per impostazione predefinita l'endpoint restituisce **solo i dati dell'entità corsa**.

    È possibile espandere dinamicamente le relazioni tramite il parametro query `include`.

    Entità espandibili:
    - `tratta`: dettagli della tratta associata
    - `percorsi`: percorsi calcolati per la corsa

    La previsione passeggeri, se presente, viene **sempre restituita**.

    Esempi:
    - `/corsa/{id}`
      → restituisce solo la corsa + previsione

    - `/corsa/{id}?include=tratta`
      → corsa + previsione + tratta

    - `/corsa/{id}?include=tratta,percorsi`
      → corsa + previsione + tratta + percorsi
    """,
    responses={
        200: {"description": "Dettaglio corsa restituito"},
        404: {"description": "Corsa non trovata"},
        400: {"description": "Parametro include non valido"}
    }
)
def get_corsa(
    corsa_id: str,
    include: Optional[str] = Query(None)
):
    includes = set(s.strip() for s in include.split(",")) if include else set()
    invalid = includes - {"tratta", "percorsi"}
    if invalid:
        raise HTTPException(
            400,
            f"include non valido: {sorted(invalid)}. Ammessi: ['tratta','percorsi']"
        )

    conn = get_connection()
    cur = conn.cursor()

    try:
        # ======================
        # QUERY BASE: CORSA
        # ======================
        cur.execute("""
            SELECT
                id,
                nome,
                tratta_id,
                orario_partenza_schedulato,
                orario_arrivo_max,
                previsione_domanda_id
            FROM corsa
            WHERE id = %s
            LIMIT 1;
        """, (corsa_id,))
        row = cur.fetchone()

        if row is None:
            raise HTTPException(404, f"Corsa non trovata: {corsa_id}")

        (
            cid, nome, tratta_id,
            orario_ps, orario_max, previsione_id
        ) = row

        # ======================
        # PREVISIONE (SEMPRE)
        # ======================
        previsione_obj = None
        if previsione_id:
            cur.execute("""
                SELECT
                    id,
                    passeggeri_stimati,
                    confidenza_min,
                    confidenza_max,
                    created_at
                FROM previsione_domanda
                WHERE id = %s
                LIMIT 1;
            """, (previsione_id,))
            pv = cur.fetchone()

            if pv:
                (pvid, stim, cmin, cmax, created_at) = pv
                previsione_obj = {
                    "id": str(pvid),
                    "passeggeri_stimati": stim,
                    "confidenza_min": cmin,
                    "confidenza_max": cmax,
                    "created_at": created_at.isoformat() if created_at else None
                }

        response = {
            "corsa_id": str(cid),
            "nome": nome,
            "orario_partenza_schedulato": orario_ps.isoformat() if orario_ps else None,
            "orario_arrivo_max": orario_max.isoformat() if orario_max else None,
            "previsione_domanda_id": str(previsione_id) if previsione_id else None,
            "previsione": previsione_obj
        }

        # ======================
        # INCLUDE: TRATTA
        # ======================
        if "tratta" in includes and tratta_id:
            cur.execute("""
                SELECT
                    id,
                    porto_partenza_id,
                    porto_arrivo_id,
                    distanza_miglia,
                    porti_intermedi,
                    tratta_multiporto,
                    ST_AsGeoJSON(geom_rotta_standard)
                FROM tratta
                WHERE id = %s
                LIMIT 1;
            """, (tratta_id,))
            t = cur.fetchone()

            if t:
                (
                    tid, porto_partenza_id, porto_arrivo_id,
                    dist, porti_intermedi, multi, geom
                ) = t

                cur.execute("SELECT nome FROM porto WHERE id = %s", (porto_partenza_id,))
                nome_pp = cur.fetchone()
                cur.execute("SELECT nome FROM porto WHERE id = %s", (porto_arrivo_id,))
                nome_pa = cur.fetchone()

                nome_tratta = None
                if nome_pp and nome_pa:
                    nome_tratta = f"{nome_pp[0]}-{nome_pa[0]}"

                response["tratta"] = {
                    "id": str(tid),
                    "nome": nome_tratta,
                    "porto_partenza_id": str(porto_partenza_id),
                    "porto_arrivo_id": str(porto_arrivo_id),
                    "distanza_miglia": dist,
                    "porti_intermedi": porti_intermedi,
                    "tratta_multiporto": multi,
                    "geometry": geom
                }

        # ======================
        # INCLUDE: PERCORSI
        # ======================
        if "percorsi" in includes:
            cur.execute("""
                SELECT
                    id,
                    pref,
                    vref,
                    EXTRACT(EPOCH FROM tempo_percorrenza_min)/60.0,
                    consumo,
                    ST_AsGeoJSON(geom_rotta),
                    comfort,
                    distanza_nm
                FROM percorso
                WHERE id_corsa = %s
                ORDER BY created_at ASC;
            """, (cid,))
            rows = cur.fetchall()

            percorsi = []
            for r in rows:
                (
                    pid, pref, vref, tempo_perc_min,
                    consumo, geom_rotta, comfort, distanza_nm
                ) = r

                percorsi.append({
                    "percorso_id": str(pid),
                    "pref": pref,
                    "vref": vref,
                    "tempo_percorrenza": tempo_perc_min,
                    "consumo": consumo,
                    "geom_rotta": geom_rotta,
                    "comfort": comfort,
                    "distanza_nm": distanza_nm
                })

            response["percorsi"] = percorsi

        return response

    finally:
        conn.close()

@router.get(
    "/dashboard/corse",
    response_model=List[DashboardCorsaItem],
    tags=["Corse"],
    summary="Dashboard riepilogo corse",
    description="""
Restituisce una vista aggregata delle corse ottimizzata per dashboard operative.

### Contenuto
Per ogni corsa include:
- Identificativi corsa e tratta
- Orario di partenza
- **Previsione passeggeri** (se disponibile)
- **Intervallo di confidenza** 95% (CI min/max)

### Utilizzo tipico
- Dashboard controllo operativo
- Monitor real-time corse giornaliere
- Panoramica rapida domanda prevista
    """,
    responses={
        200: {"description": "Dashboard generata con successo"}
    }
)
def dashboard_corse():
    return corsa_service.dashboard_corse()


@router.post(
    "/corsa/modifica",
    response_model=CorsaCreated,
    summary="Modifica corsa",
    description="""
Aggiorna una corsa esistente con nuovi parametri.

### Campi modificabili (tutti opzionali)
- **tratta_id**: Nuova tratta di riferimento
- **data**: Nuova data (formato YYYY-MM-DD)
- **orario**: Nuovo orario partenza (HH:MM)
- **orario_arrivo_max**: Nuovo limite arrivo (HH:MM)

### Comportamento
- Il **nome** della corsa viene rigenerato se cambiano tratta/data/orario
- I **percorsi esistenti** restano associati (potrebbero non essere più validi)
- La **previsione domanda** potrebbe richiedere ricalcolo

### Note
- Fornire solo i campi da modificare
- L'UUID della corsa rimane invariato
    """,
    responses={
        200: {"description": "Corsa aggiornata correttamente"},
        400: {"description": "Formato data/orario non valido"},
        404: {"description": "Corsa o tratta non trovata"}
    }
)
def modifica_corsa(data: dict):
    if operativo_delegation_enabled():
        try:
            return operativo_post_json("/internal/corsa/modifica", data)
        except OperativoDelegationError as exc:
            _handle_operativo_fallback(exc)

    return corsa_service.modifica_corsa(data)


@router.post(
    "/corsa/elimina",
    summary="Elimina corsa",
    description="""
Elimina definitivamente una corsa dal sistema.

### Attenzione
- L'eliminazione è **irreversibile**
- Vengono eliminati anche:
  - Previsioni domanda associate
  - Percorsi calcolati per la corsa
  - Assegnazioni pianificate (se non IN_CORSO)

### Prerequisiti
- Nessuna assegnazione con stato `IN_CORSO`
- Corsa non deve essere in esecuzione

### Input
```json
{"id": "uuid-corsa"}
```
    """,
    responses={
        200: {"description": "Corsa eliminata con successo", "content": {"application/json": {"example": {"id": "uuid", "esito": "eliminato"}}}},
        404: {"description": "Corsa non trovata - UUID non esistente"},
        409: {"description": "Impossibile eliminare: assegnazione in corso"}
    }
)
def elimina_corsa(data: dict):
    if operativo_delegation_enabled():
        try:
            return operativo_post_json("/internal/corsa/elimina", data)
        except OperativoDelegationError as exc:
            _handle_operativo_fallback(exc)

    return corsa_service.elimina_corsa(data)
