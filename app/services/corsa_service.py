from app.core.database import get_connection
from app.models.corsa import CorsaInput, PrevisioneRequest
from fastapi import HTTPException
from datetime import datetime
import psycopg2

def crea_corsa(data: CorsaInput):
    try:
        dt = datetime.strptime(data.data, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail="Formato data non valido (YYYY-MM-DD)")
    orario_str = data.orario.strip()
    if ":" in orario_str:
        hhmm = datetime.strptime(orario_str, "%H:%M").strftime("%H%M")
    elif len(orario_str) == 4 and orario_str.isdigit():
        hhmm = orario_str
    else:
        raise HTTPException(status_code=400, detail="Formato orario non valido (HH:MM o HHMM)")
    orario_ts = datetime.strptime(f"{dt.strftime('%Y-%m-%d')} {hhmm}", "%Y-%m-%d %H%M")
    orario_arrivo_ts = None
    if data.orario_arrivo_max:
        arr_str = data.orario_arrivo_max.strip()
        if ":" in arr_str:
            arr_hhmm = datetime.strptime(arr_str, "%H:%M").strftime("%H%M")
        elif len(arr_str) == 4 and arr_str.isdigit():
            arr_hhmm = arr_str
        else:
            raise HTTPException(status_code=400, detail="Formato orario_arrivo_max non valido")
        orario_arrivo_ts = datetime.strptime(f"{dt.strftime('%Y-%m-%d')} {arr_hhmm}", "%Y-%m-%d %H%M")

    conn = get_connection(); cur = conn.cursor()
    try:
        cur.execute("SELECT nome FROM tratta WHERE id = %s", (data.tratta_id,))
        row_tratta = cur.fetchone()
        if row_tratta is None:
            raise HTTPException(status_code=404, detail=f"Tratta non trovata: {data.tratta_id}")
        nome_tratta = row_tratta[0]
        corsa_nome_str = f"{nome_tratta}-{dt.strftime('%Y%m%d')}-{hhmm}"
        cur.execute("""
            INSERT INTO corsa (nome, tratta_id, orario_partenza_schedulato, orario_arrivo_max)
            VALUES (%s, %s, %s, %s) RETURNING id;
        """, (corsa_nome_str, data.tratta_id, orario_ts, orario_arrivo_ts))
        new_uuid = cur.fetchone()[0]
        conn.commit()
        return {"id": str(new_uuid), "nome": corsa_nome_str, "tratta_id": data.tratta_id, "tratta_nome": nome_tratta, "data": dt.strftime('%Y-%m-%d'), "orario": orario_ts.strftime('%H:%M'), "orario_partenza_schedulato": orario_ts.isoformat(), "orario_arrivo_max": orario_arrivo_ts.isoformat() if orario_arrivo_ts else None}
    except psycopg2.errors.UniqueViolation:
        conn.rollback()
        raise HTTPException(status_code=409, detail=f"Corsa già esistente: {corsa_nome_str}")
    except Exception:
        conn.rollback(); raise
    finally:
        cur.close(); conn.close()


def get_orari(tratta_id: str, data: str):
    try:
        giorno = datetime.strptime(data, "%Y-%m-%d").date()
    except ValueError:
        raise HTTPException(status_code=400, detail="Formato data non valido")
    conn = get_connection(); cur = conn.cursor()
    try:
        cur.execute("SELECT nome FROM tratta WHERE id = %s", (tratta_id,))
        row_t = cur.fetchone()
        if not row_t:
            raise HTTPException(404, "Tratta non trovata")
        nome_tratta = row_t[0]
        cur.execute("""
            SELECT DISTINCT orario_partenza_schedulato::time FROM corsa WHERE tratta_id = %s AND orario_partenza_schedulato::date = %s ORDER BY orario_partenza_schedulato::time;
        """, (tratta_id, giorno))
        orari_raw = [r[0] for r in cur.fetchall()]
        orari = [o.strftime("%H:%M") for o in orari_raw]
        return {"tratta_id": tratta_id, "tratta_nome": nome_tratta, "orari": orari}
    finally:
        cur.close(); conn.close()


def lista_corse():
    conn = get_connection(); cur = conn.cursor()
    try:
        cur.execute("""
            SELECT c.id, c.nome, c.tratta_id, t.nome, c.orario_partenza_schedulato, c.previsione_domanda_id, c.orario_arrivo_max FROM corsa c JOIN tratta t ON c.tratta_id = t.id WHERE c.orario_partenza_schedulato > NOW() ORDER BY c.orario_partenza_schedulato;
        """)
        rows = cur.fetchall(); out = []
        for r in rows:
            corsa_obj = {"id": str(r[0]), "nome": r[1], "tratta_id": str(r[2]), "tratta_nome": r[3], "orario_partenza_schedulato": r[4].isoformat(), "previsione_domanda_id": str(r[5]) if r[5] else None, "orario_arrivo_max": r[6].isoformat() if r[6] else None, "previsione": None}
            if r[5]:
                cur.execute("SELECT id, passeggeri_stimati, confidenza_min, confidenza_max, created_at FROM previsione_domanda WHERE id = %s LIMIT 1", (str(r[5]),))
                p = cur.fetchone()
                if p:
                    corsa_obj["previsione"] = {"id": str(p[0]), "passeggeri_stimati": p[1], "confidenza_min": p[2], "confidenza_max": p[3], "created_at": p[4]}
            out.append(corsa_obj)
        return out
    finally:
        cur.close(); conn.close()


def get_corse_by_giorno(giorno: str, solofuture: bool = False):
    from datetime import datetime as dt
    giorno_date = dt.strptime(giorno, "%Y-%m-%d").date()
    conn = get_connection(); cur = conn.cursor()
    try:
        query = """
            SELECT c.id, t.nome, c.orario_partenza_schedulato::time, c.tratta_id, c.nome, c.orario_arrivo_max::time, c.previsione_domanda_id
            FROM corsa c JOIN tratta t ON c.tratta_id = t.id 
            WHERE c.orario_partenza_schedulato::date = %s
        """
        if solofuture:
            query += " AND c.orario_partenza_schedulato > NOW()"
        
        query += " ORDER BY c.orario_partenza_schedulato;"
        
        cur.execute(query, (giorno_date,))
        rows = cur.fetchall()

        results = []
        for r in rows:
            item = {
                "id": str(r[0]),
                "tratta": r[1],
                "orario": r[2].strftime('%H:%M'),
                "tratta_id": str(r[3]),
                "nome": str(r[4]),
                "orario_arrivo_max": r[5].strftime('%H:%M') if r[5] else None,
                "previsione": None
            }

            if r[6]:
                cur.execute("SELECT id, passeggeri_stimati, confidenza_min, confidenza_max, created_at FROM previsione_domanda WHERE id = %s LIMIT 1", (str(r[6]),))
                p = cur.fetchone()
                if p:
                    item["previsione"] = {
                        "id": str(p[0]),
                        "passeggeri_stimati": p[1],
                        "confidenza_min": p[2],
                        "confidenza_max": p[3],
                        "created_at": p[4]
                    }
            results.append(item)
        return results
    finally:
        cur.close(); conn.close()


def get_corsa(corsa_id: str):
    conn = get_connection(); cur = conn.cursor()
    try:
        cur.execute("""
            SELECT c.id, c.nome, c.tratta_id, t.nome, c.orario_partenza_schedulato, c.previsione_domanda_id, c.orario_arrivo_max FROM corsa c JOIN tratta t ON c.tratta_id = t.id WHERE c.id = %s
        """, (corsa_id,))
        row = cur.fetchone()
        if row is None:
            raise HTTPException(404, "Corsa non trovata")
        corsa = {"id": str(row[0]), "nome": row[1], "tratta_id": str(row[2]), "tratta_nome": row[3], "orario_partenza_schedulato": row[4].isoformat(), "previsione_domanda_id": str(row[5]) if row[5] else None, "orario_arrivo_max": row[6].isoformat() if row[6] else None, "previsione": None}
        if row[5]:
            cur.execute("SELECT id, passeggeri_stimati, confidenza_min, confidenza_max FROM previsione_domanda WHERE id = %s", (str(row[5]),))
            p = cur.fetchone()
            if p:
                corsa["previsione"] = {"id": str(p[0]), "passeggeri_stimati": p[1], "confidenza_min": p[2], "confidenza_max": p[3]}
        return corsa
    finally:
        cur.close(); conn.close()


def dashboard_corse():
    conn = get_connection(); cur = conn.cursor()
    try:
        cur.execute("""
            SELECT c.id, c.nome, c.tratta_id, t.nome, c.orario_partenza_schedulato, p.passeggeri_stimati, p.confidenza_min, p.confidenza_max FROM corsa c JOIN tratta t ON c.tratta_id = t.id LEFT JOIN LATERAL (SELECT * FROM previsione_domanda WHERE corsa_id = c.id ORDER BY created_at DESC LIMIT 1) p ON TRUE ORDER BY c.orario_partenza_schedulato;
        """)
        rows = cur.fetchall(); out = []
        for r in rows:
            out.append({"corsa_id": str(r[0]), "corsa_nome": r[1], "tratta_id": str(r[2]), "tratta_nome": r[3], "orario": r[4].isoformat(), "passeggeri": r[5], "ci_min": r[6], "ci_max": r[7]})
        return out
    finally:
        cur.close(); conn.close()


def modifica_corsa(data: dict):

    conn = get_connection()
    cur = conn.cursor()

    try:
        cur.execute("""
            SELECT tratta_id, orario_partenza_schedulato, orario_arrivo_max
            FROM corsa
            WHERE id = %s
        """, (data.get('id'),))

        row_current = cur.fetchone()
        if row_current is None:
            raise HTTPException(404, "Corsa non trovata")

        current_tratta_id, current_ts, current_arr_max = row_current

        final_tratta_id = data.get('tratta_id') if data.get('tratta_id') else str(current_tratta_id)

        # DATE
        if data.get('data'):
            try:
                final_date_obj = datetime.strptime(data.get('data'), "%Y-%m-%d").date()
            except ValueError:
                raise HTTPException(400, "Formato data non valido (usa YYYY-MM-DD)")
        else:
            final_date_obj = current_ts.date()

        # ORARIO
        if data.get('orario'):
            raw_time = data.get('orario').strip()
            if ":" in raw_time:
                try:
                    final_hhmm = datetime.strptime(raw_time, "%H:%M").strftime("%H%M")
                except ValueError:
                    raise HTTPException(400, "Formato orario non valido")
            elif len(raw_time) == 4 and raw_time.isdigit():
                final_hhmm = raw_time
            else:
                raise HTTPException(400, "Formato orario non valido (usa HH:MM o HHMM)")
        else:
            final_hhmm = current_ts.strftime("%H%M")

        final_ts = datetime.strptime(f"{final_date_obj.strftime('%Y-%m-%d')} {final_hhmm}", "%Y-%m-%d %H%M")

        # ORARIO ARRIVO MAX
        final_arr_ts = None
        if data.get('orario_arrivo_max'):
            raw_arr = data.get('orario_arrivo_max').strip()
            if ":" in raw_arr:
                arr_hhmm = datetime.strptime(raw_arr, "%H:%M").strftime("%H%M")
            elif len(raw_arr) == 4 and raw_arr.isdigit():
                arr_hhmm = raw_arr
            else:
                raise HTTPException(400, "Formato orario arrivo non valido")

            final_arr_ts = datetime.strptime(f"{final_date_obj.strftime('%Y-%m-%d')} {arr_hhmm}", "%Y-%m-%d %H%M")
        else:
            final_arr_ts = current_arr_max

        cur.execute("SELECT nome FROM tratta WHERE id = %s", (final_tratta_id,))
        row_t = cur.fetchone()
        if not row_t:
            raise HTTPException(404, f"Tratta non trovata: {final_tratta_id}")
        nome_tratta = row_t[0]

        nuovo_nome_corsa = f"{nome_tratta}-{final_date_obj.strftime('%Y%m%d')}-{final_hhmm}"

        cur.execute("""
            UPDATE corsa
            SET nome = %s, tratta_id = %s, orario_partenza_schedulato = %s, orario_arrivo_max = %s
            WHERE id = %s
            RETURNING id;
        """, (nuovo_nome_corsa, final_tratta_id, final_ts, final_arr_ts, data.get('id')))

        row = cur.fetchone()
        conn.commit()

        if row is None:
            raise HTTPException(404, "Corsa non trovata durante l'aggiornamento")

        return {
            "id": data.get('id'),
            "nome": nuovo_nome_corsa,
            "tratta_id": final_tratta_id,
            "tratta_nome": nome_tratta,
            "data": final_date_obj.strftime("%Y-%m-%d"),
            "orario": final_hhmm[:2] + ":" + final_hhmm[2:],
            "orario_partenza_schedulato": final_ts.isoformat(),
            "orario_arrivo_max": final_arr_ts.isoformat() if final_arr_ts else None
        }

    except psycopg2.Error as e:
        conn.rollback()
        raise HTTPException(500, f"Errore Database: {e}")
    except Exception:
        conn.rollback(); raise
    finally:
        cur.close(); conn.close()


def elimina_corsa(data: dict):
    conn = get_connection(); cur = conn.cursor()
    try:
        cur.execute(
            "DELETE FROM assegnazione WHERE percorso_id IN (SELECT id FROM percorso WHERE id_corsa = %s);",
            (data.get('id'),)
        )
        cur.execute("DELETE FROM percorso WHERE id_corsa = %s;", (data.get('id'),))
        cur.execute("DELETE FROM corsa WHERE id = %s RETURNING id;", (data.get('id'),))
        row = cur.fetchone()
        if row is None:
            conn.rollback()
            raise HTTPException(404, "Corsa non trovata")
        conn.commit()
        return {"id": data.get('id'), "esito": "eliminato"}
    except HTTPException:
        raise
    except Exception:
        conn.rollback(); raise
    finally:
        cur.close(); conn.close()
