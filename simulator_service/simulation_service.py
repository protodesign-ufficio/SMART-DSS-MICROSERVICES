# simulation_service.py
import time
import threading
import xarray as xr
import constants
from vessel import Vessel, VesselState

class SimulationEngine:
    def __init__(self, vessels, dataset_path, timestep=1.0, simulation_id=None, sim_speed_factor=10.0):
        self.simulation_id = simulation_id
        self.vessels = vessels
        self.dataset = xr.open_dataset(dataset_path)
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

            vessel.update_raflac(dt, self.current_time, self.dataset, self.sim_speed_factor)
            vessel.navigation_time += dt
        self.current_time += dt
        # print(f"[{self.simulation_id}] Simulated time: {self.current_time} seconds")
        for vessel in self.vessels:
            if vessel.vessel_state.name != "FINISHED_WAYPOINTS":
                print(f"[{self.simulation_id}] {vessel.name} time: {vessel.navigation_time}")


    def run(self):
        """Loop continuo della simulazione."""
        self.running = True
        print(f"[{self.simulation_id}] Simulation started with {len(self.vessels)} vessels, speed factor: {self.sim_speed_factor}")
        while self.running:
            self.step()
            
            # Check if all vessels have finished
            all_finished = True
            for vessel in self.vessels:
                # Use name comparison to avoid potential Enum identity issues across imports
                if vessel.vessel_state.name != "FINISHED_WAYPOINTS":
                    all_finished = False
                    break
            
            if all_finished:
                print(f"[{self.simulation_id}] All vessels finished their routes. Stopping simulation.")
                self.running = False
                break
                
            time.sleep(constants.SIM_TIME_STEP / self.sim_speed_factor)
            #time.sleep(10)

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
