"""PostGIS persistence for hotspots and municipal boundaries."""

from __future__ import annotations

import json
from typing import Iterable

import psycopg

from .firms import Hotspot

INSERT_HOTSPOT = """
INSERT INTO hotspots (id, source, satellite, acquired_at, latitude, longitude,
                      brightness, frp, confidence, daynight, geom)
VALUES (%(id)s, %(source)s, %(satellite)s, %(acquired_at)s, %(latitude)s, %(longitude)s,
        %(brightness)s, %(frp)s, %(confidence)s, %(daynight)s,
        ST_SetSRID(ST_MakePoint(%(longitude)s, %(latitude)s), 4326))
ON CONFLICT (id) DO NOTHING
"""

# Attach each new hotspot to the municipality polygon that contains it.
ASSIGN_MUNICIPALITIES = """
UPDATE hotspots h
SET municipality_id = m.id
FROM municipalities m
WHERE h.municipality_id IS NULL
  AND ST_Contains(m.geom, h.geom)
"""

# Without boundaries loaded we keep everything in the bbox; with them, drop points outside every loaded municipality.
DELETE_OUTSIDE = """
DELETE FROM hotspots h
WHERE h.municipality_id IS NULL
  AND EXISTS (SELECT 1 FROM municipalities)
  AND NOT EXISTS (SELECT 1 FROM municipalities m WHERE ST_Contains(m.geom, h.geom))
"""


def save_hotspots(conn: psycopg.Connection, hotspots: Iterable[Hotspot]) -> int:
    rows = [h.__dict__ for h in hotspots]
    if not rows:
        return 0
    with conn.cursor() as cur:
        before = cur.execute("SELECT count(*) FROM hotspots").fetchone()[0]
        cur.executemany(INSERT_HOTSPOT, rows)
        cur.execute(ASSIGN_MUNICIPALITIES)
        cur.execute(DELETE_OUTSIDE)
        after = cur.execute("SELECT count(*) FROM hotspots").fetchone()[0]
    conn.commit()
    return max(after - before, 0)


def load_municipalities(conn: psycopg.Connection, geojson_path: str, name_field: str, province_field: str) -> int:
    with open(geojson_path, encoding="utf-8") as fh:
        data = json.load(fh)

    count = 0
    with conn.cursor() as cur:
        # DELETE (not TRUNCATE ... CASCADE, which would also wipe hotspots): the FK sets municipality_id to NULL.
        cur.execute("DELETE FROM municipalities")
        cur.execute("ALTER SEQUENCE municipalities_id_seq RESTART WITH 1")
        for feature in data.get("features", []):
            props = feature.get("properties") or {}
            geometry = feature.get("geometry")
            if not geometry:
                continue
            cur.execute(
                """
                INSERT INTO municipalities (name, province, geom)
                VALUES (%s, %s, ST_Multi(ST_Transform(ST_SetSRID(ST_GeomFromGeoJSON(%s), %s), 4326)))
                """,
                (str(props.get(name_field, "")), str(props.get(province_field, "")), json.dumps(geometry), 4326),
            )
            count += 1
        cur.execute("UPDATE hotspots SET municipality_id = NULL")
        cur.execute(ASSIGN_MUNICIPALITIES)
        cur.execute(DELETE_OUTSIDE)
    conn.commit()
    return count
