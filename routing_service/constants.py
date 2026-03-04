import math

# --- Constants ---
CUSTOM_CURRENT = None

CANVAS_SIZE_WIDTH = 600
CANVAS_SIZE_HEIGHT = 600
SIM_AREA_WIDTH = 1000.0 # Width of the simulation area in meters
SIM_AREA_HEIGHT = 1000.0 # Height of the simulation area in meters
SIM_TIME_STEP = 0.1 # Simulation time step in seconds
SIM_UPDATE_INTERVAL_MS = int(SIM_TIME_STEP * 1000/10) # Time in ms between canvas updates
TRAJECTORY_LENGTH = 100 # Number of past points to store for trajectory

# --- Constants for Grid and Scale ---
#GRID_SPACING = 1000.0 # Spacing between grid lines in simulation units (meters)
GRID_SPACING = 2000
SCALE_BAR_LENGTH_SIM = 50.0 # Length of the scale bar in simulation units (meters)
SCALE_BAR_LABEL = f"{int(SCALE_BAR_LENGTH_SIM)} meters" # Text label for the scale bar
SCALE_BAR_MARGIN = 20 # Margin from the bottom-left corner in pixels

# --- Constants for Waypoints ---
WAYPOINT_REACHED_THRESHOLD = 50.0 # Distance (in simulation units) to consider a waypoint reached
STOP_WAYPOINT_STOPPING_DISTANCE = 500.0 # Distance (in simulation units) to start slowing down for a stop waypoint #modifica ste
WAYPOINT_SIZE_PIXELS = 4 # Size of waypoint markers on the canvas

# --- Coordinate Mapping ---
# Maps simulation coordinates (x, y) to canvas coordinates (pixel_x, pixel_y)
# Assumes (0,0) simulation is bottom-left, (SIM_AREA_WIDTH, SIM_AREA_HEIGHT) is top-right
# Tkinter canvas (0,0) is top-left, y increases downwards
def sim_to_screen(x, y):
    """
    Converts simulation coordinates (meters) to screen coordinates (pixels).
    Assumes simulation (0,0) is bottom-left and canvas (0,0) is top-left.
    """
    screen_x = (x / SIM_AREA_WIDTH) * CANVAS_SIZE_WIDTH
    screen_y = CANVAS_SIZE_HEIGHT - (y / SIM_AREA_HEIGHT) * CANVAS_SIZE_HEIGHT
    return screen_x, screen_y

# Maps screen coordinates (pixel_x, pixel_y) to simulation coordinates (x, y)
def screen_to_sim(pixel_x, pixel_y):
    """
    Converts screen coordinates (pixels) to simulation coordinates (meters).
    """
    sim_x = (pixel_x / CANVAS_SIZE_WIDTH) * SIM_AREA_WIDTH
    sim_y = (CANVAS_SIZE_HEIGHT - pixel_y) / CANVAS_SIZE_HEIGHT * SIM_AREA_HEIGHT
    return sim_x, sim_y

# # — NUOVI LIMITI —
# MIN_LAT = 40.5    # latitudine minima consentita
# MAX_LAT = 40.75    # latitudine massima consentita
# MIN_LON = 14.25     # longitudine minima consentita
# MAX_LON = 14.5     # longitudine massima consentita

#mappa quadrata
MIN_LAT = 40.512314
MAX_LAT = 40.709292
MIN_LON = 14.200979
MAX_LON = 14.850346

# MIN_LAT = 39.5
# MAX_LAT = 41.5
# MIN_LON = 13.0
# MAX_LON = 15.8


# MIN_LAT = 39.727   # Sud
# MAX_LAT = 41.523   # Nord
# MIN_LON = 13.193   # Ovest
# MAX_LON = 15.557   # Est

# # — FINE LIMITI —
# # — LIMITI DI TEST RIDOTTI —
# MIN_LAT = 40.60
# MAX_LAT = 40.62
# MIN_LON = 14.30
# MAX_LON = 14.32


# Coordinate dell’origin (es. centro mappa)
ORIGIN_LAT = MIN_LAT    # gradi
ORIGIN_LON = MIN_LON     # gradi
EARTH_RADIUS = 6371000  # metri (raggio terrestre medio)

CURRENT_SCALE = 1.0
def latlon_to_xy(lat: float, lon: float, origin_lat: float = ORIGIN_LAT, origin_lon: float = ORIGIN_LON) -> tuple[float, float]:
    lat_rad = math.radians(lat)
    lon_rad = math.radians(lon)
    ori_lat_rad = math.radians(origin_lat)
    ori_lon_rad = math.radians(origin_lon)

    dlat = lat_rad - ori_lat_rad
    dlon = lon_rad - ori_lon_rad

    x = EARTH_RADIUS * dlon * math.cos(ori_lat_rad)
    y = EARTH_RADIUS * dlat
    return x, y


def xy_to_latlon(x: float, y: float, origin_lat: float = ORIGIN_LAT, origin_lon: float = ORIGIN_LON) -> tuple[float, float]:
    ori_lat_rad = math.radians(origin_lat)
    ori_lon_rad = math.radians(origin_lon)

    lat_rad = y / EARTH_RADIUS + ori_lat_rad
    lon_rad = x / (EARTH_RADIUS * math.cos(ori_lat_rad)) + ori_lon_rad

    return math.degrees(lat_rad), math.degrees(lon_rad)

# Calcolo delle estremità del bounding box in metri
SW_X, SW_Y = latlon_to_xy(MIN_LAT, MIN_LON)  # South-West
NE_X, NE_Y = latlon_to_xy(MAX_LAT, MAX_LON)  # North-East

# Larghezza e altezza in metri
MAP_WIDTH_METERS  = NE_X - SW_X
MAP_HEIGHT_METERS = NE_Y - SW_Y

SCALE_METERS_TO_PX = 0.02   # 1 m = 0.1 px, regola a piacere

#SCALE_METERS_TO_PX = 0.03   # 1 m = 0.1 px, regola a piacere
#SCALE_METERS_TO_PX = 0.3   # 1 m = 0.1 px, regola a piacere

def world_to_canvas(x: float, y: float,
                    sw_x: float = SW_X,
                    sw_y: float = SW_Y,
                    map_height_m: float = MAP_HEIGHT_METERS,
                    scale: float = SCALE_METERS_TO_PX
                   ) -> tuple[int,int]:
    rel_x = x - sw_x
    rel_y = y - sw_y
    px = int(rel_x * scale)
    py = int((map_height_m - rel_y) * scale)
    return px, py

# (opzionale) alias per mantenere compatibilità con sim_to_screen
sim_to_screen = world_to_canvas

