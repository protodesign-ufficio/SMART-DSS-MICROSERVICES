from app.core.database import get_connection
from app.models.assegnazione import AssegnazioneCreateInput, AssegnazioneUpdateStatoInput, StatoEsecuzioneEnum
from app.models.common import CreaAssegnazioniBulkInput, PercorsoAssegnazioneItem
from fastapi import HTTPException
import psycopg2

def crea_assegnazione(data: dict):
    inp = AssegnazioneCreateInput(**data) if not isinstance(data, AssegnazioneCreateInput) else data
    conn = get_connection(); cur = conn.cursor()
    try:
        # virtuale is optional in the API; use False as DB-safe default when not provided
        virtuale_val = inp.virtuale if getattr(inp, "virtuale", None) is not None else False
        cur.execute("""
            INSERT INTO assegnazione (piano_id, percorso_id, stato_esecuzione, virtuale) VALUES (%s, %s, %s, %s) RETURNING id;
        """, (inp.piano_id, inp.percorso_id, inp.stato_esecuzione.value, virtuale_val))
        assegnazione_id = cur.fetchone()[0]

        conn.commit()
        
        # Retrieve vascello_id from percorso
        cur.execute("""
            SELECT a.id, a.piano_id, p.vascello_id, a.percorso_id, a.stato_esecuzione, a.virtuale, p.id_corsa, a.orario_completamento
            FROM assegnazione a
            LEFT JOIN percorso p ON a.percorso_id = p.id
            WHERE a.id = %s;
        """, (assegnazione_id,))
        row = cur.fetchone()
        
        return {"id": row[0], "piano_id": row[1], "vascello_id": row[2], "percorso_id": row[3], "id_corsa": row[6], "stato_esecuzione": row[4], "virtuale": row[5], "orario_completamento": row[7].isoformat() if row[7] else None}
    except psycopg2.errors.UniqueViolation:
        conn.rollback(); raise HTTPException(status_code=409, detail="Esiste già un'assegnazione IN_CORSO per questo vascello")
    finally:
        conn.close()


def lista_assegnazioni_by_piano(piano_id: str):
    conn = get_connection(); cur = conn.cursor()
    try:
        cur.execute("""
            SELECT a.id, a.piano_id, p.vascello_id, a.percorso_id, p.id_corsa, a.stato_esecuzione, a.virtuale, a.orario_completamento
            FROM assegnazione a
            LEFT JOIN percorso p ON a.percorso_id = p.id
            WHERE a.piano_id = %s ORDER BY a.id;
        """, (piano_id,))
        rows = cur.fetchall()
        result = []
        for r in rows:
            result.append({
                "id": r[0],
                "piano_id": r[1],
                "vascello_id": r[2],
                "percorso_id": r[3],
                "id_corsa": r[4],
                "stato_esecuzione": r[5],
                "virtuale": r[6],
                "orario_completamento": r[7].isoformat() if r[7] else None
            })
        return result
    finally:
        conn.close()


def aggiorna_stato_assegnazione(assegnazione_id: str, data: dict):
    inp = AssegnazioneUpdateStatoInput(**data) if not isinstance(data, AssegnazioneUpdateStatoInput) else data
    conn = get_connection(); cur = conn.cursor()
    try:
        cur.execute("""
            UPDATE assegnazione SET stato_esecuzione = %s WHERE id = %s;
            SELECT a.id, a.piano_id, p.vascello_id, a.percorso_id, a.stato_esecuzione, a.virtuale, p.id_corsa, a.orario_completamento
            FROM assegnazione a
            LEFT JOIN percorso p ON a.percorso_id = p.id
            WHERE a.id = %s;
        """, (inp.stato_esecuzione.value, assegnazione_id, assegnazione_id))
        conn.commit()
        row = cur.fetchone()
        if row is None:
            raise HTTPException(404, "Assegnazione non trovata")
        return {"id": row[0], "piano_id": row[1], "vascello_id": row[2], "percorso_id": row[3], "id_corsa": row[6], "stato_esecuzione": row[4], "virtuale": row[5], "orario_completamento": row[7].isoformat() if row[7] else None}
    except psycopg2.errors.UniqueViolation:
        conn.rollback(); raise HTTPException(status_code=409, detail="Un'altra assegnazione IN_CORSO esiste già per questo vascello")
    finally:
        conn.close()


def crea_assegnazioni_bulk(data: CreaAssegnazioniBulkInput):
    """
    Crea assegnazioni bulk per un piano operativo.
    """
    conn = get_connection()
    cur = conn.cursor()
    risultati = []
    
    try:
        for item in data.percorsi:
            # Crea l'assegnazione
            cur.execute("""
                INSERT INTO assegnazione (piano_id, percorso_id, stato_esecuzione, virtuale) 
                VALUES (%s, %s, %s, %s) 
                RETURNING id;
            """, (data.piano_id, item.percorso_id, StatoEsecuzioneEnum.PIANIFICATA.value, item.virtuale))
            
            assegnazione_id = cur.fetchone()[0]
            
            risultati.append({
                "assegnazione_id": str(assegnazione_id),
                "percorso_id": item.percorso_id,
                "virtuale": item.virtuale
            })
        
        conn.commit()
        
        return {
            "piano_id": data.piano_id,
            "assegnazioni_create": len(risultati),
            "risultati": risultati
        }
    
    except psycopg2.errors.UniqueViolation:
        conn.rollback()
        raise HTTPException(status_code=409, detail="Una o più assegnazioni esistono già per i percorsi specificati")
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=f"Errore durante la creazione delle assegnazioni: {str(e)}")
    finally:
        conn.close()


def cancella_assegnazioni_virtuali_in_corso():
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("""
            UPDATE assegnazione 
            SET stato_esecuzione = %s 
            WHERE stato_esecuzione = %s AND virtuale = true;
        """, (StatoEsecuzioneEnum.CANCELLATA.value, StatoEsecuzioneEnum.IN_CORSO.value))
        count = cur.rowcount
        conn.commit()
        return {"messaggio": f"Aggiornate {count} assegnazioni", "updated_count": count}
    finally:
        conn.close()
