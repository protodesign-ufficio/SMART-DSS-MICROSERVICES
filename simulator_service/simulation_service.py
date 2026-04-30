# simulation_service.py
import time
import threading
import traceback
import xarray as xr
import constants
from vessel import Vessel, VesselState

# Cache globale del dataset: caricato una sola volta in memoria, condiviso tra tutte le simulazioni
_dataset_cache = {}
_dataset_cache_lock = threading.Lock()

def _get_dataset(dataset_path):
    """Carica il dataset in memoria una sola volta e lo condivide tra tutte le simulazioni."""
    with _dataset_cache_lock:
        if dataset_path not in _dataset_cache:
            print(f"[DATASET] Caricamento dataset in memoria: {dataset_path}")
            ds = xr.open_dataset(dataset_path)
            _dataset_cache[dataset_path] = ds.load()  # .load() carica tutto in RAM, evita I/O disco ripetuto
            ds.close()  # Chiude il file handle, i dati sono già in memoria
        return _dataset_cache[dataset_path]

class SimulationEngine:
    def __init__(self, vessels, dataset_path, timestep=1.0, simulation_id=None, sim_speed_factor=10.0):
        self.simulation_id = simulation_id
        self.vessels = vessels
        self.dataset = _get_dataset(dataset_path)
        self.running = False
        self.timestep = timestep
        self.current_time = 0.0
        self.sim_speed_factor = sim_speed_factor

    def step(self):
        """Esegue un singolo step di simulazione."""
        dt = constants.SIM_TIME_STEP # Use the constant time step
        for vessel in self.vessels:
            # Skip update if vessel is finished
            if vessel.vessel_state.name == "FINISHED_WAYPOINTS":
                continue

            try:
                vessel.update_raflac(dt, self.current_time, self.dataset, self.sim_speed_factor)
            except Exception as e:
                print(f"[{self.simulation_id}] ERROR in update_raflac for {vessel.name}: {e}")
                traceback.print_exc()
                continue

            vessel.navigation_time += dt
        self.current_time += dt
        #for vessel in self.vessels:
        #    if vessel.vessel_state.name != "FINISHED_WAYPOINTS":
        #        print(f"[{self.simulation_id}] {vessel.name} time: {vessel.navigation_time}")


    def run(self):
        """Loop continuo della simulazione."""
        self.running = True
        print(f"[{self.simulation_id}] Simulation started with {len(self.vessels)} vessels, speed factor: {self.sim_speed_factor}")
        target_interval = constants.SIM_TIME_STEP / self.sim_speed_factor
        overrun_count = 0
        step_count = 0
        last_heartbeat = time.monotonic()
        # Report diagnostico ogni 30 secondi simulati (= 300 step con SIM_TIME_STEP=0.1)
        diag_interval_steps = int(30.0 / constants.SIM_TIME_STEP)

        try:
            while self.running:
                loop_start = time.monotonic()

                # --- Step con protezione per-vessel ---
                try:
                    self.step()
                except Exception as e:
                    print(f"[{self.simulation_id}] CRITICAL step() error at step {step_count}: {e}")
                    traceback.print_exc()
                    # Non crashare: continua al prossimo step
                
                step_count += 1

                # Heartbeat ogni 10 secondi reali — prova che il thread è vivo
                now = time.monotonic()
                if now - last_heartbeat >= 10.0:
                    active = [v.name for v in self.vessels if v.vessel_state.name != "FINISHED_WAYPOINTS"]
                    finished = [v.name for v in self.vessels if v.vessel_state.name == "FINISHED_WAYPOINTS"]
                    print(f"[{self.simulation_id}] HEARTBEAT step={step_count} sim_t={self.current_time:.1f}s "
                          f"active={active} finished={finished}")
                    last_heartbeat = now
                
                # Report diagnostico periodico (ogni ~30s simulati)
                if step_count % diag_interval_steps == 0:
                    try:
                        from ais_generator import get_ais_queue_stats
                        stats = get_ais_queue_stats()
                        sim_minutes = self.current_time / 60.0
                        vessel_info = ", ".join(
                            f"{v.name}({v.vessel_state.name}, wp={v.current_waypoint_index}/{len(v.waypoints)})"
                            for v in self.vessels
                        )
                        print(f"[{self.simulation_id}] DIAG t={sim_minutes:.1f}min step={step_count} "
                              f"overruns={overrun_count} queue={stats['queue_size']}/{stats['queue_maxsize']} "
                              f"sent={stats['sent']} dropped={stats['dropped']} | {vessel_info}")
                    except Exception as e:
                        print(f"[{self.simulation_id}] DIAG error: {e}")

                # Check if all vessels have finished
                all_finished = True
                for vessel in self.vessels:
                    if vessel.vessel_state.name != "FINISHED_WAYPOINTS":
                        all_finished = False
                        break
                
                if all_finished:
                    print(f"[{self.simulation_id}] All vessels finished their routes. Stopping simulation.")
                    self.running = False
                    break
                
                # Sleep adattivo
                elapsed = time.monotonic() - loop_start
                sleep_time = target_interval - elapsed
                if sleep_time > 0:
                    time.sleep(sleep_time)
                else:
                    overrun_count += 1
                    if overrun_count % 50 == 1:
                        try:
                            from ais_generator import get_ais_queue_stats
                            stats = get_ais_queue_stats()
                            print(f"[{self.simulation_id}] WARNING: step took {elapsed:.3f}s, target was {target_interval:.3f}s "
                                  f"(overrun #{overrun_count}/{step_count} steps, "
                                  f"queue: {stats['queue_size']}/{stats['queue_maxsize']}, dropped: {stats['dropped']})")
                        except Exception as e:
                            print(f"[{self.simulation_id}] WARNING: overrun #{overrun_count}, diag error: {e}")

        except Exception as e:
            print(f"[{self.simulation_id}] FATAL: simulation thread crashed at step {step_count}!")
            print(f"[{self.simulation_id}] Exception: {e}")
            traceback.print_exc()
        finally:
            self.running = False
            print(f"[{self.simulation_id}] Simulation thread exiting. Steps={step_count}, overruns={overrun_count}")

    def stop(self):
        self.running = False
        print(f"[{self.simulation_id}] Simulation stopped")

    def get_status(self):
        """Ritorna lo stato corrente delle navi."""
        return [{
            "name": v.name,
            "x": v.x,
            "y": v.y,
            "lat": v.lat,
            "lon": v.lon,
            "speed": v.speed,
            "heading": v.heading
        } for v in self.vessels]
