# ais_generator.py

import socket
import time
from dataclasses import dataclass
from typing import Union, List, Optional
from pyais.encode import encode_dict
import json 
import threading
import queue

# ——— UDP Config ———
UDP_IP = "127.0.0.1"
UDP_IP_Demo = "192.168.1.167"
UDP_PORT = 10110
_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
_sock.settimeout(0.05)  # 50ms timeout per evitare blocchi
TELEGRAF_UDP_IP = "87.26.178.190"
TELEGRAF_UDP_PORT = 15100
sock_telegraf = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock_telegraf.settimeout(0.1)  # 100ms timeout per Telegraf remoto

# Coda asincrona per invio AIS senza bloccare i thread di simulazione
_ais_queue = queue.Queue(maxsize=20000)

# Contatori diagnostici per monitorare perdite di messaggi
_ais_drop_count = 0
_ais_drop_lock = threading.Lock()
_ais_sent_count = 0

def get_ais_queue_stats():
    """Ritorna statistiche sulla coda AIS per diagnostica."""
    return {
        "queue_size": _ais_queue.qsize(),
        "queue_maxsize": _ais_queue.maxsize,
        "dropped": _ais_drop_count,
        "sent": _ais_sent_count,
    }

def _ais_sender_worker():
    """Thread background che consuma la coda e invia i messaggi AIS."""
    global _ais_sent_count
    _consecutive_errors = 0
    while True:
        try:
            sentence, is_virtual, is_ghost = _ais_queue.get(timeout=1.0)
        except queue.Empty:
            continue
        try:
            _do_send(sentence, is_virtual, is_ghost)
            _ais_sent_count += 1
            _consecutive_errors = 0
        except Exception as e:
            _consecutive_errors += 1
            if _consecutive_errors <= 3 or _consecutive_errors % 100 == 0:
                print(f"[AIS WORKER ERROR #{_consecutive_errors}] {e}")
        finally:
            _ais_queue.task_done()

_ais_sender_thread = threading.Thread(target=_ais_sender_worker, daemon=True)
_ais_sender_thread.start()

# ——— Funzione di invio NMEA ———
def _do_send(sentence: str, is_virtual: bool, is_ghost: bool) -> None:
    """Invio effettivo (chiamato dal worker thread)."""
    # sentence può contenere più righe NMEA (multipart, separate da \n)
    lines = sentence.strip().split("\n")

    # 1. OpenCPN (Legacy) — invia ogni riga NMEA singolarmente (protocollo UDP)
    for line in lines:
        try:
            encoded = (line.strip() + "\r\n").encode('ascii')
            _sock.sendto(encoded, (UDP_IP, UDP_PORT))
            _sock.sendto(encoded, (UDP_IP_Demo, UDP_PORT))
        except socket.timeout:
            pass  # Non bloccare se OpenCPN non risponde
        except Exception:
            pass

    # 2. Telegraf (Nuova Integrazione) — invia come singolo messaggio
    try:
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
        #print(f"[AIS SENT -> {topic}] {lines[0][:30]}... ({len(lines)} part(s))")
    except socket.timeout:
        print(f"[AIS TIMEOUT] Telegraf non raggiungibile, messaggio scartato")
    except Exception as e:
        print(f"Telegraf Send Error: {e}")


def send_ais_sentence(sentence: str, is_virtual: bool = False, is_ghost: bool = False) -> None:
    """
    Accoda il messaggio AIS per invio asincrono.
    Non blocca mai il thread di simulazione.
    """
    global _ais_drop_count
    try:
        _ais_queue.put_nowait((sentence, is_virtual, is_ghost))
    except queue.Full:
        with _ais_drop_lock:
            _ais_drop_count += 1
            dc = _ais_drop_count
        if dc % 100 == 1:
            print(f"[AIS QUEUE FULL] Messaggio AIS scartato (totale drop: {dc}, qsize: {_ais_queue.maxsize})")


def send_ais_multipart(sentences: list, is_virtual: bool = False, is_ghost: bool = False) -> None:
    """
    Invia un messaggio AIS multipart (es. Type 5) come singolo messaggio Kafka.
    Tutti i frammenti NMEA vengono concatenati (\n) in un unico payload Telegraf/Kafka
    in modo che il consumer possa decodificarli insieme.
    L'invio UDP (OpenCPN) resta per-frammento (come da protocollo NMEA).
    """
    global _ais_drop_count
    if not sentences:
        return

    # Se single-part, usa il percorso normale
    if len(sentences) == 1:
        send_ais_sentence(sentences[0], is_virtual, is_ghost)
        return

    # Multipart: concatena per Telegraf/Kafka, invia singoli per UDP
    concatenated = "\n".join(s.strip() for s in sentences)
    try:
        _ais_queue.put_nowait((concatenated, is_virtual, is_ghost))
    except queue.Full:
        with _ais_drop_lock:
            _ais_drop_count += 1
            dc = _ais_drop_count
        if dc % 100 == 1:
            print(f"[AIS QUEUE FULL] Messaggio AIS multipart scartato (totale drop: {dc})")

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


# Contatore globale per ID sequenziale dei messaggi multipart NMEA
# Ruota tra 0-9 per evitare collisioni quando più vascelli inviano Type 5 contemporaneamente
_multipart_seq_id = 0
_multipart_seq_lock = threading.Lock()

def _next_multipart_seq_id() -> int:
    """Ritorna il prossimo ID sequenziale per messaggi multipart (0-9, thread-safe)."""
    global _multipart_seq_id
    with _multipart_seq_lock:
        seq = _multipart_seq_id
        _multipart_seq_id = (_multipart_seq_id + 1) % 10
    return seq


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

    # Usa ID sequenziale univoco per evitare collisioni multipart tra vascelli diversi
    seq_id = _next_multipart_seq_id()

    for idx, frag in enumerate(frags, start=1):
        body = f"{params.talker_id},{total},{idx},{seq_id},{params.radio_channel},{frag},{fill_bits if idx == total else 0}"
        cs = _nmea_checksum(body)
        sentence = f"!{body}*{cs}"
        sentences.append(sentence)

    return sentences