# Audit FK: travelmar_db vs database splittati

Data audit: 2026-02-23

## Sintesi

Confronto effettuato tra tutte le FK storiche presenti in `travelmar_db` e lo stato nei DB split:

- `PRESERVED`: 4
- `CROSS_DB` (non applicabile come FK fisica tra DB diversi): 10
- `NOT_SPLIT` (tabelle non migrate nei DB split): 2
- `MISSING_INTRA_DB`: 0

## Dettaglio per FK storica

| Esito | FK storica (monolite) | Stato nel modello split |
|---|---|---|
| CROSS_DB | `allarme.utente_assegnatario_id -> utente.id` | `alerting_db -> anagrafica_db` (vincolo fisico cross-DB non applicabile) |
| CROSS_DB | `assegnazione.percorso_id -> percorso.id` | `operativo_db -> percorsi_db` (vincolo fisico cross-DB non applicabile) |
| PRESERVED | `assegnazione.piano_id -> piano_operativo.id` | Presente in `operativo_db` (`assegnazione_piano_id_fkey`) |
| NOT_SPLIT | `componente.vascello_id -> vascello.id` | Tabella/e non presenti nello split |
| CROSS_DB | `corsa.tratta_id -> tratta.id` | `operativo_db -> anagrafica_db` |
| CROSS_DB | `corsa.previsione_domanda_id -> previsione_domanda.id` | `operativo_db -> forecast_db` |
| CROSS_DB | `deadhead_trips.porto_arrivo_id -> porto.id` | `operativo_db -> anagrafica_db` |
| PRESERVED | `deadhead_trips.piano_id -> piano_operativo.id` | Presente in `operativo_db` (`deadhead_trips_piano_id_fkey`) |
| CROSS_DB | `deadhead_trips.porto_partenza_id -> porto.id` | `operativo_db -> anagrafica_db` |
| CROSS_DB | `deadhead_trips.vascello_id -> vascello.id` | `operativo_db -> anagrafica_db` |
| CROSS_DB | `percorso.id_corsa -> corsa.id` | `percorsi_db -> operativo_db` |
| CROSS_DB | `percorso.vascello_id -> vascello.id` | `percorsi_db -> anagrafica_db` |
| NOT_SPLIT | `posizione_ais.vascello_id -> vascello.id` | Tabella/e non presenti nello split |
| CROSS_DB | `previsione_domanda.corsa_id -> corsa.id` | `forecast_db -> operativo_db` |
| PRESERVED | `tratta.porto_arrivo_id -> porto.id` | Presente in `anagrafica_db` (`tratta_porto_arrivo_id_fkey`) |
| PRESERVED | `tratta.porto_partenza_id -> porto.id` | Presente in `anagrafica_db` (`tratta_porto_partenza_id_fkey`) |

## Conclusione tecnica

- Le FK intra-dominio possibili nello split risultano preservate (4/4).
- Le FK mancanti sono tutte dovute a:
  - relazioni ora distribuite tra microservizi (`CROSS_DB`), oppure
  - tabelle non incluse nello split (`NOT_SPLIT`).
- Quindi la logica relazionale del vecchio sistema è stata mantenuta come:
  - **vincolo DB** per i casi intra-dominio,
  - **vincolo applicativo/API** per i casi cross-dominio.

## Nota di governance

Per i legami `CROSS_DB`, l'integrità va garantita tramite:
- validazioni applicative lato servizio (già presenti in più endpoint),
- test di integrazione cross-servizio,
- eventuale adozione di saghe/eventi per consistenza nel tempo.
