# Regression Old vs New

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