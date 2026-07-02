"""Climate Engine API bağlantısı ve kullanıcı anahtarı doğrulaması."""

from __future__ import annotations

import os
import json
from typing import Any

import geopandas as gpd
import pandas as pd
import requests


BASE_URL = "https://api.climateengine.org"


def api_key_available(api_key: str | None = None) -> bool:
    return bool(api_key or os.getenv("CLIMATE_ENGINE_API_KEY"))


def connection_label(api_key: str | None = None) -> str:
    return "Bağlı" if api_key_available(api_key) else "API anahtarı bekleniyor"


def validate_api_key(api_key: str) -> dict[str, Any]:
    """Anahtarı Climate Engine'in resmi doğrulama uç noktasında sınar."""
    response = requests.get(
        f"{BASE_URL}/home/validate_key",
        headers={"Authorization": api_key.strip()},
        timeout=30,
    )
    if response.status_code in {401, 403}:
        raise ValueError("API anahtarı geçersiz veya bu işlem için yetkisiz.")
    response.raise_for_status()
    try:
        validation = response.json()
    except ValueError:
        validation = {"message": response.text.strip() or "Anahtar doğrulandı."}

    expiration_response = requests.get(
        f"{BASE_URL}/home/key_expiration",
        headers={"Authorization": api_key.strip()},
        timeout=30,
    )
    expiration = None
    if expiration_response.ok:
        try:
            expiration = expiration_response.json()
        except ValueError:
            expiration = expiration_response.text.strip()
    return {"validation": validation, "expiration": expiration}


def fetch_timeseries(
    api_key: str,
    gdf: gpd.GeoDataFrame,
    start_date,
    end_date,
    dataset: str,
    variables: str,
    area_reducer: str = "mean",
) -> tuple[pd.DataFrame, dict[str, Any]]:
    """Yüklenen alan için Climate Engine native zaman serisini getirir."""
    wgs84 = gdf.to_crs(4326)
    metric_crs = wgs84.estimate_utm_crs() or "EPSG:6933"
    simplified = (
        wgs84[["geometry"]]
        .dissolve()
        .to_crs(metric_crs)
        .simplify(100, preserve_topology=True)
        .to_crs(4326)
        .iloc[0]
    )
    coordinates = json.dumps(simplified.__geo_interface__["coordinates"])
    payload = {
        "coordinates": coordinates,
        "area_reducer": area_reducer,
        "dataset": dataset.strip(),
        "variable": variables.strip(),
        "start_date": str(start_date),
        "end_date": str(end_date),
    }
    response = requests.post(
        f"{BASE_URL}/timeseries/native/coordinates",
        headers={"Authorization": api_key.strip()},
        json=payload,
        timeout=300,
    )
    if response.status_code in {401, 403}:
        raise ValueError("Climate Engine anahtarı geçersiz, süresi dolmuş veya kotası yetersiz.")
    response.raise_for_status()
    body = response.json()
    series_groups = body.get("Data")
    if not series_groups:
        raise ValueError("Climate Engine seçilen alan ve dönem için veri döndürmedi.")
    first_group = series_groups[0] if isinstance(series_groups, list) else series_groups
    records = first_group.get("Data") if isinstance(first_group, dict) else first_group
    data = pd.DataFrame.from_dict(records)
    if data.empty:
        raise ValueError("Climate Engine yanıtındaki zaman serisi boş.")
    date_column = next(
        (column for column in data.columns if column.lower() in {"date", "tarih", "time"}),
        None,
    )
    if date_column:
        data = data.rename(columns={date_column: "Tarih"})
        data["Tarih"] = pd.to_datetime(data["Tarih"], errors="coerce")
    else:
        raise ValueError("Climate Engine yanıtında tarih alanı bulunamadı.")
    centroid = wgs84.dissolve().geometry.iloc[0].centroid
    data.insert(1, "Örnek ID", 1)
    data.insert(2, "Enlem", float(centroid.y))
    data.insert(3, "Boylam", float(centroid.x))
    if "precipitation" in data.columns:
        data = data.rename(columns={"precipitation": "Toplam yağış (mm)"})
    metadata = {
        "endpoint": f"{BASE_URL}/timeseries/native/coordinates",
        "dataset": dataset,
        "variables": variables,
        "area_reducer": area_reducer,
        "response_metadata": {
            key: value for key, value in body.items() if key != "Data"
        },
    }
    return data, metadata
