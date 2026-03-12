from fastapi import APIRouter, HTTPException, Path, Query
from typing import List, Optional
from app.core.database import get_connection
from app.core.percorsi_client import delegation_enabled as percorsi_delegation_enabled, get_json as percorsi_get_json, post_json as percorsi_post_json, PercorsiDelegationError
from app.core.config import ENABLE_PERCORSI_FALLBACK
from app.models.percorso import Percorso, PercorsiByCorsa, PercorsoDeleteInput, PercorsoAPI
from app.models.common import VariazionePercorsoInput, VariazionePercorsoResponse
from app.services.variazione_percorso_service import applica_variazione_percorso
from datetime import timedelta

ALLOWED_ORDER_BY = {"tempo_percorrenza_min","consumo","created_at","pref","vref","comfort","distanza_nm"}
ALLOWED_INCLUDES = {"corsa", "tratta", "vascello"}

router = APIRouter(prefix="", tags=["Percorsi"])


def _handle_percorsi_fallback(exc: Exception) -> None:
    if not ENABLE_PERCORSI_FALLBACK:
        raise HTTPException(status_code=503, detail="Percorsi service unavailable") from exc


@router.get(
    "/percorso/{percorso_id}",
    response_model=PercorsoAPI,
    response_model_exclude_none=True,   
    summary="Dettaglio percorso",
    description="""
    Restituisce il dettaglio di un percorso.

    Per impostazione predefinita l'endpoint restituisce **solo i dati dell'entità percorso**.

    È possibile espandere dinamicamente le relazioni tramite il parametro query `include`,
    specificando una lista separata da virgole delle entità da includere.

    Entità espandibili:
    - `corsa`: informazioni sulla corsa associata
    - `tratta`: dettagli della tratta associata alla corsa
    - `vascello`: dettagli del vascello associato al percorso

    Esempi:
    - `/percorso/{id}`
      → restituisce solo il percorso

    - `/percorso/{id}?include=corsa`
      → restituisce percorso + corsa

    - `/percorso/{id}?include=corsa,tratta,vascello`
      → restituisce la gerarchia completa:
        percorso → corsa → tratta → vascello

    Questo approccio consente di:
    - ridurre il payload quando non servono tutte le relazioni
    - evitare join inutili
    - mantenere una struttura semantica coerente e modulare dell'API
    """,
    responses={
        200: {"description": "Percorso restituito"},
        404: {"description": "Percorso non trovato"},
        400: {"description": "Parametro include non valido"}
    }
)
def get_percorso(
    percorso_id: str,
    include: Optional[str] = Query(None)
):
    if percorsi_delegation_enabled():
        try:
            if include:
                return percorsi_get_json(f"/internal/percorso/{percorso_id}?include={include}")
            return percorsi_get_json(f"/internal/percorso/{percorso_id}")
        except PercorsiDelegationError as exc:
            _handle_percorsi_fallback(exc)

    includes = set(s.strip() for s in include.split(",")) if include else set()
    invalid = includes - ALLOWED_INCLUDES
    if invalid:
        raise HTTPException(
            400,
            f"include non valido: {sorted(invalid)}. Ammessi: {sorted(ALLOWED_INCLUDES)}"
        )

    conn = get_connection()
    cur = conn.cursor()

    try:
        # ======================
        # QUERY BASE: PERCORSO
        # ======================
        cur.execute("""
            SELECT
                p.id,
                p.id_corsa,
                p.pref,
                p.vref,
                EXTRACT(EPOCH FROM p.tempo_percorrenza_min)/60.0 AS tempo_percorrenza_min,
                p.consumo,
                ST_AsGeoJSON(p.geom_rotta),
                p.vascello_id,
                p.comfort,
                p.distanza_nm,
                p.weather_cache_keys
            FROM percorso p
            WHERE p.id = %s
            LIMIT 1;
        """, (percorso_id,))

        row = cur.fetchone()
        if row is None:
            raise HTTPException(404, f"Percorso non trovato: {percorso_id}")

        (
            pid, corsa_id, pref, vref, tempo_perc_min, consumo,
            geom_rotta, vascello_id, comfort, distanza_nm,
            weather_cache_keys
        ) = row

        response = {
            "percorso_id": str(pid),
            #"corsa_id": str(corsa_id),
            #"vascello_id": str(vascello_id) if vascello_id else None,
            "pref": pref,
            "vref": vref,
            "tempo_percorrenza": tempo_perc_min,
            "consumo": consumo,
            "geom_rotta": geom_rotta,
            "comfort": comfort,
            "distanza_nm": distanza_nm,
            "weather_cache_keys": weather_cache_keys
        }

        tratta_id = None
        previsione_id = None
        porto_partenza_id = None
        porto_arrivo_id = None
        porti_intermedi = None

        # ======================
        # INCLUDE: CORSA
        # ======================
        if includes & {"corsa", "tratta", "porti"}:
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
            c = cur.fetchone()

            if c:
                (
                    cid, cnome, tratta_id,
                    orario_ps, orario_max, previsione_id
                ) = c

                # Recupero SEMPRE nome tratta
                cur.execute("SELECT nome FROM tratta WHERE id = %s", (tratta_id,))
                t_nome = cur.fetchone()
                nome_tratta = t_nome[0] if t_nome else None

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

                if "corsa" in includes:
                    response["corsa"] = {
                        "id": str(cid),
                        "nome": cnome,
                        "tratta_id": str(tratta_id),
                        "tratta_nome": nome_tratta,
                        "orario_partenza_schedulato": orario_ps.isoformat() if orario_ps else None,
                        "orario_arrivo_max": orario_max.isoformat() if orario_max else None,
                        "previsione_domanda_id": str(previsione_id) if previsione_id else None,
                        "previsione": previsione_obj
                    }

        # ======================
        # INCLUDE: VASCELLO
        # ======================
        if "vascello" in includes and vascello_id:
            cur.execute("""
                SELECT
                    id,
                    mmsi,
                    nome,
                    capacita_passeggeri,
                    costo_orario_esercizio,
                    velocita_max_nodi,
                    stato_salute_aggregato,
                    profilo_consumo_json,
                    data_creazione
                FROM vascello
                WHERE id = %s
                LIMIT 1;
            """, (vascello_id,))
            v = cur.fetchone()

            if v:
                (
                    vid, mmsi, nome, cap, costo,
                    vmax, salute, profilo, dc
                ) = v

                response["vascello"] = {
                    "id": str(vid),
                    "mmsi": mmsi,
                    "nome": nome,
                    "capacita_passeggeri": cap,
                    "costo_orario_esercizio": costo,
                    "velocita_max_nodi": vmax,
                    "stato_salute_aggregato": salute,
                    "profilo_consumo_json": profilo,
                    "data_creazione": dc.isoformat() if dc else None
                }

        # ======================
        # INCLUDE: TRATTA
        # ======================
        if includes & {"tratta", "porti"} and tratta_id:
            cur.execute("""
                SELECT
                    id,
                    nome,
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
                    tid, tnome, porto_partenza_id, porto_arrivo_id,
                    dist, porti_intermedi, multi, geom
                ) = t

                if "tratta" in includes:
                    # recupero nomi porti per costruire nome tratta
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
                    if "corsa" in response:
                        response["corsa"]["tratta_nome"] = nome_tratta
        return response

    finally:
        conn.close()


@router.get(
    "/percorso/by_corsa/{corsa_id}",
    response_model=PercorsiByCorsa,
    response_model_exclude_none=True,
    summary="Elenco percorsi per corsa",
    description="""
    Restituisce i percorsi calcolati per una specifica corsa.

    È possibile espandere dinamicamente le relazioni tramite il parametro query `include`,
    specificando una lista separata da virgole delle entità da includere.

    Entità espandibili:
    - `corsa`: informazioni sulla corsa associata
    - `tratta`: dettagli della tratta associata alla corsa
    - `vascello`: dettagli del vascello associato al percorso
    """,
    responses={
        200: {"description": "Lista percorsi restituita"},
        404: {"description": "Nessun percorso trovato"},
        400: {"description": "Parametro include non valido"}
    }
)
def get_percorsi_by_corsa(
    corsa_id: str = Path(...),
    order_by: str = Query("tempo_percorrenza_min"),
    mode: str = Query("ASC"),
    limit: int = Query(100, ge=1),
    vascello_id: Optional[str] = Query(None),
    include: Optional[str] = Query(None)
):
    if percorsi_delegation_enabled():
        try:
            query_parts = [
                f"order_by={order_by}",
                f"mode={mode}",
                f"limit={limit}",
            ]
            if vascello_id is not None:
                query_parts.append(f"vascello_id={vascello_id}")
            if include:
                query_parts.append(f"include={include}")
            return percorsi_get_json(f"/internal/percorso/by_corsa/{corsa_id}?{'&'.join(query_parts)}")
        except PercorsiDelegationError as exc:
            _handle_percorsi_fallback(exc)

    if order_by not in ALLOWED_ORDER_BY:
        raise HTTPException(400, detail=f"order_by non valido. Valori ammessi: {sorted(ALLOWED_ORDER_BY)}")
    includes = set(s.strip() for s in include.split(",")) if include else set()
    invalid = includes - ALLOWED_INCLUDES
    if invalid:
        raise HTTPException(
            400,
            f"include non valido: {sorted(invalid)}. Ammessi: {sorted(ALLOWED_INCLUDES)}"
        )

    conn = get_connection()
    cur = conn.cursor()

    try:
        where_clauses = ["id_corsa = %s"]
        params = [corsa_id]
        if vascello_id is not None:
            where_clauses.append("vascello_id = %s")
            params.append(vascello_id)
        params.append(limit)

        query = f"""
            SELECT
                p.id,
                p.id_corsa,
                p.pref,
                p.vref,
                EXTRACT(EPOCH FROM p.tempo_percorrenza_min)/60.0 AS tempo_percorrenza_min,
                p.consumo,
                ST_AsGeoJSON(p.geom_rotta),
                c.orario_partenza_schedulato,
                p.created_at,
                p.vascello_id,
                v.capacita_passeggeri,
                pv.passeggeri_stimati,
                pv.confidenza_min,
                pv.confidenza_max,
                pv.created_at AS previsione_created_at,
                p.comfort,
                p.distanza_nm,
                p.weather_cache_keys
            FROM percorso p
            JOIN corsa c ON p.id_corsa = c.id
            LEFT JOIN vascello v ON p.vascello_id = v.id
            LEFT JOIN previsione_domanda pv ON pv.id = c.previsione_domanda_id
            WHERE {' AND '.join(where_clauses)}
            ORDER BY {order_by} {mode}
            LIMIT %s;
        """

        cur.execute(query, params)
        rows = cur.fetchall()

        if not rows:
            raise HTTPException(404, detail=f"Nessun percorso trovato per corsa_id: {corsa_id}")

        corsa_obj = None
        tratta_obj = None
        if includes & {"corsa", "tratta"}:
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
            c = cur.fetchone()

            if c:
                (
                    cid, cnome, tratta_id,
                    orario_ps, orario_max, previsione_id
                ) = c

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

                nome_tratta = None
                if tratta_id:
                    cur.execute("""
                        SELECT
                            id,
                            nome,
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
                            tid, tnome, porto_partenza_id, porto_arrivo_id,
                            dist, porti_intermedi, multi, geom
                        ) = t

                        cur.execute("SELECT nome FROM porto WHERE id = %s", (porto_partenza_id,))
                        nome_pp = cur.fetchone()
                        cur.execute("SELECT nome FROM porto WHERE id = %s", (porto_arrivo_id,))
                        nome_pa = cur.fetchone()

                        if nome_pp and nome_pa:
                            nome_tratta = f"{nome_pp[0]}-{nome_pa[0]}"

                        if "tratta" in includes:
                            tratta_obj = {
                                "id": str(tid),
                                "nome": nome_tratta,
                                "porto_partenza_id": str(porto_partenza_id),
                                "porto_arrivo_id": str(porto_arrivo_id),
                                "distanza_miglia": dist,
                                "porti_intermedi": porti_intermedi,
                                "tratta_multiporto": multi,
                                "geometry": geom
                            }

                if "corsa" in includes:
                    corsa_obj = {
                        "id": str(cid),
                        "nome": cnome,
                        "tratta_id": str(tratta_id),
                        "tratta_nome": nome_tratta,
                        "orario_partenza_schedulato": orario_ps.isoformat() if orario_ps else None,
                        "orario_arrivo_max": orario_max.isoformat() if orario_max else None,
                        "previsione_domanda_id": str(previsione_id) if previsione_id else None,
                        "previsione": previsione_obj
                    }

        vascello_map = {}
        if "vascello" in includes:
            vascello_ids = {r[9] for r in rows if r[9]}
            if vascello_ids:
                cur.execute("""
                    SELECT
                        id,
                        mmsi,
                        nome,
                        capacita_passeggeri,
                        costo_orario_esercizio,
                        velocita_max_nodi,
                        stato_salute_aggregato,
                        profilo_consumo_json,
                        data_creazione
                    FROM vascello
                    WHERE id = ANY(%s::uuid[]);
                """, (list(vascello_ids),))
                for v in cur.fetchall():
                    (
                        vid, mmsi, nome, cap, costo,
                        vmax, salute, profilo, dc
                    ) = v
                    vascello_map[str(vid)] = {
                        "id": str(vid),
                        "mmsi": mmsi,
                        "nome": nome,
                        "capacita_passeggeri": cap,
                        "costo_orario_esercizio": costo,
                        "velocita_max_nodi": vmax,
                        "stato_salute_aggregato": salute,
                        "profilo_consumo_json": profilo,
                        "data_creazione": dc.isoformat() if dc else None
                    }

        percorsi = []
        for r in rows:
            (
                pid, cid, pref, vref, tempo_perc_min, consumo, geom_rotta,
                orario_partenza_schedulato, created_at, vascello_id,
                capacita_passeggeri, previsione_previsti, confidenza_min,
                confidenza_max, previsione_data, comfort, distanza_nm, weather_cache_keys
            ) = r

            orario_arrivo_previsto = None
            if orario_partenza_schedulato is not None and tempo_perc_min is not None:
                try:
                    orario_arrivo_previsto = (
                        orario_partenza_schedulato + timedelta(minutes=float(tempo_perc_min))
                    ).isoformat()
                except Exception:
                    orario_arrivo_previsto = None

            passeggeri = {
                "capacita_vascello": capacita_passeggeri,
                "previsione_confidenza_min": confidenza_min,
                "previsione_confidenza_max": confidenza_max,
                "previsti": previsione_previsti,
                "data_previsione": previsione_data.isoformat() if previsione_data is not None else None
            }

            item = {
                "id": str(pid),
                "corsa_id": str(cid),
                "vascello_id": str(vascello_id) if vascello_id else None,
                "orario_partenza_schedulato": orario_partenza_schedulato.isoformat()
                if orario_partenza_schedulato is not None else None,
                "tempo_percorrenza": tempo_perc_min,
                "orario_arrivo_previsto": orario_arrivo_previsto,
                "passeggeri": passeggeri,
                "consumo": consumo,
                "comfort": comfort,
                "distanza_nm": distanza_nm,
                "pref": pref,
                "vref": vref,
                "geom_rotta": geom_rotta,
                "weather_cache_keys": weather_cache_keys,
            }

            if "corsa" in includes and corsa_obj:
                item["corsa"] = corsa_obj
            if "tratta" in includes and tratta_obj:
                item["tratta"] = tratta_obj
            if "vascello" in includes and vascello_id:
                vascello_data = vascello_map.get(str(vascello_id))
                if vascello_data:
                    item["vascello"] = vascello_data

            percorsi.append(item)

        return {"corsa_id": corsa_id, "percorsi": percorsi}
    finally:
        conn.close()


@router.post(
    "/percorso/elimina",
    summary="Elimina un percorso",
    description="Elimina un percorso dato il suo ID",
    responses={
        200: {"description": "Percorso eliminato"},
        404: {"description": "Percorso non trovato"}
    }
)
def elimina_percorso(payload: PercorsoDeleteInput):
    if percorsi_delegation_enabled():
        try:
            return percorsi_post_json("/internal/percorso/elimina", {"id": payload.id})
        except PercorsiDelegationError as exc:
            _handle_percorsi_fallback(exc)

    conn = get_connection()
    cur = conn.cursor()

    try:
        # verifica esistenza
        cur.execute(
            "SELECT id FROM percorso WHERE id = %s",
            (payload.id,)
        )
        row = cur.fetchone()

        if row is None:
            raise HTTPException(
                status_code=404,
                detail=f"Percorso non trovato: {payload.id}"
            )

        # eliminazione
        cur.execute(
            "DELETE FROM percorso WHERE id = %s",
            (payload.id,)
        )

        conn.commit()

        return {
            "status": "ok",
            "percorso_id": payload.id
        }

    finally:
        conn.close()


@router.post(
    "/percorso/applica_variazione",
    response_model=VariazionePercorsoResponse,
    summary="Applica variazione a un percorso",
    description="""
    Applica una variazione controllata a un percorso esistente e crea una copia modificata.

    Tipi di variazione supportati:

    - **GUASTO**: Simula un guasto al motore o problema meccanico.
      Sceglie casualmente un waypoint con vref valido e divide la velocità
      di riferimento per 8, simulando una navigazione a velocità ridotta.

    - **DEVIAZIONE**: Simula una deviazione dalla rotta originale.
      Sceglie una coppia di waypoint consecutivi e inserisce un waypoint
      intermedio spostato perpendicolarmente rispetto alla retta tra i due.
      L'offset è configurabile (default: 0.5 miglia nautiche).

    La variazione crea sempre un **nuovo percorso** nel database,
    mantenendo intatto il percorso originale.

    Esempi di utilizzo:
    - Testare il comportamento del simulatore in caso di avaria
    - Validare la robustezza delle assegnazioni in scenari alterati
    - Generare scenari what-if per analisi di rischio
    """,
    responses={
        200: {"description": "Variazione applicata con successo"},
        400: {"description": "Tipo variazione non valido o percorso non adatto"},
        404: {"description": "Percorso non trovato"}
    }
)
def post_applica_variazione(payload: VariazionePercorsoInput):
    if percorsi_delegation_enabled():
        try:
            return percorsi_post_json("/internal/percorso/applica_variazione", {
                "percorso_id": payload.percorso_id,
                "tipo_variazione": payload.tipo_variazione,
                "offset_deviazione_nm": payload.offset_deviazione_nm,
            })
        except PercorsiDelegationError as exc:
            _handle_percorsi_fallback(exc)

    return applica_variazione_percorso(payload)

