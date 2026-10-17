# Datasets

Every dataset used by the planner, where it comes from, how it is labelled and how to replace it.
The pilot area is a 10 km radius around 11.72 N, 76.64 E (Bandipur cluster, D-19).

## Synthetic seed (shelters and settlements)

Phase 3 ships a clearly labelled **synthetic** seed so CI and demos never wait on real data (D-18).
These rows are invented test data. They do not describe real buildings, capacities or populations
and must never be presented as real (S3, S9).

| File | Loaded by | Key | Rows |
|------|-----------|-----|------|
| `config/seed/shelters_bandipur.csv` | `scripts/seed_shelters.py` | `external_ref` (`SYN-SH-01..20`) | 20 |
| `config/seed/settlements_bandipur.csv` | `scripts/seed_settlements.py` | `external_ref` (`SYN-ST-01..10`) | 10 |

Shelter columns: `external_ref, name, kind, lat, lon, capacity, usable_factor, capacity_source,
is_simulated, notes`.

- `kind` is `school`, `community_hall` or `other`.
- `capacity_source` is a mandatory label. The value `synthetic` marks invented data and requires
  `is_simulated=true`.
- `usable_factor` is optional (blank means the config default, `shelter_usable_factor`, 0.6).
  Usable capacity is `floor(capacity x factor)`, computed exactly in decimal.

Settlement columns: `external_ref, name, kind, population, pop_source, lat, lon, buffer_m,
is_simulated`.

- `pop_source` is a mandatory label. `synthetic` requires `is_simulated=true`.
- `buffer_m` (100 to 20000, seed value 2000) is the radius used to decide whether a settlement is
  at risk from a forecast perimeter.

Both loaders validate every row (`wildfire_core.seed`): reference pattern, bounded numbers, no
control characters, unique references. CSV text is treated as data only and is never evaluated.
The seed scripts upsert on `external_ref`, so they are safe to re-run, and they never reset shelter
occupancy (occupancy changes only through `update_occupancy`).

Run `uv run python scripts/seed_shelters.py --dry-run` (validate only) or without `--dry-run` to
load into the database. Each script warns while any synthetic row is loaded.

### Replacing the seed with curated data

Provide curated CSVs with the same columns, give each row a real `capacity_source` or `pop_source`
(for example the name of the survey or directory) and set `is_simulated=false`, then point
`--csv` (or `shelters_seed_path` / `settlements_seed_path` in `config/defaults.yaml`) at them.
Existing synthetic rows with `SYN-` references stay in the database until removed, so deactivate
or delete them when switching to real data. Plan 03-12 holds the human checkpoint for this swap.

## OpenStreetMap drive network

- Source: OpenStreetMap road data downloaded through OSMnx.
- Built once by a human-run script: `uv run python scripts/build_osm_graph.py`, covering the 10 km
  pilot buffer around 11.72 N, 76.64 E (D-05, D-06, D-19).
- Cached under `data/osm/` (git-ignored, never committed); planning loads it from disk and does
  not download at plan time. CI does not download OSM and uses a synthetic graph fixture.
- Attribution: (c) OpenStreetMap contributors, licensed under the Open Database License (ODbL).
  Keep this attribution wherever derived routes or maps are shown.

## NASA FIRMS active-fire detections

- Source: NASA FIRMS VIIRS/MODIS near-real-time hotspots, ingested by the ingest worker.
- Stored with `source`, acquisition time, confidence and a `data_origin` label (live or replay).
- Attribution: we acknowledge the use of data and imagery from NASA's Fire Information for
  Resource Management System (FIRMS), part of NASA's Earth Science Data and Information System
  (ESDIS).

## Open-Meteo weather

- Source: Open-Meteo forecast and observation API (temperature, humidity, wind speed and direction,
  gusts, precipitation) at the cluster centroid.
- Observations (valid time at or before issue time) and forecasts are stored separately, each
  with a `data_origin` label and a freshness status.
- Attribution: weather data by Open-Meteo.com, licensed CC BY 4.0.
