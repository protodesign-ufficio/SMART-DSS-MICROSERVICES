#!/usr/bin/env python3
from http.client import HTTPException
from flask import Flask, request, jsonify
from Api_Copernicus import generate_fake_copernicus_dataset_km
from graphs_cell import _CACHE, floor_time, get_cached_namoa_graph, load_cached_graphs_from_disk, save_namoa_graph
from optimizer_service import build_graph_from_grib, debug_dataset, load_dataset_for_date, normalize_time, optimize_route, _apply_scenario_to_dataset
from constants import CUSTOM_CURRENT, latlon_to_xy, xy_to_latlon
from datetime import datetime, timedelta

from routing import build_double_weighted_graph_NAMOA
app = Flask(__name__)
load_cached_graphs_from_disk()


@app.route("/set_current_box", methods=["POST"])
def set_current_box():
    """Imposta un box in cui la corrente è forzata a valori costanti."""
    global CUSTOM_CURRENT
    payload = request.get_json(force=True)

    CUSTOM_CURRENT = {
        "min_lat": float(payload["min_lat"]),
        "max_lat": float(payload["max_lat"]),
        "min_lon": float(payload["min_lon"]),
        "max_lon": float(payload["max_lon"]),
        "uo": float(payload["uo"]),
        "vo": float(payload["vo"]),
    }

    return jsonify({"ok": True, "custom_box": CUSTOM_CURRENT})


@app.route("/clear_current_box", methods=["POST"])
def clear_current_box():
    """Ripristina il comportamento normale (solo Copernicus)."""
    global CUSTOM_CURRENT
    CUSTOM_CURRENT = None
    return jsonify({"ok": True, "message": "Custom current cleared"})


@app.route("/graphs/precompute", methods=["POST"])
def precompute():
    global CUSTOM_CURRENT
    try:
        payload = request.get_json(force=True)

        vessel = payload.get("vessel", {})
        params = payload.get("params", {})

        bbox = {
            "minimum_latitude": 40.512314,
            "maximum_latitude": 40.709292,
            "minimum_longitude": 14.200979,
            "maximum_longitude": 14.850346,
        }

        vessel_length = float(vessel.get("length_m", 30.0))
        vp_max = vessel["vmax_knots"] * 1.852
        vessel_signature = vessel.get("id",  "default_vessel")  
        print(f"[PRECOMPUTE] vessel_signature: {vessel_signature}") 

        vel_vec = (
            [v * 1.852 for v in params["vel_vect_knots"]]
            if "vel_vect_knots" in params
            else [
                0.25 * vp_max,
                0.50 * vp_max,
                0.75 * vp_max,
                vp_max
            ]
        )

        # vessel_signature = payload.get("vessel_id", "default_vessel")
        grid_spacing = int(payload.get("grid_spacing", 1000))
        ve_min = float(payload.get("ve_min", 0.1))
        empty = bool(payload.get("empty", False))
        fake_data = bool(payload.get("fake_data", False))

        # tolleranza in minuti → secondi
        tollerance_minutes = int(payload.get("tollerance", 60))
        T = tollerance_minutes * 60

        delta_minute = int(payload.get("delta", 60))

        start_time = datetime.fromisoformat(params["start_time_utc"])
        t_max = params["time_max"]
        end_time = start_time + timedelta(minutes=t_max)

        created = 0
        skipped = 0

        dataset_current = "cmems_mod_med_phy-cur_anfc_4.2km_PT15M-i"
        dataset_wave = "cmems_mod_med_wav_anfc_4.2km_PT1H-i"

        scenario = payload.get("scenario", None)
        if scenario:
            import json, hashlib
            sc_hash = "_sc_" + hashlib.sha256(json.dumps(scenario, sort_keys=True).encode()).hexdigest()[:12]
        else:
            sc_hash = ""
        empty_suffix = "_empty" if empty else "_full"
        dataset_hash = f"{dataset_current}_{dataset_wave}{sc_hash}{empty_suffix}"

        print(f"[PRECOMPUTE] tollerance={tollerance_minutes} min, delta={delta_minute} min")

        t = start_time
        while t <= end_time:

            graph_time = t
            bucket_time = floor_time(graph_time, T)

            cached = get_cached_namoa_graph(
                time=bucket_time,
                bbox=bbox,
                dataset_hash=dataset_hash,
                vessel_signature=vessel_signature,
                fake_data=fake_data,
                tollerance_seconds=T
            )

            if cached is not None:
                skipped += 1
                t += timedelta(minutes=delta_minute)
                continue

            print(f"[PRECOMPUTE] Building graph for t={graph_time}, bucket={bucket_time}")

            # 1) Dataset
            if fake_data:
                ds = generate_fake_copernicus_dataset_km(bbox, resolution_km=2)
            else:
                ds = load_dataset_for_date(
                    graph_time.strftime("%Y-%m-%d %H:%M:%S"),
                    bbox,
                    dataset_current
                )

            ds_wav = load_dataset_for_date(
                graph_time.strftime("%Y-%m-%d %H:%M:%S"),
                bbox,
                dataset_wave
            )

            debug_dataset(ds)

            # Applica scenario what-if ai dataset (se presente)
            if scenario:
                ds = _apply_scenario_to_dataset(ds, "currents", scenario)
                ds_wav = _apply_scenario_to_dataset(ds_wav, "waves", scenario)

            # 2) Grafo base
            grafo_base, nodes = build_graph_from_grib(ds, graph_time)

            # 3) Grafo NAMOA
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
                custom_current=CUSTOM_CURRENT,
                empty=empty,
                vessel_length=vessel_length
            )

            # 4) Cache
            save_namoa_graph(
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

            created += 1
            t += timedelta(minutes=delta_minute)

        return jsonify({
            "ok": True,
            "created": created,
            "skipped": skipped
        }), 200

    except Exception as e:
        print(f"[PRECOMPUTE ERROR] {e}")
        return jsonify({"ok": False, "error": str(e)}), 400


@app.route("/optimize", methods=["POST"])
def optimize():
    global CUSTOM_CURRENT
    try:
        if CUSTOM_CURRENT:
            print("Using custom current box:", CUSTOM_CURRENT)
        else: 
            print("No custom current box set.")
        
        payload = request.get_json(force=True)
        print("Received optimization request:", payload)
        vessel = payload.get("vessel", {})
        start = payload.get("start", {})
        goal = payload.get("goal", {})
        params = payload.get("params", {})
        optimization_id = payload.get("optimization_id", {})
        # Bounding box fisso per l'area di simulazione
        bbox = {
            "minimum_latitude": 40.512314,
            "maximum_latitude": 40.709292,
            "minimum_longitude": 14.200979,
            "maximum_longitude": 14.850346,
        }
        # bbox = {
        #     "minimum_latitude": 40.512314,
        #     "maximum_latitude": 40.809292,
        #     "minimum_longitude": 14.200979,
        #     "maximum_longitude": 14.950346,
        # }
        

        print(f"params: {params['start_time_utc']}")
        # dentro /optimize, prima di chiamare optimize_route
        tollerance_minutes = int(payload.get("tollerance", 60))
        vessel_signature = vessel["id"]
        scenario = payload.get("scenario", None)

        result = optimize_route(
            vessel_id=vessel["id"],
            vessel_name=vessel["name"],
            vessel_length = float(vessel.get("length_m", 30.0)),
            start_lat=float(start["lat"]),
            start_lon=float(start["lon"]),
            goal_lat=float(goal["lat"]),
            goal_lon=float(goal["lon"]),
            bbox=bbox,
            alpha=0,
            t_max=params["time_max"],
            vp_max=vessel["vmax_knots"]*1.852,
            # vel_vec=params["vel_vect_knots"] * 1.852 if "vel_vect_knots" in params else [0.25*vessel["vmax_knots"]*1.852, 0.50*vessel["vmax_knots"]*1.852, 0.75*vessel["vmax_knots"]*1.852, vessel["vmax_knots"]*1.852],
            vel_vec = [v * 1.852 for v in params["vel_vect_knots"]] if "vel_vect_knots" in params else [
                0.25 * vessel["vmax_knots"] * 1.852,
                0.50 * vessel["vmax_knots"] * 1.852,
                0.75 * vessel["vmax_knots"] * 1.852,
                vessel["vmax_knots"] * 1.852
            ],
            date_str=datetime.fromisoformat(params["start_time_utc"]).strftime("%Y-%m-%d %H:%M:%S"),
            optimization_id=optimization_id,
            ve_min=float(payload.get("ve_min", 0.1)),
            grid_spacing=int(payload.get("grid_spacing", 1000)),
            custom_current=CUSTOM_CURRENT,
            eps_time=float(payload.get("eps_time", 0.0)),
            empty=bool(payload.get("empty", False)),
            fake_data=bool(payload.get("fake_data", False)),
            # NUOVI (coerenza cache):
            tollerance_minutes=tollerance_minutes,
            vessel_signature=vessel_signature,
            scenario=scenario,
        )

        percorsi = convert_optimizer_output_to_percorsi(result)
        response = round_output(percorsi)
        print("Optimization result:", response)
        return jsonify(response), 200

        #print("Optimization result:", result)
        #return jsonify(result), 200

    except Exception as e:
        print(f"Error during optimization: {e}")
        return jsonify({"ok": False, "error": str(e)}), 400

@app.route("/optimize/list", methods=["POST"])
def optimizelist():
    global CUSTOM_CURRENT
    try:
        if CUSTOM_CURRENT:
            print("Using custom current box:", CUSTOM_CURRENT)
        else:
            print("No custom current box set.")
        
        payload = request.get_json(force=True)
        print("Received optimization request:", payload)

        # --- Normalizzazione input ---
        if isinstance(payload, list):
            jobs = payload
            batch_mode = True
        elif isinstance(payload, dict):
            jobs = [payload]
            batch_mode = False
        else:
            raise ValueError("Invalid payload: expected JSON object or list of objects")

        results = []

        # Bounding box fisso per l'area di simulazione
        bbox = {
            "minimum_latitude": 40.512314,
            "maximum_latitude": 40.709292,
            "minimum_longitude": 14.200979,
            "maximum_longitude": 14.850346,
        }

        for job in jobs:

            vessel = job.get("vessel", {})
            start = job.get("start", {})
            goal = job.get("goal", {})
            params = job.get("params", {})
            optimization_id = job.get("optimization_id", None)

            print(f"params.start_time_utc: {params.get('start_time_utc')}")

            tollerance_minutes = int(job.get("tollerance", 60))
            vessel_signature = vessel.get("id", "default_vessel")
            scenario = job.get("scenario", None)

            result = optimize_route(
                vessel_id=vessel["id"],
                vessel_name=vessel["name"],
                vessel_length=float(vessel.get("length_m", 30.0)),
                start_lat=float(start["lat"]),
                start_lon=float(start["lon"]),
                goal_lat=float(goal["lat"]),
                goal_lon=float(goal["lon"]),
                bbox=bbox,
                alpha=0,
                t_max=params["time_max"],
                vp_max=vessel["vmax_knots"] * 1.852,
                vel_vec=[v * 1.852 for v in params["vel_vect_knots"]] if "vel_vect_knots" in params else [
                    0.25 * vessel["vmax_knots"] * 1.852,
                    0.50 * vessel["vmax_knots"] * 1.852,
                    0.75 * vessel["vmax_knots"] * 1.852,
                    vessel["vmax_knots"] * 1.852
                ],
                date_str=datetime.fromisoformat(params["start_time_utc"]).strftime("%Y-%m-%d %H:%M:%S"),
                optimization_id=optimization_id,
                ve_min=float(job.get("ve_min", 0.1)),
                grid_spacing=int(job.get("grid_spacing", 1000)),
                custom_current=CUSTOM_CURRENT,
                eps_time=float(job.get("eps_time", 0.0)),
                empty=bool(job.get("empty", False)),
                fake_data=bool(job.get("fake_data", False)),
                tollerance_minutes=tollerance_minutes,
                vessel_signature=vessel_signature,
                scenario=scenario,
            )

            percorsi = convert_optimizer_output_to_percorsi(result)
            response = round_output(percorsi)
            results.append(response)

        return jsonify(results if batch_mode else results[0]), 200

    except Exception as e:
        print(f"Error during optimization: {e}")
        return jsonify({"ok": False, "error": str(e)}), 400

def round_output(obj, ndigits=3):
    if isinstance(obj, float):
        return round(obj, ndigits)
    if isinstance(obj, list):
        return [round_output(x, ndigits) for x in obj]
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if k == "geom_rotta":
                out[k] = v  # NO rounding
            else:
                out[k] = round_output(v, ndigits)
        return out
    return obj


def convert_optimizer_output_to_percorsi(opt_data):
    percorsi = []
    weather_cache_keys = opt_data.get("weather_cache_keys")

    CONSUMO_PER_NM_PIENO_CARICO = 1.0
    FATTORE_VUOTO = 0.2

    # tempo minimo assoluto della tratta
    tempo_riposizionamento = min(
        route["cost_time"] for route in opt_data["routes"]
    )

    for route in opt_data["routes"]:
        name = route["name"]
        try:
            id_corsa = int(name.split("rotta id:")[1].split(")")[0].strip())
        except Exception:
            raise ValueError(f"Impossibile estrarre id_corsa da: {name}")

        waypoints = route["waypoints"]

        geom_rotta = []
        pref = []
        vref = []

        for wp in waypoints:
            geom_rotta.append([wp["lat"], wp["lon"]])
            pref.append(wp.get("heading_deg"))
            vref.append(wp["vref"]["speed"] if wp.get("vref") else None)

        # ---- distanza totale rotta (NM) ----
        distanza_nm = 0.0
        for (lat1, lon1), (lat2, lon2) in zip(geom_rotta[:-1], geom_rotta[1:]):
            distanza_nm += haversine_nm(lat1, lon1, lat2, lon2)

        # ---- consumi derivati ----
        consumo_pieno_carico = CONSUMO_PER_NM_PIENO_CARICO * distanza_nm
        consumo_vuoto = FATTORE_VUOTO * consumo_pieno_carico

        percorsi.append({
            "id_corsa": id_corsa,
            "geom_rotta": geom_rotta,
            "pref": pref,
            "vref": vref,

            # tempi
            "tempo_percorrenza": route["cost_time"],

            # comfort (ex cost_energy)
            "comfort": route["cost_energy"],

            # consumo reale
            "distanza_nm": distanza_nm,
            "consumo_pieno_carico": consumo_pieno_carico,
            "consumo_vuoto": consumo_vuoto,
        })

    return {
        "tempo_riposizionamento": tempo_riposizionamento,
        "percorsi": percorsi,
        "weather_cache_keys": weather_cache_keys,
    }

import math

def haversine_nm(lat1, lon1, lat2, lon2):
    """
    Distanza tra due punti geografici in Nautical Miles.
    """
    R_km = 6371.0  # raggio terrestre medio

    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)

    a = (
        math.sin(dphi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2.0) ** 2
    )
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))

    distanza_km = R_km * c
    distanza_nm = distanza_km / 1.852  # km → NM

    return distanza_nm


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8090, debug=True)
