# Regression Old vs New

Data confronto iniziale: 2026-02-26

Total cases: 15
Mismatches: 1

| Method | Path | Old | New | Notes |
|---|---|---:|---:|---|
| GET | /docs | 200 | 200 | ok |
| GET | /openapi.json | 200 | 200 | ok |
| GET | /porto/lista | 200 | 200 | ok |
| GET | /tratta/lista | 200 | 200 | ok |
| GET | /vascello/lista | 200 | 200 | ok |
| GET | /corsa/lista | 200 | 200 | ok |
| GET | /corsa/giorno?giorno=2026-02-26&solofuture=false | 200 | 200 | ok |
| GET | /piano/lista | 200 | 200 | ok |
| GET | /allarme/lista | 404 | 200 | status-diff |
| GET | /api/config/kafka-settings | 200 | 200 | ok |
| GET | /config | 200 | 200 | ok |
| POST | /weather_routing/vuoto | 200 | 200 | ok |
| GET | /percorso/by_corsa/{id} | 200 | 200 | ok |
| POST | /weather_routing/carico#1 | 200 | 200 | ok old=['cached'] new=['cached'] |
| POST | /weather_routing/carico#2 | 200 | 200 | ok old=['cached'] new=['cached'] |

## Nota sul mismatch `/allarme/lista`

Lo stack old restituiva 404 perché il router `allarme.py` e il servizio `alerting_service` non erano ancora disponibili. Nel nuovo stack è funzionante e delegato ad `alerting_service` (:8075).

---

## Aggiornamento 2026-03-04

### Fix applicati dopo audit completo

I seguenti endpoint avevano problemi di performance o funzionalità nel nuovo stack; sono ora risolti:

| Endpoint | Problema (pre-fix) | Stato attuale |
|----------|---------------------|---------------|
| `GET /health` | 404 (mancante) | ✅ 200 |
| `GET /dashboard/corse` | 503 timeout | ✅ 200 (29s, cache N+1) |
| `GET /corsa/lista` | Lento (21.6s, rischio timeout) | ✅ 200 (10.6s, cache N+1) |
| `GET /piano/lista` | Rischio timeout | ✅ 200 (timeout 60s) |
| `GET /percorso/by_corsa?include=` | Include ignorato silenziosamente | ✅ 200 (expansion funzionante) |
| `GET /assegnazione/by_piano/{id}` | Rischio timeout | ✅ 200 (timeout 60s) |
| `POST /assegnazione/bulk` | Rischio timeout | ✅ 200 (timeout 60s) |
| `GET /corsa/giorno` | N+1 query lento | ✅ 200 (cache N+1) |

### Nuovi endpoint aggiunti nel nuovo stack (non presenti in old)

| Metodo | Endpoint | Servizio |
|--------|----------|----------|
| GET | `/health` | gateway |
| GET | `/weather/health` | gateway → weather |
| POST | `/weather/layer` | gateway → weather |
| GET | `/weather/cache/layer` | gateway → weather |
| GET | `/weather/cache/layer/{key}` | gateway → weather |
| GET | `/check_replanning/status` | gateway → replanning |