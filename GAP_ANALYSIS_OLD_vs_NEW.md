# Gap Analysis: SMART-DSS-NEW vs SMART-DSS-MICROSERVICES

Data: 2026-02-26

## Metodo usato

1. Confronto file-by-file (hash) tra i due progetti.
2. Confronto code-to-code degli endpoint (decorator FastAPI su tutti i `.py`).
3. Confronto runtime su stack old (`localhost:15080`) vs stack new (`localhost:25080`).
4. Verifica flussi critici (`weather_routing/carico`, `percorso/by_corsa`, core GET).

## Esito sintetico

- Differenze codice runtime: **7 file**.
- Parità endpoint a livello sorgente: **nessuna perdita funzionale** rispetto a `SMART-DSS-NEW`.
  - `missing_in_new = 0`
  - `added_in_new = 1` (`POST /internal/percorso/crea_batch`)
- Gap comportamentale critico individuato: **cache logic su `weather_routing/carico` non allineata**.

## File cambiati con impatto runtime

- `app/services/ottimizzatore_service.py`
- `percorsi_service/main.py`
- `docker-compose.yml`
- `Dockerfile.backend`
- `Dockerfile.ottimizzatore`
- `Dockerfile.scheduler`
- `Dockerfile.simulator`

## Gap critico trovato

### 1) `weather_routing/carico`: perdita comportamento cache del vecchio flusso

Nel vecchio progetto, `ottimizzatore_service` controllava cache percorsi recente su DB e restituiva stato `cached` senza rigenerare sempre.
Nel nuovo progetto questo check è stato rimosso (passaggio a lettura/scrittura via microservizi), quindi le chiamate ripetute risultano `computed` e inseriscono nuovi percorsi.

**Evidenza runtime**
- Vecchio stack (`15080`): due chiamate consecutive -> `status: cached`
- Nuovo stack (`25080`): due chiamate consecutive -> `status: computed`
- Conteggio percorsi stessa coppia corsa/vascello:
  - old: `6`
  - new: `30`

**Impatto**
- aumento record duplicati/varianti nel tempo;
- maggiore costo computazionale su ottimizzatore;
- differenza comportamentale rispetto al vecchio progetto.

## Coerenza generale flussi principali

Verifiche positive su nuovo stack (`25080`):
- `/porto/lista`, `/tratta/lista`, `/vascello/lista`, `/corsa/lista` -> OK
- `POST /weather_routing/carico` -> OK
- `GET /percorso/by_corsa/{id}` -> OK
- `POST /weather_routing/vuoto` -> OK

## Nota su differenze runtime old vs new (OpenAPI live)

Nel confronto tra i due stack in esecuzione è emersa una divergenza di contratto live (`/assegnazione/{assegnazione_id}`, `/check_replanning/status`, `/allarme/lista`).
Poiché il confronto **code-to-code** tra `SMART-DSS-NEW` e `SMART-DSS-MICROSERVICES` non mostra queste mancanze, è probabile che lo stack old in esecuzione non corrisponda esattamente allo stesso snapshot sorgente analizzato.

## Raccomandazione prioritaria

Ripristinare la semantica cache di `weather_routing/carico` anche nel nuovo flusso microservizi (cache lookup per coppia `corsa_id + vascello_id` su finestra temporale configurabile), mantenendo la persistenza su `percorsi_db`.
