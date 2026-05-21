####################################
# ISTRUZIONI PER L'USO
# 1. Assicurati di avere i file .json nella stessa cartella.
# 2. Avvia il server: uvicorn service:app --reload
# 3. Apri il file index.html
####################################

####################################
# SERVIZIO PREVISIONI + CI + AUTOCALCOLO STAGIONE/WEEKEND/FESTIVI + METEO
####################################

import json
import numpy as np
import re
from datetime import datetime, date
from fastapi import FastAPI
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
import requests


#####################################
# INIZIALIZZAZIONE APP & CORS
#####################################
app = FastAPI(title="Servizio Previsioni Biglietti")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


#####################################
# LISTA FESTIVI FISSI (ITALIA)
#####################################
FESTIVI_FISSI = {
    (1, 1),    # Capodanno
    (1, 6),    # Epifania
    (4, 25),   # Liberazione
    (5, 1),    # Lavoratori
    (6, 2),    # Repubblica
    (8, 15),   # Ferragosto
    (11, 1),   # Ognissanti
    (12, 8),   # Immacolata
    (12, 25),  # Natale
    (12, 26),  # S.Stefano
}


#####################################
# FUNZIONE: AUTODETERMINA STAGIONE
#####################################
def get_stagione(dt: date) -> str:
    m = dt.month
    if 3 <= m <= 5:
        return "Primavera"
    elif 6 <= m <= 8:
        return "Estate"
    elif 9 <= m <= 11:
        return "Autunno"
    else:
        return "Inverno"


#####################################
# FUNZIONI METEO (OPEN-METEO)
#####################################
def classify_weathercode(code: int | None) -> str | None:
    """
    Regole:
    - None      -> None  (si segnala al chiamante che va fatto doppio calcolo)
    - 0,1,2,3,45,48 -> 'bel tempo'
    - 82+      -> 'tempesta'
    - tutto il resto (51–86 ecc.) -> 'brutto tempo'
    """
    if code is None:
        return None

    if code in [0, 1, 2, 3, 45, 48]:
        return "bel tempo"

    if code >= 82:
        return "tempesta"

    return "brutto tempo"


def get_meteo_salerno(dt: date, orario_str: str | None):
    """
    Restituisce il meteo (bel tempo / brutto tempo / tempesta / None)
    prendendo il weather_code più vicino all'orario della corsa.
    Se orario_str è None → fallback alle 12:00.
    """

    # Parsing dell’orario della corsa: es. "1530" → "15:30"
    if orario_str is not None:
        try:
            hh = int(orario_str[:2])
            mm = int(orario_str[2:])
            target_time = datetime(dt.year, dt.month, dt.day, hh, mm)
        except Exception:
            # fallback alle 12:00 se parsing fallisce
            target_time = datetime(dt.year, dt.month, dt.day, 12, 0)
    else:
        # fallback alle 12:00
        target_time = datetime(dt.year, dt.month, dt.day, 12, 0)

    base = "https://api.open-meteo.com/v1/forecast"
    day_str = dt.strftime("%Y-%m-%d")

    url = (
        f"{base}?latitude=40.6754&longitude=14.7933"
        f"&hourly=weather_code"
        f"&timezone=Europe%2FRome"
        f"&start_date={day_str}&end_date={day_str}"
    )

    try:
        r = requests.get(url, timeout=5).json()
        times = r["hourly"]["time"]
        codes = r["hourly"]["weather_code"]
    except Exception:
        return None  # meteo sconosciuto

    # Converto tutti i timestamp in datetime (ora locale)
    time_objs = []
    for ts in times:
        try:
            time_objs.append(datetime.strptime(ts, "%Y-%m-%dT%H:%M"))
        except:
            time_objs.append(None)

    # Trovo il weather_code dell’ora più vicina
    best_idx = None
    best_diff = float("inf")

    for i, t_obj in enumerate(time_objs):
        if t_obj is None:
            continue
        diff = abs((t_obj - target_time).total_seconds())
        if diff < best_diff:
            best_diff = diff
            best_idx = i

    if best_idx is None:
        return None

    code = codes[best_idx]
    return classify_weathercode(code)



#####################################
# FUNZIONE: AUTODETERMINA WEEKEND
#####################################
def is_weekend(dt: date) -> bool:
    # weekday(): 0 lunedì … 6 domenica
    return dt.weekday() in (5, 6)  # sabato o domenica


#####################################
# FUNZIONE: AUTODETERMINA FESTIVO
#####################################
def is_festivo(dt: date, festivo_from_user: bool | None) -> bool:
    # PRIORITÀ:
    # 1. Se l’utente specifica festivo=True, allora forziamo a True
    #    (serve per Pasquetta o festività locali non in lista)
    if festivo_from_user is True:
        return True

    if festivo_from_user is False:
        return False

    # 2. Se l’utente NON specifica nulla → usa elenco fisso
    return (dt.month, dt.day) in FESTIVI_FISSI


#####################################
# CARICAMENTO MODELLI (params + cov + sigma)
#####################################
def load_model(fname: str):
    with open(fname, encoding="utf-8") as f:
        m = json.load(f)
    return m["params"], np.array(m["cov"]), m["sigma"], m


try:
    params_tot, cov_tot, sigma_tot, model_tot = load_model("mod_macro.json")
    params_m1,  cov_m1,  sigma_m1,  model_m1  = load_model("mod_micro_step1.json")
    params_m2,  cov_m2,  sigma_m2,  model_m2  = load_model("mod_micro_step2.json")

    CORSA_WEIGHT_MODEL = (
        model_m1.get("corsa_weight_model")
        or model_m2.get("corsa_weight_model")
        or model_tot.get("corsa_weight_model")
        or {}
    )

    config = json.load(open("config_modelli.json"))
    REF_DATE = datetime.strptime(config["ref_date"], "%Y-%m-%d").date()

except Exception as e:
    print(f"Errore nel caricamento dei JSON: {e}")
    REF_DATE = datetime.now().date()
    params_tot = params_m1 = params_m2 = {}
    cov_tot = cov_m1 = cov_m2 = np.eye(1)
    CORSA_WEIGHT_MODEL = {}


#####################################
# MODEL INPUT
#####################################
class CorsaInput(BaseModel):
    giorno_target: str
    corsa: str | None = None
    orario: str | None = None
    weekend: bool | None = None
    stagione: str | None = None
    festivo: bool | None = None
    biglietti_venduti_al_sample: float


#####################################
# FUNZIONI UTILI MODELLO
#####################################
def compute_time_features(giorno_target_str: str):
    dt = datetime.strptime(giorno_target_str, "%Y-%m-%d").date()
    t = (dt - REF_DATE).days
    dow = dt.weekday()
    doy = dt.timetuple().tm_yday
    sin365 = np.sin(2 * np.pi * doy / 365)
    cos365 = np.cos(2 * np.pi * doy / 365)
    return dt, t, dow, sin365, cos365


def build_x_vector(params: dict, feature_dict: dict) -> np.ndarray:
    keys = list(params.keys())
    return np.array([feature_dict.get(k, 0.0) for k in keys])


def predict_with_ci(params: dict, cov: np.ndarray, x_vec: np.ndarray):
    beta = np.array([params[k] for k in params.keys()])
    y = x_vec @ beta
    se = float(np.sqrt(x_vec @ cov @ x_vec))
    lo = y - 1.96 * se
    hi = y + 1.96 * se
    return y, lo, hi


def compute_biglietti_medi(sample: float, gap: int) -> float:
    return sample / max(1, 21 - gap)


def _normalizza_codice(value: str | None) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", value or "").upper()


def _normalizza_orario(value: str | None) -> str | None:
    digits = re.sub(r"[^0-9]", "", value or "")
    return digits[:4] if len(digits) >= 4 else None


def _normalizza_corsa(value: str | None) -> str:
    norm = _normalizza_codice(value)
    aliases = CORSA_WEIGHT_MODEL.get("port_code_aliases", {})
    for name_norm, code in sorted(aliases.items(), key=lambda item: len(item[0]), reverse=True):
        norm = norm.replace(name_norm, code)
    return norm


def resolve_corsa_weight(corsa: str | None, orario: str | None) -> tuple[float, str, str | None]:
    """
    Resolve a historical demand weight for a ride.
    Priority: exact route+time, route, departure time, default.
    """
    model = CORSA_WEIGHT_MODEL or {}
    default_weight = float(model.get("default_weight", 1.0))
    route_weights = model.get("route_weights", {})
    ride_weights = model.get("ride_weights", {})
    time_weights = model.get("time_weights", {})

    time_key = _normalizza_orario(orario)
    ride_norm = _normalizza_corsa(corsa)

    if ride_norm:
        if len(ride_norm) > 4 and ride_norm[-4:].isdigit():
            candidate = f"{ride_norm[:-4]}-{ride_norm[-4:]}"
            if candidate in ride_weights:
                return float(ride_weights[candidate]["weight"]), "ride", candidate

        if time_key:
            for route_key in sorted(route_weights.keys(), key=len, reverse=True):
                if route_key in ride_norm:
                    candidate = f"{route_key}-{time_key}"
                    if candidate in ride_weights:
                        return float(ride_weights[candidate]["weight"]), "ride", candidate

        for route_key in sorted(route_weights.keys(), key=len, reverse=True):
            if route_key in ride_norm:
                return float(route_weights[route_key]["weight"]), "route", route_key

    if time_key and time_key in time_weights:
        return float(time_weights[time_key]["weight"]), "time", time_key

    return default_weight, "default", None


#####################################
# BOOTSTRAP PER IL FINALE
#####################################
def bootstrap_final_prediction(
    B: int,
    params_tot, cov_tot,
    params_m1,  cov_m1,
    params_m2,  cov_m2,
    feat_tot: dict, feat_m1: dict, feat_m2: dict,
    sample_biglietti: float
):

    keys_tot = list(params_tot.keys())
    keys_m1  = list(params_m1.keys())
    keys_m2  = list(params_m2.keys())

    x_tot = np.array([feat_tot.get(k, 0.0) for k in keys_tot])
    x_m1  = np.array([feat_m1.get(k, 0.0) for k in keys_m1])

    results = []

    for _ in range(B):
        # 1. campione coefficienti
        beta_tot = np.random.multivariate_normal(
            [params_tot[k] for k in keys_tot], cov_tot
        )
        beta_m1 = np.random.multivariate_normal(
            [params_m1[k] for k in keys_m1], cov_m1
        )
        beta_m2 = np.random.multivariate_normal(
            [params_m2[k] for k in keys_m2], cov_m2
        )

        # 2. macro
        tot_raw = x_tot @ beta_tot
        tot_final = max(0, tot_raw)

        # 3. micro base
        base_raw = x_m1 @ beta_m1
        base_final = max(0, base_raw)

        # 4. micro adjustment
        feat_m2_iter = {
            "Intercept": 1,
            "biglietti_medi": feat_m2["biglietti_medi"],
            "totali_previsti": tot_final,
            "biglietti_medi:totali_previsti": feat_m2["biglietti_medi"] * tot_final,
        }
        x_m2_iter = np.array([feat_m2_iter.get(k, 0.0) for k in keys_m2])

        adj_raw = x_m2_iter @ beta_m2

        # 5. finale
        finale = max(sample_biglietti, base_final + adj_raw)
        results.append(finale)

    return float(np.percentile(results, 2.5)), float(np.percentile(results, 97.5))


#####################################
# ENDPOINT
#####################################
@app.post("/predict")
def predict(inp: CorsaInput):

    ##################################
    # PARSING DATA TARGET
    ##################################
    dt, t, dow, sin365, cos365 = compute_time_features(inp.giorno_target)

    ##################################
    # METEO SALERNO (CATEGORIA O None)
    ##################################
    meteo_auto_raw = get_meteo_salerno(dt, inp.orario)

    # Caso speciale: meteo sconosciuto → doppio calcolo (bel tempo + tempesta)
    if meteo_auto_raw is None:
        meteos_to_test = ["bel tempo", "tempesta"]
    else:
        meteos_to_test = [meteo_auto_raw]

    ##################################
    # AUTOCALCOLO WEEKEND / STAGIONE / FESTIVO
    ##################################
    weekend = is_weekend(dt)
    stagione = get_stagione(dt)
    festivo = is_festivo(dt, inp.festivo)

    ##################################
    # MACRO MODEL (unico, non dipende dal meteo)
    ##################################
    feat_tot = {
        "Intercept": 1,
        "t": t,
        "sin365": sin365,
        "cos365": cos365,
        f"C(dow)[T.{dow}]": 1 if dow != 0 else 0,
    }

    x_tot = build_x_vector(params_tot, feat_tot)
    tot_raw, tot_lo, tot_hi = predict_with_ci(params_tot, cov_tot, x_tot)
    tot_final = max(0, tot_raw)

    ##################################
    # GIORNI ALLA PARTENZA (CALCOLATI)
    ##################################
    oggi = datetime.now().date()
    giorni_alla_partenza_auto = max(0, (dt - oggi).days)

    biglietti_medi = compute_biglietti_medi(
        inp.biglietti_venduti_al_sample,
        giorni_alla_partenza_auto
    )

    peso_corsa, peso_corsa_source, peso_corsa_key = resolve_corsa_weight(inp.corsa, inp.orario)
    peso_corsa_delta = peso_corsa - 1.0

    ##################################
    # LOOP SU SCENARI METEO
    ##################################
    final_preds = []
    final_ci_lows = []
    final_ci_highs = []

    # per output dettagliato mostriamo micro_base/adjust del primo scenario
    base_final_first = None
    adj_raw_first = None
    base_lo_first = base_hi_first = None
    adj_lo_first = adj_hi_first = None
    micro_finale_first = None
    final_lo_first = final_hi_first = None
    meteo_used_for_components = None

    for idx_m, meteo_auto in enumerate(meteos_to_test):

        # ----- MICRO BASE MODEL -----
        feat_m1 = {
            "Intercept": 1,
            "peso_corsa_delta": peso_corsa_delta,
        }

        if weekend:
            feat_m1["C(weekend)[T.True]"] = 1

        feat_m1[f"C(stagione)[T.{stagione}]"] = 1

        if festivo:
            feat_m1["C(festivo)[T.si]"] = 1

        feat_m1[f"C(meteo_previsto_al_sample)[T.{meteo_auto}]"] = 1

        x_m1 = build_x_vector(params_m1, feat_m1)
        base_raw, base_lo, base_hi = predict_with_ci(params_m1, cov_m1, x_m1)
        base_final = max(0, base_raw)

        # ----- MICRO ADJUST MODEL -----
        feat_m2 = {
            "Intercept": 1,
            "biglietti_medi": biglietti_medi,
            "totali_previsti": tot_final,
            "biglietti_medi:totali_previsti": biglietti_medi * tot_final,
        }

        x_m2 = build_x_vector(params_m2, feat_m2)
        adj_raw, adj_lo, adj_hi = predict_with_ci(params_m2, cov_m2, x_m2)

        # ----- PREVISIONE FINALE (scenario corrente) -----
        micro_finale_raw = base_final + adj_raw
        micro_finale = max(inp.biglietti_venduti_al_sample, micro_finale_raw)

        # ----- BOOTSTRAP FINALE (scenario corrente) -----
        final_lo, final_hi = bootstrap_final_prediction(
            B=400,
            params_tot=params_tot, cov_tot=cov_tot,
            params_m1=params_m1,  cov_m1=cov_m1,
            params_m2=params_m2,  cov_m2=cov_m2,
            feat_tot=feat_tot,
            feat_m1=feat_m1,
            feat_m2=feat_m2,
            sample_biglietti=inp.biglietti_venduti_al_sample
        )

        final_preds.append(micro_finale)
        final_ci_lows.append(final_lo)
        final_ci_highs.append(final_hi)

        if idx_m == 0:
            base_final_first = base_final
            adj_raw_first = adj_raw
            base_lo_first, base_hi_first = base_lo, base_hi
            adj_lo_first, adj_hi_first = adj_lo, adj_hi
            micro_finale_first = micro_finale
            final_lo_first, final_hi_first = final_lo, final_hi
            meteo_used_for_components = meteo_auto

    ###############################################
    # COMBINAZIONE RISULTATI SE METEO ERA UNKNOWN
    ###############################################
    if len(meteos_to_test) == 1:
        # nessuna incertezza meteo: uso lo scenario calcolato
        combined_low = final_lo_first
        combined_high = final_hi_first
        combined_pred = micro_finale_first
        meteo_out = meteo_used_for_components
    else:
        # meteo sconosciuto: intervallo combinato = min(low), max(high)
        combined_low = min(final_ci_lows)
        combined_high = max(final_ci_highs)
        combined_pred = (combined_low + combined_high) / 2.0
        meteo_out = "Non Disponibile"

    ##################################
    # OUTPUT
    ##################################
    return {
        "giorno_target": inp.giorno_target,
        "weekend_auto": weekend,
        "stagione_auto": stagione,
        "festivo_auto": festivo,
        "giorni_alla_partenza_auto": int(giorni_alla_partenza_auto),
        "meteo_auto": meteo_out,
        "peso_corsa": round(peso_corsa, 4),
        "peso_corsa_source": peso_corsa_source,
        "peso_corsa_key": peso_corsa_key,

        "totali_previsti": int(round(tot_final)),
        "totali_ci_95": [int(round(tot_lo)), int(round(tot_hi))],

        # micro_base/adjust riferiti al primo scenario meteo (tipicamente 'bel tempo')
        "micro_base": int(round(base_final_first)) if base_final_first is not None else None,
        "micro_base_ci_95": [
            int(round(base_lo_first)) if base_lo_first is not None else None,
            int(round(base_hi_first)) if base_hi_first is not None else None,
        ],

        "micro_adjust": int(round(adj_raw_first)) if adj_raw_first is not None else None,
        "micro_adjust_ci_95": [
            int(round(adj_lo_first)) if adj_lo_first is not None else None,
            int(round(adj_hi_first)) if adj_hi_first is not None else None,
        ],

        # finale combinato (gestisce il caso meteo incerto)
        "micro_finale": int(round(combined_pred)),
        "micro_finale_ci_95": [
            int(round(combined_low)),
            int(round(combined_high)),
        ],
    }
