# MineGeoAI-Pre 矿地智预

**An offline-first desktop system for multi-scenario land-use prediction in open-pit mining regions.**

MineGeoAI-Pre turns open geodata (CLCD annual land cover, Copernicus DEM, Landsat-based spectral
indices) into 30 m multi-scenario land-use predictions for open-pit mining regions — fully
offline, on a regular 4 GB office PC, with no programming required. It closes a gap that
cloud platforms (e.g., SEALS on Google Earth Engine) leave open: the business terminal,
where hardware is modest, networks are restricted, and data must not leave the intranet.

> If you use MineGeoAI-Pre, please cite it (see [Citation](#citation)).

## Key features

- **Mining land-use class generation** — public land-cover products contain no "mining land"
  class. MineGeoAI-Pre generates it per year by change-detection seeding, adaptive quantile
  spectral signatures, and morphological reconstruction; reclaimed pixels drop out automatically.
- **Dual-period training protocol** — transition matrices from 2000→2005 and 2005→2010 are
  averaged (row-stochasticity preserved) and suitability is calibrated on the union of changed
  pixels (~120k samples); validation is extrapolated to **two target years** (2015, 2020).
- **Four-scenario 30 m prediction** — 12 mining-semantic scenario parameters (extraction
  intensity, reclamation effort, cropland protection, ecological redlines) drive a
  cellular-automata allocation with parameterized hard constraints.
- **Offline AI assistant** — a local 1.5B LLM (Qwen2.5-1.5B-Instruct, Q4_K_M) with
  retrieval-augmented generation kept *outside* the model, mandatory source citation, and a
  number-checking mechanism that reconciles quoted figures against computed results.
- **Report generation** — one-click analysis reports aligned with land-resource agency review
  practice.
- **Desktop + mobile** — single-page desktop client (12 apps, two themes) and a mobile web
  entry covering all of them on the LAN.

## Validation summary (two real mining regions, 830 km²)

| Region | Area | Mining land 2000→2020 | OA (2015) | OA (2020, 10-yr extrapolation) |
|---|---|---|---|---|
| Pingshuo, Shanxi | 413 km² | 492 → 1,826 ha | 83.41% (κ 0.704) | 78.84% (κ 0.631) |
| Heidaigou, Inner Mongolia | 417 km² | 27 → 815 ha | 90.01% (κ 0.604) | 87.06% (κ 0.493) |

Training: joint 2000→2005 + 2005→2010 transitions; base year 2010. Land-cover ground data:
CLCD, whose own label noise propagates into any training/accuracy protocol (see paper for the
full error discussion). Stratified ground-truth samples (400 points × 2 regions) are being
interpreted for a stratified-weighted error matrix.

## Quick start

```bash
pip install -r requirements.txt
python backend/main.py
# open http://127.0.0.1:8321
```

Two example datasets ship with the repository (`backend/data/pingshuo-full`,
`backend/data/heidaigou`), so prediction runs out of the box.

For the offline AI assistant, download the model once:

```
Qwen2.5-1.5B-Instruct Q4_K_M (GGUF)
https://huggingface.co/Qwen/Qwen2.5-1.5B-Instruct-GGUF
→ place the .gguf file in backend/models/
```

The assistant also works with a cloud LLM API as an optional provider; the RAG retrieval,
citation, and number-checking pipeline is provider-independent.

## Reproducible data pipeline

From public sources to the aligned analysis grid, all steps are versioned scripts in `tools/`:

1. **Rasters** — `tools/download_area_data.py` fetches CLCD (cloud-optimized, windowed to your
   region of interest; failure-isolated so one blocked source never blocks the rest) and
   Copernicus GLO-30 DEM. Proxy-aware, resumable.
2. **Spectral indices** — `example/gee/*.js` (parameterized Earth Engine scripts, growing-season
   median composites of Landsat 5/7/8/9: NDVI, BSI, NDBI, LST). Submit dozens of export tasks
   from the browser with zero coding.
3. **Ingestion & mining class** — `tools/import_real_dataset.py` reprojects everything to a
   common UTM 49N / 30 m grid and runs the mining-land identification chain.
4. **AOI examples** — `example/aoi/*.geojson` (bounding working boxes, mining disturbance
   outlines, and the delineated Pingshuo mining boundary).

See `docs/data-pipeline.md` for the full walkthrough.

## System requirements

| Item | Minimum | Recommended |
|---|---|---|
| OS | Windows 10/11 x64, Ubuntu 22.04 | either |
| RAM | 4 GB (tight) | 8 GB |
| Disk | 3 GB | 10 GB (with datasets) |
| GPU / instruction set | not required; no AVX2 needed | — |
| Network | fully offline; first data acquisition needs internet | — |

Measured on the minimum configuration: cold start 5.2 s, resident service memory 0.19 GB
(model loads on demand), local inference peak 1.8–2.1 GB.

## Repository layout

```
backend/          FastAPI service, prediction engine, identification chain
  core/           14 domain modules (predict, importdetect, llm, kb, report, ...)
  data/           two example datasets + spectral indices (10 m-100 m GeoTIFFs)
frontend/         single-page client + mobile entry (no build step)
tools/            reproducible data-chain scripts (download, ingest, sample, release)
example/          AOI GeoJSONs and Earth Engine export scripts
docs/             data-pipeline walkthrough
```

## The four engineering problems, in short

Turning a paper model into deployable software surfaced four rarely documented breakpoints;
this repository is also a reference implementation for crossing them:

1. **Reproducible data acquisition under restricted networks** — COG windowed fetching,
   failure isolation, resumable downloads, proxy compatibility, automated GEE exports.
2. **A missing land-use class at 30 m** — mine-point priors + majority-connected disturbance
   components constrain the search; quantile signatures + reconstruction-by-dilation recover
   the full mining footprint that strict spectral signatures miss (~4% pass rate).
3. **LLM inference inside a 4 GB budget** — model selection by measurement (0.5B unusable,
   1.5B viable), on-demand loading, RAG and verification external to the model.
4. **Binary portability** — CPU-compatible wheel pinning, bundled runtimes, and a
   release checklist that validates on the *weakest* target environment (a recall event
   taught us this the hard way).

## License & citation

Code: MIT license. Example data derive from open sources (CLCD, Copernicus GLO-30, Landsat).

### Citation

A software paper is in preparation for *Environmental Modelling & Software*. Until it and the
Zenodo archive DOI are available, cite the repository:

```
MineGeoAI-Pre Development Team (2026). MineGeoAI-Pre: an offline-first desktop system for
multi-scenario land-use prediction in open-pit mining regions.
https://github.com/mengzhuoer/MineGeoAI-Pre
```

### Data sources to acknowledge

- Yang & Huang (2021), CLCD — China annual land cover, ESSD
- Copernicus GLO-30 DEM (ESA)
- Landsat Collection 2 Surface Reflectance (USGS)
- Gorelick et al. (2017), Google Earth Engine, RSE
