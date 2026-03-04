#!/usr/bin/env python3
import os
import copernicusmarine as cm
import xarray as xr
from datetime import datetime

import os
import copernicusmarine as cm

def ensure_copernicus_login():
    """
    Esegue il login solo se il file credenziali non esiste.
    Evita qualsiasi prompt interattivo.
    """
    cred_path = os.path.expanduser("~/.copernicusmarine/.copernicusmarine-credentials")

    if not os.path.exists(cred_path):
        print("[Copernicus] Credenziali non trovate, eseguo login...")
        # cm.login()
        cm.login(username="sriccardi", password="Napoli1926")

    else:
        # credenziali già presenti → non fare nulla
        pass


def download_copernicus(dataset_id, variables, bbox, start, end, out_dir, out_file):
    # Setup
    ensure_copernicus_login()
    os.makedirs(out_dir, exist_ok=True)
    full_path = os.path.join(out_dir, out_file)
    
    # Definiamo una funzione per verificare se il file è valido
    def is_file_valid(path):
            if not os.path.exists(path):
                return False
            try:
                # Proviamo ad aprire e forziamo la lettura dei metadati
                with xr.open_dataset(path, engine="h5netcdf") as ds:
                    # Tenta di accedere a una variabile per essere sicuro che sia leggibile
                    # (senza caricare tutto in RAM)
                    test = ds.data_vars
                return True
            except Exception as e:
                # STAMPIAMO L'ERRORE REALE NEI LOG
                print(f"❌ DEBUG XARRAY FALLITO SU {path}")
                print(f"❌ TIPO ERRORE: {type(e)._name_}")
                print(f"❌ MESSAGGIO: {e}") 
                return False
    # Se il file esiste ma è corrotto, cancellalo subito
    if os.path.exists(full_path) and not is_file_valid(full_path):
        print(f"[Warning] File corrotto trovato: {out_file}. Rimozione e nuovo download...")
        os.remove(full_path)

    # Procedi al download se il file non esiste (o è stato appena cancellato)
    if not os.path.exists(full_path):
        print(f"[Info] Download in corso: {out_file}...")
        try:
            cm.subset(
                dataset_id=dataset_id,
                start_datetime=start,
                end_datetime=end,
                **bbox,
                output_directory=out_dir,
                output_filename=out_file,
                force_download=True
                #overwrite_output_data=True
            )
        except Exception as e:
            # Se il download fallisce, assicurati di non lasciare file parziali
            if os.path.exists(full_path):
                os.remove(full_path)
            raise e

    # Controllo finale post-download
    if not is_file_valid(full_path):
        # Se siamo qui, il download è apparentemente riuscito ma il file è rotto
        if os.path.exists(full_path):
            os.remove(full_path)
        raise Exception(f"Errore critico: Il file scaricato {out_file} risulta corrotto o illeggibile.")

    return full_path

def read_point(ds, target_time, target_lat, target_lon):
    # seleziona il punto più vicino in spazio/tempo
    sel = ds.sel(
        time=target_time,
        latitude=target_lat,
        longitude=target_lon,
        method="pad"
    )

    # estrai le variabili
    uo = sel["uo"].values.item()
    vo = sel["vo"].values.item()

    return uo, vo


def read_point_range(ds, target_time, min_lat, max_lat, min_lon, max_lon):
    """
    Estrae le correnti (uo, vo) per un intervallo di tempo e coordinate spaziali dal dataset.

    Args:
    - ds: il dataset xarray caricato.
    - start_time: la data di inizio dell'intervallo.
    - end_time: la data di fine dell'intervallo.
    - min_lat, max_lat: latitudine minima e massima.
    - min_lon, max_lon: longitudine minima e massima.

    Returns:
    - uo, vo: le velocità orizzontale e verticale delle correnti per l'intervallo.
    """
    # Seleziona l'intervallo di tempo e lo spazio (latitudine e longitudine)
    sel = ds.sel(
        time=target_time,  # Seleziona il range di tempo
        latitude=slice(min_lat, max_lat),  # Seleziona il range di latitudine
        longitude=slice(min_lon, max_lon),  # Seleziona il range di longitudine
    )

    # Estrai le correnti (uo e vo) su tutto l'intervallo
    uo = sel["uo"].values  # Estrai tutte le correnti orizzontali
    vo = sel["vo"].values  # Estrai tutte le correnti verticali

    # Estrai le coordinate di latitudine e longitudine
    latitudes = sel["latitude"].values
    longitudes = sel["longitude"].values

    # Ora, per ogni elemento di uo e vo, puoi associare una latitudine e longitudine
    # Creiamo una lista di tuple per ciascuna coordinata (lat, lon) corrispondente
    coordinates = []
    for i in range(uo.shape[0]):  # iterare sulle latitudini
        for j in range(uo.shape[1]):  # iterare sulle longitudini
            lat = latitudes[i]
            lon = longitudes[j]
            coordinates.append((lat, lon, uo[i, j], vo[i, j]))  # Aggiungi coordinate e valori di corrente


    return uo, vo, coordinates


def generate_fake_copernicus_dataset_km(bbox, resolution_km=2.5):
    """
    Crea un dataset xarray finto tipo Copernicus, ma con griglia regolare
    in metri, compatibile con il tuo latlon_to_xy / xy_to_latlon.

    resolution_km: passo griglia in km (es. 0.1 = 100 m)
    """
    import numpy as np
    import xarray as xr
    from datetime import datetime
    from constants import latlon_to_xy, xy_to_latlon

    # 1) bbox in world coordinates (metri)
    sw_x, sw_y = latlon_to_xy(bbox["minimum_latitude"], bbox["minimum_longitude"])
    ne_x, ne_y = latlon_to_xy(bbox["maximum_latitude"], bbox["maximum_longitude"])

    dx = resolution_km * 1000.0  # metri
    dy = resolution_km * 1000.0  # metri

    # 2) griglia in metri
    xs = np.arange(sw_x, ne_x, dx)
    ys = np.arange(sw_y, ne_y, dy)

    # 3) converti back a lat/lon (Mercatore inversa)
    #    lat dipende solo da y, lon solo da x nel tuo sistema
    lats = []
    for y in ys:
        lat, _ = xy_to_latlon(0.0, y)   # lon fittizia, non influenza lat
        lats.append(lat)
    lons = []
    for x in xs:
        _, lon = xy_to_latlon(x, 0.0)   # lat fittizia, non influenza lon
        lons.append(lon)

    lats = np.array(lats)
    lons = np.array(lons)

    # 4) dimensione tempo
    times = np.array([np.datetime64(datetime.utcnow())])

    nlat = len(lats)
    nlon = len(lons)

    # 5) campo di correnti sintetico (puoi cambiarlo)
    #    shape: (time, lat, lon)
    #    uso un pattern semplice e continuo
    Lon_grid, Lat_grid = np.meshgrid(lons, lats)
    #uo2d = 0.3 * np.sin(Lon_grid * np.pi / 180.0)   # componente est
    #vo2d = 0.3 * np.cos(Lat_grid * np.pi / 180.0)   # componente nord
    
    uo2d = np.full_like(Lon_grid, 0.3)
    vo2d = np.full_like(Lat_grid, 0.3)

    # uo2d = 0.3   # componente est
    # vo2d = 0.3   # componente nord
    uo = uo2d[np.newaxis, :, :]
    vo = vo2d[np.newaxis, :, :]

    ds = xr.Dataset(
        {
            "uo": (["time", "latitude", "longitude"], uo),
            "vo": (["time", "latitude", "longitude"], vo),
        },
        coords={
            "time": times,
            "latitude": lats,
            "longitude": lons,
        },
    )

    return ds

def debug_plot_currents(ds):
    """
    Plotta:
      - Heatmap uo
      - Heatmap vo
      - Campo vettoriale (quiver)
    Dataset: deve contenere latitude, longitude, uo, vo
    """
    import matplotlib.pyplot as plt
    import numpy as np

    # Prendo il primo time index
    uo = ds["uo"].values[0]  # shape: (nlat, nlon)
    vo = ds["vo"].values[0]  # shape: (nlat, nlon)
    lats = ds["latitude"].values
    lons = ds["longitude"].values

    Lon_grid, Lat_grid = np.meshgrid(lons, lats)

    # --- HEATMAP UO ---
    plt.figure(figsize=(12, 5))
    plt.subplot(1, 3, 1)
    plt.title("uo (eastward)")
    plt.xlabel("lon")
    plt.ylabel("lat")
    plt.pcolormesh(Lon_grid, Lat_grid, uo, cmap="coolwarm", shading="auto")
    plt.colorbar(label="uo")

    # --- HEATMAP VO ---
    plt.subplot(1, 3, 2)
    plt.title("vo (northward)")
    plt.xlabel("lon")
    plt.ylabel("lat")
    plt.pcolormesh(Lon_grid, Lat_grid, vo, cmap="coolwarm", shading="auto")
    plt.colorbar(label="vo")

    # --- QUIVER (campo vettoriale) ---
    plt.subplot(1, 3, 3)
    plt.title("Campo vettoriale uo/vo")
    plt.xlabel("lon")
    plt.ylabel("lat")
    skip = max(1, uo.shape[0] // 20)  # per non plottare troppi vettori
    plt.quiver(Lon_grid[::skip, ::skip], 
               Lat_grid[::skip, ::skip], 
               uo[::skip, ::skip], 
               vo[::skip, ::skip], 
               color="black", scale=2)

    plt.tight_layout()
    plt.show()
