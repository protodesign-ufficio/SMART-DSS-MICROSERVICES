# ais_generator.py

import socket
import time
from dataclasses import dataclass
from typing import Union, List, Optional
from pyais.encode import encode_dict
import json 
import threading

# ——— UDP Config ———
UDP_IP = "127.0.0.1"
UDP_IP_Demo = "192.168.1.167"
UDP_PORT = 10110
_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
TELEGRAF_UDP_IP = "87.26.178.190"
TELEGRAF_UDP_PORT = 15100
sock_telegraf = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

# Lock per thread-safety nell'invio AIS
_ais_send_lock = threading.Lock()

# ——— Funzione di invio NMEA ———
def send_ais_sentence(sentence: str, is_virtual: bool = False, is_ghost: bool = False) -> None:
    """
    Invia NMEA:
    1. Raw a OpenCPN (come prima)
    2. JSON Envelope a Telegraf (per Kafka Dashboard)
    
    Args:
        sentence: la frase NMEA da inviare
        is_virtual: True per navi virtuali (topic ais_simulation.raw)
        is_ghost: True per navi ghost (topic ais_ghost.raw)
    """
    with _ais_send_lock:
        # 1. OpenCPN (Legacy)
        try:
            _sock.sendto((sentence + "\r\n").encode('ascii'), (UDP_IP, UDP_PORT))
            _sock.sendto((sentence + "\r\n").encode('ascii'), (UDP_IP_Demo, UDP_PORT))
        except: pass

        # 2. Telegraf (Nuova Integrazione)
        try:
            # Determina il topic in base ai flag passati come parametri
            if is_ghost:
                topic = "ais_ghost.raw"
            elif is_virtual:
                topic = "ais_simulation.raw"
            else:
                topic = "ais.raw"

            payload = {
                "kafka_topic": topic,
                "value": sentence.strip()
            }

            sock_telegraf.sendto(json.dumps(payload).encode('utf-8'), (TELEGRAF_UDP_IP, TELEGRAF_UDP_PORT))
            print(f"[AIS SENT -> {topic}] {sentence[:30]}...")
        except Exception as e:
            print(f"Telegraf Send Error: {e}")

# ——— “Struct” per i parametri ———
@dataclass
class PositionReportParams:
    mmsi: Union[int, str]
    latitude: float
    longitude: float
    speed: float = 0.0
    course: float = 360.0
    heading: int = 511
    # Usare preferibilmente `timestamp`, altrimenti `second` di default
    timestamp: Optional[int] = None
    second: int = 60
    talker_id: str = "AIVDM"
    radio_channel: str = "A"



# # ——— Funzioni di generazione ———
def generate_position_report(params: PositionReportParams) -> List[str]:
    """Genera i frammenti NMEA per un Position Report (Type 1)."""
    sec = params.timestamp if params.timestamp is not None else params.second
    data = {
        "type":    1,
        "mmsi":    params.mmsi,
        "lat":     params.latitude,
        "lon":     params.longitude,
        "speed":   params.speed,
        "course":  params.course,
        "heading": params.heading,
        "second":  sec
    }
    return encode_dict(data, talker_id=params.talker_id, radio_channel=params.radio_channel)


@dataclass
class StaticVoyageParams:
    mmsi: Union[int, str]
    callsign: str
    name: str
    ship_type: int
    to_bow: int
    to_stern: int
    to_port: int
    to_starboard: int
    eta_month: int
    eta_day: int
    eta_hour: int
    eta_minute: int
    draft: float
    destination: str
    talker_id: str = "AIVDM"
    radio_channel: str = "A"


# -------------------------
# Helper per encoding AIS
# -------------------------

AIS_CHARSET = "@ABCDEFGHIJKLMNOPQRSTUVWXYZ[\\]^_ !\"#$%&'()*+,-./0123456789:;<=>?"


def _text_to_sixbit(text: str, length: int) -> str:
    """
    Converte una stringa in una sequenza di bit (stringa di '0'/'1') secondo
    l'alfabeto AIS a 6 bit. Troncata/padded a 'length' caratteri.
    """
    text = (text or "").upper().ljust(length)[:length]
    bits = []
    for ch in text:
        idx = AIS_CHARSET.find(ch)
        if idx < 0:
            idx = AIS_CHARSET.find(" ")  # fallback: spazio
        bits.append(f"{idx:06b}")
    return "".join(bits)


def _nmea_checksum(body: str) -> str:
    """
    Calcola il checksum NMEA (XOR di tutti i caratteri della stringa 'body').
    """
    cs = 0
    for c in body:
        cs ^= ord(c)
    return f"{cs:02X}"


def _encode_payload_type5(p: StaticVoyageParams) -> tuple[str, int]:
    """
    Costruisce il payload AIS (prima di frammentarlo in AIVDM) per un messaggio
    di tipo 5 (Static & Voyage), come stringa di caratteri NMEA (armoring) +
    il numero di bit di fill usati.
    Ritorna: (payload_str, fill_bits)
    """
    # 1) Costruzione bitfield secondo ITU-R M.1371
    bits = ""

    def add(val: int, size: int):
        nonlocal bits
        bits += f"{val & ((1 << size) - 1):0{size}b}"

    # Message ID (6) + Repeat (2) + MMSI (30)
    add(5, 6)            # type 5
    add(0, 2)            # repeat = 0
    mmsi = int(p.mmsi)
    add(mmsi, 30)

    # AIS version (2) + IMO (30)
    add(0, 2)            # ais_version = 0
    add(0, 30)           # imo = 0 (unknown)

    # Callsign (7 char * 6 bit)
    bits += _text_to_sixbit(p.callsign, 7)

    # Name (20 char * 6 bit)
    bits += _text_to_sixbit(p.name, 20)

    # Ship type (8)
    add(p.ship_type, 8)

    # Dimension: to_bow(9) + to_stern(9) + to_port(6) + to_starboard(6)
    add(p.to_bow, 9)
    add(p.to_stern, 9)
    add(p.to_port, 6)
    add(p.to_starboard, 6)

    # EPFD type (4) - mettiamo 1 = GPS
    add(1, 4)

    # ETA: mese(4), giorno(5), ora(5), minuto(6)
    add(p.eta_month, 4)
    add(p.eta_day, 5)
    add(p.eta_hour, 5)
    add(p.eta_minute, 6)

    # Draught (8) in decimetri
    draught_dm = int(max(0, min(int(p.draft * 10), 255)))
    add(draught_dm, 8)

    # Destination (20 char * 6 bit)
    bits += _text_to_sixbit(p.destination, 20)

    # DTE (1) + spare (1)
    add(0, 1)  # DTE = 0 (data terminal available)
    add(0, 1)  # spare

    # 2) Padding a multiplo di 6 bit
    remainder = len(bits) % 6
    if remainder != 0:
        fill_bits = 6 - remainder
        bits += "0" * fill_bits
    else:
        fill_bits = 0

    # 3) Conversione in caratteri NMEA (armoring 6-bit)
    payload = []
    for i in range(0, len(bits), 6):
        v = int(bits[i:i+6], 2)
        c = v + 48
        if c > 87:
            c += 8
        payload.append(chr(c))

    return "".join(payload), fill_bits


def generate_static_voyage_report(params: StaticVoyageParams) -> List[str]:
    """
    Genera le frasi NMEA AIVDM per un messaggio AIS Type 5
    SENZA usare pyais (encoding manuale).
    Ritorna una lista di frasi complete "!AIVDM,...*CS".
    """
    payload, fill_bits = _encode_payload_type5(params)

    # Frammentazione: per sicurezza usiamo max 60 char per frammento
    max_len = 60
    frags = [payload[i:i+max_len] for i in range(0, len(payload), max_len)]
    total = len(frags)
    sentences = []

    for idx, frag in enumerate(frags, start=1):
        body = f"{params.talker_id},{total},{idx},0,{params.radio_channel},{frag},{fill_bits if idx == total else 0}"
        cs = _nmea_checksum(body)
        sentence = f"!{body}*{cs}"
        sentences.append(sentence)

    return sentences