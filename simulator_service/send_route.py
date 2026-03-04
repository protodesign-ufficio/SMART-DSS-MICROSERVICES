import socket
import time
import datetime
from pyais.encode import encode_dict

UDP_IP = "127.0.0.1"
UDP_PORT = 10110
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

# -------------------------------
# Funzione per invio NMEA
# -------------------------------
def send_nmea(sentence: str):
    sentence_no_cs = sentence.strip().lstrip('$')
    checksum = 0
    for c in sentence_no_cs:
        checksum ^= ord(c)
    full_sentence = f"${sentence_no_cs}*{checksum:02X}\r\n"
    sock.sendto(full_sentence.encode("ascii"), (UDP_IP, UDP_PORT))
    print("NMEA:", full_sentence.strip())

# -------------------------------
# Funzioni AIS
# -------------------------------
def send_ais(data: dict, talker="AIVDM", channel="A"):
    frags = encode_dict(data, talker_id=talker, radio_channel=channel)
    for frag in frags:
        sock.sendto((frag + "\r\n").encode("ascii"), (UDP_IP, UDP_PORT))
        print("AIS:", frag)

# -------------------------------
# Configurazione nave e rotta
# -------------------------------
MMSI = 111222333
SHIP_NAME = "TESTSHIP"
CALLSIGN = "CALL01"
ROUTE_NAME = "TESTROUTE"

waypoints = [
    ("WP1", 40.3500, 14.4300, "N", "E"),
    ("WP2", 40.3000, 14.3000, "N", "E"),
    ("WP3", 40.2500, 14.1000, "N", "E"),
]

# -------------------------------
# LOOP
# -------------------------------
lat, lon = 40.3500, 14.4300
course = 180.0
speed = 10.0

while True:
    now = datetime.datetime.utcnow()

    # --- AIS Static & Voyage Report (Type 5) ---
    static_data = {
        "type": 5,
        "mmsi": MMSI,
        "callsign": CALLSIGN,
        "name": SHIP_NAME,
        "ship_type": 70,
        "to_bow": 50, "to_stern": 20,
        "to_port": 10, "to_starboard": 10,
        "eta_month": now.month,
        "eta_day": now.day,
        "eta_hour": now.hour,
        "eta_minute": now.minute + 5,
        "draught": 60,
        "destination": "SALERNO",
    }
    send_ais(static_data)

    # --- AIS Position Report (Type 1) ---
    pos_data = {
        "type": 1,
        "mmsi": MMSI,
        "lat": lat,
        "lon": lon,
        "speed": speed,
        "course": course,
        "heading": int(course),
        "second": now.second,
    }
    send_ais(pos_data)

    # --- Waypoints GPWPL ---
    for name, wlat, wlon, ns, ew in waypoints:
        lat_deg = int(wlat)
        lat_min = (wlat - lat_deg) * 60
        lat_str = f"{lat_deg:02d}{lat_min:05.2f}"

        lon_deg = int(wlon)
        lon_min = (wlon - lon_deg) * 60
        lon_str = f"{lon_deg:03d}{lon_min:05.2f}"

        wpl = f"GPWPL,{lat_str},{ns},{lon_str},{ew},{name}"
        send_nmea(wpl)

    # --- Route GPRTE ---
    wp_names = ",".join(w[0] for w in waypoints)
    rte = f"GPRTE,1,1,c,{ROUTE_NAME},{wp_names}"
    send_nmea(rte)

    # Avanza un pochino la nave (solo per vedere che si muove)
    lon -= 0.01

    time.sleep(10)
