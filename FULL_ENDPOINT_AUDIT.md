# Full Endpoint Audit (New Stack)

Total operations tested: 64
Status distribution: {"200": 27, "422": 31, "404": 6}
Hard failures (5xx or no-response): 0

## Hard failures
| Method | Path | Status | URL |
|---|---|---:|---|

## All results
| Method | Path | Status | Payload Mode |
|---|---|---:|---|
| GET | /allarme/lista | 200 | no-body |
| GET | /api/config/kafka-settings | 200 | no-body |
| POST | /api/config/kafka-settings | 200 | safe-body |
| POST | /assegnazione/bulk | 422 | safe-body |
| GET | /assegnazione/by_piano/{piano_id} | 200 | no-body |
| POST | /assegnazione/check_validita | 422 | safe-body |
| POST | /assegnazione/crea | 422 | safe-body |
| POST | /assegnazione/in_corso2cancellata | 200 | safe-body |
| POST | /assegnazione/pianifica | 422 | safe-body |
| PATCH | /assegnazione/{assegnazione_id}/stato | 422 | safe-body |
| POST | /check_replanning | 200 | safe-body |
| GET | /config | 200 | no-body |
| POST | /config | 200 | safe-body |
| POST | /corsa/crea | 422 | safe-body |
| POST | /corsa/elimina | 404 | safe-body |
| GET | /corsa/giorno | 200 | no-body |
| GET | /corsa/lista | 200 | no-body |
| POST | /corsa/modifica | 404 | safe-body |
| GET | /corsa/orari/{tratta_id} | 422 | no-body |
| GET | /corsa/{corsa_id} | 200 | no-body |
| POST | /corsa/{corsa_id}/prevedi | 422 | safe-body |
| GET | /dashboard/corse | 200 | no-body |
| POST | /deadhead/crea | 422 | safe-body |
| POST | /deadhead/elimina | 422 | safe-body |
| GET | /deadhead/lista | 200 | no-body |
| POST | /deadhead/modifica | 422 | safe-body |
| POST | /percorso/applica_variazione | 422 | safe-body |
| GET | /percorso/by_corsa/{corsa_id} | 200 | no-body |
| POST | /percorso/elimina | 422 | safe-body |
| GET | /percorso/{percorso_id} | 200 | no-body |
| POST | /pianificazione/compatibili | 422 | safe-body |
| POST | /piano/crea | 422 | safe-body |
| POST | /piano/elimina | 422 | safe-body |
| GET | /piano/lista | 200 | no-body |
| POST | /piano/modifica | 422 | safe-body |
| POST | /piano/valida | 422 | safe-body |
| GET | /piano/{piano_id} | 200 | no-body |
| GET | /porto/by_name/{nome} | 404 | no-body |
| POST | /porto/crea | 422 | safe-body |
| POST | /porto/elimina | 422 | safe-body |
| GET | /porto/lista | 200 | no-body |
| POST | /porto/modifica | 422 | safe-body |
| GET | /porto/{porto_id} | 200 | no-body |
| POST | /scheduling/giorno | 422 | safe-body |
| POST | /scheduling/ottimizza | 422 | safe-body |
| POST | /simulation/build_and_run | 422 | safe-body |
| GET | /simulation/schedulate | 404 | no-body |
| POST | /simulation/simula_piano | 422 | safe-body |
| POST | /tratta/crea | 422 | safe-body |
| POST | /tratta/crea_multi | 422 | safe-body |
| POST | /tratta/elimina | 404 | safe-body |
| GET | /tratta/lista | 200 | no-body |
| POST | /tratta/modifica | 422 | safe-body |
| GET | /tratta/{tratta_id} | 200 | no-body |
| GET | /vascello/by_mmsi/{mmsi} | 200 | no-body |
| POST | /vascello/crea | 422 | safe-body |
| POST | /vascello/elimina | 422 | safe-body |
| GET | /vascello/lista | 200 | no-body |
| POST | /vascello/modifica | 422 | safe-body |
| GET | /vascello/{mmsi}/image | 200 | no-body |
| GET | /vascello/{mmsi}/percorso_attivo | 404 | no-body |
| GET | /vascello/{vascello_id} | 200 | no-body |
| POST | /weather_routing/carico | 200 | safe-body |
| POST | /weather_routing/vuoto | 200 | safe-body |