import math
import numpy as np
from constants import CURRENT_SCALE, latlon_to_xy, xy_to_latlon
from Api_Copernicus import read_point
from waypoint import Waypoint, WaypointType
import requests
import numpy as np
GRID_SPACING_DEFAULT = None
import numpy as np
import pickle
import os
#from app_server import custom_current  # importa la variabile globale

import pickle
import os
import json

POINT_CACHE_FILE = "./point_water_cache.json"

# cache in RAM
_water_cache = {}

_water_mask_cache = {}  # cache in RAM {grid_spacing: mask}

def build_water_mask(bbox, grid_spacing):
    """Costruisce o carica da file la maschera acqua/terra per il bbox e grid_spacing."""
    global _water_mask_cache

    # Se già in RAM
    if grid_spacing in _water_mask_cache:
        return _water_mask_cache[grid_spacing]

    # Nome file specifico per grid_spacing
    WATER_MASK_FILE = f"./water_mask/water_mask_{grid_spacing}.pkl"

    # Se esiste su disco → carico
    if os.path.exists(WATER_MASK_FILE):
        with open(WATER_MASK_FILE, "rb") as f:
            mask = pickle.load(f)
        print(f"[INFO] Water mask caricata da {WATER_MASK_FILE} ({len(mask)} celle)")
        _water_mask_cache[grid_spacing] = mask
        return mask

    # Altrimenti la costruisco
    print(f"[INFO] Genero nuova water mask per grid_spacing={grid_spacing}...")
    sw_x, sw_y = latlon_to_xy(bbox["minimum_latitude"], bbox["minimum_longitude"])
    ne_x, ne_y = latlon_to_xy(bbox["maximum_latitude"], bbox["maximum_longitude"])

    width = int((ne_x - sw_x) // grid_spacing) + 1
    height = int((ne_y - sw_y) // grid_spacing) + 1

    mask = {}
    for i in range(height):
        for j in range(width):
            x = sw_x + j * grid_spacing
            y = sw_y + i * grid_spacing
            lat, lon = xy_to_latlon(x, y)
            mask[(i, j)] = is_point_water(lat, lon)  # chiamata API (cachata internamente)

    # Salvo su file
    with open(WATER_MASK_FILE, "wb") as f:
        pickle.dump(mask, f)
    print(f"[INFO] Water mask salvata in {WATER_MASK_FILE}")

    _water_mask_cache[grid_spacing] = mask
    return mask


def calcola_consumo_minimo_ottimo(A, B, Vc, Ve_min=0.1*1.852): 
    #NOT USED
    """
    Calcola la velocità propria minima Vp necessaria per avanzare da A a B (rotta retta),
    compensando la corrente nel modo più efficiente possibile.

    Parametri:
        A, B: tuple di coordinate (x, y)
        Vc: vettore corrente (vx, vy)

    Ritorna:
        Vp_mod: modulo della velocità propria minima (m/s)
        Pv: angolo di prora in radianti
        Ve: velocità effettiva lungo la rotta A→B (m/s)
        Vp_vec: vettore Vp
        Ve_vec: vettore Ve risultante
    """
    A = np.array(A, dtype=float)
    B = np.array(B, dtype=float)
    Vc = np.array(Vc, dtype=float)

    AB = B - A
    D = np.linalg.norm(AB)
    if D == 0:
        return 0.0, 0.0, 0.0, np.array([0.0, 0.0]), np.array([0.0, 0.0])

    u_Rv = AB / D  # direzione unitaria della rotta

    # Proiezione della corrente sulla direzione di rotta
    Vc_proj = np.dot(Vc, u_Rv)

    # Ve ottimo = lascia fare tutto alla corrente lungo la rotta
    Ve_opt = max(Vc_proj, Ve_min)

    # Calcolo vettore Ve e Vp
    Ve_vec = Ve_opt * u_Rv
    Vp_vec = Ve_vec - Vc
    Vp_mod = np.linalg.norm(Vp_vec)
    if Vp_mod < Ve_min or np.isnan(Vp_mod):
        Vp_mod = Ve_min
        # direzione di fallback: stessa di Ve_vec o unitaria lungo Rv
        dir_v = u_Rv if np.linalg.norm(u_Rv) > 0 else np.array([1.0, 0.0])
        Vp_vec = Vp_mod * dir_v
    Pv = np.arctan2(Vp_vec[1], Vp_vec[0])
    D_km = D / 1000.0  # distanza in km
    t_consumo_h = D_km / Ve_opt if Ve_opt > 0 else float('inf')
    t_consumo = t_consumo_h * 60  # in minuti

    return Vp_mod, Pv, Ve_opt, Vp_vec, Ve_vec, t_consumo    

def calcola_tempo_minimo(A, B, Vc, Vp_max):
    """
    Calcola il tempo minimo di percorrenza tra i punti A e B
    considerando la corrente marina.

    Parametri:
    - A: tuple o array (x_A, y_A)
    - B: tuple o array (x_B, y_B)
    - Vc: tuple o array (Vcx, Vcy) => velocità della corrente
    - Vp_max: float => velocità massima della barca

    Ritorna:
    - t_min: tempo minimo di percorrenza (in secondi)
    - Ve: modulo della velocità effettiva
    - Pv: direzione (angolo in radianti) della prora vera
    """
    A = np.array(A, dtype=float)
    B = np.array(B, dtype=float)
    Vc = np.array(Vc, dtype=float)

    # Vettore AB e distanza
    AB = B - A
    D = np.linalg.norm(AB)

    # Direzione unitaria della rotta vera
    u_Rv = AB / D

    # Coefficienti equazione quadratica per Ve
    a = 1
    b = -2 * np.dot(u_Rv, Vc)
    c = np.dot(Vc, Vc) - Vp_max**2

    delta = b**2 - 4*a*c
    if delta < 0:
        raise ValueError("La velocità propria è insufficiente per compensare la corrente.")

    # Soluzione positiva di Ve
    Ve1 = (-b + np.sqrt(delta)) / (2*a)
    Ve2 = (-b - np.sqrt(delta)) / (2*a)
    Ve = max(Ve1, Ve2)

    # Calcolo tempo minimo
    # print("t_min: D, Ve", D, Ve)
    D_km = D / 1000.0  # distanza in km
    # print("D_km", D_km, Ve)
    t_h = D_km / Ve
    t_min = t_h * 60  # in secondi


    # Calcolo direzione prora vera (Pv)
    Ve_vector = Ve * u_Rv
    Vp_vector = Ve_vector - Vc
    Pv_angle = np.arctan2(Vp_vector[1], Vp_vector[0])  # in radianti
    #print("angolo Ve: ", np.arctan2(Ve[1], Ve[0]) , "angolo Vp: ", Pv_angle)


    return t_min, Ve, Pv_angle, Vp_vector


# cache globale: { (lat_rounded, lon_rounded): True/False }
_water_cache = {}

def is_point_water(lat: float, lon: float, precision: int = 3) -> bool:
    """
    Verifica se un punto è acqua con caching locale + salvataggio su file.
    precision: numero di decimali per la chiave cache (~100m se 3).
    """
    global _water_cache
    print(f"[DEBUG] Chiamata is_point_water per ({lat}, {lon})")


    # Arrotondo per chiave
    lat_r = round(lat, precision)
    lon_r = round(lon, precision)
    key = f"{lat_r},{lon_r}"

    # 1️ Se esiste cache in RAM → ritorna subito
    if key in _water_cache:
        return _water_cache[key]

    # 2️ Se esiste cache su file → caricala (solo la prima volta)
    if not _water_cache and os.path.exists(POINT_CACHE_FILE):
        with open(POINT_CACHE_FILE, "r") as f:
            try:
                _water_cache.update(json.load(f))
            except json.JSONDecodeError:
                pass  # file corrotto, ignora

    # 3️ Se trovato dopo aver caricato il file
    if key in _water_cache:
        return _water_cache[key]

    # 4️ Altrimenti → chiama API remota
    import requests
    try:
        url = f"https://is-on-water.balbona.me/api/v1/get/{lat_r}/{lon_r}"
        resp = requests.get(url, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            is_water = data.get("isWater", False)
        else:
            is_water = False
    except Exception as e:
        print(f"[⚠️] Errore API is-on-water per ({lat_r}, {lon_r}): {e}")
        is_water = False

    # 5️ Aggiorna cache in RAM e salva su file
    _water_cache[key] = is_water
    with open(POINT_CACHE_FILE, "w") as f:
        json.dump(_water_cache, f)

    return is_water

def build_double_weighted_graph_NAMOA(dataset, dataset_wave, time, bbox,
                                grid_spacing,
                                Vp_max, vel_vec ,Ve_min=0.1, custom_current=None,
                                grafo=None, nodes=None, empty=False, vessel_length=30.0):
    """
    Costruisce un grafo pesato multi-obiettivo per NAMOA*.

    Ogni arco (i,j) → (ni,nj) viene espanso su più velocità proprie (Vp_test),
    generando più archi paralleli con:
      - costo 1: tempo minimo di percorrenza
      - costo 2: comfort (derivato da stato del mare)

    IMPORTANTI:
    - Le correnti NON sono per-nodo, ma già incorporate negli archi di `grafo`
      (costruito da build_graph_from_grib).
    - Il grafo risultante è un multigrafo logico: più archi tra le stesse celle,
      distinti dal label "vel=XX.XX".
    - Questa funzione NON esegue routing: prepara solo la struttura dati.
    """
    print("Costruzione grafo pesato per NAMOA*...vess length", vessel_length)
    

    sw_x, sw_y = latlon_to_xy(bbox["minimum_latitude"], bbox["minimum_longitude"])
    ne_x, ne_y = latlon_to_xy(bbox["maximum_latitude"], bbox["maximum_longitude"])

    width = int((ne_x - sw_x) // grid_spacing) + 1
    height = int((ne_y - sw_y) // grid_spacing) + 1

    cell_to_xy = {}
    currents = {}
    edge_data = {}  # (from_cell, to_cell) -> {"tempo": ..., "consumo": ..., "Pv": ..., "Vref": ...}

    # 🔹 Caso nuovo: usiamo grafo e nodes costruiti con build_graph_from_grib
    grafo_pesato = {}

    for (i, j), edges in grafo.items():
        # nodes[(i,j)] contiene (lat, lon) → converto in metri (x,y)
        lat, lon = nodes[(i, j)]
        x, y = latlon_to_xy(lat, lon)
        cell_to_xy[(i, j)] = (x, y)
        currents[(i, j)] = None  # correnti per-archi, non per-nodo
        grafo_pesato[(i, j)] = []

        for (ni, nj), Vc in edges:
            Vc = np.array(Vc, dtype=float)

            lat2, lon2 = nodes[(ni, nj)]
            x2_temp, y2_temp = latlon_to_xy(lat2, lon2)
            vel_set = vel_vec  # uso il set di velocità passate
            for Vp_test in vel_set:
                try:
                    t_min, Ve, Pv, Vp_vec = calcola_tempo_minimo(
                        A=(x, y), B=(x2_temp, y2_temp), Vc=Vc, Vp_max=Vp_test
                    )
                    Pv_tempo = np.arctan2(Vp_vec[1], Vp_vec[0])  # Calcola angolo di prua per Tempo

                    if empty is False:
                        wave_point = dataset_wave.sel(
                                time=time,
                                latitude=lat,
                                longitude=lon,
                                method="nearest"
                            )
                        
                        #Pv_tempo = np.arctan2(Vp_vec[1], Vp_vec[0])  # Calcola angolo di prua per Tempo

                        #print(f"Comfort :")

                        comfort = calcola_comfort(Ve, Pv_tempo, wave_point, vessel_length) 
                    else:
                        comfort = 0.0 # costo disabilitato in modalità vuoto

                    #print(f"Comfort calcolato per arco ({i},{j})→({ni},{nj}) a Vp={Vp_test:.2f}: {comfort:.4f}")
                    # print("Tempo min: ", t_min, "V: ", Vp_vec)
                    # Vp_mod, Pv_min_costo, Ve_opt, Vp_vec_min_costo, Ve_vec, t_consumo = calcola_consumo_minimo_ottimo(
                    #     A=(x, y), B=(x2_temp, y2_temp), Vc=Vc, Ve_min=Ve_min
                    # )
                    # print("Consumo min: tempo: ", t_consumo, "Vref: ", Vp_vec_min_costo)
                    # # 👇 archi con (tempo, "consumo") per build_aggregated_weight_graph/Dijkstra
                    #grafo_pesato[(i, j)].append(((ni, nj), t_min, Vp_mod))

                    # Variante Tempo: aggiungi arco con t_min e Vp_vec
                    grafo_pesato[(i, j)].append(((ni, nj), t_min,  comfort, f"vel={Vp_test:.2f}"))  # arco per Tempo

                    # Variante Consumo: aggiungi arco con Vp_mod e Vp_vec_min_costo
                    # grafo_pesato[(i, j)].append(((ni, nj), t_consumo, np.sqrt(Vp_vec_min_costo[0]**2 + Vp_vec_min_costo[1]**2), "consumo"))  # arco per Consumo
                    # Pv_consumo = np.arctan2(Vp_vec_min_costo[1], Vp_vec_min_costo[0])  # Calcola angolo di prua per Consumo

                    # Salva i dati separati per Tempo e Consumo
                    key = ((i, j), (ni, nj))
                    if key not in edge_data:
                        edge_data[key] = []  # crea lista la prima volta

                    edge_data[key].append({
                        "vel_label": f"vel={Vp_test:.2f}",  # coerente con il label usato in grafo_pesato
                        "Vp_test": float(Vp_test),
                        "Pv": float(Pv_tempo),
                        "Vref": (float(Vp_vec[0]), float(Vp_vec[1])),
                    })



                except Exception:
                    grafo_pesato[(i, j)].append(((ni, nj), float("inf"), float("inf")))
                    edge_data[((i, j), (ni, nj))] = {"Pv": None, "Vref": None}

    # usa il grafo pesato al posto di quello con pesi (uo, vo)
    grafo = grafo_pesato
    # print("edge data:", edge_data)
    # print("Grafo costruito con NAMOA*: ", grafo)


    # ---- Trova start e goal ----
    # def world_to_cell(x, y, sw_x, sw_y, grid_spacing):
    #     i = round((y - sw_y) / grid_spacing)
    #     j = round((x - sw_x) / grid_spacing)
    #     return i, j

    # if cell_to_xy:  # caso Copernicus

    #     def is_valid_cell(c):
    #         # cella navigabile = ha almeno un arco valido
    #         return (
    #             c in grafo and
    #             any(
    #                 (edge[1] < float("inf"))
    #                 for edge in grafo[c]
    #             )
    #         )

    #     valid_cells = [c for c in cell_to_xy.keys() if is_valid_cell(c)]

    #     if not valid_cells:
    #         raise RuntimeError("Nessuna cella navigabile nel grafo")

    #     start_cell = min(
    #         valid_cells,
    #         key=lambda c: math.hypot(
    #             cell_to_xy[c][0] - x1,
    #             cell_to_xy[c][1] - y1
    #         )
    #     )

    #     goal_cell = min(
    #         valid_cells,
    #         key=lambda c: math.hypot(
    #             cell_to_xy[c][0] - x2,
    #             cell_to_xy[c][1] - y2
    #         )
    #     )

    # else:
    #     # fallback: griglia artificiale
    #     start_i, start_j = world_to_cell(x1, y1, sw_x, sw_y, grid_spacing)
    #     goal_i, goal_j   = world_to_cell(x2, y2, sw_x, sw_y, grid_spacing)
    #     start_cell = find_nearest_valid((start_i, start_j), grafo)
    #     goal_cell  = find_nearest_valid((goal_i, goal_j), grafo)

    return grafo, cell_to_xy, currents, edge_data

import math
from constants import latlon_to_xy

def find_start_goal_cells(
    *,
    grafo,
    cell_to_xy,
    bbox,
    grid_spacing,
    start_lat,
    start_lon,
    goal_lat,
    goal_lon
):
    """
    Determina start_cell e goal_cell sul grafo NAMOA già costruito.
    NON modifica il grafo.
    """

    x1, y1 = latlon_to_xy(start_lat, start_lon)
    x2, y2 = latlon_to_xy(goal_lat, goal_lon)

    # ---- caso Copernicus (cell_to_xy popolato) ----
    if cell_to_xy:

        def is_valid_cell(c):
            return (
                c in grafo and
                any(edge[1] < float("inf") for edge in grafo[c])
            )

        valid_cells = [c for c in cell_to_xy.keys() if is_valid_cell(c)]

        if not valid_cells:
            raise RuntimeError("Nessuna cella navigabile nel grafo")

        start_cell = min(
            valid_cells,
            key=lambda c: math.hypot(
                cell_to_xy[c][0] - x1,
                cell_to_xy[c][1] - y1
            )
        )

        goal_cell = min(
            valid_cells,
            key=lambda c: math.hypot(
                cell_to_xy[c][0] - x2,
                cell_to_xy[c][1] - y2
            )
        )

        return start_cell, goal_cell

    # ---- fallback griglia artificiale ----
    sw_x, sw_y = latlon_to_xy(
        bbox["minimum_latitude"],
        bbox["minimum_longitude"]
    )

    def world_to_cell(x, y):
        i = round((y - sw_y) / grid_spacing)
        j = round((x - sw_x) / grid_spacing)
        return i, j

    start_cell = find_nearest_valid(
        world_to_cell(x1, y1), grafo
    )
    goal_cell = find_nearest_valid(
        world_to_cell(x2, y2), grafo
    )

    return start_cell, goal_cell

def calcola_comfort(Ve, Pv, wave_point, vessel_length):
    """
    Calcola un costo di comfort (penalità) associato alla navigazione su un arco,
    da usare come secondo obiettivo nel routing multi-criterio (NAMOA*).

    Il modello NON rappresenta una grandezza fisica assoluta, ma un indicatore
    adimensionale di “disagio” relativo, pensato per confrontare percorsi diversi.

    Il costo combina tre effetti principali:
    1) Altezza d’onda significativa (Hs): scala globalmente la penalità.
    2) Risonanza nave-onda: massima quando la lunghezza d’onda è confrontabile
    con la lunghezza caratteristica della nave (lambda ≈ L_ship).
    3) Periodo d’onda incontrato (Te): dipende dalla direzione dell’onda rispetto
    alla prua (Pv) e dalla velocità effettiva della nave (Ve).

    Assunzioni e limiti:
    - Modello semi-empirico e calibrabile (k1, k2, L_ship sono parametri fissi).
    - Valori mancanti o non fisici (Hs < 0, Tp ≤ 0) producono costo nullo.
    - Il risultato è una penalità: valori più alti indicano condizioni peggiori.
    """

    #print("Calcolo comfort con Ve:", Ve, "Pv:", Pv)

    # --- estrazione variabili onda ---
    Hs   = float(wave_point["VHM0"].values)
    Tp   = float(wave_point["VTPK"].values)
    Mdir = math.radians(float(wave_point["VMDR"].values))  # porto in radianti

    # se manca il dato → comfort nullo
    if Tp <= 0 or Hs < 0:
        return 0.0

    # --- lunghezza onda ---
    g = 9.81
    L_ship = vessel_length  # lunghezza della nave 
    lambda_wave = g * (Tp**2) / (2 * math.pi)

    # --- risonanza (r ≈ 1) ---
    r = lambda_wave / L_ship
    k1 = 1.0        # puoi calibrare
    C_reso = k1 * math.exp(-(r - 1.0)**2)

    # --- periodo incontrato ---
    mu = Mdir - Pv
    c_phase = lambda_wave / Tp
    c_parallel = c_phase * math.cos(mu)
    Te = lambda_wave / (abs(c_parallel - Ve) + 1e-6)

    k2 = 0.5        # più basso di k1
    C_enc = k2 * (1.0 / Te)

    # --- effetto altezza onda ---
    C =10* Hs * (C_reso + C_enc)
    if math.isnan(C):
        C = 1.0

    return float(C)


def find_nearest_valid(cell, grafo):
    """
    Trova la cella valida più vicina a 'cell' (start o goal) che esiste nel grafo.
    Usa distanza euclidea sulle coordinate (i,j).
    """
    import math
    if cell in grafo:
        return cell

    ci, cj = cell
    nearest = None
    best_dist = float("inf")

    for (i, j) in grafo.keys():
        d = math.hypot(i - ci, j - cj)
        if d < best_dist:
            best_dist = d
            nearest = (i, j)

    return nearest


def path_to_waypoints_from_graph_NAMOA(path_cells, cell_to_xy, edge_data, alpha, beta):
    """
    Converte i percorsi trovati da NAMOA* (in termini di celle di griglia)
    in una lista di Waypoint geometrici arricchiti con informazioni cinematiche.

    Per ogni percorso non dominato:
    - ogni nodo della path diventa un Waypoint con coordinate metriche (x, y);
    - per ogni arco (prev_node → node) vengono recuperati, tramite edge_data,
    i parametri associati alla velocità selezionata dall’algoritmo:
        - angolo di prua (Pa, in radianti),
        - vettore velocità propria di riferimento (Vr),
        - etichetta di velocità (vel_label),
        - valore scalare della velocità propria (vp).

    Note importanti:
    - La selezione dei dati d’arco avviene tramite il campo `types`, che contiene
    il label dell’arco scelto da NAMOA* (es. "vel=3.50").
    - `edge_data` può contenere più configurazioni per lo stesso arco fisico
    (una per ogni velocità testata).
    - La funzione non calcola tempi né costi: si limita a ricostruire la soluzione
    scelta dal routing in forma di waypoints navigabili.
    """
   
    waypoints = []
    for cost, path, types in path_cells:
        for k, node in enumerate(path):
            wp = Waypoint(*cell_to_xy[node])

            if k > 0:
                prev_node = path[k-1]
                tipo_arco = types[k-1]  
                edge_key = (prev_node, node)

                if edge_key in edge_data:
                    e_data = edge_data[edge_key]

                    match = next((d for d in e_data if f"vel={d['Vp_test']:.2f}" == tipo_arco), None)
                    if match:
                        wp.Pa = match["Pv"]        # direzione effettiva (radians)
                        wp.Vr = match["Vref"]      # vettore velocità (vx, vy)
                        wp.vel_label = match["vel_label"]
                        wp.vp = match["Vp_test"]
                    

                    # if tipo_arco == "tempo":
                    #     wp.Pa = e.get("Pv")
                    #     wp.Vr = e.get("Vref")
                    # elif tipo_arco == "consumo":
                    #     wp.Pa = e.get("Pv_costo")
                    #     wp.Vr = e.get("Vref_min_costo")

            waypoints.append(wp)
    return waypoints

