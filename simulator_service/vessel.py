from datetime import datetime, timedelta
import math
from ais_generator import PositionReportParams, StaticVoyageParams, generate_position_report, generate_static_voyage_report, send_ais_sentence, send_ais_multipart
import numpy as np
import constants
from waypoint import Waypoint, WaypointType
from constants import (
    CURRENT_SCALE, TRAJECTORY_LENGTH, WAYPOINT_REACHED_THRESHOLD, STOP_WAYPOINT_STOPPING_DISTANCE, xy_to_latlon
)
import enum
from Api_Copernicus import read_point  # Assicurati sia importato

# --- Enums ---
class VesselState(enum.Enum):
    """
    Defines the current state of a vessel's waypoint navigation.
    """
    IDLE = "Idle"
    MOVING_TO_WAYPOINT = "Moving to Waypoint"
    STOPPING_AT_WAYPOINT = "Stopping at Waypoint"
    WAITING_AT_WAYPOINT = "Waiting at Waypoint" # Currently not used, but kept for future expansion
    FINISHED_WAYPOINTS = "Finished Waypoints"


# --- Vessel Class ---
class Vessel:
    """
    Represents a single vessel in the simulation, including its physical properties,
    dynamics, and waypoint navigation logic.
    """
    def __init__(self, x, y, heading=0, speed=0, mass=1000, drag_coeff=5000, max_thrust=50000.0, max_turn_rate=math.pi/30, turning_gain=1, name="Vessel", mmsi = None):
        self.name = name # Unique identifier for the vessel
        self.mmsi = mmsi
        self.x = x # Simulation x position (meters)
        self.y = y # Simulation y position (meters)
        self.lat, self.lon = xy_to_latlon(self.x, self.y)
        self.heading = heading # Radians (0=east, pi/2=north)
        self.speed = speed # Scalar speed (meters/second)
        self.speed_eff = speed #velocità effettiva...speed + speed_current
        self.Vx = self.speed * math.cos(self.heading)
        self.Vy = self.speed * math.sin(self.heading)
        self.omega = 0.0
        self.Vx_eff = None
        self.Vy_eff = None
        self.mass = mass # Kilograms
        self.drag_coeff = drag_coeff # Unitless
        self.max_thrust = max_thrust # Newtons
        self.max_turn_rate = max_turn_rate # Radians per second
        self.turning_gain = turning_gain # Proportional gain for heading control

        self.thrust_force = 0 # Current thrust force applied (Newtons)
        self.drag_force = 0 # Current drag force (Newtons)
        self.net_force = 0 # Sum of forces (Newtons)
        self.acceleration = 0 # Current acceleration (meters/second^2)

        self.trajectory = [] # List of (x, y) tuples for past positions
        self.max_trajectory_points = TRAJECTORY_LENGTH # Max points to store for trajectory

        # Control inputs
        self.throttle = 0.0 # Proportion of max_thrust (0.0 to 1.0)
        self.target_heading = heading # Desired heading in radians

        # Waypoint Navigation
        self.waypoints = [] # List of Waypoint objects
        self.current_waypoint_index = 0 # Index of the current target waypoint
        self.vessel_state = VesselState.IDLE # Current state of waypoint following
        self.current_stop_time = 0.0 # Timer for STOP waypoints
        # self.current_time
        # Tkinter canvas object IDs (managed by the main application)
        self.canvas_id = None
        self.trajectory_canvas_id = None
        self.waypoint_canvas_ids = [] # List to store canvas IDs for drawing waypoints
    
        self.navigation_time = 0.0  # Tempo di navigazione per questa nave
        self.speed_decay_factor = 1.0        # < 1 => nave rallentata
        self.external_velocity = (0.0, 0.0)  # (vx, vy) perturbazione esterna in m/s

        self.predicted_position = None  # (x, y) posizione futura stimata
        self.future_collision = False  # Indica se c'è rischio di collisione nei prossimi secondi
        self.collision_point = None  
        self.destination = None  # Destinazione della nave
        self.eta = None  # Ora stimata di arrivo
        self.is_ghost = False
        self.ais_stopped = False  # Flag per tracciare se l'invio AIS è stato interrotto
        self.virtuale = True  # True = ais_simulation.raw, False = ais.raw
        self._last_ais_send_time = -999.0  # Ultimo tempo simulato in cui è stato inviato AIS

    
    def add_waypoint(self, waypoint):
        """Aggiunge un waypoint alla lista dei waypoint della nave."""
        self.waypoints.append(waypoint)
        #print(f"{self.name}: Added waypoint: {waypoint.x}, {waypoint.y}, Type: {waypoint.type}, Pa: {waypoint.Pa}, Vr: {waypoint.Vr}")


    def clear_waypoints(self):
        """Clears all waypoints and resets waypoint navigation state."""
        self.waypoints = []
        self.current_waypoint_index = 0
        self.vessel_state = VesselState.IDLE
        self.current_stop_time = 0.0
        print(f"{self.name}: All waypoints cleared.")

    def _interpolate_waypoints(self):
        """
        Interpola waypoint virtuali tra i waypoint originali per aumentare
        la precisione della navigazione. Inserisce un waypoint ogni 
        WAYPOINT_INTERPOLATION_DISTANCE metri.
        """
        from constants import WAYPOINT_INTERPOLATION_DISTANCE
        
        if len(self.waypoints) < 2:
            return  # Niente da interpolare
        
        original_count = len(self.waypoints)
        new_waypoints = []
        
        for i in range(len(self.waypoints) - 1):
            wp_start = self.waypoints[i]
            wp_end = self.waypoints[i + 1]
            
            # Aggiungi il waypoint di partenza (tranne l'ultimo che sarà aggiunto alla fine)
            new_waypoints.append(wp_start)
            
            # Calcola distanza tra i due waypoint
            dx = wp_end.x - wp_start.x
            dy = wp_end.y - wp_start.y
            distance = math.sqrt(dx**2 + dy**2)
            
            # Se la distanza è maggiore della soglia, interpola
            if distance > WAYPOINT_INTERPOLATION_DISTANCE:
                num_segments = int(distance / WAYPOINT_INTERPOLATION_DISTANCE)
                
                for j in range(1, num_segments + 1):
                    # Fattore di interpolazione (0 = start, 1 = end)
                    t = j / (num_segments + 1)
                    
                    # Coordinate interpolate
                    interp_x = wp_start.x + t * dx
                    interp_y = wp_start.y + t * dy
                    
                    # Interpola Vr se entrambi i waypoint ce l'hanno
                    interp_Vr = None
                    if wp_start.Vr is not None and wp_end.Vr is not None:
                        vx_start, vy_start = wp_start.Vr
                        vx_end, vy_end = wp_end.Vr
                        interp_vx = vx_start + t * (vx_end - vx_start)
                        interp_vy = vy_start + t * (vy_end - vy_start)
                        interp_Vr = [interp_vx, interp_vy]
                    elif wp_start.Vr is not None:
                        interp_Vr = wp_start.Vr  # Usa Vr del waypoint precedente
                    elif wp_end.Vr is not None:
                        interp_Vr = wp_end.Vr  # Usa Vr del waypoint successivo
                    
                    # Crea waypoint virtuale (sempre WALKTHROUGH)
                    virtual_wp = Waypoint(
                        x=interp_x,
                        y=interp_y,
                        waypoint_type=WaypointType.WALKTHROUGH,
                        stop_duration=0,
                        Pa=None,  # Pa sarà calcolato con atan2
                        Vr=interp_Vr
                    )
                    new_waypoints.append(virtual_wp)
        
        # Aggiungi l'ultimo waypoint originale
        new_waypoints.append(self.waypoints[-1])
        
        # Sostituisci la lista dei waypoint
        self.waypoints = new_waypoints
        
        interpolated_count = len(self.waypoints) - original_count
        #print(f"{self.name}: Interpolated {interpolated_count} virtual waypoints (total: {len(self.waypoints)})")

    def update_raflac(self, dt, current_time, dataset, sim_speed_factor=1.0):
            """
            Updates the vessel's state based on dynamics and waypoint navigation
            over a time step dt. dt is in seconds.
            sim_speed_factor: fattore di accelerazione della simulazione.
            """
            # Store current position for trajectory
            self.trajectory.append((self.x, self.y))
            
            if len(self.trajectory) > self.max_trajectory_points:
                self.trajectory.pop(0) # Remove the oldest point to maintain trajectory length
            # --- Waypoint Navigation Logic ---
            if self.vessel_state == VesselState.MOVING_TO_WAYPOINT:
                if self.current_waypoint_index < len(self.waypoints):
                    target_waypoint = self.waypoints[self.current_waypoint_index]
                    dx = target_waypoint.x - self.x
                    dy = target_waypoint.y - self.y
                    distance_to_waypoint = math.sqrt(dx**2 + dy**2)
                    
                    # SEMPRE usa atan2 - ignora Pa (da riabilitare quando routing sarà corretto)
                    self.target_heading = math.atan2(dy, dx)
                    
                    # Stampa distanza dal waypoint corrente
                    #print(f"[NAV] {self.name}: WP{self.current_waypoint_index + 1}/{len(self.waypoints)} | dist={distance_to_waypoint:.1f}m | heading={math.degrees(self.heading):.1f}° → target={math.degrees(self.target_heading):.1f}°")
                    
                    # --- Controllo della velocità ---
                    if target_waypoint.type == WaypointType.STOP and distance_to_waypoint <= self.speed*self.mass/self.drag_coeff:
                        #print("DEBUG, ingresso nel raggio: ", STOP_WAYPOINT_STOPPING_DISTANCE, "distanza: ", distance_to_waypoint)
                        # Reduce throttle linearly as we get closer to the stop waypoint
                        # from full throttle at STOP_WAYPOINT_STOPPING_DISTANCE to 0 at WAYPOINT_REACHED_THRESHOLD
                        throttle_reduction = (STOP_WAYPOINT_STOPPING_DISTANCE - distance_to_waypoint) / \
                                            (STOP_WAYPOINT_STOPPING_DISTANCE - WAYPOINT_REACHED_THRESHOLD)
                        self.throttle = max(0.0, 1.0 - throttle_reduction) # Ensure throttle doesn't go below 0
                        self.throttle = 0 # Ensure throttle doesn't go below 0
                    else:
                        # --- controllo con Vref ---
                        if hasattr(target_waypoint, "Vr") and target_waypoint.Vr is not None:
                            #print("Vr calcolato:", target_waypoint.Vr)
                            vx_ref, vy_ref = target_waypoint.Vr
                            speed_ref = math.sqrt(vx_ref**2 + vy_ref**2)
                        else: 
                            speed_ref = 30.0 # default speed if no reference provided 
                        speed_now = math.sqrt(self.Vx**2 + self.Vy**2)
                        # Controllo proporzionale per avvicinare la velocità desiderata
                        # Throttle minimo stimato per vincere il drag
                        drag_force = self.drag_coeff * speed_now
                        base_throttle = drag_force / self.max_thrust
                        error = speed_ref - speed_now
                        gain = 0.2 
                        self.throttle = max(0.0, min(1.0, base_throttle + gain * error))
                        #print(self.name, "Speed now:", speed_now, "Speed ref:", speed_ref, "Throttle:", self.throttle)
                        
                    # Check if waypoint is reached
                    if distance_to_waypoint < WAYPOINT_REACHED_THRESHOLD:
                        target_waypoint.reached = True
                        #print(f"{self.name}: Reached waypoint {self.current_waypoint_index + 1}")

                        if target_waypoint.type == WaypointType.STOP:
                            self.vessel_state = VesselState.STOPPING_AT_WAYPOINT
                            self.throttle = 0.0 # Stop the vessel immediately
                            self.current_stop_time = 0.0 # Reset stop timer
                            #print(f"{self.name}: Stopping at waypoint {self.current_waypoint_index + 1} for {target_waypoint.stop_duration} seconds.")
                        else: # Walkthrough waypoint
                            self.current_waypoint_index += 1
                            if self.current_waypoint_index >= len(self.waypoints):
                                self.vessel_state = VesselState.FINISHED_WAYPOINTS
                                self.throttle = 0.0 # Stop the vessel once all waypoints are finished
                                #print(f"{self.name}: Finished all waypoints.")
                            else:
                                pass #print(f"{self.name}: Moving to next waypoint {self.current_waypoint_index + 1}.")

                else: # Should not happen if state is MOVING_TO_WAYPOINT but no waypoints left
                    self.vessel_state = VesselState.FINISHED_WAYPOINTS
                    self.throttle = 0.0
                    #print(f"{self.name}: No waypoints to move to, state was MOVING_TO_WAYPOINT.")

            elif self.vessel_state == VesselState.STOPPING_AT_WAYPOINT:
                # Maintain stopped state and wait for stop duration
                self.throttle = 0.0
                self.current_stop_time += dt

                if self.current_stop_time >= self.waypoints[self.current_waypoint_index].stop_duration:
                    #print(f"{self.name}: Finished stopping at waypoint {self.current_waypoint_index + 1}.")
                    self.current_waypoint_index += 1
                    if self.current_waypoint_index >= len(self.waypoints):
                        self.vessel_state = VesselState.FINISHED_WAYPOINTS
                        #print(f"{self.name}: Finished all waypoints.")
                    else:
                        self.vessel_state = VesselState.MOVING_TO_WAYPOINT
                        #print(f"{self.name}: Moving to next waypoint {self.current_waypoint_index + 1}.")

            elif self.vessel_state == VesselState.WAITING_AT_WAYPOINT:
                # This state is currently not used, but could be for more complex waiting logic
                pass

            elif self.vessel_state == VesselState.FINISHED_WAYPOINTS:
                self.throttle = 0.0 # Stop the vessel
                # Il messaggio di arrivo viene stampato solo una volta quando si entra nello stato
                
            # --- Dynamics (Apply forces and update position/heading) ---
            try:
                times = dataset["time"].values
                idx = int(current_time // dt)  # calcolo indice temporale discreto
                idx = min(idx, len(times) - 1)
                target_time = times[idx]
                uo, vo = read_point(dataset, target_time, self.lat, self.lon)
                scale = CURRENT_SCALE #Aumento correnti
                uo, vo = uo * scale, vo* scale
            except Exception as e:
                uo, vo = 0.0, 0.0  # fallback

            # 1. Turning (Update Heading)
            # Calculate the shortest angle difference between current and target heading
            delta_heading = (self.target_heading - self.heading + math.pi * 3) % (math.pi * 2) - math.pi
            angular_velocity = self.turning_gain * delta_heading
            # Clamp angular velocity to max turn rate
            angular_velocity = max(-self.max_turn_rate, min(self.max_turn_rate, angular_velocity))
            self.heading += angular_velocity * dt

            # Normalize heading to be within [0, 2*pi)
            self.heading = self.heading % (math.pi * 2)
            if self.heading < 0: self.heading += math.pi * 2

            # 2. Speed (Update Speed)
            self.thrust_force = self.throttle * self.max_thrust
            # Simple drag model: force is proportional to speed, opposing motion
            self.drag_force = -self.drag_coeff * self.speed
            self.net_force = self.thrust_force + self.drag_force
            self.acceleration = self.net_force / self.mass
            self.speed += self.acceleration * dt
            self.speed = max(0.0, self.speed) # Speed cannot be negative

            # 3. Position (Update Position)
            # Calculate velocity components based on current speed and heading
            self.Vx = self.speed * math.cos(self.heading)
            #print("heading: ", math.degrees(self.heading))
            self.Vy = self.speed * math.sin(self.heading)
            if not self.is_ghost:
                # Ritardo (decadimento velocità)
                self.Vx *= self.speed_decay_factor
                self.Vy *= self.speed_decay_factor

                # Deriva / spinta esterna (m/s)
                self.Vx += self.external_velocity[0]
                self.Vy += self.external_velocity[1]

            # Somma la corrente marina alla velocità propulsiva
            self.Vx_eff = self.Vx + uo
            self.Vy_eff = self.Vy + vo

            self.x += self.Vx_eff * dt
            self.y += self.Vy_eff * dt
            self.speed_eff = math.sqrt(self.Vx_eff**2 + self.Vy_eff**2)
            
            self.lat, self.lon = xy_to_latlon(self.x, self.y)

            # --- Invio messaggio AIS NMEA via UDP ---
            # NON inviare AIS se la nave ha terminato i waypoint (arrivata a destinazione)
            if self.vessel_state == VesselState.FINISHED_WAYPOINTS:
                # La nave è arrivata a destinazione, stop invio AIS
                if not self.ais_stopped:
                    print(f"[AIS STOP] {self.name} (MMSI: {self.mmsi}) - Nave arrivata a destinazione, invio AIS terminato.")
                    self.ais_stopped = True
                return
            
            # Throttling AIS: invia solo ogni AIS_SEND_INTERVAL secondi simulati
            # Riduce da ~100 msg/s a ~2 msg/s per nave, evitando saturazione Kafka/consumer
            if current_time - self._last_ais_send_time < constants.AIS_SEND_INTERVAL:
                # Aggiorna comunque la predizione posizione
                self.predicted_position = self.predict_position(dt*100)
                return
            self._last_ais_send_time = current_time
            try:
                now = datetime.utcnow()
                # Usa mmsi_originale per l'invio a Telegraf
                mmsi_to_send = getattr(self, 'mmsi_originale', self.mmsi)
                pos_cfg = PositionReportParams(
                    mmsi = int(mmsi_to_send),
                    latitude=self.lat,
                    longitude=self.lon,
                    speed=self.speed_eff,     # velocità effettiva (in nodi se vuoi)
                    course=int(90 - math.degrees(self.heading)) % 360,
                    heading=int(90 - math.degrees(self.heading)) % 360, # heading vero (VEDI BENE 180 - HEADING))
                    timestamp=now.second
                )

                # Passa i flag come parametri (thread-safe)
                for frag in generate_position_report(pos_cfg):
                    send_ais_sentence(frag, is_virtual=self.virtuale, is_ghost=self.is_ghost)
                    #print(f"[AIS SENT] {frag}")
            except Exception as e:
                print(f"[⚠️] Errore invio NMEA/AIS per {self.name}: {e}")

            # AIS TYPE 5 ogni 5 minuti (300 sec) o all'inizio
            #print("current_time: ", current_time, " dt: ", dt)
            if current_time == 0.0 or (current_time % 10 < dt):
                #print("Invio AIS TYPE 5 per nave:", self.name)
                self.send_static_ais(sim_speed_factor)

            # Prevede la posizione futura e aggiorna la logica della nave
            self.predicted_position = self.predict_position(dt*100) #Predice la posizione nei prossimi 100 passi, ma se ogni passo è un decimo di secondo, predico la posizione nei prossimi 10 secondi
            
        
    def predict_position(self, t):
        """
        Prevede la posizione della nave dopo un certo intervallo di tempo t.
        :param t: intervallo di tempo in secondi
        :return: (x, y) posizione prevista
        """
        # Calcola la posizione futura in base alla velocità e alla direzione
        future_x = self.x + self.Vx * t
        future_y = self.y + self.Vy * t

        #self.predicted_position = (future_x, future_y)
        return future_x, future_y


    def to_dict(self):
        """
        Converts the Vessel object's essential attributes into a dictionary
        for serialization (e.g., to JSON).
        """
        return {
            "name": self.name,
            "x": self.x,
            "y": self.y,
            "heading": self.heading,  # in radianti
            "speed": self.speed,
            "mass": self.mass,
            "drag_coeff": self.drag_coeff,
            "max_thrust": self.max_thrust,
            "max_turn_rate": self.max_turn_rate,  # in radianti
            "turning_gain": self.turning_gain,
            "mmsi": self.mmsi,
            # Nuovi parametri dinamici
            # "I_z": self.I_z,
            # "drag_coeff_angular": self.drag_coeff_angular,
            # "rudder_coeff": self.rudder_coeff,
            # "rudder_distance": self.rudder_distance,
            # Waypoints
            "waypoints": [
                {"x": wp.x, "y": wp.y, "type": wp.type.value, "stop_duration": wp.stop_duration}
                for wp in self.waypoints
            ]
    }

    @classmethod
    def from_dict(cls, data):
        """
        Creates a Vessel object from a dictionary (e.g., loaded from JSON).
        """

        if "x" not in data or "y" not in data:
            if "lat" in data and "lon" in data:
                data["x"], data["y"] = constants.latlon_to_xy(data["lat"], data["lon"])
            else:
                raise ValueError("Mancano coordinate: serve x/y oppure lat/lon, testina.")
         

        vessel = cls(
            x=data["x"],
            y=data["y"],
            heading=data["heading"],
            speed=data["speed"],
            mass=data.get("mass", 1000.0),
            drag_coeff=data.get("drag_coeff", 0.5),
            max_thrust=data.get("max_thrust", 500.0),
            max_turn_rate=data.get("max_turn_rate", 3.14159 / 30),
            turning_gain=data.get("turning_gain", 0.1),
            #mmsi=data["mmsi"],
            mmsi=int(data.get("mmsi")) if data.get("mmsi") is not None else None,
            name=data["name"],
            
            # Nuovi parametri con valori di default se non presenti
            # I_z=data.get("I_z", 1000.0),
            # drag_coeff_angular=data.get("drag_coeff_angular", 10.0),
            # rudder_coeff=data.get("rudder_coeff", 100.0),
            # rudder_distance=data.get("rudder_distance", 5.0),
        )

        #print("x e y", vessel.x, vessel.y, "lat e lon:", constants.xy_to_latlon(vessel.x, vessel.y))
        #print("Creata nave da dict:", vessel.name, " - mmsi: ", vessel.mmsi)

        vessel.throttle = data.get("throttle", 0.0)
        vessel.target_heading = data.get("target_heading", data["heading"])
        vessel.destination = data.get("destination")
        vessel.eta = data.get("eta")  # formato "YYYY-MM-DD HH:MM"
        vessel.is_ghost = data.get("ghost", False)
        
        # Parametro obbligatorio "virtuale": True = ais_simulation.raw, False = ais.raw
        if "virtuale" not in data:
            raise ValueError(f"Parametro 'virtuale' obbligatorio mancante per la nave {data.get('name', 'sconosciuta')}")
        vessel.virtuale = data.get("virtuale")
        
        # Salva MMSI originale per l'invio a Telegraf
        vessel.mmsi_originale = vessel.mmsi
        
        # Suffisso automatico per navi virtuali per distinguerle internamente
        if vessel.virtuale:
            if not vessel.name.endswith("_sim"):
                vessel.name = vessel.name + "_sim"
            # Offset MMSI per distinguere internamente (non usato per Telegraf)
            if vessel.mmsi is not None:
                vessel.mmsi = vessel.mmsi + 100000000

        # Carica waypoint
        if "waypoints" in data:
            for wp_data in data["waypoints"]:
                # Conversione automatica se arrivano lat/lon
                if "x" not in wp_data or "y" not in wp_data:
                    if "lat" in wp_data and "lon" in wp_data:
                        wp_data["x"], wp_data["y"] = constants.latlon_to_xy(wp_data["lat"], wp_data["lon"])
                    else:
                        raise ValueError("Waypoint senza coordinate valide, pirla: servono x/y o lat/lon.")

                wp_type = WaypointType(wp_data.get("type", WaypointType.WALKTHROUGH.value))
                stop_duration = wp_data.get("stop_duration", 0)
                #print("Aggiungo waypoint da dict:", wp_data)

                vessel.add_waypoint(
                    Waypoint(
                        wp_data["x"],
                        wp_data["y"],
                        wp_type,
                        stop_duration,
                        Pa=wp_data.get("Pa", None),
                        Vr=wp_data.get("Vr", None)
                    )
                )

        # Interpola waypoint virtuali per maggiore precisione
        vessel._interpolate_waypoints()
        
        # Reset stato navigazione
        vessel.current_waypoint_index = 0
        vessel.current_stop_time = 0.0
        if vessel.waypoints:
            vessel.vessel_state = VesselState.MOVING_TO_WAYPOINT
            for wp in vessel.waypoints:
                wp.reached = False
        else:
            vessel.vessel_state = VesselState.IDLE

        # Inizializza velocità globale e omega per il nuovo modello, se non già presenti
        import math
        vessel.Vx = vessel.speed * math.cos(vessel.heading)
        vessel.Vy = vessel.speed * math.sin(vessel.heading)
        vessel.omega = 0.0

        return vessel
    
    from datetime import datetime
    from ais_generator import StaticVoyageParams, generate_static_voyage_report, send_ais_sentence

    def send_static_ais(self, sim_speed_factor=1.0):
        # 1. Controllo dati minimi
        if not self.destination:
            print(f"[TYPE5 SKIP] No destination for {self.name}")
            return

        # 2. Calcolo ETA dinamico SOLO ora (diviso per sim_speed_factor per tempo reale utente)
        try:
            eta_dt = self.compute_eta(datetime.now(), sim_speed_factor)   # <<=== QUI LA MAGIA
        except Exception as e:
            print(f"[TYPE5 ERROR] ETA computation failed for {self.name}: {e}")
            return

        #print(f"[DEBUG ETA] Computed ETA: {eta_dt}")

        try:
            # Usa mmsi_originale per l'invio a Telegraf
            mmsi_to_send = getattr(self, 'mmsi_originale', self.mmsi)
            stat_cfg = StaticVoyageParams(
                mmsi=mmsi_to_send,
                callsign=self.name[:7].upper(),
                name=self.name[:20].upper(),
                ship_type=70,
                to_bow=50,
                to_stern=20,
                to_port=10,
                to_starboard=10,
                eta_month=eta_dt.month,
                eta_day=eta_dt.day,
                eta_hour=eta_dt.hour,
                eta_minute=eta_dt.minute,
                draft=5,
                destination=self.destination[:20].upper()
            )

            # Invia tutti i frammenti come singolo messaggio Kafka (evita collisioni multipart)
            sentences = generate_static_voyage_report(stat_cfg)
            #for frag in sentences:
            #    print(f"[TYPE5 SEND] {self.name} virtual={self.virtuale} ghost={self.is_ghost} → {frag}")
            send_ais_multipart(sentences, is_virtual=self.virtuale, is_ghost=self.is_ghost)
            #print(f"[TYPE5 SENT] {self.name} ({len(sentences)} frammenti bundled)")

        except Exception as e:
            print(f"[TYPE5 ERROR] {self.name}: {e}")


    
    def compute_eta(self, current_time, sim_speed_factor=1.0):
        """
        Calcola l'ETA assoluta (datetime) basandosi su:
        - posizione attuale nave
        - waypoint corrente + successivi
        - sola velocità effettiva attuale della nave
        
        sim_speed_factor: se >1, la simulazione è accelerata, quindi l'ETA
        nel tempo reale dell'utente sarà più vicina.
        """
        # Se non ci sono WP o li hai finiti
        if not self.waypoints or self.current_waypoint_index >= len(self.waypoints):
            return current_time  # niente da stimare, pirla

        # Usa SOLO la velocità effettiva attuale della nave
        current_speed = max(0.1, self.speed_eff)

        # ---- accumula ETA ----
        eta_seconds = 0.0

        # posizione iniziale del segmento
        x0, y0 = self.x, self.y

        # ciclo sui WP residui
        for wp in self.waypoints[self.current_waypoint_index:]:

            # distanza segmento
            dx = wp.x - x0
            dy = wp.y - y0
            dist = (dx*dx + dy*dy) ** 0.5

            eta_seconds += dist / current_speed

            # punto finale del segmento diventa l'inizio del prossimo
            x0, y0 = wp.x, wp.y

        # Dividi per sim_speed_factor per ottenere ETA in tempo reale utente
        eta_seconds_real = eta_seconds / sim_speed_factor
        
        # restituisci datetime assoluto
        return current_time + timedelta(seconds=eta_seconds_real)

