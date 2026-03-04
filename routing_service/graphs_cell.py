import os
import pickle
import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, Optional

# =========================
# CONFIG
# =========================

GRAPH_CACHE_DIR = "./graph_cache"
GRAPH_TTL_HOURS = 12

os.makedirs(GRAPH_CACHE_DIR, exist_ok=True)

# =========================
# UTILS
# =========================

def floor_time(dt: datetime, bucket_seconds: int) -> datetime:
    return datetime.fromtimestamp(
        int(dt.timestamp() // bucket_seconds) * bucket_seconds
    )

def _time_bucket(dt: datetime, bucket_seconds: int) -> int:
    return int(dt.timestamp() // bucket_seconds)

# =========================
# DATA STRUCTURE
# =========================

@dataclass
class CachedNAMOAGraph:
    grafo: dict
    cell_to_xy: dict
    currents: dict
    edge_data: dict
    bbox: dict
    time: datetime
    created_at: datetime
    dataset_hash: str
    vessel_signature: str
    fake_data: bool

# =========================
# IN-MEMORY CACHE
# =========================

_CACHE: Dict[str, CachedNAMOAGraph] = {}

# =========================
# INTERNAL UTILS
# =========================

def _make_key(
    dataset_hash: str,
    time: datetime,
    bbox: dict,
    vessel_signature: str,
    fake_data: bool,
    tollerance_seconds: int
) -> str:

    bucket = _time_bucket(time, tollerance_seconds)

    raw = (
        dataset_hash,
        bucket,
        bbox["minimum_latitude"],
        bbox["minimum_longitude"],
        bbox["maximum_latitude"],
        bbox["maximum_longitude"],
        vessel_signature,
        fake_data,
    )

    return hashlib.sha256(repr(raw).encode()).hexdigest()

def _path(key: str) -> str:
    return os.path.join(GRAPH_CACHE_DIR, f"namoa_{key}.pkl")

def _is_expired(g: CachedNAMOAGraph) -> bool:
    return datetime.utcnow() - g.created_at > timedelta(hours=GRAPH_TTL_HOURS)

# =========================
# PUBLIC API
# =========================

def load_cached_graphs_from_disk():
    count = 0
    for fname in os.listdir(GRAPH_CACHE_DIR):
        if not fname.startswith("namoa_"):
            continue
        try:
            with open(os.path.join(GRAPH_CACHE_DIR, fname), "rb") as f:
                g: CachedNAMOAGraph = pickle.load(f)
            key = fname.replace("namoa_", "").replace(".pkl", "")
            _CACHE[key] = g
            count += 1
        except Exception as e:
            print("[CACHE LOAD ERROR]", fname, e)

    print(f"[CACHE] Loaded {count} graphs from disk")

def save_namoa_graph(
    *,
    grafo: dict,
    cell_to_xy: dict,
    currents: dict,
    edge_data: dict,
    time: datetime,
    bbox: dict,
    dataset_hash: str,
    vessel_signature: str,
    fake_data: bool,
    tollerance_seconds: int
) -> CachedNAMOAGraph:

    key = _make_key(
        dataset_hash=dataset_hash,
        time=time,
        bbox=bbox,
        vessel_signature=vessel_signature,
        fake_data=fake_data,
        tollerance_seconds=tollerance_seconds
    )

    g = CachedNAMOAGraph(
        grafo=grafo,
        cell_to_xy=cell_to_xy,
        currents=currents,
        edge_data=edge_data,
        bbox=bbox,
        time=time,
        created_at=datetime.utcnow(),
        dataset_hash=dataset_hash,
        vessel_signature=vessel_signature,
        fake_data=fake_data
    )

    _CACHE[key] = g

    with open(_path(key), "wb") as f:
        pickle.dump(g, f)

    print(f"[CACHE SAVE] key={key} time={time}")

    return g

def get_cached_namoa_graph(
    *,
    time: datetime,
    bbox: dict,
    dataset_hash: str,
    vessel_signature: str,
    fake_data: bool,
    tollerance_seconds: int
) -> Optional[CachedNAMOAGraph]:

    wanted_bucket = _time_bucket(time, tollerance_seconds)

    for g in _CACHE.values():
        if _is_expired(g):
            continue
        if g.dataset_hash != dataset_hash:
            continue
        if g.vessel_signature != vessel_signature:
            continue
        if g.fake_data != fake_data:
            continue
        if g.bbox != bbox:
            continue
        if _time_bucket(g.time, tollerance_seconds) != wanted_bucket:
            continue

        return g

    return None

def purge_expired_graphs():
    to_delete = []

    for key, g in _CACHE.items():
        if _is_expired(g):
            to_delete.append(key)

    for key in to_delete:
        _CACHE.pop(key, None)
        try:
            os.remove(_path(key))
        except Exception:
            pass

    if to_delete:
        print(f"[CACHE] Purged {len(to_delete)} expired graphs")
