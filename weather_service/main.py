import os
import threading
import json
import hashlib
from datetime import datetime
from pathlib import Path

import copernicusmarine
import numpy as np
import pandas as pd
import xarray as xr
import psycopg2
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field

app = FastAPI(
    title="Weather Internal Service",
    version="0.1.0",
    description=(
        "Microservizio interno dedicato al recupero e alla cache dei dati "
        "meteo-oceanografici da Copernicus Marine Service (CMEMS). "
        "Fornisce dati di correnti e onde per la dashboard (layer) e subset "
        "NetCDF per l'ottimizzatore di rotta NAMOA*."
    ),
    contact={"name": "SMART-DSS Team"},
)

_USERNAME = os.getenv("COPERNICUSMARINE_SERVICE_USERNAME", "")
_PASSWORD = os.getenv("COPERNICUSMARINE_SERVICE_PASSWORD", "")
_DATA_DIR = os.getenv("WEATHER_DATA_DIR", "/app/copernicus-data")
_WEATHER_DB_CONN = os.getenv(
    "WEATHER_DB_CONN",
    "dbname=weather_db user=postgres password=admin host=host.docker.internal",
)
_LAYER_CACHE_TTL_MIN = int(os.getenv("WEATHER_LAYER_CACHE_TTL_MIN", "120"))

_login_lock = threading.Lock()
_logged_in = False


class Bounds(BaseModel):
    """Bounding-box geografico per il ritaglio dei dati meteo."""
    north: float | None = Field(None, description="Latitudine nord (gradi decimali, es. 40.80)")
    south: float | None = Field(None, description="Latitudine sud (gradi decimali, es. 40.50)")
    east: float | None = Field(None, description="Longitudine est (gradi decimali, es. 14.90)")
    west: float | None = Field(None, description="Longitudine ovest (gradi decimali, es. 14.30)")


class LayerRequest(BaseModel):
    """Richiesta di un layer meteo (correnti o onde) per la dashboard."""
    layer_type: str = Field(
        pattern="^(currents|waves)$",
        description="Tipo di layer meteo: 'currents' per correnti marine, 'waves' per moto ondoso.",
    )
    bounds: Bounds | None = Field(None, description="Area geografica di interesse. Se omesso usa il default Golfo di Napoli.")
    timestamp: str | None = Field(None, description="Timestamp ISO-8601 del dato richiesto (es. '2026-03-04T12:00'). Se omesso usa l'ora corrente.")
    use_cache: bool = Field(True, description="Se true, tenta di servire il dato dalla cache DB prima di interrogare Copernicus.")
    save_cache: bool = Field(True, description="Se true, salva il risultato in cache DB dopo il fetch da Copernicus.")
    force_refresh: bool = Field(False, description="Se true, ignora la cache e forza un nuovo fetch da Copernicus.")
    max_age_minutes: int | None = Field(None, description="TTL massimo della cache in minuti. Se omesso usa il default di sistema (env WEATHER_LAYER_CACHE_TTL_MIN).")


class SubsetRequest(BaseModel):
    """Richiesta di download di un subset NetCDF da Copernicus Marine Service."""
    dataset_id: str = Field(..., description="ID del dataset CMEMS (es. 'cmems_mod_med_wav_anfc_4.2km_PT1H-i').")
    variables: list[str] = Field(..., description="Lista di variabili da scaricare (es. ['uo', 'vo']).")
    bbox: dict[str, float] = Field(
        ...,
        description=(
            "Bounding-box per il subset. Chiavi richieste: "
            "minimum_latitude, maximum_latitude, minimum_longitude, maximum_longitude."
        ),
    )
    start: str = Field(..., description="Inizio finestra temporale ISO-8601 (es. '2026-03-04T00:00:00').")
    end: str = Field(..., description="Fine finestra temporale ISO-8601 (es. '2026-03-04T23:59:59').")
    out_file: str = Field(..., description="Nome del file di output NetCDF (deve terminare con .nc).")


def _get_db_connection():
    return psycopg2.connect(_WEATHER_DB_CONN)


def _ensure_schema() -> None:
    conn = _get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS weather_layer_cache (
                cache_key TEXT PRIMARY KEY,
                layer_type TEXT NOT NULL,
                request_timestamp TEXT NULL,
                effective_timestamp TEXT NULL,
                dataset_id TEXT NOT NULL,
                bounds_json JSONB NULL,
                payload_json JSONB NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_weather_layer_cache_lookup
            ON weather_layer_cache (layer_type, created_at DESC);
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS weather_subset_downloads (
                id BIGSERIAL PRIMARY KEY,
                request_key TEXT UNIQUE NOT NULL,
                dataset_id TEXT NOT NULL,
                start_time TEXT NOT NULL,
                end_time TEXT NOT NULL,
                variables_json JSONB NOT NULL,
                bbox_json JSONB NOT NULL,
                filename TEXT NOT NULL,
                file_path TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            );
            """
        )
        conn.commit()
    finally:
        cur.close()
        conn.close()


@app.on_event("startup")
def startup_init() -> None:
    _ensure_schema()


def _bounds_to_dict(bounds: Bounds | None) -> dict | None:
    if not bounds:
        return None
    return {
        "north": bounds.north,
        "south": bounds.south,
        "east": bounds.east,
        "west": bounds.west,
    }


def _cache_key_for_layer(req: LayerRequest) -> str:
    payload = {
        "layer_type": req.layer_type,
        "timestamp": req.timestamp,
        "bounds": _bounds_to_dict(req.bounds),
    }
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _subset_request_key(req: SubsetRequest, filename: str) -> str:
    payload = {
        "dataset_id": req.dataset_id,
        "variables": req.variables,
        "bbox": req.bbox,
        "start": req.start,
        "end": req.end,
        "filename": filename,
    }
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _get_cached_layer(cache_key: str, max_age_minutes: int):
    conn = _get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT payload_json
            FROM weather_layer_cache
            WHERE cache_key = %s
              AND created_at >= NOW() - (%s * INTERVAL '1 minute')
            ORDER BY created_at DESC
            LIMIT 1;
            """,
            (cache_key, max_age_minutes),
        )
        row = cur.fetchone()
        return row[0] if row else None
    finally:
        cur.close()
        conn.close()


def _upsert_layer_cache(
    cache_key: str,
    req: LayerRequest,
    dataset_id: str,
    effective_timestamp: str,
    payload: dict,
) -> None:
    conn = _get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            """
            INSERT INTO weather_layer_cache (
                cache_key,
                layer_type,
                request_timestamp,
                effective_timestamp,
                dataset_id,
                bounds_json,
                payload_json,
                created_at
            ) VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, NOW())
            ON CONFLICT (cache_key)
            DO UPDATE SET
                layer_type = EXCLUDED.layer_type,
                request_timestamp = EXCLUDED.request_timestamp,
                effective_timestamp = EXCLUDED.effective_timestamp,
                dataset_id = EXCLUDED.dataset_id,
                bounds_json = EXCLUDED.bounds_json,
                payload_json = EXCLUDED.payload_json,
                created_at = NOW();
            """,
            (
                cache_key,
                req.layer_type,
                req.timestamp,
                effective_timestamp,
                dataset_id,
                json.dumps(_bounds_to_dict(req.bounds)),
                json.dumps(payload),
            ),
        )
        conn.commit()
    finally:
        cur.close()
        conn.close()


def _upsert_subset_download(req: SubsetRequest, filename: str, path: str, status: str) -> None:
    request_key = _subset_request_key(req, filename)
    conn = _get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            """
            INSERT INTO weather_subset_downloads (
                request_key,
                dataset_id,
                start_time,
                end_time,
                variables_json,
                bbox_json,
                filename,
                file_path,
                status,
                created_at,
                updated_at
            ) VALUES (%s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s, %s, NOW(), NOW())
            ON CONFLICT (request_key)
            DO UPDATE SET
                file_path = EXCLUDED.file_path,
                status = EXCLUDED.status,
                updated_at = NOW();
            """,
            (
                request_key,
                req.dataset_id,
                req.start,
                req.end,
                json.dumps(req.variables),
                json.dumps(req.bbox),
                filename,
                path,
                status,
            ),
        )
        conn.commit()
    finally:
        cur.close()
        conn.close()


def _ensure_login() -> None:
    global _logged_in
    if _logged_in:
        return
    with _login_lock:
        if _logged_in:
            return
        if not _USERNAME or not _PASSWORD:
            raise HTTPException(status_code=500, detail="Copernicus credentials not configured")
        copernicusmarine.login(
            username=_USERNAME,
            password=_PASSWORD,
            force_overwrite=False,
        )
        _logged_in = True


def _sanitize_filename(name: str) -> str:
    candidate = Path(name).name
    if not candidate.endswith(".nc"):
        raise HTTPException(status_code=400, detail="out_file must end with .nc")
    return candidate


def _normalize_layer_bounds(bounds: Bounds | None, pad: float = 0.0) -> tuple[float, float, float, float]:
    if bounds:
        north = bounds.north if bounds.north is not None else 40.76
        south = bounds.south if bounds.south is not None else 40.50
        east = bounds.east if bounds.east is not None else 14.90
        west = bounds.west if bounds.west is not None else 14.30
    else:
        north, south, east, west = 40.76, 40.50, 14.90, 14.30

    lat_min = min(south, north) - pad
    lat_max = max(south, north) + pad
    lon_min = min(west, east) - pad
    lon_max = max(west, east) + pad
    return lat_min, lat_max, lon_min, lon_max


def _slice_for_coord(ds, coord_name: str, low: float, high: float):
    if coord_name not in ds.coords:
        return ds

    values = ds[coord_name].values
    if len(values) < 2:
        return ds.sel({coord_name: slice(low, high)})

    is_ascending = bool(values[0] <= values[-1])
    if is_ascending:
        return ds.sel({coord_name: slice(low, high)})
    return ds.sel({coord_name: slice(high, low)})


@app.get(
    "/health",
    tags=["Infrastruttura"],
    summary="Health check",
    description=(
        "Verifica lo stato del microservizio weather e la connettività al database weather_db. "
        "Restituisce lo stato del servizio e del database."
    ),
)
def health():
    try:
        conn = _get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT 1")
        cur.fetchone()
        cur.close()
        conn.close()
        db_status = "ok"
    except Exception:
        db_status = "error"
    return {"status": "ok", "service": "weather", "db": db_status}


@app.post(
    "/internal/weather/subset/download",
    tags=["Subset"],
    summary="Download subset NetCDF da Copernicus",
    description=(
        "Scarica un subset spazio-temporale di dati oceanografici dal Copernicus Marine Service "
        "in formato NetCDF. Se il file esiste già localmente e risulta valido, restituisce la versione "
        "in cache locale senza riscaricare. Il download viene registrato nella tabella "
        "weather_subset_downloads. Usato dall'ottimizzatore NAMOA* per i dati meteo di rotta."
    ),
)
def subset_download(req: SubsetRequest):
    """Esegue il download o restituisce il file cached per il subset richiesto."""
    _ensure_login()
    os.makedirs(_DATA_DIR, exist_ok=True)

    output_filename = _sanitize_filename(req.out_file)
    full_path = os.path.join(_DATA_DIR, output_filename)

    if os.path.exists(full_path):
        try:
            with xr.open_dataset(full_path, engine="h5netcdf") as ds:
                _ = list(ds.data_vars)
            _upsert_subset_download(req, output_filename, full_path, "cached")
            return {"status": "cached", "path": full_path, "filename": output_filename}
        except Exception:
            os.remove(full_path)

    try:
        copernicusmarine.subset(
            dataset_id=req.dataset_id,
            variables=req.variables,
            start_datetime=req.start,
            end_datetime=req.end,
            minimum_latitude=req.bbox["minimum_latitude"],
            maximum_latitude=req.bbox["maximum_latitude"],
            minimum_longitude=req.bbox["minimum_longitude"],
            maximum_longitude=req.bbox["maximum_longitude"],
            output_directory=_DATA_DIR,
            output_filename=output_filename,
            force_download=True,
        )
    except Exception as exc:
        if os.path.exists(full_path):
            os.remove(full_path)
        raise HTTPException(status_code=502, detail=f"Copernicus subset failed: {exc}") from exc

    try:
        with xr.open_dataset(full_path, engine="h5netcdf") as ds:
            _ = list(ds.data_vars)
    except Exception as exc:
        if os.path.exists(full_path):
            os.remove(full_path)
        raise HTTPException(status_code=500, detail=f"Downloaded file invalid: {exc}") from exc

    _upsert_subset_download(req, output_filename, full_path, "downloaded")
    return {"status": "downloaded", "path": full_path, "filename": output_filename}


@app.post(
    "/internal/weather/layer",
    tags=["Layer"],
    summary="Dati meteo layer per la dashboard",
    description=(
        "Restituisce i dati meteo (correnti o onde) formattati per la visualizzazione su mappa. "
        "Supporta cache DB con TTL configurabile: se use_cache=true e il dato è ancora valido, "
        "viene servito dalla cache; altrimenti interroga Copernicus Marine Service in tempo reale. "
        "Il campo 'source' nella risposta indica se il dato proviene da 'db_cache' o da 'copernicus'."
    ),
)
def get_layer_data(req: LayerRequest):
    """Recupera dati correnti/onde da cache o Copernicus e restituisce items geolocalizzati."""
    _ensure_login()

    ttl_minutes = req.max_age_minutes if req.max_age_minutes is not None else _LAYER_CACHE_TTL_MIN
    cache_key = _cache_key_for_layer(req)

    if req.use_cache and not req.force_refresh:
        cached_payload = _get_cached_layer(cache_key, ttl_minutes)
        if cached_payload:
            if isinstance(cached_payload, dict):
                cached_payload["source"] = "db_cache"
                cached_payload["cache_key"] = cache_key
            return cached_payload

    if req.layer_type == "currents":
        dataset_id = "cmems_mod_med_phy-cur_anfc_4.2km_PT15M-i"
        req_vars = ["uo", "vo"]
    else:
        dataset_id = "cmems_mod_med_wav_anfc_4.2km_PT1H-i"
        req_vars = ["VMDR_WW", "VTM01_WW", "VHM0_WW"]

    try:
        ds = copernicusmarine.open_dataset(
            dataset_id=dataset_id,
            username=_USERNAME,
            password=_PASSWORD,
        )

        target_time = pd.to_datetime(req.timestamp) if req.timestamp else datetime.now()
        try:
            ds_slice = ds.sel(time=target_time, method="nearest")
        except KeyError:
            ds_slice = ds.isel(time=-1)

        req_lat_min, req_lat_max, req_lon_min, req_lon_max = _normalize_layer_bounds(req.bounds, pad=0.0)
        lat_min, lat_max, lon_min, lon_max = _normalize_layer_bounds(req.bounds, pad=0.05)

        ds_slice = _slice_for_coord(ds_slice, "latitude", lat_min, lat_max)
        ds_slice = _slice_for_coord(ds_slice, "longitude", lon_min, lon_max)
        ds_slice = ds_slice.isel(
            latitude=slice(0, None, 1),
            longitude=slice(0, None, 1),
        )

        ds_slice = ds_slice[req_vars]
        df = ds_slice.to_dataframe().dropna().reset_index()

        dt_val = ds_slice.time.values if "time" in ds_slice.coords else None
        data_time = str(np.datetime_as_string(dt_val, unit="m")) if dt_val is not None else "?"

        lat_col = "latitude" if "latitude" in df.columns else "lat"
        lon_col = "longitude" if "longitude" in df.columns else "lon"
        df = df[
            (df[lat_col] >= req_lat_min)
            & (df[lat_col] <= req_lat_max)
            & (df[lon_col] >= req_lon_min)
            & (df[lon_col] <= req_lon_max)
        ]

        val_min, val_max = 0.0, 1.0
        if req.layer_type == "currents":
            mags = np.sqrt(df["uo"] ** 2 + df["vo"] ** 2)
            if not mags.empty:
                val_min = float(mags.min())
                val_max = float(mags.max())
        else:
            if "VHM0_WW" in df.columns and not df.empty:
                val_min = float(df["VHM0_WW"].min())
                val_max = float(df["VHM0_WW"].max())

        def _row_val(row, keys: list[str]) -> float:
            for key in keys:
                if hasattr(row, key):
                    return float(getattr(row, key))
            return 0.0

        items = []
        if req.layer_type == "currents":
            for row in df.itertuples():
                items.append(
                    {
                        "lat": _row_val(row, ["lat", "latitude"]),
                        "lon": _row_val(row, ["lon", "longitude"]),
                        "u": float(row.uo),
                        "v": float(row.vo),
                    }
                )
        else:
            for row in df.itertuples():
                if hasattr(row, "VMDR_WW") and hasattr(row, "VHM0_WW") and hasattr(row, "VTM01_WW"):
                    items.append(
                        {
                            "lat": _row_val(row, ["lat", "latitude"]),
                            "lon": _row_val(row, ["lon", "longitude"]),
                            "dir": float(row.VMDR_WW),
                            "height": float(row.VHM0_WW),
                            "period": float(row.VTM01_WW),
                        }
                    )

        ds.close()
        payload = {
            "timestamp": data_time.replace("T", " "),
            "dataset": dataset_id,
            "items": items,
            "range": {"min": val_min, "max": val_max},
        }
        if req.save_cache:
            _upsert_layer_cache(
                cache_key=cache_key,
                req=req,
                dataset_id=dataset_id,
                effective_timestamp=payload["timestamp"],
                payload=payload,
            )
        payload["source"] = "copernicus"
        payload["cache_key"] = cache_key
        return payload
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Weather fetch failed: {exc}") from exc


@app.get(
    "/internal/weather/cache/layer",
    tags=["Cache"],
    summary="Lista entry cache layer",
    description=(
        "Restituisce l'elenco delle entry salvate nella cache dei layer meteo, "
        "ordinate per data di creazione decrescente. Filtrabile per tipo di layer."
    ),
)
def list_cached_layers(
    layer_type: str | None = Query(
        default=None,
        pattern="^(currents|waves)$",
        description="Filtra per tipo di layer: 'currents' o 'waves'. Se omesso mostra entrambi.",
    ),
    limit: int = Query(
        default=20,
        ge=1,
        le=200,
        description="Numero massimo di entry da restituire (1-200, default 20).",
    ),
):
    conn = _get_db_connection()
    cur = conn.cursor()
    try:
        if layer_type:
            cur.execute(
                """
                SELECT cache_key, layer_type, request_timestamp, effective_timestamp, dataset_id, created_at
                FROM weather_layer_cache
                WHERE layer_type = %s
                ORDER BY created_at DESC
                LIMIT %s;
                """,
                (layer_type, limit),
            )
        else:
            cur.execute(
                """
                SELECT cache_key, layer_type, request_timestamp, effective_timestamp, dataset_id, created_at
                FROM weather_layer_cache
                ORDER BY created_at DESC
                LIMIT %s;
                """,
                (limit,),
            )
        rows = cur.fetchall()
        return {
            "items": [
                {
                    "cache_key": row[0],
                    "layer_type": row[1],
                    "request_timestamp": row[2],
                    "effective_timestamp": row[3],
                    "dataset": row[4],
                    "created_at": row[5].isoformat() if row[5] else None,
                }
                for row in rows
            ]
        }
    finally:
        cur.close()
        conn.close()


@app.get(
    "/internal/weather/cache/layer/{cache_key}",
    tags=["Cache"],
    summary="Dettaglio payload cache layer",
    description=(
        "Recupera il payload completo (items, range, timestamp) di un layer meteo "
        "precedentemente salvato in cache, identificato dalla sua cache_key SHA-256."
    ),
)
def get_cached_layer_payload(cache_key: str):
    conn = _get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute(
            """
            SELECT payload_json, created_at
            FROM weather_layer_cache
            WHERE cache_key = %s
            LIMIT 1;
            """,
            (cache_key,),
        )
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Cache key not found")
        payload = row[0] if isinstance(row[0], dict) else {}
        payload["source"] = "db_cache"
        payload["cache_key"] = cache_key
        payload["cached_at"] = row[1].isoformat() if row[1] else None
        return payload
    finally:
        cur.close()
        conn.close()
