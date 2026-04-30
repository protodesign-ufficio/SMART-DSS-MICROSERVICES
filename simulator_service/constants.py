import math

# --- Simulation Constants ---
SIM_TIME_STEP = 0.1 # Simulation time step in seconds
AIS_SEND_INTERVAL = 0.5  # Intervallo minimo (secondi simulati) tra messaggi AIS per nave
TRAJECTORY_LENGTH = 100 # Number of past points to store for trajectory

# --- Constants for Waypoints ---
WAYPOINT_REACHED_THRESHOLD = 50.0 # Distance (in simulation units) to consider a waypoint reached
STOP_WAYPOINT_STOPPING_DISTANCE = 500.0 # Distance (in simulation units) to start slowing down for a stop waypoint #modifica ste
WAYPOINT_INTERPOLATION_DISTANCE = 200.0 # Distance (in meters) between interpolated virtual waypoints

#mappa quadrata
MIN_LAT = 40.513
MAX_LAT = 40.737
MIN_LON = 14.227
MAX_LON = 14.523

# Coordinate dell’origin (es. centro mappa
ORIGIN_LAT = MIN_LAT    # gradi
ORIGIN_LON = MIN_LON     # gradi
EARTH_RADIUS = 6371000  # metri (raggio terrestre medio)
CURRENT_SCALE = 10

def latlon_to_xy(lat: float, lon: float) -> tuple[float, float]:
    """
    Converte latitudine e longitudine in coordinate cartesiane (metri)
    rispetto all’origin definito in ORIGIN_LAT, ORIGIN_LON.
    """
    # converti gradi in radianti
    lat_rad = math.radians(lat)
    lon_rad = math.radians(lon)
    ori_lat_rad = math.radians(ORIGIN_LAT)
    ori_lon_rad = math.radians(ORIGIN_LON)

    # delta
    dlat = lat_rad - ori_lat_rad
    dlon = lon_rad - ori_lon_rad

    # calcolo x,y
    x = EARTH_RADIUS * dlon * math.cos(ori_lat_rad)
    y = EARTH_RADIUS * dlat
    return x, y

def xy_to_latlon(x: float, y: float) -> tuple[float, float]:
    """
    Converte coordinate cartesiane (metri) in latitudine e longitudine
    rispetto all’origin definito in ORIGIN_LAT, ORIGIN_LON.
    """
    ori_lat_rad = math.radians(ORIGIN_LAT)
    ori_lon_rad = math.radians(ORIGIN_LON)

    lat_rad = y / EARTH_RADIUS + ori_lat_rad
    lon_rad = x / (EARTH_RADIUS * math.cos(ori_lat_rad)) + ori_lon_rad

    return math.degrees(lat_rad), math.degrees(lon_rad)
