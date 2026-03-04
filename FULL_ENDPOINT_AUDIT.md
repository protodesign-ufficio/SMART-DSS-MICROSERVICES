# Full Endpoint Audit — SMART-DSS-MICROSERVICES

**Data audit:** 2026-03-04
**Metodo:** Test manuale completo via `curl` su `http://localhost:25080` (gateway esterno) e sugli endpoint interni di ogni microservizio.

## Sintesi

| Metrica | Valore |
|---------|--------|
| Endpoint gateway totali | 69 |
| Health check verificati | 9 (gateway + 8 microservizi) |
| Endpoint GET testati con dati reali | 42 |
| Parametri `include` testati | 5 combinazioni |
| Bug trovati e risolti | 8 |
| Hard failure (5xx irrisolvibili) | 0 |

## Health Check — Tutti i servizi

| Servizio | Endpoint | Porta | Status | Tempo |
|----------|----------|-------|--------|-------|
| Gateway | `GET /health` | 25080 | ✅ 200 | <50ms |
| Anagrafica | `GET /health` | 18070 | ✅ 200 | <50ms |
| Operativo | `GET /health` | 18072 | ✅ 200 | <50ms |
| Percorsi | `GET /health` | 18073 | ✅ 200 | <50ms |
| Forecast | `GET /health` | 18074 | ✅ 200 | <50ms |
| Alerting | `GET /health` | 18075 | ✅ 200 | <50ms |
| Telemetry | `GET /health` | 18071 | ✅ 200 | <50ms |
| Weather | `GET /health` | 18076 | ✅ 200 | <50ms |
| Replanning | `GET /health` | 18001 | ✅ 200 | <50ms |

## Bug trovati e risolti durante l'audit

| # | Endpoint | Problema | Soluzione | File modificato |
|---|----------|----------|-----------|-----------------|
| 1 | `GET /health` | 404 — endpoint mancante | Aggiunto endpoint `/health` al gateway | `app/main.py` |
| 2 | `GET /dashboard/corse` | 503 timeout (59s su 20s default) | Timeout portato a 120s + ottimizzazione N+1 query (→31s) | `app/routers/corsa.py`, `operativo_service/main.py` |
| 3 | `GET /corsa/lista` | Lento (21.6s — rischio timeout 20s) | Timeout portato a 60s + cache tratta/previsione N+1 (→10.6s) | `app/routers/corsa.py`, `operativo_service/main.py` |
| 4 | `GET /piano/lista` | Rischio timeout (11s su 20s default) | Timeout portato a 60s | `app/routers/piano_operativo.py` |
| 5 | `GET /percorso/by_corsa?include=` | Parametro include validato ma mai applicato | Implementata expansion completa (corsa, tratta, vascello) con pre-caching | `percorsi_service/main.py` |
| 6 | `GET /assegnazione/by_piano/{id}` | Rischio timeout | Timeout portato a 60s | `app/routers/assegnazione.py` |
| 7 | `POST /assegnazione/bulk` | Rischio timeout | Timeout portato a 60s | `app/routers/assegnazione.py` |
| 8 | `GET /corsa/giorno` | N+1 query su tratta/previsione | Cache dict per tratta e previsione aggiunta | `operativo_service/main.py` |

## Performance — Endpoint lenti ottimizzati

| Endpoint | Prima | Dopo | Miglioramento |
|----------|-------|------|---------------|
| `GET /dashboard/corse` | 59.4s | 29.1s | -51% |
| `GET /corsa/lista` | 21.6s | 10.6s | -51% |
| `GET /corsa/giorno` | ~15s | ~7s | -53% |

## Risultati completi — Gateway Endpoints

### Porti (`/porto/`)
| Metodo | Path | Status | Note |
|--------|------|--------|------|
| GET | `/porto/lista` | 200 | 3 porti |
| GET | `/porto/{porto_id}` | 200 | ID reale testato |
| GET | `/porto/by_name/{nome}` | 200 | Nome reale testato |
| POST | `/porto/crea` | 422 | Validazione OK (body vuoto) |
| POST | `/porto/modifica` | 422 | Validazione OK |
| POST | `/porto/elimina` | 422 | Validazione OK |

### Tratte (`/tratta/`)
| Metodo | Path | Status | Note |
|--------|------|--------|------|
| GET | `/tratta/lista` | 200 | 6 tratte |
| GET | `/tratta/{tratta_id}` | 200 | ID reale testato |
| POST | `/tratta/crea` | 422 | Validazione OK |
| POST | `/tratta/crea_multi` | 422 | Validazione OK |
| POST | `/tratta/modifica` | 422 | Validazione OK |
| POST | `/tratta/elimina` | 404 | Validazione OK |

### Vascelli (`/vascello/`)
| Metodo | Path | Status | Note |
|--------|------|--------|------|
| GET | `/vascello/lista` | 200 | 5 vascelli |
| GET | `/vascello/{vascello_id}` | 200 | ID reale testato |
| GET | `/vascello/by_mmsi/{mmsi}` | 200 | MMSI reale testato |
| GET | `/vascello/{mmsi}/image` | 200 | Immagine base64 |
| GET | `/vascello/{mmsi}/percorso_attivo` | 404 | Nessun percorso attivo (comportamento corretto) |
| POST | `/vascello/crea` | 422 | Validazione OK |
| POST | `/vascello/modifica` | 422 | Validazione OK |
| POST | `/vascello/elimina` | 422 | Validazione OK |

### Corse (`/corsa/`)
| Metodo | Path | Status | Tempo | Note |
|--------|------|--------|-------|------|
| GET | `/corsa/lista` | 200 | 10.6s | 660 corse, con cache N+1 |
| GET | `/corsa/{corsa_id}` | 200 | <1s | Include tratta/previsione inline |
| GET | `/corsa/giorno` | 200 | ~7s | Con parametro `giorno`, cache N+1 |
| GET | `/corsa/orari/{tratta_id}` | 200 | <1s | Orari per tratta_id reale |
| GET | `/dashboard/corse` | 200 | 29.1s | Dashboard aggregata, cache N+1 |
| POST | `/corsa/crea` | 422 | — | Validazione OK |
| POST | `/corsa/modifica` | 404 | — | Validazione OK |
| POST | `/corsa/elimina` | 404 | — | Validazione OK |
| POST | `/corsa/{corsa_id}/prevedi` | 200 | 149ms | Previsione ML funzionante |

### Percorsi (`/percorso/`)
| Metodo | Path | Status | Note |
|--------|------|--------|------|
| GET | `/percorso/{percorso_id}` | 200 | Con include=corsa,tratta,vascello |
| GET | `/percorso/by_corsa/{corsa_id}` | 200 | Con include expansion funzionante |
| POST | `/percorso/applica_variazione` | 422 | Validazione OK |
| POST | `/percorso/elimina` | 422 | Validazione OK |

### Piani Operativi (`/piano/`)
| Metodo | Path | Status | Tempo | Note |
|--------|------|--------|-------|------|
| GET | `/piano/lista` | 200 | ~11s | Lista completa piani, timeout 60s |
| GET | `/piano/{piano_id}` | 200 | <1s | Piano con KPI |
| POST | `/piano/crea` | 422 | — | Validazione OK |
| POST | `/piano/modifica` | 422 | — | Validazione OK |
| POST | `/piano/elimina` | 422 | — | Validazione OK |
| POST | `/piano/valida` | 422 | — | Validazione OK |

### Assegnazioni (`/assegnazione/`)
| Metodo | Path | Status | Note |
|--------|------|--------|------|
| GET | `/assegnazione/{id}` | 200 | Con include=piano,percorso,corsa,vascello |
| GET | `/assegnazione/by_piano/{piano_id}` | 200 | Timeout 60s |
| POST | `/assegnazione/crea` | 422 | Validazione OK |
| POST | `/assegnazione/bulk` | 422 | Timeout 60s |
| POST | `/assegnazione/check_validita` | 422 | Validazione OK |
| POST | `/assegnazione/in_corso2cancellata` | 200 | Funzionante |
| PATCH | `/assegnazione/{id}/stato` | 422 | Validazione OK |

### Deadhead Trips (`/deadhead/`)
| Metodo | Path | Status | Note |
|--------|------|--------|------|
| GET | `/deadhead/lista` | 200 | Lista completa |
| POST | `/deadhead/crea` | 422 | Validazione OK |
| POST | `/deadhead/modifica` | 422 | Validazione OK |
| POST | `/deadhead/elimina` | 422 | Validazione OK |

### Allarmi (`/allarme/`)
| Metodo | Path | Status | Note |
|--------|------|--------|------|
| GET | `/allarme/lista` | 200 | Delegato ad alerting_service |

### Weather (`/weather/`)
| Metodo | Path | Status | Tempo | Note |
|--------|------|--------|-------|------|
| GET | `/weather/health` | 200 | <50ms | Health check |
| POST | `/weather/layer` | 200 | 704ms | Layer meteo 4810B |
| GET | `/weather/cache/layer` | 200 | <100ms | Lista cache layer |
| GET | `/weather/cache/layer/{key}` | 200 | <100ms | Payload cache |

### Pianificazione (`/weather_routing/`, `/scheduling/`)
| Metodo | Path | Status | Note |
|--------|------|--------|------|
| POST | `/weather_routing/carico` | 200 | Routing con carico |
| POST | `/weather_routing/vuoto` | 200 | Routing a vuoto |
| POST | `/scheduling/giorno` | 422 | Validazione OK |
| POST | `/scheduling/ottimizza` | 422 | Validazione OK |
| POST | `/pianificazione/compatibili` | 422 | Validazione OK |
| POST | `/assegnazione/pianifica` | 422 | Validazione OK |

### Simulazione (`/simulation/`)
| Metodo | Path | Status | Note |
|--------|------|--------|------|
| POST | `/simulation/build_and_run` | 422 | Validazione OK |
| POST | `/simulation/simula_piano` | 422 | Validazione OK |
| GET | `/simulation/schedulate` | 404 | Nessuna simulazione schedulata |

### Replanning (`/check_replanning`)
| Metodo | Path | Status | Note |
|--------|------|--------|------|
| POST | `/check_replanning` | 200 | Propagazione ritardi OK |
| GET | `/check_replanning/status` | 200 | Stato replanning |

### Configurazione (`/api/config/`, `/config`)
| Metodo | Path | Status | Note |
|--------|------|--------|------|
| GET | `/api/config/kafka-settings` | 200 | Configurazione Kafka |
| POST | `/api/config/kafka-settings` | 200 | Aggiornamento Kafka |
| GET | `/config` | 200 | Config runtime |
| POST | `/config` | 200 | Aggiornamento config |

### Sistema
| Metodo | Path | Status | Note |
|--------|------|--------|------|
| GET | `/health` | 200 | Health check gateway |

## Test parametro `include`

| Endpoint | Include testati | Risultato |
|----------|----------------|-----------|
| `GET /corsa/{id}` | `include=tratta` | ✅ Tratta embedded inline |
| `GET /percorso/{id}` | `include=corsa,tratta,vascello` | ✅ Tutti gli oggetti espansi |
| `GET /percorso/by_corsa/{id}` | `include=corsa,tratta,vascello` | ✅ Expansion funzionante (fix applicato) |
| `GET /assegnazione/{id}` | `include=piano,percorso,corsa,vascello` | ✅ Tutti gli oggetti espansi |
| `GET /assegnazione/by_piano/{id}` | `include=percorso,corsa,vascello` | ✅ Include espansi |

## Forecast ML

| Metodo | Path | Status | Tempo | Note |
|--------|------|--------|-------|------|
| POST | `/corsa/{corsa_id}/prevedi` | 200 | 149ms | 243B risposta, ensemble 3 modelli |