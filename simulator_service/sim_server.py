#!/usr/bin/env python3
from flask import Flask, request, jsonify
from simulation_service import SimulationEngine
from waypoint import Waypoint, WaypointType
from vessel import Vessel
import threading
import os
import uuid

from waypoint import WaypointType

app = Flask(__name__)

# Dizionario per gestire simulazioni multiple, chiave = simulation_id
simulations = {}
simulations_lock = threading.Lock()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATASET_PATH = os.path.join(BASE_DIR, "copernicus-data", "test.nc")

@app.route("/simulate/start", methods=["POST"])
def start_simulation():
    data = request.get_json(force=True)
    print("Received simulation start request:", data)

    vessels_data = data.get("vessels", [])
    simulation_id = data.get("simulation_id", str(uuid.uuid4()))  # ID unico per la simulazione
    dataset_path = DATASET_PATH
    timestep = float(data.get("timestep", 1.0))
    sim_speed_factor = float(data.get("sim_speed_factor", 1.0))  # Velocità simulazione rispetto al tempo reale

    if not os.path.exists(dataset_path):
        return jsonify({"ok": False, "error": "Dataset not found"}), 400

    # Verifica se esiste già una simulazione con questo ID
    with simulations_lock:
        if simulation_id in simulations:
            return jsonify({"ok": False, "error": f"Simulation {simulation_id} already exists"}), 400

    vessels = []
    GHOST_MMSI_OFFSET = 500000000
    for v in vessels_data:
        # nave reale
        real_vessel = Vessel.from_dict(v)

        # nave ghost (copia profonda)
        # ghost_data = dict(v)
        # ghost_data["name"] = real_vessel.name + "_ghost"
        # ghost_data["ghost"] = True  # tag per routing Kafka
        # ghost_data["mmsi"] = int(v["mmsi"]) + GHOST_MMSI_OFFSET
        # print(f"Creating GHOST vessel for {real_vessel.name} with MMSI {ghost_data['mmsi']}")
        # ghost_vessel = Vessel.from_dict(ghost_data)

        vessels.append(real_vessel)
        # vessels.append(ghost_vessel)

        print(f"[{simulation_id}] Created REAL vessel: {real_vessel.name} MMSI={real_vessel.mmsi}")
        # print(f"Created GHOST vessel: {ghost_vessel.name} MMSI={ghost_vessel.mmsi}")

    # vessels.append(vessel)
    sim_engine = SimulationEngine(vessels, dataset_path, timestep, simulation_id, sim_speed_factor)
    
    with simulations_lock:
        simulations[simulation_id] = sim_engine

    threading.Thread(target=sim_engine.run, daemon=True).start()
    return jsonify({"ok": True, "message": "Simulation started", "simulation_id": simulation_id}), 200


@app.route("/simulate/status", methods=["GET"])
def get_status():
    simulation_id = request.args.get("simulation_id")
    
    with simulations_lock:
        if simulation_id:
            # Status di una simulazione specifica
            if simulation_id not in simulations:
                return jsonify({"ok": False, "error": f"Simulation {simulation_id} not found"}), 404
            sim_engine = simulations[simulation_id]
            if not sim_engine.running:
                return jsonify({"ok": False, "error": "Simulation not running"}), 400
            return jsonify({
                "ok": True,
                "simulation_id": simulation_id,
                "time": sim_engine.current_time,
                "vessels": sim_engine.get_status()
            })
        else:
            # Status di tutte le simulazioni
            all_status = {}
            for sim_id, sim_engine in simulations.items():
                all_status[sim_id] = {
                    "running": sim_engine.running,
                    "time": sim_engine.current_time,
                    "vessels": sim_engine.get_status()
                }
            return jsonify({"ok": True, "simulations": all_status})


@app.route("/simulate/stop", methods=["POST"])
def stop_simulation():
    data = request.get_json(force=True) if request.data else {}
    simulation_id = data.get("simulation_id")
    
    with simulations_lock:
        if simulation_id:
            # Ferma una simulazione specifica
            if simulation_id not in simulations:
                return jsonify({"ok": False, "error": f"Simulation {simulation_id} not found"}), 404
            simulations[simulation_id].stop()
            del simulations[simulation_id]
            return jsonify({"ok": True, "message": f"Simulation {simulation_id} stopped"})
        else:
            # Ferma tutte le simulazioni
            for sim_engine in simulations.values():
                sim_engine.stop()
            simulations.clear()
            return jsonify({"ok": True, "message": "All simulations stopped"})


@app.route("/simulate/list", methods=["GET"])
def list_simulations():
    """Lista tutte le simulazioni attive."""
    with simulations_lock:
        sim_list = []
        for sim_id, sim_engine in simulations.items():
            sim_list.append({
                "simulation_id": sim_id,
                "running": sim_engine.running,
                "vessels": [v.name for v in sim_engine.vessels],
                "time": sim_engine.current_time
            })
        return jsonify({"ok": True, "simulations": sim_list})

@app.route('/vessel/<name>/disturbance', methods=['POST'])
def set_disturbance(name):
    payload = request.json
    decay = payload.get("speed_decay_factor")
    ext_v = payload.get("external_velocity")
    simulation_id = payload.get("simulation_id")

    with simulations_lock:
        # Se simulation_id è specificato, cerca solo in quella simulazione
        if simulation_id:
            if simulation_id not in simulations:
                return {"status": "simulation not found"}, 404
            target_engines = [simulations[simulation_id]]
        else:
            # Cerca in tutte le simulazioni
            target_engines = list(simulations.values())
        
        for sim_engine in target_engines:
            for v in sim_engine.vessels:
                if v.name == name and not v.is_ghost:
                    if decay is not None:
                        v.speed_decay_factor = float(decay)
                    if ext_v is not None:
                        v.external_velocity = (float(ext_v[0]), float(ext_v[1]))
                    return {"status": "ok"}

    return {"status": "vessel not found"}, 404



if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=True)
