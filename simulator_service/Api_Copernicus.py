#!/usr/bin/env python3
import os
import copernicusmarine as cm
import xarray as xr
from datetime import datetime

def download_copernicus(dataset_id, variables, bbox, start, end, out_dir, out_file):
    # login (oppure imposta le variabili d’ambiente COPERNICUSMARINE_SERVICE_USERNAME/PASSWORD)
    #cm.login(username="sriccardi", password="Napoli1926", interactive=False)

    # creazione directory se non esiste
    os.makedirs(out_dir, exist_ok=True)

    # subset dei dati
    response = cm.subset(
        dataset_id=dataset_id,
        variables=variables,
        start_datetime=start,
        end_datetime=end,
        **bbox,
        output_directory=out_dir,
        output_filename=out_file
    )
    return response.file_path

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

import xarray as xr

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

def main():
    # Parametri di download
    dataset_id = "cmems_mod_glo_phy_anfc_0.083deg_PT1H-m"
    variables = ["uo", "vo", "zos", "thetao", "so"]
    bbox = {
        "minimum_longitude": 14.25,
        "maximum_longitude": 14.75,
        "minimum_latitude": 40.5,
        "maximum_latitude": 40.75,
        "minimum_depth": 0.0,
        "maximum_depth": 1.0,
    }
    start = "2025-07-03"
    end = "2025-07-03"
    out_dir = "./copernicus-data"
    out_file = "test.nc"

    # 1) scarica i dati
    nc_path = download_copernicus(dataset_id, variables, bbox, start, end, out_dir, out_file)
    print(f"File salvato in: {nc_path}")

    # 2) definisci punto e orario di interesse
    target_time = datetime(2023, 3, 31, 11)  # 2020-01-01 12:00 UTC
    target_lat = 14.498364092059573   # latitudine 40.51798643211838, 14.498364092059573
    target_lon = 40.51798643211838   # longitudine

    # 3) leggi i valori di uo, vo
    # 1) scarica i dati
    nc_path = download_copernicus(dataset_id, variables, bbox, start, end, out_dir, out_file)
    print(f"File salvato in: {nc_path}")

    # 2) apri il dataset
    ds = xr.open_dataset(nc_path)

    # 3) definisci punto e orario di interesse
    target_time = datetime(2023, 3, 31, 11)
    target_lat = 40.51798643211838
    target_lon = 14.498364092059573

    # 4) leggi i valori di uo, vo
    uo, vo = read_point(ds, target_time, target_lat, target_lon)
    print(f"Valori per il punto ({target_lat}N, {target_lon}E) alle {target_time}:")
    print(f"Eastward sea water velocity (uo): {uo:.3f} m/s")
    print(f"Northward sea water velocity (vo): {vo:.3f} m/s")

    print(f"Valori per il punto ({target_lat}N, {target_lon}E) alle {target_time}:")

if __name__ == "__main__":
    main()
