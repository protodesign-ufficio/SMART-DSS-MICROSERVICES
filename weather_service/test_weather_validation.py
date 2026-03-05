"""
Test di validazione: Weather Service API vs Copernicus diretto.

Confronta i dati ottenuti da due sorgenti LIVE:
  A) Fetch diretto Copernicus API (copernicusmarine.open_dataset)  — "verità"
  B) Weather service HTTP API (/internal/weather/layer)            — da validare

Per ogni timestamp genera:
  - Plot affiancati (Copernicus vs Weather Service) con stessa scala colori
  - Mappa differenza con RMSE e statistiche
  - Tabella riepilogativa a console

Uso:
  # Timestamp specifico (formato ISO)
  python test_weather_validation.py --timestamp 2026-03-05T12:00

  # Ora corrente (default)
  python test_weather_validation.py

  # URL custom del weather service
  python test_weather_validation.py --service-url http://localhost:8080

  # Bounds custom
  python test_weather_validation.py --north 41.0 --south 40.3 --east 15.0 --west 14.0

Requisiti:  pip install matplotlib numpy xarray copernicusmarine requests pandas
Env vars:   COPERNICUSMARINE_SERVICE_USERNAME, COPERNICUSMARINE_SERVICE_PASSWORD
"""

import argparse
import os
import sys
from datetime import datetime

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
import numpy as np
import pandas as pd

# ── Config di default (Golfo di Napoli) ─────────────────────────────
DEFAULT_BOUNDS = {"north": 40.76, "south": 40.50, "east": 14.90, "west": 14.30}
CURRENTS_DATASET = "cmems_mod_med_phy-cur_anfc_4.2km_PT15M-i"
WAVES_DATASET    = "cmems_mod_med_wav_anfc_4.2km_PT1H-i"
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "validation_plots")


# ═════════════════════════════════════════════════════════════════════
# Sorgente A: Copernicus API diretta
# ═════════════════════════════════════════════════════════════════════
def fetch_copernicus_direct(dataset_id, variables, timestamp_iso, bounds):
    """Apre il dataset Copernicus completo e ritaglia spazio/tempo."""
    import copernicusmarine

    username = os.getenv("COPERNICUSMARINE_SERVICE_USERNAME", "")
    password = os.getenv("COPERNICUSMARINE_SERVICE_PASSWORD", "")
    if not username or not password:
        print("  [ERRORE] Credenziali Copernicus non configurate")
        print("           Imposta COPERNICUSMARINE_SERVICE_USERNAME e COPERNICUSMARINE_SERVICE_PASSWORD")
        return None

    print(f"  [Copernicus] Fetch: {dataset_id}")
    print(f"               vars={variables}, time={timestamp_iso}")
    ds = copernicusmarine.open_dataset(
        dataset_id=dataset_id,
        username=username,
        password=password,
    )

    target = pd.to_datetime(timestamp_iso)
    ds_t = ds.sel(time=target, method="nearest")
    actual_time = str(np.datetime_as_string(ds_t.time.values, unit="m")) if "time" in ds_t.coords else "?"
    print(f"               Tempo effettivo selezionato: {actual_time}")

    lat_min, lat_max = min(bounds["south"], bounds["north"]), max(bounds["south"], bounds["north"])
    lon_min, lon_max = min(bounds["west"], bounds["east"]), max(bounds["west"], bounds["east"])

    lat_vals = ds_t.latitude.values
    if lat_vals[0] > lat_vals[-1]:
        ds_t = ds_t.sel(latitude=slice(lat_max, lat_min))
    else:
        ds_t = ds_t.sel(latitude=slice(lat_min, lat_max))
    ds_t = ds_t.sel(longitude=slice(lon_min, lon_max))

    ds_t = ds_t[variables]
    result = ds_t.load()
    ds.close()
    print(f"               Griglia: {dict(result.sizes)}")
    return result, actual_time


# ═════════════════════════════════════════════════════════════════════
# Sorgente B: Weather Service HTTP
# ═════════════════════════════════════════════════════════════════════
def fetch_weather_service(service_url, layer_type, timestamp_iso, bounds):
    """Chiama POST /internal/weather/layer."""
    import requests

    url = f"{service_url}/internal/weather/layer"
    payload = {
        "layer_type": layer_type,
        "bounds": bounds,
        "timestamp": timestamp_iso,
        "use_cache": False,
        "save_cache": False,
        "force_refresh": True,
    }
    print(f"  [WeatherSvc] POST {url}")
    print(f"               layer={layer_type}, time={timestamp_iso}")

    resp = requests.post(url, json=payload, timeout=180)
    resp.raise_for_status()
    data = resp.json()
    n_items = len(data.get("items", []))
    src = data.get("source", "?")
    svc_time = data.get("timestamp", "?")
    print(f"               Ricevuti {n_items} items, source={src}, timestamp={svc_time}")
    return data


def _items_to_grids(items, layer_type):
    """Converte lista items JSON in griglie 2D numpy."""
    if not items:
        return None
    lats = np.array([it["lat"] for it in items])
    lons = np.array([it["lon"] for it in items])
    ulat = np.sort(np.unique(lats))
    ulon = np.sort(np.unique(lons))

    def _make_grid(key):
        g = np.full((len(ulat), len(ulon)), np.nan)
        for it in items:
            i = np.searchsorted(ulat, it["lat"])
            j = np.searchsorted(ulon, it["lon"])
            if i < len(ulat) and j < len(ulon):
                g[i, j] = it.get(key, np.nan)
        return g

    if layer_type == "currents":
        return ulat, ulon, {"u": _make_grid("u"), "v": _make_grid("v")}
    else:
        return ulat, ulon, {
            "height": _make_grid("height"),
            "dir": _make_grid("dir"),
            "period": _make_grid("period"),
        }


def _extract_grid(ds, var_name):
    """Estrae lat, lon e valori 2D da xarray Dataset."""
    data = ds[var_name]
    while data.ndim > 2:
        data = data.isel({data.dims[0]: 0})
    lat_c = "latitude" if "latitude" in ds.coords else "lat"
    lon_c = "longitude" if "longitude" in ds.coords else "lon"
    return ds[lat_c].values, ds[lon_c].values, data.values


# ═════════════════════════════════════════════════════════════════════
# Interpolazione per confronto su stessa griglia
# ═════════════════════════════════════════════════════════════════════
def _interp_to_common_grid(lat_a, lon_a, grid_a, lat_b, lon_b, grid_b):
    """Interpola entrambe le griglie su una griglia comune (unione)."""
    from scipy.interpolate import RegularGridInterpolator

    common_lat = np.sort(np.unique(np.concatenate([lat_a, lat_b])))
    common_lon = np.sort(np.unique(np.concatenate([lon_a, lon_b])))

    def _interp(lat, lon, grid):
        # Assicurati che lat sia crescente
        if lat[0] > lat[-1]:
            lat = lat[::-1]
            grid = grid[::-1, :]
        interp = RegularGridInterpolator(
            (lat, lon), grid,
            method="linear", bounds_error=False, fill_value=np.nan,
        )
        clat2d, clon2d = np.meshgrid(common_lat, common_lon, indexing="ij")
        return interp((clat2d, clon2d))

    return common_lat, common_lon, _interp(lat_a, lon_a, grid_a), _interp(lat_b, lon_b, grid_b)


# ═════════════════════════════════════════════════════════════════════
# Plotting
# ═════════════════════════════════════════════════════════════════════
def _add_stats_box(ax, values, prefix=""):
    v = values[~np.isnan(values)]
    if len(v) == 0:
        return
    txt = f"{prefix}min={v.min():.5f}  max={v.max():.5f}\nmean={v.mean():.5f}  std={v.std():.5f}  N={len(v)}"
    ax.text(0.02, 0.02, txt, transform=ax.transAxes, fontsize=7,
            va="bottom", bbox=dict(boxstyle="round", fc="white", alpha=0.85))


def plot_currents(cop_ds, svc_data, timestamp, out_path, bounds):
    """Plot correnti: Copernicus vs Weather Service + differenza."""
    # Copernicus
    clat, clon, cu = _extract_grid(cop_ds, "uo")
    _, _, cv = _extract_grid(cop_ds, "vo")
    cmag = np.sqrt(cu**2 + cv**2)

    # Weather Service
    svc_result = _items_to_grids(svc_data.get("items", []), "currents")
    if not svc_result:
        print("  [WARN] Nessun item dal Weather Service per correnti")
        return
    slat, slon, sgrids = svc_result
    su, sv = sgrids["u"], sgrids["v"]
    smag = np.sqrt(su**2 + sv**2)

    # Range comune
    all_vals = np.concatenate([cmag[~np.isnan(cmag)], smag[~np.isnan(smag)]])
    norm = mcolors.Normalize(vmin=all_vals.min(), vmax=all_vals.max())

    fig, axes = plt.subplots(1, 3, figsize=(22, 7))
    fig.suptitle(f"CORRENTI — {timestamp}\nCopernicus diretto vs Weather Service\n"
                 f"Bounds: {bounds}", fontsize=13, fontweight="bold")

    # Panel 1: Copernicus
    ax = axes[0]
    lon2d, lat2d = np.meshgrid(clon, clat)
    pcm = ax.pcolormesh(lon2d, lat2d, cmag, cmap="viridis", norm=norm, shading="auto", alpha=0.7)
    ax.quiver(lon2d, lat2d, cu, cv, color="black", scale=3, width=0.004, alpha=0.8)
    ax.set_title("A) Copernicus API diretta", fontsize=11)
    ax.set_xlabel("Lon"); ax.set_ylabel("Lat"); ax.set_aspect("equal")
    plt.colorbar(pcm, ax=ax, label="Velocità (m/s)", shrink=0.8)
    _add_stats_box(ax, cmag)

    # Panel 2: Weather Service
    ax = axes[1]
    lon2d, lat2d = np.meshgrid(slon, slat)
    pcm = ax.pcolormesh(lon2d, lat2d, smag, cmap="viridis", norm=norm, shading="auto", alpha=0.7)
    ax.quiver(lon2d, lat2d, su, sv, color="black", scale=3, width=0.004, alpha=0.8)
    ax.set_title("B) Weather Service API", fontsize=11)
    ax.set_xlabel("Lon"); ax.set_ylabel("Lat"); ax.set_aspect("equal")
    plt.colorbar(pcm, ax=ax, label="Velocità (m/s)", shrink=0.8)
    _add_stats_box(ax, smag)

    # Panel 3: Differenza (interpolata su griglia comune)
    ax = axes[2]
    try:
        ilat, ilon, icu, isu = _interp_to_common_grid(clat, clon, cu, slat, slon, su)
        _, _, icv, isv = _interp_to_common_grid(clat, clon, cv, slat, slon, sv)
        diff_mag = np.sqrt((icu - isu)**2 + (icv - isv)**2)
        lon2d, lat2d = np.meshgrid(ilon, ilat)
        max_d = np.nanmax(diff_mag)
        pcm = ax.pcolormesh(lon2d, lat2d, diff_mag, cmap="Reds", shading="auto",
                             vmin=0, vmax=max(max_d, 1e-6))
        plt.colorbar(pcm, ax=ax, label="Δ velocità (m/s)", shrink=0.8)

        valid = diff_mag[~np.isnan(diff_mag)]
        if len(valid) > 0:
            rmse = np.sqrt(np.nanmean(diff_mag**2))
            stats = f"RMSE = {rmse:.6f} m/s\nmax Δ = {np.nanmax(diff_mag):.6f}\nmean Δ = {np.nanmean(diff_mag):.6f}"
            ax.text(0.02, 0.02, stats, transform=ax.transAxes, fontsize=9,
                    va="bottom", bbox=dict(boxstyle="round", fc="white", alpha=0.9))
    except Exception as e:
        ax.text(0.5, 0.5, f"Errore interpolazione:\n{e}", transform=ax.transAxes, ha="center", va="center")

    ax.set_title("C) Differenza |A − B|", fontsize=11)
    ax.set_xlabel("Lon"); ax.set_ylabel("Lat"); ax.set_aspect("equal")

    fig.tight_layout()
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  Salvato: {out_path}")


def plot_waves(cop_ds, svc_data, timestamp, out_path, bounds):
    """Plot onde: Copernicus vs Weather Service per altezza, direzione, periodo."""
    clat, clon, ch = _extract_grid(cop_ds, "VHM0_WW")
    _, _, cd = _extract_grid(cop_ds, "VMDR_WW")
    _, _, cp = _extract_grid(cop_ds, "VTM01_WW")

    svc_result = _items_to_grids(svc_data.get("items", []), "waves")
    if not svc_result:
        print("  [WARN] Nessun item dal Weather Service per onde")
        return
    slat, slon, sgrids = svc_result
    sh, sd, sp = sgrids["height"], sgrids["dir"], sgrids["period"]

    vars_info = [
        ("Altezza onda (m)", "YlOrRd", ch, sh, "VHM0_WW"),
        ("Direzione onda (°)", "hsv", cd, sd, "VMDR_WW"),
        ("Periodo onda (s)", "cool", cp, sp, "VTM01_WW"),
    ]

    fig, axes = plt.subplots(3, 3, figsize=(22, 18))
    fig.suptitle(f"ONDE — {timestamp}\nCopernicus diretto vs Weather Service\n"
                 f"Bounds: {bounds}", fontsize=13, fontweight="bold", y=0.98)

    for row, (label, cmap, c_grid, s_grid, var_name) in enumerate(vars_info):
        all_v = np.concatenate([c_grid[~np.isnan(c_grid)].flatten(), s_grid[~np.isnan(s_grid)].flatten()])
        vmin = all_v.min() if len(all_v) > 0 else 0
        vmax = all_v.max() if len(all_v) > 0 else 1
        vmax = max(vmax, vmin + 1e-6)

        # Copernicus
        ax = axes[row, 0]
        lon2d, lat2d = np.meshgrid(clon, clat)
        pcm = ax.pcolormesh(lon2d, lat2d, c_grid, cmap=cmap, vmin=vmin, vmax=vmax, shading="auto")
        plt.colorbar(pcm, ax=ax, label=label, shrink=0.8)
        if row == 0: ax.set_title("A) Copernicus API diretta", fontsize=11)
        ax.set_ylabel(f"{label}\nLat", fontsize=9); ax.set_xlabel("Lon"); ax.set_aspect("equal")
        _add_stats_box(ax, c_grid)

        # Weather Service
        ax = axes[row, 1]
        lon2d, lat2d = np.meshgrid(slon, slat)
        pcm = ax.pcolormesh(lon2d, lat2d, s_grid, cmap=cmap, vmin=vmin, vmax=vmax, shading="auto")
        plt.colorbar(pcm, ax=ax, label=label, shrink=0.8)
        if row == 0: ax.set_title("B) Weather Service API", fontsize=11)
        ax.set_ylabel("Lat", fontsize=9); ax.set_xlabel("Lon"); ax.set_aspect("equal")
        _add_stats_box(ax, s_grid)

        # Differenza
        ax = axes[row, 2]
        try:
            ilat, ilon, ic, is_ = _interp_to_common_grid(clat, clon, c_grid, slat, slon, s_grid)
            diff = np.abs(ic - is_)
            lon2d, lat2d = np.meshgrid(ilon, ilat)
            max_d = np.nanmax(diff)
            pcm = ax.pcolormesh(lon2d, lat2d, diff, cmap="Reds", shading="auto",
                                 vmin=0, vmax=max(max_d, 1e-6))
            plt.colorbar(pcm, ax=ax, label=f"Δ {label}", shrink=0.8)
            valid = diff[~np.isnan(diff)]
            if len(valid) > 0:
                rmse = np.sqrt(np.nanmean(diff**2))
                ax.text(0.02, 0.02, f"RMSE={rmse:.6f}\nmax={np.nanmax(diff):.6f}\nmean={np.nanmean(diff):.6f}",
                        transform=ax.transAxes, fontsize=8, va="bottom",
                        bbox=dict(boxstyle="round", fc="white", alpha=0.9))
        except Exception as e:
            ax.text(0.5, 0.5, f"Errore:\n{e}", transform=ax.transAxes, ha="center", va="center")

        if row == 0: ax.set_title("C) Differenza |A − B|", fontsize=11)
        ax.set_ylabel("Lat", fontsize=9); ax.set_xlabel("Lon"); ax.set_aspect("equal")

    fig.tight_layout()
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  Salvato: {out_path}")


# ═════════════════════════════════════════════════════════════════════
# Tabella riepilogativa
# ═════════════════════════════════════════════════════════════════════
def print_comparison_table(cop_ds, svc_data, layer_type):
    if layer_type == "currents":
        cop_vars = [("uo", "u"), ("vo", "v")]
    else:
        cop_vars = [("VHM0_WW", "height"), ("VMDR_WW", "dir"), ("VTM01_WW", "period")]

    print(f"\n{'='*80}")
    print(f"  CONFRONTO {layer_type.upper()}: Copernicus vs Weather Service")
    print(f"{'='*80}")
    hdr = f"{'Variabile':<12} | {'Sorgente':<20} | {'Min':>10} | {'Max':>10} | {'Mean':>10} | {'Std':>10} | {'N':>5}"
    print(hdr)
    print("-" * len(hdr))

    items = svc_data.get("items", [])

    for cop_var, svc_key in cop_vars:
        # Copernicus
        vals_cop = cop_ds[cop_var].values.flatten()
        v = vals_cop[~np.isnan(vals_cop)]
        if len(v) > 0:
            print(f"{cop_var:<12} | {'Copernicus':<20} | {v.min():>10.5f} | {v.max():>10.5f} | {v.mean():>10.5f} | {v.std():>10.5f} | {len(v):>5}")

        # Weather Service
        vals_svc = np.array([it[svc_key] for it in items if svc_key in it])
        if len(vals_svc) > 0:
            print(f"{'':<12} | {'Weather Service':<20} | {vals_svc.min():>10.5f} | {vals_svc.max():>10.5f} | {vals_svc.mean():>10.5f} | {vals_svc.std():>10.5f} | {len(vals_svc):>5}")

        # Delta
        if len(v) > 0 and len(vals_svc) > 0:
            d_mean = abs(v.mean() - vals_svc.mean())
            d_max = abs(v.max() - vals_svc.max())
            status = "OK" if d_mean < 0.01 else "DIFF"
            print(f"{'':<12} | {'Δ mean/max':<20} | {'':>10} | {'':>10} | {d_mean:>10.5f} | {d_max:>10.5f} | {status:>5}")
        print()


# ═════════════════════════════════════════════════════════════════════
# Generazione mappa Leaflet interattiva
# ═════════════════════════════════════════════════════════════════════
def _cop_ds_to_items(ds, layer_type):
    """Converte un xarray Dataset Copernicus in lista items (stesso formato Weather Service)."""
    lat_c = "latitude" if "latitude" in ds.coords else "lat"
    lon_c = "longitude" if "longitude" in ds.coords else "lon"
    lats = ds[lat_c].values
    lons = ds[lon_c].values

    items = []
    if layer_type == "currents":
        u_data = ds["uo"].values
        v_data = ds["vo"].values
        while u_data.ndim > 2:
            u_data = u_data[0]
            v_data = v_data[0]
        for i, lat in enumerate(lats):
            for j, lon in enumerate(lons):
                u_val = float(u_data[i, j])
                v_val = float(v_data[i, j])
                if np.isnan(u_val) or np.isnan(v_val):
                    continue
                items.append({"lat": float(lat), "lon": float(lon), "u": u_val, "v": v_val})
    else:
        h_data = ds["VHM0_WW"].values
        d_data = ds["VMDR_WW"].values
        p_data = ds["VTM01_WW"].values
        while h_data.ndim > 2:
            h_data, d_data, p_data = h_data[0], d_data[0], p_data[0]
        for i, lat in enumerate(lats):
            for j, lon in enumerate(lons):
                h_val = float(h_data[i, j])
                d_val = float(d_data[i, j])
                p_val = float(p_data[i, j])
                if np.isnan(h_val) or np.isnan(d_val):
                    continue
                items.append({"lat": float(lat), "lon": float(lon),
                              "height": h_val, "dir": d_val, "period": p_val})
    return items


def generate_leaflet_html(
    cop_cur_items, svc_cur_items,
    cop_wav_items, svc_wav_items,
    timestamp, bounds, out_path,
):
    """Genera HTML self-contained con mappa Leaflet per confronto interattivo."""
    import json

    center_lat = (bounds["north"] + bounds["south"]) / 2
    center_lon = (bounds["east"] + bounds["west"]) / 2

    html = f"""<!DOCTYPE html>
<html lang="it">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Weather Validation — {timestamp}</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: 'Segoe UI', system-ui, sans-serif; background: #1a1a2e; color: #eee; }}
  .header {{ background: #16213e; padding: 12px 20px; display: flex; align-items: center; gap: 20px; flex-wrap: wrap; }}
  .header h1 {{ font-size: 16px; color: #4fc3f7; }}
  .header .info {{ font-size: 12px; color: #aaa; }}
  .controls {{ background: #0f3460; padding: 8px 20px; display: flex; gap: 16px; align-items: center; flex-wrap: wrap; }}
  .controls label {{ font-size: 13px; cursor: pointer; }}
  .controls input[type="checkbox"] {{ margin-right: 4px; }}
  .btn {{ padding: 4px 12px; border: 1px solid #4fc3f7; background: transparent; color: #4fc3f7;
          border-radius: 4px; cursor: pointer; font-size: 12px; }}
  .btn:hover {{ background: #4fc3f7; color: #000; }}
  .btn.active {{ background: #4fc3f7; color: #000; }}
  .map-container {{ display: flex; height: calc(100vh - 90px); }}
  .map-panel {{ flex: 1; position: relative; border-right: 2px solid #0f3460; }}
  .map-panel:last-child {{ border-right: none; }}
  .map-panel .map {{ width: 100%; height: 100%; }}
  .map-label {{ position: absolute; top: 8px; left: 50px; z-index: 1000; background: rgba(15,52,96,0.9);
                padding: 6px 14px; border-radius: 4px; font-size: 13px; font-weight: bold; pointer-events: none; }}
  .map-label.cop {{ color: #4fc3f7; border: 1px solid #4fc3f7; }}
  .map-label.svc {{ color: #f7c948; border: 1px solid #f7c948; }}
  .legend {{ position: absolute; bottom: 25px; right: 10px; z-index: 1000; background: rgba(0,0,0,0.8);
             padding: 8px 12px; border-radius: 6px; font-size: 11px; line-height: 1.6; }}
  .legend .grad {{ display: flex; align-items: center; gap: 6px; }}
  .legend .grad .bar {{ width: 80px; height: 12px; border-radius: 2px; }}
  .stats-box {{ position: absolute; bottom: 25px; left: 10px; z-index: 1000; background: rgba(0,0,0,0.85);
                padding: 8px 12px; border-radius: 6px; font-size: 11px; line-height: 1.5; max-width: 220px; }}
</style>
</head>
<body>

<div class="header">
  <h1>&#x1F30A; Weather Service Validation</h1>
  <span class="info">Timestamp: <b>{timestamp}</b> | Bounds: N={bounds['north']} S={bounds['south']} E={bounds['east']} W={bounds['west']}</span>
</div>

<div class="controls">
  <span style="font-size:13px;font-weight:bold;color:#4fc3f7">Layer:</span>
  <button class="btn active" onclick="showLayer('currents')">Correnti</button>
  <button class="btn" onclick="showLayer('waves')">Onde</button>
  <span style="margin-left:16px;font-size:13px;font-weight:bold;color:#4fc3f7">Mostra:</span>
  <label><input type="checkbox" id="chkArrows" checked onchange="redraw()"> Frecce vettoriali</label>
  <label><input type="checkbox" id="chkMag" checked onchange="redraw()"> Magnitudine/Altezza</label>
  <label><input type="checkbox" id="chkSync" checked> Sincronizza mappe</label>
</div>

<div class="map-container">
  <div class="map-panel">
    <div class="map-label cop">A) Copernicus diretto</div>
    <div id="map-cop" class="map"></div>
    <div id="stats-cop" class="stats-box"></div>
  </div>
  <div class="map-panel">
    <div class="map-label svc">B) Weather Service API</div>
    <div id="map-svc" class="map"></div>
    <div id="stats-svc" class="stats-box"></div>
  </div>
</div>

<script>
const DATA = {{
  currents: {{
    cop: {json.dumps(cop_cur_items)},
    svc: {json.dumps(svc_cur_items)}
  }},
  waves: {{
    cop: {json.dumps(cop_wav_items)},
    svc: {json.dumps(svc_wav_items)}
  }}
}};

let currentLayer = 'currents';
let mapCop, mapSvc;
let layersCop = [], layersSvc = [];
let syncing = false;

function initMaps() {{
  mapCop = L.map('map-cop', {{ zoomControl: true }}).setView([{center_lat}, {center_lon}], 11);
  mapSvc = L.map('map-svc', {{ zoomControl: true }}).setView([{center_lat}, {center_lon}], 11);

  const tiles = 'https://{{s}}.basemaps.cartocdn.com/dark_all/{{z}}/{{x}}/{{y}}{{r}}.png';
  const attr = '&copy; OpenStreetMap &copy; CARTO';
  L.tileLayer(tiles, {{ attribution: attr, maxZoom: 18 }}).addTo(mapCop);
  L.tileLayer(tiles, {{ attribution: attr, maxZoom: 18 }}).addTo(mapSvc);

  // Sync maps
  function syncMap(src, dst) {{
    if (syncing) return;
    if (!document.getElementById('chkSync').checked) return;
    syncing = true;
    dst.setView(src.getCenter(), src.getZoom(), {{ animate: false }});
    syncing = false;
  }}
  mapCop.on('move', () => syncMap(mapCop, mapSvc));
  mapSvc.on('move', () => syncMap(mapSvc, mapCop));

  redraw();
}}

function clearLayers() {{
  layersCop.forEach(l => mapCop.removeLayer(l));
  layersSvc.forEach(l => mapSvc.removeLayer(l));
  layersCop = [];
  layersSvc = [];
}}

function magColor(val, min, max) {{
  const t = max > min ? (val - min) / (max - min) : 0;
  const r = Math.round(34 + t * 221);
  const g = Math.round(139 + (1 - Math.abs(t - 0.5) * 2) * 116);
  const b = Math.round(230 - t * 180);
  return `rgb(${{r}},${{g}},${{b}})`;
}}

function waveColor(val, min, max) {{
  const t = max > min ? (val - min) / (max - min) : 0;
  const r = Math.round(255 * t);
  const g = Math.round(255 * (1 - t) * 0.8);
  const b = Math.round(50);
  return `rgb(${{r}},${{g}},${{b}})`;
}}

function computeStats(items, type) {{
  if (!items.length) return '';
  if (type === 'currents') {{
    const mags = items.map(it => Math.sqrt(it.u * it.u + it.v * it.v));
    const min = Math.min(...mags).toFixed(5);
    const max = Math.max(...mags).toFixed(5);
    const mean = (mags.reduce((a, b) => a + b, 0) / mags.length).toFixed(5);
    return `<b>Correnti</b><br>N=${{items.length}}<br>|V| min: ${{min}} m/s<br>|V| max: ${{max}} m/s<br>|V| mean: ${{mean}} m/s`;
  }} else {{
    const hs = items.map(it => it.height);
    const min = Math.min(...hs).toFixed(4);
    const max = Math.max(...hs).toFixed(4);
    const mean = (hs.reduce((a, b) => a + b, 0) / hs.length).toFixed(4);
    return `<b>Onde</b><br>N=${{items.length}}<br>H min: ${{min}} m<br>H max: ${{max}} m<br>H mean: ${{mean}} m`;
  }}
}}

function drawCurrents(map, items, layersArr) {{
  const showArrows = document.getElementById('chkArrows').checked;
  const showMag = document.getElementById('chkMag').checked;
  const mags = items.map(it => Math.sqrt(it.u * it.u + it.v * it.v));
  const magMin = Math.min(...mags);
  const magMax = Math.max(...mags);

  items.forEach((it, idx) => {{
    const mag = mags[idx];

    if (showMag) {{
      const c = L.circleMarker([it.lat, it.lon], {{
        radius: 6, fillColor: magColor(mag, magMin, magMax),
        fillOpacity: 0.7, stroke: false
      }}).addTo(map);
      c.bindPopup(`<b>Corrente</b><br>lat: ${{it.lat.toFixed(4)}}<br>lon: ${{it.lon.toFixed(4)}}<br>u: ${{it.u.toFixed(5)}} m/s<br>v: ${{it.v.toFixed(5)}} m/s<br>|V|: ${{mag.toFixed(5)}} m/s`);
      layersArr.push(c);
    }}

    if (showArrows && mag > 1e-6) {{
      const scale = 0.03;
      const dlat = it.v * scale / mag * Math.min(mag * 8, 0.4);
      const dlon = it.u * scale / mag * Math.min(mag * 8, 0.4);
      const endLat = it.lat + dlat;
      const endLon = it.lon + dlon;
      const line = L.polyline([[it.lat, it.lon], [endLat, endLon]], {{
        color: '#fff', weight: 1.5, opacity: 0.8
      }}).addTo(map);
      layersArr.push(line);

      // Arrowhead
      const angle = Math.atan2(dlat, dlon);
      const headLen = 0.008;
      const a1Lat = endLat - headLen * Math.sin(angle - 0.5);
      const a1Lon = endLon - headLen * Math.cos(angle - 0.5);
      const a2Lat = endLat - headLen * Math.sin(angle + 0.5);
      const a2Lon = endLon - headLen * Math.cos(angle + 0.5);
      const head = L.polyline([[a1Lat, a1Lon], [endLat, endLon], [a2Lat, a2Lon]], {{
        color: '#fff', weight: 1.5, opacity: 0.8
      }}).addTo(map);
      layersArr.push(head);
    }}
  }});
}}

function drawWaves(map, items, layersArr) {{
  const showArrows = document.getElementById('chkArrows').checked;
  const showMag = document.getElementById('chkMag').checked;
  const heights = items.map(it => it.height);
  const hMin = Math.min(...heights);
  const hMax = Math.max(...heights);

  items.forEach((it, idx) => {{
    if (showMag) {{
      const r = 4 + (hMax > hMin ? ((it.height - hMin) / (hMax - hMin)) * 8 : 4);
      const c = L.circleMarker([it.lat, it.lon], {{
        radius: r, fillColor: waveColor(it.height, hMin, hMax),
        fillOpacity: 0.7, stroke: true, color: '#fff', weight: 0.5
      }}).addTo(map);
      c.bindPopup(`<b>Onda</b><br>lat: ${{it.lat.toFixed(4)}}<br>lon: ${{it.lon.toFixed(4)}}<br>Altezza: ${{it.height.toFixed(4)}} m<br>Dir: ${{it.dir.toFixed(1)}}°<br>Periodo: ${{it.period.toFixed(3)}} s`);
      layersArr.push(c);
    }}

    if (showArrows) {{
      // Arrow direction from meteorological convention (dir = from)
      const rad = (270 - it.dir) * Math.PI / 180;
      const len = 0.015 + (hMax > hMin ? ((it.height - hMin) / (hMax - hMin)) * 0.02 : 0.01);
      const dlat = Math.sin(rad) * len;
      const dlon = Math.cos(rad) * len;
      const endLat = it.lat + dlat;
      const endLon = it.lon + dlon;
      const line = L.polyline([[it.lat, it.lon], [endLat, endLon]], {{
        color: '#f7c948', weight: 1.5, opacity: 0.8
      }}).addTo(map);
      layersArr.push(line);

      const angle = Math.atan2(dlat, dlon);
      const hl = 0.006;
      const a1 = [endLat - hl * Math.sin(angle - 0.5), endLon - hl * Math.cos(angle - 0.5)];
      const a2 = [endLat - hl * Math.sin(angle + 0.5), endLon - hl * Math.cos(angle + 0.5)];
      const head = L.polyline([a1, [endLat, endLon], a2], {{
        color: '#f7c948', weight: 1.5, opacity: 0.8
      }}).addTo(map);
      layersArr.push(head);
    }}
  }});
}}

function redraw() {{
  clearLayers();
  const copItems = DATA[currentLayer].cop;
  const svcItems = DATA[currentLayer].svc;

  if (currentLayer === 'currents') {{
    drawCurrents(mapCop, copItems, layersCop);
    drawCurrents(mapSvc, svcItems, layersSvc);
  }} else {{
    drawWaves(mapCop, copItems, layersCop);
    drawWaves(mapSvc, svcItems, layersSvc);
  }}

  document.getElementById('stats-cop').innerHTML = computeStats(copItems, currentLayer);
  document.getElementById('stats-svc').innerHTML = computeStats(svcItems, currentLayer);
}}

function showLayer(type) {{
  currentLayer = type;
  document.querySelectorAll('.controls .btn').forEach(b => b.classList.remove('active'));
  event.target.classList.add('active');
  redraw();
}}

document.addEventListener('DOMContentLoaded', initMaps);
</script>
</body>
</html>"""

    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"  Salvato mappa Leaflet: {out_path}")


# ═════════════════════════════════════════════════════════════════════
# Main
# ═════════════════════════════════════════════════════════════════════
def main():
    parser = argparse.ArgumentParser(
        description="Confronto Weather Service API vs Copernicus diretto",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Esempio:\n"
            "  python test_weather_validation.py --timestamp 2026-03-05T12:00\n"
            "  python test_weather_validation.py --service-url http://localhost:8080\n"
        ),
    )
    parser.add_argument("--service-url", default="http://localhost:8090",
                        help="URL del weather service (default: http://localhost:8090)")
    parser.add_argument("--timestamp", default=None,
                        help="Timestamp ISO-8601 (es. 2026-03-05T12:00). Default: ora corrente.")
    parser.add_argument("--north", type=float, default=DEFAULT_BOUNDS["north"])
    parser.add_argument("--south", type=float, default=DEFAULT_BOUNDS["south"])
    parser.add_argument("--east", type=float, default=DEFAULT_BOUNDS["east"])
    parser.add_argument("--west", type=float, default=DEFAULT_BOUNDS["west"])
    args = parser.parse_args()

    bounds = {"north": args.north, "south": args.south, "east": args.east, "west": args.west}
    ts = args.timestamp or datetime.now().strftime("%Y-%m-%dT%H:%M")
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    ts_safe = ts.replace(":", "").replace("-", "")

    print("=" * 80)
    print("  WEATHER SERVICE vs COPERNICUS — VALIDAZIONE LIVE")
    print("=" * 80)
    print(f"  Timestamp:      {ts}")
    print(f"  Bounds:         N={bounds['north']} S={bounds['south']} E={bounds['east']} W={bounds['west']}")
    print(f"  Weather Svc:    {args.service_url}")
    print(f"  Output:         {os.path.abspath(OUTPUT_DIR)}")
    print()

    # ── CORRENTI ─────────────────────────────────────────────────
    print(f"\n{'#'*80}")
    print(f"  CORRENTI")
    print(f"{'#'*80}")

    cop_cur = None
    svc_cur = None
    try:
        result = fetch_copernicus_direct(CURRENTS_DATASET, ["uo", "vo"], ts, bounds)
        if result:
            cop_cur, cop_cur_time = result
    except Exception as e:
        print(f"  [ERRORE] Copernicus correnti: {e}")

    try:
        svc_cur = fetch_weather_service(args.service_url, "currents", ts, bounds)
    except Exception as e:
        print(f"  [ERRORE] Weather Service correnti: {e}")

    if cop_cur is not None and svc_cur is not None:
        print_comparison_table(cop_cur, svc_cur, "currents")
        plot_currents(cop_cur, svc_cur, ts, os.path.join(OUTPUT_DIR, f"currents_{ts_safe}.png"), bounds)
    elif cop_cur is not None:
        print("  [WARN] Solo dati Copernicus disponibili (Weather Service non raggiungibile)")
    elif svc_cur is not None:
        print("  [WARN] Solo dati Weather Service disponibili (Copernicus fallito)")
    else:
        print("  [ERRORE] Nessun dato correnti ottenuto da nessuna sorgente!")

    # ── ONDE ─────────────────────────────────────────────────────
    print(f"\n{'#'*80}")
    print(f"  ONDE")
    print(f"{'#'*80}")

    cop_wav = None
    svc_wav = None
    try:
        result = fetch_copernicus_direct(WAVES_DATASET, ["VHM0_WW", "VMDR_WW", "VTM01_WW"], ts, bounds)
        if result:
            cop_wav, cop_wav_time = result
    except Exception as e:
        print(f"  [ERRORE] Copernicus onde: {e}")

    try:
        svc_wav = fetch_weather_service(args.service_url, "waves", ts, bounds)
    except Exception as e:
        print(f"  [ERRORE] Weather Service onde: {e}")

    if cop_wav is not None and svc_wav is not None:
        print_comparison_table(cop_wav, svc_wav, "waves")
        plot_waves(cop_wav, svc_wav, ts, os.path.join(OUTPUT_DIR, f"waves_{ts_safe}.png"), bounds)
    elif cop_wav is not None:
        print("  [WARN] Solo dati Copernicus disponibili (Weather Service non raggiungibile)")
    elif svc_wav is not None:
        print("  [WARN] Solo dati Weather Service disponibili (Copernicus fallito)")
    else:
        print("  [ERRORE] Nessun dato onde ottenuto da nessuna sorgente!")

    # ── MAPPA LEAFLET INTERATTIVA ────────────────────────────────
    print(f"\n{'#'*80}")
    print(f"  GENERAZIONE MAPPA LEAFLET")
    print(f"{'#'*80}")

    cop_cur_items = _cop_ds_to_items(cop_cur, "currents") if cop_cur is not None else []
    svc_cur_items = svc_cur.get("items", []) if svc_cur else []
    cop_wav_items = _cop_ds_to_items(cop_wav, "waves") if cop_wav is not None else []
    svc_wav_items = svc_wav.get("items", []) if svc_wav else []

    html_path = os.path.join(OUTPUT_DIR, f"leaflet_validation_{ts_safe}.html")
    generate_leaflet_html(
        cop_cur_items, svc_cur_items,
        cop_wav_items, svc_wav_items,
        ts, bounds, html_path,
    )

    if cop_cur is not None:
        cop_cur.close()
    if cop_wav is not None:
        cop_wav.close()

    print(f"\n{'='*80}")
    print(f"  COMPLETATO!")
    print(f"  Plot PNG:  {os.path.abspath(OUTPUT_DIR)}")
    print(f"  Mappa web: {os.path.abspath(html_path)}")
    print(f"{'='*80}")


if __name__ == "__main__":
    main()
