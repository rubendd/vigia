-- Vigía schema (PostgreSQL + PostGIS)
CREATE EXTENSION IF NOT EXISTS postgis;

CREATE TABLE IF NOT EXISTS municipalities (
    id        SERIAL PRIMARY KEY,
    name      TEXT NOT NULL,
    province  TEXT NOT NULL,
    geom      geometry(MultiPolygon, 4326) NOT NULL
);
CREATE INDEX IF NOT EXISTS municipalities_geom_idx ON municipalities USING GIST (geom);
CREATE INDEX IF NOT EXISTS municipalities_province_idx ON municipalities (province);

CREATE TABLE IF NOT EXISTS hotspots (
    id               TEXT PRIMARY KEY,
    source           TEXT NOT NULL,
    satellite        TEXT,
    acquired_at      TIMESTAMPTZ NOT NULL,
    latitude         DOUBLE PRECISION NOT NULL,
    longitude        DOUBLE PRECISION NOT NULL,
    brightness       DOUBLE PRECISION,
    frp              DOUBLE PRECISION,
    confidence       TEXT NOT NULL CHECK (confidence IN ('low', 'nominal', 'high')),
    daynight         CHAR(1),
    municipality_id  INTEGER REFERENCES municipalities (id) ON DELETE SET NULL,
    geom             geometry(Point, 4326) NOT NULL,
    ingested_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS hotspots_geom_idx ON hotspots USING GIST (geom);
CREATE INDEX IF NOT EXISTS hotspots_acquired_idx ON hotspots (acquired_at DESC);
