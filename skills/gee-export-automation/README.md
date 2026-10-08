# Batch GEE exports without clicking every task

**Drop a local JavaScript export script into the [Google Earth Engine](https://code.earthengine.google.com/)
Code Editor, hit Run, and submit all export tasks at once — instead of copy-pasting code and
clicking 40 individual task buttons.**

This is the automation used to acquire the spectral-index rasters (NDVI / BSI / NDBI / LST,
5 epochs × 2 study regions) for the MineGeoAI-Pre datasets. It is published here because the
GEE step is part of our reproducible data pipeline (see `docs/data-pipeline.md`), and because
it is useful to anyone exporting imagery in bulk (by AOI, by year, by index).

## What it does

- Injects a local `.js` file into the Code Editor's editor (via the ACE API — reliable, no
  typing simulation, handles 40 KB+ scripts with non-ASCII comments).
- Clicks **Run**, reads the Console output, and reports client-side errors (empty collections,
  wrong band names, quota) **before** submitting tasks.
- Opens the **Tasks** panel and clicks **Run all** to submit every export in one action.
- Verifies submission by reading the hidden Tasks panel state, and leaves a per-region
  `driveFolder` convention so outputs land in separate Drive folders.

## Prerequisites

1. A Google account registered for Earth Engine (any account that has opened the Code Editor).
2. A browser you can drive: an in-app browser controlled by an AI assistant, or a local
   Chromium launched with CDP / Playwright. External browsers opened by hand (Quark, Edge…)
   are not controllable unless started with a debugging port.
3. Sign in **yourself** in the browser window — never paste credentials into automation code.
4. Access to Google (proxy/VPN as needed for your network).

## Two ways to use it

### A. With an AI coding assistant (recommended)

Point the assistant at this folder. If your assistant supports agent-skill files, it can load
`SKILL.md` directly; the file documents the exact sequence (ACE injection, Run, Tasks → Run
all, verification) and the pitfalls that will otherwise cost you an afternoon — including the
big one: **the Tasks panel lives in a shadow DOM**, so naive `document.querySelector` reads
return nothing, and you must use your automation tool's full-page snapshot instead.

### B. By hand

The same knowledge works manually:

1. Open the Code Editor, paste your script, press Run, check the Console for errors.
2. Click **Tasks** → **Run all**. (Do not click 20 task buttons one at a time.)
3. Wait ~10 s; make sure the *Unsubmitted* list is empty and all tasks appear under
   *Submitted tasks*.
4. Give each region its own `CONFIG.driveFolder` in the script — task display names may be
   identical across scripts (all called `ndvi_2000`), so the Drive folder is the only place
   provenance survives.

## Output convention (matches this repository's ingestion tools)

- One GeoTIFF per index-year: `ndvi_2000.tif`, `bsi_2000.tif`, … following `CONFIG.driveFolder`.
- Export scripts for the two example regions: `example/gee/gee_export_indices_admin-*.js`.
- These files feed `tools/import_real_dataset.py --indices-dir` — that is the contract this
  automation exists to fulfill.

## Caveats

- Server-side queueing is gradual: small AOIs take minutes each; LST (thermal) is the slowest.
- Failed tasks (cloud cover, quota) must be re-submitted individually — re-inject the script,
  then click that task's Run.
- Judge "region done" by **counting files in its Drive folder** (epochs × indices), not by
  task names.
