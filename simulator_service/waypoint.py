import enum

# --- Enums ---
class WaypointType(enum.Enum):
    """
    Defines the types of waypoints a vessel can navigate to.
    - WALKTHROUGH: The vessel passes through this waypoint without stopping.
    - STOP: The vessel stops at this waypoint for a specified duration.
    """
    WALKTHROUGH = "Walkthrough"
    STOP = "Stop"

# --- Waypoint Class ---
class Waypoint:
    """
    Represents a single navigation point for a vessel.
    """
    _id_counter = 0  # contatore di classe privato

    def __init__(self, x, y, waypoint_type=WaypointType.WALKTHROUGH, stop_duration=0,lat: float = None, lon: float = None, Pa = None, Vr = None):
        self.x = x # Simulation x position (meters)
        self.y = y # Simulation y position (meters)
        self.type = waypoint_type # Type of waypoint (WaypointType enum)
        self.stop_duration = stop_duration # Seconds to stop for (only for STOP type)
        self.Pa = Pa  # Angolo di prua suggerito
        self.Vr = Vr  # velocità di riferimento
        # Assegna un ID univoco incrementale
        self.id = Waypoint._id_counter
        Waypoint._id_counter += 1
        self.reached = False # Flag to indicate if this waypoint has been reached
        self.lat = lat
        self.lon = lon

    def to_dict(self) -> dict:
        data = {
            "id": self.id,
            "x": self.x,
            "y": self.y,
            "type": self.type.name,
            "duration": self.duration,
        }
        if self.lat is not None and self.lon is not None:
            data["lat"] = self.lat
            data["lon"] = self.lon
        return data

    @classmethod
    def from_dict(cls, data: dict):
        # estrae x,y o lat,lon
        lat = data.get("lat")
        lon = data.get("lon")
        if lat is not None and lon is not None:
            from constants import latlon_to_xy
            x, y = latlon_to_xy(lat, lon)
        else:
            x, y = data["x"], data["y"]
        w = cls(x, y, WaypointType[data["type"]], data.get("duration", 0.0), lat, lon, Pa=data.get("Pa"), Vr=data.get("Vr"))
        w.id = data["id"]
        return w