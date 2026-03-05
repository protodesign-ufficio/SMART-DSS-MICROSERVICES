import math
from datetime import datetime
import numpy as np
import re
import time as pytime
import json
import requests
import matplotlib.pyplot as plt

from NAMOA import build_time_min_graph, dijkstra_single_cost, dijkstra_time_from_start, filter_graph_by_reachable, filter_graph_by_reachable, namoa_instrumented, namoa_instrumented_visual, reverse_graph
from constants import (
    latlon_to_xy, xy_to_latlon
)
from math import hypot, log
from graphs_cell import floor_time, get_cached_namoa_graph, save_namoa_graph


from Api_Copernicus import debug_plot_currents, generate_fake_copernicus_dataset_km
from graphs_cell import get_cached_namoa_graph
from routing import (
    build_double_weighted_graph_NAMOA,
    find_start_goal_cells,
    path_to_waypoints_from_graph_NAMOA
)
import xarray as xr
import os


# DATASET_ID = "cmems_mod_med_phy-cur_anfc_4.2km_PT15M-i"
VARIABLES = ["uo", "vo"]
OUT_DIR = "./copernicus-data"
WEATHER_SERVICE_URL = os.getenv("WEATHER_SERVICE_URL", "http://weather:8076")
os.environ["HDF5_USE_FILE_LOCKING"] = "FALSE"
os.environ["HDF5_DISABLE_VERSION_CHECK"] = "2"


# ── Scenario what-if su xarray Dataset ────────────────────────────

def _apply_scenario_to_dataset(ds, dataset_type, scenario):
    """
    Applica un modificatore di scenario what-if a un xarray Dataset in-place.

    dataset_type: 'currents' oppure 'waves'
    scenario: dict con chiavi opzionali multiplier, function, function_params, variables
    """
    if scenario is None:
        return ds

    multiplier = scenario.get("multiplier")
    func_name = scenario.get("function")
    func_params = scenario.get("function_params") or {}
    target_vars = scenario.get("variables")

    if dataset_type == "currents":
        all_vars = ["uo", "vo"]
    else:
        all_vars = ["VHM0_WW", "VTM01_WW"]  # VMDR_WW (direzione) non viene scalato di default

    vars_to_modify = [v for v in all_vars if v in ds.data_vars]
    if target_vars:
        # Mappa nomi scenario → nomi dataset
        name_map = {"u": "uo", "v": "vo", "height": "VHM0_WW", "period": "VTM01_WW", "dir": "VMDR_WW"}
        mapped = [name_map.get(v, v) for v in target_vars]
        vars_to_modify = [v for v in mapped if v in ds.data_vars]

    if not vars_to_modify:
        return ds

    # Calcola fattore spaziale
    spatial_factor = None
    if func_name and "latitude" in ds.coords and "longitude" in ds.coords:
        lats = ds.coords["latitude"].values
        lons = ds.coords["longitude"].values
        lon_grid, lat_grid = np.meshgrid(lons, lats)

        if func_name == "sinusoidal":
            amplitude = func_params.get("amplitude", 0.5)
            frequency = func_params.get("frequency", 1)
            axis = func_params.get("axis", "lon")
            phase = func_params.get("phase", 0.0)
            arr = lon_grid if axis == "lon" else lat_grid
            t = (arr - arr.min()) / max(arr.max() - arr.min(), 1e-9)
            spatial_factor = 1.0 + amplitude * np.sin(2 * np.pi * frequency * t + phase)

        elif func_name == "linear_ramp":
            start_f = func_params.get("start_factor", 0.5)
            end_f = func_params.get("end_factor", 2.0)
            axis = func_params.get("axis", "lon")
            arr = lon_grid if axis == "lon" else lat_grid
            t = (arr - arr.min()) / max(arr.max() - arr.min(), 1e-9)
            spatial_factor = start_f + (end_f - start_f) * t

        elif func_name == "gaussian_peak":
            cx = func_params.get("center_lat", (lats.min() + lats.max()) / 2)
            cy = func_params.get("center_lon", (lons.min() + lons.max()) / 2)
            radius = func_params.get("radius_deg", 0.1)
            peak = func_params.get("peak_factor", 3.0)
            dist2 = (lat_grid - cx) ** 2 + (lon_grid - cy) ** 2
            spatial_factor = 1.0 + (peak - 1.0) * np.exp(-dist2 / (2 * radius ** 2))

    # Combina multiplier e spatial_factor
    if multiplier is not None and spatial_factor is not None:
        total_factor = multiplier * spatial_factor
    elif multiplier is not None:
        total_factor = multiplier
    elif spatial_factor is not None:
        total_factor = spatial_factor
    else:
        return ds

    ds = ds.copy(deep=True)
    for var in vars_to_modify:
        ds[var] = ds[var] * total_factor

    print(f"[SCENARIO] Applicato scenario a dataset ({dataset_type}): vars={vars_to_modify}, "
          f"multiplier={multiplier}, function={func_name}")
    return ds

def _ts_for_filename(s: str) -> str:
    # prova a fare parse ISO; altrimenti fallback a semplice sanificazione
    try:
        # supporta anche la Z finale
        s2 = s.replace("Z", "+00:00") if "Z" in s else s
        dt = datetime.fromisoformat(s2)
        return dt.strftime("%Y%m%dT%H%M%S")
    except Exception:
        # rimpiazza qualunque char non alfanum con '-'
        return re.sub(r"[^0-9A-Za-z]+", "-", s)

def load_dataset_for_date(date_str, bbox, dataset_id):
    print(f"Loading dataset for {date_str} and bbox {bbox}...")
    os.makedirs(OUT_DIR, exist_ok=True)

    safe = _ts_for_filename(date_str)
    out_file = f"start_{safe}_end_{safe}_{dataset_id}.nc"   # << niente caratteri illegali
    out_path = os.path.join(OUT_DIR, out_file)
    print("!!! !!! !!! !!! !!! Dataset path:", out_path)

    if "wav" in dataset_id:
        requested_variables = ["VMDR_WW", "VTM01_WW", "VHM0_WW"]
    else:
        requested_variables = VARIABLES

    if not os.path.exists(out_path):
        payload = {
            "dataset_id": dataset_id,
            "variables": requested_variables,
            "bbox": bbox,
            "start": date_str,
            "end": date_str,
            "out_file": out_file,
        }
        try:
            response = requests.post(
                f"{WEATHER_SERVICE_URL.rstrip('/')}/internal/weather/subset/download",
                json=payload,
                timeout=120,
            )
        except requests.RequestException as exc:
            raise RuntimeError(f"Weather service unavailable: {exc}") from exc

        if response.status_code >= 400:
            detail = response.text
            try:
                body = response.json()
                if isinstance(body, dict):
                    detail = body.get("detail", detail)
            except Exception:
                pass
            raise RuntimeError(f"Weather service error: {detail}")

        if not os.path.exists(out_path):
            raise RuntimeError(f"Weather service did not produce expected file: {out_path}")
    
    ds = xr.open_dataset(out_path, engine="h5netcdf")
    print("Dataset loaded:", ds)


    return ds
def normalize_time(dt: datetime) -> datetime:
    return dt.replace(minute=0, second=0, microsecond=0)


def _count_navigable_cells(grafo: dict) -> int:
    navigable = 0
    for edges in grafo.values():
        if any(len(edge) >= 2 and edge[1] < float("inf") for edge in edges):
            navigable += 1
    return navigable


def optimize_route(
    vessel_id,
    vessel_name,
    vessel_length,
    start_lat, start_lon,
    goal_lat, goal_lon,
    bbox,
    date_str=None,
    alpha=0.5,
    beta=None,
    vp_max=10.0,
    vel_vec=None,
    t_max=3600,
    optimization_id=None,
    ve_min=0.1,
    grid_spacing=2000,
    custom_current=None,
    eps_time=0.0, eps_cost=0.0, empty=False, fake_data=False, tollerance_minutes=60,
    vessel_signature="default_vessel",
    scenario=None,
):
    """
    Esegue l'ottimizzazione del percorso tra start e goal usando Copernicus + routing.
    Restituisce un dict JSON-friendly.
    """
    
    print(f"Optimizing route for vessel {vessel_id} ({vessel_name})...")
    if beta is None:
        beta = 1.0 - alpha

    # Default: oggi UTC arrotondato all'ora
    if not date_str:
        now = datetime.utcnow().replace(minute=0, second=0, microsecond=0)
        date_str = now.strftime("%Y-%m-%d")

    # # 1) Dataset Copernicus
    # #ds = load_dataset_for_date(date_str, bbox)
    # dataset_wave = "cmems_mod_med_wav_anfc_4.2km_PT1H-i"
    # ds_wav= load_dataset_for_date(date_str, bbox, dataset_wave)
    # print("Wave dataset SCARICATO:")
    # #debug_dataset(ds_wav)

    # print("Current dataset:")
    # dataset_current = "cmems_mod_med_phy-cur_anfc_4.2km_PT15M-i"  # "cmems_mod_glo_phy_anfc_0.083deg_PT1H-m" #"cmems_mod_med_phy-cur_anfc_4.2km_PT15M-i"
    
    # #ds = load_dataset_for_date(date_str, bbox, dataset_current)
    # print("Current dataset SCARICATO:")
    # # Commenta se vuoi usare dataset REALE
    # if fake_data:
    #     ds = generate_fake_copernicus_dataset_km(bbox, resolution_km=2)
    # # debug_plot_currents(ds)
    # else:
    #     ds = load_dataset_for_date(date_str, bbox, dataset_current)

    # # 2) debug
    # debug_dataset(ds)
    # #print(ds)
    # # debug_dataset(ds_wav)
    # # print(ds_wave)

    # time = ds["time"].values[0]

    # print("Building base graph from dataset...")
    # grafo, nodes = build_graph_from_grib(ds, time)
    # #plot_graph(ds, grafo, nodes, time)

    # # 2) Conversione in coordinate "world"
    # origin_xy = latlon_to_xy(start_lat, start_lon)
    # goal_xy = latlon_to_xy(goal_lat, goal_lon)
    

    # # 3) Costruzione grafo pesato (tempo + comfort)
    # print("Building graph...")
    
    # grafo, cell_to_xy, start_cell, goal_cell, currents, edge_data = \
    #     build_double_weighted_graph_NAMOA(
    #         dataset=ds,
    #         dataset_wave=ds_wav,
    #         time=time,
    #         origin_xy=origin_xy,
    #         goal_xy=goal_xy,
    #         bbox=bbox,
    #         grid_spacing=grid_spacing,
    #         Vp_max=vp_max,
    #         vel_vec=vel_vec,
    #         Ve_min=ve_min,
    #         custom_current=custom_current,
    #         grafo=grafo,
    #         nodes=nodes,
    #         empty=empty,
    #         vessel_length=vessel_length
    #     )
    
    #print("Graph built.", grafo)
    
    dataset_current = "cmems_mod_med_phy-cur_anfc_4.2km_PT15M-i"
    dataset_wave = "cmems_mod_med_wav_anfc_4.2km_PT1H-i"
    # Se c’è uno scenario, aggiungiamo un hash dei parametri al dataset_hash
    # per separare i grafi cached con e senza scenario
    if scenario:
        scenario_hash = json.dumps(scenario, sort_keys=True)
        import hashlib
        scenario_suffix = "_sc_" + hashlib.sha256(scenario_hash.encode()).hexdigest()[:12]
    else:
        scenario_suffix = ""
    dataset_hash = f"{dataset_current}_{dataset_wave}{scenario_suffix}"

    graph_time = datetime.fromisoformat(date_str)   # date_str che passi è "%Y-%m-%d %H:%M:%S"
    T = int(tollerance_minutes) * 60
    bucket_time = floor_time(graph_time, T)

    def _build_and_cache_graph(ignore_land_mask: bool):
        if ignore_land_mask:
            print("[OPTIMIZE] Rebuild con fallback: ignore_land_mask=True")

        if fake_data:
            ds = generate_fake_copernicus_dataset_km(bbox, resolution_km=2)
        else:
            ds = load_dataset_for_date(
                graph_time.strftime("%Y-%m-%d %H:%M:%S"),
                bbox,
                dataset_current
            )

        print("[DEBUG] Loading wave dataset...")
        try:
            ds_wav = load_dataset_for_date(
                graph_time.strftime("%Y-%m-%d %H:%M:%S"),
                bbox,
                dataset_wave
            )
            print("[DEBUG] Wave dataset loaded successfully")
        except Exception as wave_exc:
            print(f"[DEBUG][ERROR] Wave dataset failed: {wave_exc}")
            ds_wav = None  # se le onde falliscono, continuo con empty=True

        debug_dataset(ds)

        # Applica scenario what-if ai dataset (se presente)
        if scenario:
            ds = _apply_scenario_to_dataset(ds, "currents", scenario)
            if ds_wav is not None:
                ds_wav = _apply_scenario_to_dataset(ds_wav, "waves", scenario)

        print(f"[DEBUG] Building base graph with ignore_land_mask={ignore_land_mask}")
        grafo_base, nodes = build_graph_from_grib(
            ds,
            graph_time,
            ignore_land_mask=ignore_land_mask,
        )
        print(f"[DEBUG] Base graph built: {len(grafo_base)} cells")

        # se le onde non sono disponibili, disabilito calcolo comfort
        use_empty = empty or (ds_wav is None)
        if ds_wav is None:
            print("[DEBUG] Wave dataset non disponibile, uso empty=True per calcolo comfort")

        print(f"[DEBUG] Building weighted NAMOA graph (empty={use_empty})...")
        grafo, cell_to_xy, currents, edge_data = build_double_weighted_graph_NAMOA(
            grafo=grafo_base,
            nodes=nodes,
            dataset=ds,
            dataset_wave=ds_wav,
            time=graph_time,
            bbox=bbox,
            grid_spacing=grid_spacing,
            Vp_max=vp_max,
            vel_vec=vel_vec,
            Ve_min=ve_min,
            custom_current=custom_current,
            empty=use_empty,
            vessel_length=vessel_length
        )

        navigable_cells = _count_navigable_cells(grafo)
        print(f"[OPTIMIZE] Navigable cells: {navigable_cells}")
        if navigable_cells == 0:
            return None

        return save_namoa_graph(
            grafo=grafo,
            cell_to_xy=cell_to_xy,
            currents=currents,
            edge_data=edge_data,
            time=bucket_time,
            bbox=bbox,
            dataset_hash=dataset_hash,
            vessel_signature=vessel_signature,
            fake_data=fake_data,
            tollerance_seconds=T
        )


    g = get_cached_namoa_graph(
        time=bucket_time,
        bbox=bbox,
        dataset_hash=dataset_hash,
        vessel_signature=vessel_signature,
        fake_data=fake_data,
        tollerance_seconds=T
    )

    if g is None:
        print("[OPTIMIZE] Graph not in cache → generating on demand...")

        g = _build_and_cache_graph(ignore_land_mask=False)
        if g is None:
            print("[OPTIMIZE][WARN] Grafo non navigabile al primo tentativo, retry con fallback.")
            g = _build_and_cache_graph(ignore_land_mask=True)
            if g is None:
                raise RuntimeError("Impossibile generare un grafo navigabile anche con fallback")

        print("[OPTIMIZE] Graph generated and cached.")
    else:
        cached_navigable = _count_navigable_cells(g.grafo)
        if cached_navigable == 0:
            print("[OPTIMIZE][WARN] Cached graph non navigabile, rigenerazione in corso...")
            g = _build_and_cache_graph(ignore_land_mask=True)
            if g is None:
                raise RuntimeError("Cached graph non navigabile e rebuild fallita")
    
    try:
        start_cell, goal_cell = find_start_goal_cells(
            grafo=g.grafo,
            cell_to_xy=g.cell_to_xy,
            bbox=bbox,
            grid_spacing=grid_spacing,
            start_lat=start_lat,
            start_lon=start_lon,
            goal_lat=goal_lat,
            goal_lon=goal_lon
        )
    except RuntimeError as exc:
        if "Nessuna cella navigabile nel grafo" not in str(exc):
            raise
        print("[OPTIMIZE][WARN] Nessuna cella navigabile da find_start_goal_cells, retry fallback...")
        g_retry = _build_and_cache_graph(ignore_land_mask=True)
        if g_retry is None:
            raise
        g = g_retry
        start_cell, goal_cell = find_start_goal_cells(
            grafo=g.grafo,
            cell_to_xy=g.cell_to_xy,
            bbox=bbox,
            grid_spacing=grid_spacing,
            start_lat=start_lat,
            start_lon=start_lon,
            goal_lat=goal_lat,
            goal_lon=goal_lon
        )

    grafo = g.grafo
    cell_to_xy = g.cell_to_xy
    edge_data = g.edge_data

    start_cell = (start_cell[0], start_cell[1])
    start = xy_to_latlon(start_cell[0], start_cell[1])
    goal_cell  = (goal_cell[0], goal_cell[1] )
    goal = xy_to_latlon(goal_cell[0], goal_cell[1])
    print("! ! Start: ", start, "StartCell", start_cell, "goal", goal, "GoalCell", goal_cell)


    print("NOMOA* search...")
    start_t = pytime.time()
    
    print("Starting NAMOA* with eps_time =", eps_time, " eps_cost =", eps_cost)
    path_cells, log = namoa_instrumented(grafo, start_cell, goal_cell, heuristic=lambda n: (0.0, 0.0), t_max=t_max, eps_time=eps_time, eps_cost=eps_cost)
    # path_cells, log = namoa_eps_paper(grafo, start_cell, goal_cell, heuristic=lambda n: (0.0, 0.0), t_max=t_max, eps_time=eps_time, eps_cost=eps_cost)
    end = pytime.time()
    print(f"Tempo impiegato - NAMOA*: {end - start_t:.3f} secondi")

    ## PLOT FRONTE DI PARETO ##

    # tempi = [float(cost[0]) for cost, _, _ in path_cells]
    # comfort = [float(cost[1]) for cost, _, _ in path_cells]

    # # Plot fronte di Pareto
    # plt.figure(figsize=(8, 6))
    # plt.scatter(tempi, comfort, c='blue', label="Soluzioni Pareto")
    # plt.xlabel("Tempo [unità costo 1]")
    # plt.ylabel("comfort [unità costo 2]")
    # plt.title("Fronte di Pareto - NAMOA*")
    # plt.grid(True)
    # plt.legend()
    # plt.show()

    # plot_graph(ds, grafo_pesato, nodes, time, start_cell=start_cell, goal_cell=goal_cell)

    if not path_cells:
        return {
            "vessel_id": vessel_id,
            "vessel_name": vessel_name,
            "date": date_str,
            "route": [],
            "summary": {"path_found": False},
        }


    routes = []
    k=0
    for cost, path, types in path_cells:
        k+=1
        # Costruisci i waypoint da NAMOA
        waypoints = path_to_waypoints_from_graph_NAMOA(
            [(cost, path, types)],
            cell_to_xy,
            edge_data,
            alpha,
            beta
        )

        # Converte Waypoint → dizionario compatibile JSON
        route = []
        for i, wp in enumerate(waypoints):
            lat, lon = xy_to_latlon(wp.x, wp.y)
            heading_deg = math.degrees(wp.Pa) if getattr(wp, "Pa", None) is not None else None
            if getattr(wp, "Vr", None) is not None:
                vx, vy = wp.Vr
                speed_ref = math.sqrt(vx**2 + vy**2)
                vr = {"vx": float(vx), "vy": float(vy), "speed": float(speed_ref)}
            else:
                vr = None

            route.append({
                # "x": float(wp.x),
                # "y": float(wp.y),
                "lat": float(lat),
                "lon": float(lon),
                "heading_deg": heading_deg,
                "vref": vr,
                "name": f"wp_{i}",
            })

        routes.append({
            "cost_time": float(cost[0]),
            # "cost_energy": float(cost[1]),
            "cost_energy": None if empty else float(cost[1]),
            "n_waypoints": len(route),
            "name": f"{vessel_name} (opt_id: {optimization_id}, rotta id: {k})",
            "waypoints": route
        })

    # 🔹 Ora costruiamo la risposta finale
    return {
        "vessel_id": vessel_id,
        "vessel_name": vessel_name,
        "date": date_str,
        "summary": {
            "path_found": len(routes) > 0,
            "pareto_count": len(routes),
            "start_cell": list(start_cell),
            "goal_cell": list(goal_cell),
        },
        "routes": routes,
        "optimization_id": optimization_id,
    }



def build_graph_from_grib(ds, time, ignore_land_mask: bool = False):
    ''' 
    Costruzione degli archi (edges) del grafo:
    Per ogni nodo (i, j) consideriamo tutti i vicini ortogonali e diagonali (8 direzioni):
      - Destra (E):     (i, j+1)   se j+1 < n_lon
      - Sinistra (W):   (i, j-1)   se j-1 >= 0
      - Sopra (N):      (i+1, j)   se i+1 < n_lat
      - Sotto (S):      (i-1, j)   se i-1 >= 0
      - NE:             (i-1, j+1)
      - SE:             (i+1, j+1)
      - NW:             (i-1, j-1)
      - SW:             (i+1, j-1)
    
    Calcolo del peso (corrente u,v):
      - Vicini ortogonali (N, S, E, W): uso la media delle correnti tra il nodo attuale e il vicino
        (due punti adiacenti sul lato comune).
      - Vicini diagonali (NE, NW, SE, SW): uso direttamente il valore del punto diagonale
        (eventualmente sostituibile con la media dei 4 corner per maggiore coerenza).
    
    In tutti i casi:
      - Se i valori di corrente risultano NaN → assegno peso (0.0, 0.0)
      - Altrimenti peso = (u, v) o la media come sopra

    Costruisce il grafo direttamente dal dataset:
    - nodi = centri cella
    - archi = media delle correnti sui due grib adiacenti al lato comune 
    '''

    import numpy as np

    lats = ds["latitude"].values
    lons = ds["longitude"].values
    # sel = ds.sel(time=time)
    sel = ds.sel(time=time, method="nearest")


    grafo = {}
    nodes = {}

    n_lat = len(lats) - 1   # centri cella
    n_lon = len(lons) - 1

    for i in range(n_lat):
        for j in range(n_lon):
            # nodo al centro della cella
            lat_c = (lats[i] + lats[i+1]) / 2
            lon_c = (lons[j] + lons[j+1]) / 2
            nodes[(i,j)] = (lat_c, lon_c)

            edges = []

            # 👉 se il nodo è terra: tutti archi a peso infinito
            if (not ignore_land_mask) and (not is_point_water(lat_c, lon_c)):
                grafo[(i, j)] = [((i, j), float("inf"))]  # self-loop "bloccato"
                continue

            # HO ASSUNTO CHE SE ENTRAMBE LE CORRENTI NAN ALLORA PESO 0! - Vedere come gestire
            # vicino a destra
            if j+1 < n_lon:
                u0 = sel["uo"].sel(latitude=lats[i], longitude=lons[j]).item()
                v0 = sel["vo"].sel(latitude=lats[i], longitude=lons[j]).item()
                u1 = sel["uo"].sel(latitude=lats[i+1], longitude=lons[j]).item()
                v1 = sel["vo"].sel(latitude=lats[i+1], longitude=lons[j]).item()
                if any(np.isnan([u0, v0, u1, v1])):
                    peso = (0.0, 0.0)
                else:
                    peso = ((u0+u1)/2.0, (v0+v1)/2.0)
                edges.append(((i, j+1), peso))

            # vicino sopra
            if i+1 < n_lat:
                u0 = sel["uo"].sel(latitude=lats[i], longitude=lons[j]).item()
                v0 = sel["vo"].sel(latitude=lats[i], longitude=lons[j]).item()
                u1 = sel["uo"].sel(latitude=lats[i], longitude=lons[j+1]).item()
                v1 = sel["vo"].sel(latitude=lats[i], longitude=lons[j+1]).item()
                if any(np.isnan([u0, v0, u1, v1])):
                    peso = (0.0, 0.0)
                else:
                    peso = ((u0+u1)/2.0, (v0+v1)/2.0)
                edges.append(((i+1, j), peso))

            # --- NUOVO: vicino a sinistra
            if j-1 >= 0:
                u0 = sel["uo"].sel(latitude=lats[i], longitude=lons[j]).item()
                v0 = sel["vo"].sel(latitude=lats[i], longitude=lons[j]).item()
                u1 = sel["uo"].sel(latitude=lats[i+1], longitude=lons[j]).item()
                v1 = sel["vo"].sel(latitude=lats[i+1], longitude=lons[j]).item()
                if any(np.isnan([u0, v0, u1, v1])):
                    peso = (0.0, 0.0)
                else:
                    peso = ((u0+u1)/2.0, (v0+v1)/2.0)
                edges.append(((i, j-1), peso))

            # --- NUOVO: vicino sotto
            if i-1 >= 0:
                u0 = sel["uo"].sel(latitude=lats[i], longitude=lons[j]).item()
                v0 = sel["vo"].sel(latitude=lats[i], longitude=lons[j]).item()
                u1 = sel["uo"].sel(latitude=lats[i], longitude=lons[j+1]).item()
                v1 = sel["vo"].sel(latitude=lats[i], longitude=lons[j+1]).item()
                if any(np.isnan([u0, v0, u1, v1])):
                    peso = (0.0, 0.0)
                else:
                    peso = ((u0+u1)/2.0, (v0+v1)/2.0)
                edges.append(((i-1, j), peso))

            # diagonali (come le avevi già, ma controlla bene l’indice j-1 nella SW)
            if i+1 < n_lat and j+1 < n_lon:   # SE
                u = sel["uo"].sel(latitude=lats[i+1], longitude=lons[j+1]).item()
                v = sel["vo"].sel(latitude=lats[i+1], longitude=lons[j+1]).item()
                peso = (0.0, 0.0) if np.isnan(u) or np.isnan(v) else (u, v)
                edges.append(((i+1, j+1), peso))

            if i-1 >= 0 and j+1 < n_lon:      # NE
                u = sel["uo"].sel(latitude=lats[i-1], longitude=lons[j+1]).item()
                v = sel["vo"].sel(latitude=lats[i-1], longitude=lons[j+1]).item()
                peso = (0.0, 0.0) if np.isnan(u) or np.isnan(v) else (u, v)
                edges.append(((i-1, j+1), peso))

            if i+1 < n_lat and j-1 >= 0:      # SW
                u = sel["uo"].sel(latitude=lats[i+1], longitude=lons[j-1]).item()
                v = sel["vo"].sel(latitude=lats[i+1], longitude=lons[j-1]).item()
                peso = (0.0, 0.0) if np.isnan(u) or np.isnan(v) else (u, v)
                edges.append(((i+1, j-1), peso))

            if i-1 >= 0 and j-1 >= 0:         # NW
                u = sel["uo"].sel(latitude=lats[i-1], longitude=lons[j-1]).item()
                v = sel["vo"].sel(latitude=lats[i-1], longitude=lons[j-1]).item()
                peso = (0.0, 0.0) if np.isnan(u) or np.isnan(v) else (u, v)
                edges.append(((i-1, j-1), peso))



            grafo[(i,j)] = edges

    return grafo, nodes

import requests

POINT_CACHE_FILE = "./point_water_cache.json"
# cache globale: { (lat_rounded, lon_rounded): True/False }
_water_cache = {}
def is_point_water(lat: float, lon: float, precision: int = 3) -> bool:
    """
    Verifica se un punto è acqua con caching locale + salvataggio su file.
    precision: numero di decimali per la chiave cache (~100m se 3).
    """
    global _water_cache
    # print(f"[DEBUG] Chiamata is_point_water per ({lat}, {lon})")


    # Arrotondo per chiave
    lat_r = round(lat, precision)
    lon_r = round(lon, precision)
    key = f"{lat_r},{lon_r}"

    # 1️⃣ Se esiste cache in RAM → ritorna subito
    if key in _water_cache:
        return _water_cache[key]

    # 2️⃣ Se esiste cache su file → caricala (solo la prima volta)
    if not _water_cache and os.path.exists(POINT_CACHE_FILE):
        with open(POINT_CACHE_FILE, "r") as f:
            try:
                _water_cache.update(json.load(f))
            except json.JSONDecodeError:
                pass  # file corrotto, ignora

    # 3️⃣ Se trovato dopo aver caricato il file
    if key in _water_cache:
        return _water_cache[key]

    # 4️⃣ Altrimenti → chiama API remota
    import requests
    try:
        url = f"https://is-on-water.balbona.me/api/v1/get/{lat_r}/{lon_r}"
        resp = requests.get(url, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            is_water = bool(data.get("isWater", True))
        else:
            print(f"[⚠️] is-on-water status {resp.status_code} per ({lat_r}, {lon_r}) -> fallback acqua")
            is_water = True
    except Exception as e:
        print(f"[⚠️] Errore API is-on-water per ({lat_r}, {lon_r}): {e} -> fallback acqua")
        is_water = True

    # 5️⃣ Aggiorna cache in RAM e salva su file
    _water_cache[key] = is_water
    with open(POINT_CACHE_FILE, "w") as f:
        json.dump(_water_cache, f)

    return is_water



def plot_graph(ds, grafo, nodes, time, start_cell=None, goal_cell=None, path_cells=None):
    """
    Visualizza:
      - punti grib (rossi) con valori (uo, vo)
      - nodi (neri) al centro cella
      - archi (blu) con pesi (uo, vo) già nel grafo (quello 'raw' da build_graph_from_grib)
      - griglia tratteggiata allineata ai nodi
      - start/goal evidenziati
      - (opzionale) path evidenziato
    """
    import matplotlib.pyplot as plt
    import numpy as np

    sel = ds.sel(time=time)

    # coordinate grib
    lats = sel["latitude"].values
    lons = sel["longitude"].values
    Lon_grib, Lat_grib = np.meshgrid(lons, lats)

    # valori correnti sui punti grib
    u = sel["uo"].values
    v = sel["vo"].values

    fig, ax = plt.subplots(figsize=(10, 7))

    # --- Punti grib (rossi) + valori ---
    # ax.scatter(Lon_grib, Lat_grib, color="red", s=20, label="Punti grib")
    # for i in range(len(lats)):
    #     for j in range(len(lons)):
    #         ax.annotate(f"({u[i,j]:.2f},{v[i,j]:.2f})",
    #                     (Lon_grib[i,j], Lat_grib[i,j]),
    #                     textcoords="offset points", xytext=(3,3),
    #                     fontsize=6, color="black")

    # --- Nodi (neri) ---
    for (ci, cj), (lat, lon) in nodes.items():
        ax.plot(lon, lat, "ko", markersize=4)

        # --- Archi (blu) con pesi dal grafo 'raw' ---
        # --- Archi (blu) ---
    for (i, j), edges in grafo.items():
        lat, lon = nodes[(i, j)]
        for edge in edges:
            if len(edge) == 2:
                (ni, nj), peso = edge
                label = f"{peso:.2f}"
            elif len(edge) == 3:
                (ni, nj), t_min, Vp_mod = edge
                label = f"t={t_min:.2f}, c={Vp_mod:.2f}"
            else:
                continue

            lat_b, lon_b = nodes[(ni, nj)]
            ax.plot([lon, lon_b], [lat, lat_b], color="blue", linewidth=0.5)
            mid_lon = (lon + lon_b) / 2
            mid_lat = (lat + lat_b) / 2
            ax.annotate(label,
                        (mid_lon, mid_lat),
                        textcoords="offset points", xytext=(0,0),
                        fontsize=6, color="blue", ha="center")

    # --- Evidenzia START e GOAL (se presenti) ---
    if start_cell in nodes:
        slat, slon = nodes[start_cell]
        ax.plot(slon, slat, marker="*", markersize=14, color="gold", label="Start")
        ax.annotate("START", (slon, slat), textcoords="offset points", xytext=(6,6),
                    fontsize=8, color="gold")

    if goal_cell in nodes:
        glat, glon = nodes[goal_cell]
        ax.plot(glon, glat, marker="X", markersize=10, color="green", label="Goal")
        ax.annotate("GOAL", (glon, glat), textcoords="offset points", xytext=(6,6),
                    fontsize=8, color="green")

    # # --- (Opzionale) Path trovato da Dijkstra ---
    # if path_cells and len(path_cells) >= 2:
    #     path_lons = [nodes[c][1] for c in path_cells]
    #     path_lats = [nodes[c][0] for c in path_cells]
    #     ax.plot(path_lons, path_lats, color="orange", linewidth=2.0, label="Percorso")

    ax.set_xlabel("Longitude")
    ax.set_ylabel("Latitude")
    ax.set_title(f"Grafo dal dataset Copernicus (time={str(time)})")
    ax.legend(loc="best")
    plt.tight_layout()
    plt.show()



import numpy as np

def debug_dataset(ds):
    """
    Debug dei dati di corrente (uo, vo) in un dataset xarray.
    """
    print("\n=== DEBUG DATASET ===")
    print(ds)

    uo = ds["uo"].values
    vo = ds["vo"].values

    # conteggio NaN
    nan_uo = np.isnan(uo).sum()
    nan_vo = np.isnan(vo).sum()
    total = uo.size

    print(f"\nTotale punti: {total}")
    print(f"uo: NaN={nan_uo} ({nan_uo/total:.2%})")
    print(f"vo: NaN={nan_vo} ({nan_vo/total:.2%})")

    # range valori validi
    valid_uo = uo[~np.isnan(uo)]
    valid_vo = vo[~np.isnan(vo)]
    if valid_uo.size > 0 and valid_vo.size > 0:
        print(f"\nRange uo: {valid_uo.min():.3f} .. {valid_uo.max():.3f}")
        print(f"Range vo: {valid_vo.min():.3f} .. {valid_vo.max():.3f}")
    else:
        print("⚠️ Nessun dato valido in uo/vo!")

    print("====================\n")

def normalize_solutions(solutions, cost_round=6):
    norm = set()
    for sol in solutions:
        cost = sol[0]
        path = sol[1]

        cost_n = (round(cost[0], cost_round), round(cost[1], cost_round))
        path_n = tuple(path)

        norm.add((cost_n, path_n))
    return norm

import time

def benchmark_namoa_with_isocrona(
    grafo,
    start_cell,
    goal_cell,
    t_max,
    heuristic=lambda n: (0.0, 0.0),
    cost_round=3
):
    """
    Esegue:
    1) NAMOA normale
    2) Preprocessing (isocrona) + NAMOA

    Ritorna un dict con:
    - soluzioni
    - tempi dettagliati
    """

    results = {}

    # =========================
    # CASO 1 — NAMOA NORMALE
    # =========================
    t0 = time.perf_counter()

    sol_plain, log_plain = namoa_instrumented(
        grafo,
        start_cell,
        goal_cell,
        heuristic=heuristic,
        cost_round=cost_round,
        t_max=t_max
    )

    t1 = time.perf_counter()

    results["plain"] = {
        "solutions": sol_plain,
        "log": log_plain,
        "time_namoa": t1 - t0
    }

    # =========================
    # CASO 2 — PREPROCESSING
    # =========================
    t0 = time.perf_counter()

    graph_time = build_time_min_graph(grafo)
    dist_time = dijkstra_time_from_start(graph_time, start_cell)

    reachable = {v for v, t in dist_time.items() if t <= t_max}

    if goal_cell not in reachable:
        raise ValueError("Goal non raggiungibile entro T_max (isocrona)")

    grafo_iso = filter_graph_by_reachable(grafo, reachable)

    t_pre = time.perf_counter()

    sol_iso, log_iso = namoa_instrumented(
        grafo_iso,
        start_cell,
        goal_cell,
        heuristic=heuristic,
        cost_round=cost_round,
        t_max=t_max
    )

    t_end = time.perf_counter()

    results["isocrona"] = {
        "solutions": sol_iso,
        "log": log_iso,
        "time_preprocessing": t_pre - t0,
        "time_namoa": t_end - t_pre,
        "time_total": t_end - t0,
        "reachable_nodes": len(reachable),
        "original_nodes": len(grafo)
    }

    return results
