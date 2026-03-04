from app.core.database import get_connection
from app.models.deadhead import DeadheadCreateInput, DeadheadUpdateInput, DeadheadDeleteInput
from fastapi import HTTPException
import psycopg2


def crea_deadhead(data: DeadheadCreateInput):
    conn = get_connection()
    cur = conn.cursor()
    try:
        idle_val = data.idle if data.idle is not None else False
        cur.execute("""
            INSERT INTO deadhead_trips (
                orario_partenza_schedulato, porto_partenza_id, porto_arrivo_id,
                idle, non_productive_time_min, consumo, vascello_id, piano_id
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id, orario_partenza_schedulato, porto_partenza_id, porto_arrivo_id,
                      idle, non_productive_time_min, consumo, vascello_id, piano_id;
        """, (
            data.orario_partenza_schedulato, data.porto_partenza_id, data.porto_arrivo_id,
            idle_val, data.non_productive_time_min, data.consumo,
            data.vascello_id, data.piano_id
        ))
        row = cur.fetchone()
        conn.commit()
        return _row_to_dict(row)
    except psycopg2.errors.ForeignKeyViolation:
        conn.rollback()
        raise HTTPException(status_code=400, detail="Porto, vascello o piano operativo non trovato")
    finally:
        cur.close()
        conn.close()


def modifica_deadhead(data: DeadheadUpdateInput):
    conn = get_connection()
    cur = conn.cursor()
    try:
        updates = []
        params = []
        if data.orario_partenza_schedulato is not None:
            updates.append("orario_partenza_schedulato = %s"); params.append(data.orario_partenza_schedulato)
        if data.porto_partenza_id is not None:
            updates.append("porto_partenza_id = %s"); params.append(data.porto_partenza_id)
        if data.porto_arrivo_id is not None:
            updates.append("porto_arrivo_id = %s"); params.append(data.porto_arrivo_id)
        if data.idle is not None:
            updates.append("idle = %s"); params.append(data.idle)
        if data.non_productive_time_min is not None:
            updates.append("non_productive_time_min = %s"); params.append(data.non_productive_time_min)
        if data.consumo is not None:
            updates.append("consumo = %s"); params.append(data.consumo)
        if data.vascello_id is not None:
            updates.append("vascello_id = %s"); params.append(data.vascello_id)
        if data.piano_id is not None:
            updates.append("piano_id = %s"); params.append(data.piano_id)

        if not updates:
            raise HTTPException(status_code=400, detail="Nessun campo da aggiornare")

        params.append(data.id)
        sql = (
            "UPDATE deadhead_trips SET " + ", ".join(updates) +
            " WHERE id = %s RETURNING id, orario_partenza_schedulato, porto_partenza_id, porto_arrivo_id,"
            " idle, non_productive_time_min, consumo, vascello_id, piano_id;"
        )
        cur.execute(sql, tuple(params))
        row = cur.fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Deadhead trip non trovato")
        conn.commit()
        return _row_to_dict(row)
    except psycopg2.errors.ForeignKeyViolation:
        conn.rollback()
        raise HTTPException(status_code=400, detail="Porto, vascello o piano operativo non trovato")
    finally:
        cur.close()
        conn.close()


def elimina_deadhead(data: DeadheadDeleteInput):
    conn = get_connection()
    cur = conn.cursor()
    try:
        cur.execute("DELETE FROM deadhead_trips WHERE id = %s RETURNING id;", (data.id,))
        row = cur.fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Deadhead trip non trovato")
        conn.commit()
        return {"id": str(row[0]), "esito": "eliminato"}
    finally:
        cur.close()
        conn.close()


def lista_deadhead(piano_id: str = None, vascello_id: str = None):
    conn = get_connection()
    cur = conn.cursor()
    try:
        conditions = []
        params = []
        if piano_id:
            conditions.append("piano_id = %s"); params.append(piano_id)
        if vascello_id:
            conditions.append("vascello_id = %s"); params.append(vascello_id)

        where_clause = " WHERE " + " AND ".join(conditions) if conditions else ""
        cur.execute(
            "SELECT id, orario_partenza_schedulato, porto_partenza_id, porto_arrivo_id,"
            " idle, non_productive_time_min, consumo, vascello_id, piano_id"
            " FROM deadhead_trips" + where_clause +
            " ORDER BY orario_partenza_schedulato;",
            tuple(params)
        )
        rows = cur.fetchall()
        return [_row_to_dict(r) for r in rows]
    finally:
        cur.close()
        conn.close()


def _row_to_dict(row):
    """Converte una riga del risultato in dizionario DeadheadResponse."""
    return {
        "id": str(row[0]),
        "orario_partenza_schedulato": row[1],
        "porto_partenza_id": str(row[2]),
        "porto_arrivo_id": str(row[3]),
        "idle": row[4],
        "non_productive_time_min": float(row[5]) if row[5] is not None else None,
        "consumo": float(row[6]) if row[6] is not None else None,
        "vascello_id": str(row[7]),
        "piano_id": str(row[8]) if row[8] is not None else None
    }
