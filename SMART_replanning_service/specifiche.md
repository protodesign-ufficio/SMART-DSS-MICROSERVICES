# Propagazione del Ritardo per un Piano Operativo

## Obiettivo

Dato un istante corrente **X**, l’obiettivo è propagare in avanti i ritardi sulle corse future di ogni nave della flotta, considerando i tempi di **deadhead** (attesa o riposizionamento) tra corse consecutive.

L’algoritmo produce una previsione futura del piano operativo reale.

---

## Notazione

* **v** = indice nave
* **j** = indice corsa della nave v
* **S_dep[v,j]** = orario schedulato di partenza
* **Dur[v,j]** = durata della corsa
* **Deadhead[v,j]** = tempo morto dopo la corsa j
* **Pred_dep[v,j]** = partenza prevista reale
* **Pred_arr[v,j]** = arrivo previsto reale
* **k[v]** = prima corsa non completata della nave v all’istante X
* **ETA_real[v]** = ETA reale se la nave è in navigazione
* **Ready_time[v]** = istante in cui la nave è pronta a partire

---

## Algoritmo

### Propagazione del Ritardo sulla Flotta

```
PER ogni nave v

    j ← k[v]    # prima corsa non completata

    SE la nave v è in navigazione
        Pred_dep[v,j] ← S_dep[v,j]
        Pred_arr[v,j] ← ETA_real[v]
    ALTRIMENTI
        Pred_dep[v,j] ← max(S_dep[v,j], Ready_time[v])
        Pred_arr[v,j] ← Pred_dep[v,j] + Dur[v,j]
    FINE SE

    PER j = k[v] + 1 fino all’ultima corsa della nave v

        earliest_dep ← Pred_arr[v,j-1] + Deadhead[v,j-1]

        Pred_dep[v,j] ← max(S_dep[v,j], earliest_dep)

        Pred_arr[v,j] ← Pred_dep[v,j] + Dur[v,j]

    FINE PER

FINE PER
```

---

## Spiegazione

Per ogni nave:

1. Si individua la prima corsa non completata al tempo **X**.
2. Si inizializza la previsione:

   * usando l’ETA reale se la nave è in navigazione,
   * oppure usando il tempo di disponibilità se la nave è ferma.
3. Si propaga il ritardo:

   * la corsa successiva non può iniziare prima della fine della precedente e del deadhead,
   * se la nave è pronta prima dell’orario schedulato, il ritardo viene assorbito,
   * altrimenti il ritardo si propaga.

---

### Regola di propagazione

[
Pred_{dep}[v,j] = \max\left(S_{dep}[v,j],; Pred_{arr}[v,j-1] + Deadhead[v,j-1]\right)
]

Il ritardo si propaga solo se:

[
Pred_{arr}[v,j-1] + Deadhead[v,j-1] > S_{dep}[v,j]
]

---

## Esempio

**Nave ACQUARIUS**, istante **X = 12:00**

* C1: AMA–SAL, partenza 10:30, durata 1h30
* Deadhead dopo C1: 20 min
* C2: POS–AMA, partenza 12:30, durata 1h
* C3: AMA–CET, partenza 13:30, durata 1h
* Deadhead dopo C3: 10 min
* C4: CET–MAI, partenza 15:00, durata 2h

Supponiamo che la corsa **C1 finisca in ritardo alle 12:30**.

### C2

Ready = 12:30 + 20 min = **12:50**

Pred_dep[C2] = max(12:30, 12:50) = **12:50**
Pred_arr[C2] = **13:50**

### C3

Pred_dep[C3] = max(13:30, 13:50) = **13:50**
Pred_arr[C3] = **14:50**

### C4

earliest = 14:50 + 10 min = **15:00**
Pred_dep[C4] = **15:00**
Pred_arr[C4] = **17:00**

Il ritardo si propaga su C2 e C3, ma viene riassorbito su C4.

---

## Esempio grafico

![Esempio propagazione ritardo](example_delay_propagation.png)

---

# Criteri per l’Attivazione del Replanning

Dopo aver eseguito la propagazione del ritardo su tutta la flotta, si calcolano indicatori globali per valutare se il piano operativo sta diventando instabile e richiede un ricalcolo.

---

## Parametri di soglia

* **θ** = soglia minima di ritardo per considerare una corsa in ritardo (es. 10 min)
* **Θ** = soglia di ritardo severo (es. 30 min)
* **M** = numero massimo tollerabile di corse in ritardo
* **M_c** = numero massimo tollerabile di corse critiche
* **D_tot_max** = ritardo totale massimo tollerabile
* **D_max_max** = massimo ritardo singolo tollerabile
* **H** = orizzonte temporale di controllo (es. prossime 2 ore)

---

## Indicatori globali

Si considerano le corse future nell’intervallo **[X, X+H]**:

[
LateCount = \sum_v \sum_{j \in J_H(v)} 1{Delay_{arr}[v,j] > \theta}
]

[
CriticalCount = \sum_v \sum_{j \in J_H(v)} 1{Delay_{arr}[v,j] > \Theta}
]

[
TotalDelay = \sum_v \sum_{j \in J_H(v)} \max(0, Delay_{arr}[v,j])
]

[
MaxDelay = \max_{v,j \in J_H(v)} Delay_{arr}[v,j]
]

---

## Regole di decisione

Si attiva il replanning se:

* LateCount > M
* CriticalCount > M_c
* TotalDelay > D_tot_max
* MaxDelay > D_max_max

---

## Stabilità operativa

Per evitare replanning troppo frequenti:

* introdurre un **cooldown operativo** tra due replanning consecutivi
* definire una **finestra congelata** (modificabile solo per ritardi critici)

---

## Interpretazione

* Se molte corse accumulano ritardo → il piano perde stabilità
* Se il ritardo totale cresce → impatto operativo significativo
* Se compare un grande ritardo singolo → possibile propagazione a cascata

Questi criteri trasformano la propagazione del ritardo in un **trigger automatico di replanning**.

