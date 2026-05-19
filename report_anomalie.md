# Audit del Codice e Report Anomalie

**Progetto:** SMART-DSS-MICROSERVICES  
**Data audit:** 2026-05-18  
**Contesto:** TRL5 – focus esclusivo su bug funzionali che compromettono la correttezza del sistema

---

## 1. Riepilogo Esecutivo

Il progetto è un sistema a microservizi Python per la gestione di trasporti marittimi. L'architettura generale è solida, ma sono stati identificati **bug funzionali critici** che causano comportamenti errati o silenziosi in operazioni chiave: aggiornamento stato assegnazioni, validazione del piano operativo, stato condiviso tra thread nello scheduler, e perdita dei job schedulati al riavvio. Questi bug devono essere risolti per garantire il corretto funzionamento del sistema in fase di test e validazione TRL5.

### Conteggio Problemi per Priorità

| Priorità | Conteggio |
|---------|-----------|
| **Critica** | 2 |
| **Alta** | 3 |
| **Media** | 3 |
| **Totale** | **8** |

---

## 2. Analisi Dettagliata dei Problemi

---

### Bug 1 – Multi-Statement SQL in Singolo `execute()`: Aggiornamento Stato Sempre Fallante

**Priorità:** Critica  
**File e Linea:** [`app/services/assegnazione_service.py:67-73`](app/services/assegnazione_service.py#L67-L73)

**Descrizione:**  
La funzione `aggiorna_stato_assegnazione` passa due statement SQL separati da `;` in una singola chiamata `cur.execute()`. In psycopg2, `execute()` esegue solo il **primo** statement e ignora il resto. Di conseguenza la `SELECT` non viene mai eseguita, `cur.fetchone()` restituisce sempre `None`, e viene sempre sollevata `HTTPException(404, "Assegnazione non trovata")`.

```python
# BUGGY — solo l'UPDATE viene eseguito, la SELECT viene ignorata
cur.execute("""
    UPDATE assegnazione SET stato_esecuzione = %s WHERE id = %s;
    SELECT a.id, a.piano_id, ...
    FROM assegnazione a ...
    WHERE a.id = %s;
""", (inp.stato_esecuzione.value, assegnazione_id, assegnazione_id))
conn.commit()
row = cur.fetchone()  # Sempre None → HTTP 404
```

**Impatto:**  
L'endpoint `PATCH /assegnazione/{id}/stato` non funziona mai. Conseguenza diretta: lo scheduler (`app/core/scheduler.py:129-136`) che aggiorna lo stato a `IN_CORSO` prima di avviare le simulazioni **fallisce silenziosamente a ogni esecuzione** — le simulazioni schedulate non vengono mai avviate correttamente.

**Soluzione proposta:**  
Separare i due statement in due chiamate distinte.

```python
cur.execute(
    "UPDATE assegnazione SET stato_esecuzione = %s WHERE id = %s;",
    (inp.stato_esecuzione.value, assegnazione_id)
)
conn.commit()
cur.execute("""
    SELECT a.id, a.piano_id, p.vascello_id, a.percorso_id, a.stato_esecuzione,
           a.virtuale, p.id_corsa, a.orario_completamento
    FROM assegnazione a
    LEFT JOIN percorso p ON a.percorso_id = p.id
    WHERE a.id = %s;
""", (assegnazione_id,))
row = cur.fetchone()
```

---

### Bug 2 – Piano Marcato `VALIDATO` anche se la Schedulazione delle Simulazioni Fallisce

**Priorità:** Critica  
**File e Linea:** [`app/services/pianificazione_service.py:953-998`](app/services/pianificazione_service.py#L953-L998)

**Descrizione:**  
In `valida_piano`, il piano viene aggiornato a `VALIDATO` con un UPDATE SQL (riga 953), poi il loop di schedulazione delle simulazioni può sollevare eccezioni (riga 996). Se una o più simulazioni falliscono nel loop, l'eccezione viene solo loggata con `print` e il `conn.commit()` viene **comunque eseguito** alla riga 998. Il piano risulta validato nel DB ma le simulazioni non sono state schedulate.

```python
# Riga 953: UPDATE stato = 'VALIDATO'
# ...
for assegnazione_id, orario_partenza in assegnazioni_virtuali:
    try:
        schedule_simulation_job(...)
        simulazioni_schedulate += 1
    except Exception as e:
        print(f"[valida_piano] Errore scheduling: {e}")  # Solo print, nessun rollback

conn.commit()  # Riga 998: commit avviene sempre, anche con simulazioni mancanti
```

**Impatto:**  
Stato del DB inconsistente: il piano è `VALIDATO` ma le simulazioni non partono mai. In fase di test TRL5 questo rende impossibile distinguere se un piano è stato effettivamente validato con tutte le simulazioni programmate o meno.

**Soluzione proposta:**  
Raccogliere gli errori durante il loop e fare rollback se necessario, oppure come minimo segnalare nel risultato quante simulazioni sono fallite:

```python
errori_scheduling = []
for assegnazione_id, orario_partenza in assegnazioni_virtuali:
    try:
        schedule_simulation_job(...)
        simulazioni_schedulate += 1
    except Exception as e:
        errori_scheduling.append(str(e))
        print(f"[valida_piano] Errore scheduling assegnazione {assegnazione_id}: {e}")

if errori_scheduling:
    conn.rollback()
    raise HTTPException(500, f"Schedulazione parzialmente fallita: {errori_scheduling}")

conn.commit()
```

---

### Bug 3 – Race Condition su `LAST_REPLANNING_STATUS`: Stato Letto Inconsistente

**Priorità:** Alta  
**File e Linea:** [`app/core/scheduler.py:36-63`](app/core/scheduler.py#L36-L63)

**Descrizione:**  
Il dizionario `LAST_REPLANNING_STATUS` è uno stato globale condiviso scritto dal thread dello scheduler APScheduler (`ThreadPoolExecutor`) e letto dal thread HTTP FastAPI (endpoint `/config/replanning/status`). Non esiste alcun lock. In Python, l'assegnazione a chiavi di dizionario non è atomica in tutti i casi, e il thread HTTP può leggere un dizionario in aggiornamento parziale.

```python
LAST_REPLANNING_STATUS = {"last_started_at": None, "last_success": None, ...}

def _run_periodic_replanning_job():
    LAST_REPLANNING_STATUS["last_started_at"] = now   # scrittura thread scheduler
    # ... operazione lunga ...
    LAST_REPLANNING_STATUS["last_success"] = True      # altra scrittura
    LAST_REPLANNING_STATUS["last_result"] = result     # altra scrittura
```

**Impatto:**  
L'endpoint di status può restituire uno stato ibrido (es. `last_started_at` aggiornato ma `last_success` del ciclo precedente) rendendo il monitoraggio del replanning inaffidabile durante i test.

**Soluzione proposta:**  
Aggiornare lo stato in modo atomico con una singola assegnazione di dizionario, o proteggere con un lock:

```python
import threading
_status_lock = threading.Lock()

# Nel job:
with _status_lock:
    LAST_REPLANNING_STATUS.update({
        "last_finished_at": ...,
        "last_success": True,
        "last_error": None,
        "last_result": result,
    })

# Nell'endpoint di lettura:
with _status_lock:
    return dict(LAST_REPLANNING_STATUS)
```

---

### Bug 4 – Job Schedulati Persi al Riavvio (MemoryJobStore)

**Priorità:** Alta  
**File e Linea:** [`app/core/scheduler.py:14-16`](app/core/scheduler.py#L14-L16)

**Descrizione:**  
APScheduler è configurato con `MemoryJobStore`. Tutti i job schedulati per simulazioni future vengono persi ad ogni riavvio dell'applicazione. Non esiste alcun meccanismo di recovery.

```python
jobstores = {
    'default': MemoryJobStore()  # Non persistente — perso al riavvio
}
```

**Impatto:**  
Se l'applicazione viene riavviata (deploy, crash, restart) dopo la validazione di un piano ma prima dell'orario di partenza delle simulazioni, tutte le simulazioni pianificate non partono. Il piano rimane `VALIDATO` nel DB ma nessuna simulazione viene mai eseguita. In ambiente TRL5 con riavvii frequenti durante i test, questo causa perdita di dati di test difficile da diagnosticare.

**Soluzione proposta:**  
Usare `SQLAlchemyJobStore` per persistere i job nel database esistente:

```python
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from app.core.config import DB_CONN_ALCHEMY  # connection string formato SQLAlchemy

jobstores = {
    'default': SQLAlchemyJobStore(url=DB_CONN_ALCHEMY)
}
```

In alternativa (soluzione rapida), aggiungere un meccanismo di re-schedulazione all'avvio che recupera le assegnazioni `PIANIFICATA` con orario futuro e le riaggiunge allo scheduler.

---

### Bug 5 – File Handle Leak in `load_model`

**Priorità:** Alta  
**File e Linea:** [`service.py:184`](service.py#L184)

**Descrizione:**  
I file JSON dei modelli ML vengono aperti con `open(fname)` passato direttamente a `json.load()` senza context manager. Se `json.load()` solleva un'eccezione (file malformato, chiave mancante), il file handle rimane aperto.

```python
def load_model(fname: str):
    m = json.load(open(fname))  # file handle non chiuso in caso di eccezione
    return m["params"], np.array(m["cov"]), m["sigma"]
```

**Impatto:**  
Accumulando handle aperti, il servizio può esaurire il limite di file descriptor del processo. Il problema si manifesta principalmente se i file JSON vengono modificati o se il caricamento viene ripetuto (es. hot reload).

**Soluzione proposta:**  
```python
def load_model(fname: str):
    with open(fname, "r", encoding="utf-8") as f:
        m = json.load(f)
    return m["params"], np.array(m["cov"]), m["sigma"]
```

---

### Bug 6 – Token Copernicus Non Rinnovato Dopo Scadenza

**Priorità:** Media  
**File e Linea:** [`weather_service/main.py:386-403`](weather_service/main.py#L386-L403)

**Descrizione:**  
Il flag `_logged_in` viene impostato a `True` dopo il primo login riuscito e non viene mai resettato. Se il token Copernicus scade durante l'uptime del servizio, il corto-circuito `if _logged_in: return` impedisce qualsiasi tentativo di re-login. Tutte le successive fetch di dati meteo falliscono con errori di autenticazione non gestiti.

```python
_logged_in = False

def _ensure_login() -> None:
    global _logged_in
    if _logged_in:
        return  # Non si ri-autentica mai, anche dopo scadenza token
    ...
    _logged_in = True  # Impostato una volta sola
```

**Impatto:**  
Dopo un certo periodo di uptime, tutti gli endpoint del weather service che accedono a Copernicus iniziano a restituire errori 500, rendendo inutilizzabile il weather routing. L'unica soluzione attuale è riavviare il servizio.

**Soluzione proposta:**  
Aggiungere una scadenza al flag con timestamp:

```python
_login_expires_at: float = 0.0

def _ensure_login() -> None:
    global _logged_in, _login_expires_at
    if _logged_in and time.time() < _login_expires_at:
        return
    with _login_lock:
        if _logged_in and time.time() < _login_expires_at:
            return
        # ... login ...
        _logged_in = True
        _login_expires_at = time.time() + 3600  # re-login ogni ora
```

---

### Bug 7 – Pattern N+1 HTTP in `compute_assignments` con Possibile Timeout

**Priorità:** Media  
**File e Linea:** [`app/services/pianificazione_service.py:83-99`](app/services/pianificazione_service.py#L83-L99)

**Descrizione:**  
Per ogni corsa nell'intervallo temporale, viene eseguita prima una chiamata per la lista corse del giorno e poi una chiamata HTTP separata per il dettaglio di **ogni singola corsa**. Per un intervallo di 7 giorni con 10 corse al giorno: 7 + 70 = 77 chiamate HTTP sincrone e bloccanti.

```python
while day <= end_dt.date():
    corse_giorno = _safe_get(..., f"/internal/corsa/giorno?giorno={day}")  # 1 per giorno
    for c in corse_giorno:
        detail = _safe_get(..., f"/internal/corsa/id/{corsa_id}")  # 1 per ogni corsa
```

**Impatto:**  
Con timeout di 10s per chiamata, una pianificazione settimanale può richiedere diversi minuti. In ambiente di test con più chiamate concorrenti, il servizio diventa non responsivo.

**Soluzione proposta:**  
Aggiungere al servizio operativo un endpoint batch `GET /internal/corsa/by_ids?ids=id1,id2,...` che restituisca tutti i dettagli in una singola risposta. Come soluzione immediata, aumentare il timeout solo per questa funzione e documentare il comportamento atteso.

---

### Bug 8 – Pattern N+1 Query SQL in `lista_piani`

**Priorità:** Media  
**File e Linea:** [`app/services/pianificazione_service.py:326-334`](app/services/pianificazione_service.py#L326-L334)

**Descrizione:**  
Per ogni piano restituito dalla query principale, viene eseguita una seconda query SQL per recuperare le relative assegnazioni. Con N piani nel database vengono eseguite N+1 query.

```python
rows = cur.fetchall()  # 1 query per tutti i piani
for r in rows:
    piano_id = r[0]
    cur.execute("SELECT ... FROM assegnazione ... WHERE a.piano_id = %s", (piano_id,))  # N query
```

**Impatto:**  
Con molti piani accumulati durante i test, l'endpoint `/piano/lista` diventa progressivamente più lento. Con 50 piani: 51 query per ogni chiamata all'endpoint.

**Soluzione proposta:**  
Sostituire con una singola JOIN:

```python
cur.execute("""
    SELECT po.id, po.data_riferimento, po.stato,
           po.kpi_profitto_stimato, po.kpi_robustezza, po.versione,
           a.id, a.stato_esecuzione, a.virtuale,
           p.vascello_id, a.percorso_id, p.id_corsa
    FROM piano_operativo po
    LEFT JOIN assegnazione a ON a.piano_id = po.id
    LEFT JOIN percorso p ON p.id = a.percorso_id
    ORDER BY po.data_riferimento DESC, a.id;
""")
```

---

## 3. Consigli di Miglioramento (Non Bloccanti per TRL5)

- **Logging strutturato**: sostituire i `print()` sparsi con `logging.getLogger()` per avere tracce leggibili durante i test. Particolarmente utile nello scheduler e nei servizi di ottimizzazione.
- **Timeout consistenti**: i timeout HTTP variano tra 3s e 600s senza una logica documentata. Definire costanti centralizzate in `app/core/config.py` (`TIMEOUT_FAST`, `TIMEOUT_STD`, `TIMEOUT_OPT`) per facilitare la diagnostica di problemi di latenza durante i test.
- **Health check DB**: gli endpoint `/health` non verificano la connettività al database. Durante i test di integrazione, un health check che esegue `SELECT 1` permette di rilevare immediatamente problemi di connessione al DB senza dover analizzare i log.

---

*Report generato il 2026-05-18 — Contesto TRL5, focus su correttezza funzionale*
