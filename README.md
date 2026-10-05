# Vigía

**Satellite wildfire monitoring for Spain.** Vigía ingests near-real-time active-fire detections from NASA FIRMS (VIIRS instruments), assigns each detection to its municipality and province with PostGIS, and serves them through a .NET API and an interactive map in Spanish.

It runs for **Andalucía** or the **whole of Spain** (Peninsula, Balearic and Canary Islands, Ceuta and Melilla) with a single setting.

![Vigía map showing satellite fire detections over Andalucía](docs/screenshot.png)

> ⚠️ **Not an official emergency service.** Satellite detections arrive with a delay of several hours and include false positives (agricultural burns, industrial heat sources). In an emergency call **112**. Official information comes from each autonomous community's emergency service (in Andalucía, Plan INFOCA).

## Why

Global fire maps (NASA FIRMS, Copernicus EFFIS) are excellent but generic. Vigía focuses on what local users need: detections by **province and municipality**, in Spanish, with a clean view of recent hours and a path towards local alerts and burned-area history.

## Architecture

```
NASA FIRMS API ──► ingest (Python) ──► PostgreSQL + PostGIS ──► API (.NET 8) ──► Web map (Leaflet)
                    · download CSV         · hotspots               · GeoJSON
                    · normalise/dedupe     · municipalities         · stats
                    · per-region boxes     · spatial join           · per-province counts
```

Python and .NET never call each other: the database is the integration point. The ingestion writes every 15 minutes, the API only reads. Either can fail or be redeployed without affecting the other.

| Component | Stack | Responsibility |
|-----------|-------|----------------|
| `ingest/` | Python 3.12, requests, psycopg 3 | Polls FIRMS, parses VIIRS/MODIS CSV, normalises confidence, deduplicates with deterministic ids (idempotent ingestion), stores in PostGIS and assigns municipalities |
| `db/` | PostgreSQL 16 + PostGIS 3.4 | Schema with GiST spatial indexes |
| `api/` | ASP.NET Core 8 minimal API, Npgsql | Read-only endpoints; GeoJSON is built inside PostgreSQL and streamed as-is; provinces are read from the loaded boundaries, so the API is region-agnostic |
| `api/VigiaApi/wwwroot` | HTML + Leaflet | Map, filters, counters, per-province list; mobile friendly, dark mode |

## Quick start

1. Get a free FIRMS MAP_KEY: https://firms.modaps.eosdis.nasa.gov/api/map_key/
2. Configure and run:

```bash
cp .env.example .env        # set FIRMS_MAP_KEY and REGION (andalucia | espana)
docker compose up --build
```

3. Open http://localhost:8080

The first ingestion runs immediately and then every `INGEST_INTERVAL_SECONDS`.

> **Fedora / SELinux:** the bind mounts in `docker-compose.yml` already carry the `:Z` flag. If you created the database before that, run `docker compose down -v` once so the schema is initialised again.

### Regions

| `REGION` | Download areas | Map view |
|----------|----------------|----------|
| `andalucia` (default) | One box around Andalucía | Andalucía |
| `espana` | Two boxes: Peninsula + Balearics + Ceuta/Melilla, and the Canary Islands | Spain |

The Canary Islands use a separate box because a single one would also download most of the Atlantic and Morocco.

### Loading municipal boundaries (recommended)

Without boundaries, every detection inside the download boxes is shown, including some from neighbouring countries and regions. With boundaries, detections are clipped to the loaded municipalities and labelled with municipality and province, and the province filter and list are populated automatically.

1. Download municipal boundaries, e.g. CNIG *Líneas límite municipales* (all of Spain) or IECA (Andalucía).
2. Convert to GeoJSON in WGS84. Field names vary by source, so inspect them first with `ogrinfo`. Keep only the municipalities of your region:

```bash
ogr2ogr -f GeoJSON -t_srs EPSG:4326 data/municipios.geojson recintos_municipales.shp
```

3. Load them:

```bash
docker compose run --rm ingest python -m vigia_ingest load-boundaries /data/municipios.geojson \
  --name-field NAMEUNIT --province-field provincia
```

## API

| Endpoint | Description |
|----------|-------------|
| `GET /api/hotspots?hours=24&province=Córdoba&minConfidence=nominal` | GeoJSON FeatureCollection (max 5,000 features). `hours` 1–240, `minConfidence` low/nominal/high, `province` case-insensitive |
| `GET /api/stats` | Totals for the same filters as `/api/hotspots`, latest detection and last ingestion time |
| `GET /api/provinces?hours=24&minConfidence=nominal` | Detection count for every loaded province, busiest first |
| `GET /api/config` | Region key, display name and map bounds |
| `GET /api/health` | Database connectivity check |

## Development

```bash
# Unit tests (no database needed)
cd ingest && pip install -r requirements.txt && pytest

# Integration tests against a real PostGIS (they clear the hotspot and municipality tables)
docker compose up -d db
VIGIA_TEST_DATABASE_URL=postgresql://vigia:vigia@localhost:5432/vigia pytest

# API
cd api/VigiaApi && dotnet run
```

## Roadmap

- [ ] Alerts by email/Telegram when a detection appears within a given distance of a user-defined point (`ST_DWithin`)
- [ ] Burned-area history per municipality from Sentinel-2 (dNBR)
- [ ] Group detections from different satellites that belong to the same fire
- [ ] Filter out known persistent heat sources (industry, solar thermal plants)
- [ ] API integration tests with Testcontainers
- [ ] Public deployment

## Data and licences

- Active fire data: NASA FIRMS (LANCE), freely available; please acknowledge NASA FIRMS when using the data.
- Base map: © OpenStreetMap contributors (ODbL).
- Code: [MIT](LICENSE).
