# Reproducible data pipeline

From public sources to the aligned 30 m analysis grid. All commands are versioned scripts;
running them twice yields the same datasets.

## 0. Region of interest

Pick or draw an AOI in WGS84 (GeoJSON). Two examples ship in `example/aoi/`:

| File | Meaning | Area |
|---|---|---|
| `aoi-pingshuo-full.geojson` | Pingshuo working box (Shanxi) | 413 km² |
| `aoi-heidaigou.geojson` | Heidaigou working box (Inner Mongolia) | 417 km² |
| `mine-pingshuo-full.geojson` / `mine-heidaigou.geojson` | mining disturbance outlines (from mine-point priors + disturbance connectivity) | — |
| `aoi-pingshuo-mine-boundary.geojson` | smoothed actual mining boundary (Pingshuo) | ~112 km² |

## 1. Land cover + DEM

```bash
python tools/download_area_data.py \
    --aoi example/aoi/aoi-pingshuo-full.geojson \
    --years 2000 2005 2010 2015 2020 \
    --clcd-out backend/data/clcd --dem-out backend/data/dem
```

- CLCD is fetched as cloud-optimized GeoTIFF, windowed to the AOI only.
- Downloads are failure-isolated (a blocked source never blocks the others), resumable,
  and honor system proxies.

## 2. Spectral indices (Google Earth Engine)

Open `example/gee/gee_export_indices_pingshuo-full.js` (and the heidaigou variant) in the
[Earth Engine Code Editor](https://code.earthengine.google.com/), adjust the export folder if
needed, and run all tasks. The scripts build growing-season (Jun–Sep) median composites from
Landsat 5/7/8/9 Collection 2 Level-2 surface reflectance and export **NDVI, BSI, NDBI, LST**
as GeoTIFFs (invalid pixels = -9999) to your Google Drive.

Collect the Drive files and place them in `backend/data/indices-pingshuo-full/` (naming must
contain the year and index, e.g. `ndvi_2010.tif`).

## 3. Ingestion & mining-land identification

```bash
python tools/import_real_dataset.py \
    --aoi example/aoi/aoi-pingshuo-full.geojson \
    --name pingshuo-full \
    --mine example/aoi/mine-pingshuo-full.geojson \
    --indices backend/data/indices-pingshuo-full
```

This reprojects everything to a common UTM 49N / 30 m grid, runs the mining-land chain
(change-detection seeding → adaptive quantile signatures → morphological reconstruction →
mine-constraint and reclamation filtering), and writes the yearly land-use stacks plus
metadata into `backend/data/pingshuo-full/`.

## 4. (Optional) Stratified ground-truth samples

```bash
python tools/make_truth_samples.py   # 400 stratified random points per region
```

## 5. Run the system

```bash
pip install -r requirements.txt
python backend/main.py          # http://127.0.0.1:8321
```

Both example datasets are pre-built in the repository, so you can also skip steps 1–4
entirely and explore prediction, scenario analysis, and reporting immediately.
