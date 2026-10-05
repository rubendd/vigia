"""Command-line entry point.

    python -m vigia_ingest run-once            # one ingestion cycle
    python -m vigia_ingest loop                # ingest every INGEST_INTERVAL_SECONDS
    REGION=espana python -m vigia_ingest run-once    # region: andalucia (default) or espana
    python -m vigia_ingest load-boundaries municipios.geojson --name-field NAMEUNIT --province-field provincia
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import time

import psycopg

from . import db
from .firms import FirmsError, deduplicate, fetch, get_region

log = logging.getLogger("vigia_ingest")


def _settings() -> dict:
    return {
        "region": os.environ.get("REGION", "andalucia"),
        "map_key": os.environ.get("FIRMS_MAP_KEY", ""),
        "sources": [s.strip() for s in os.environ.get("FIRMS_SOURCES", "VIIRS_SNPP_NRT,VIIRS_NOAA20_NRT").split(",") if s.strip()],
        "days": int(os.environ.get("FIRMS_DAYS", "1")),
        "database_url": os.environ.get("DATABASE_URL", "postgresql://vigia:vigia@localhost:5432/vigia"),
        "interval": int(os.environ.get("INGEST_INTERVAL_SECONDS", "900")),
    }


def run_once(settings: dict) -> int:
    collected = []
    for bbox in get_region(settings["region"]):
        for source in settings["sources"]:
            try:
                batch = fetch(settings["map_key"], source, days=settings["days"], bbox=bbox)
                log.info("%s %s: %d detections", source, bbox, len(batch))
                collected.extend(batch)
            except (FirmsError, OSError) as exc:  # requests errors subclass OSError
                log.error("%s %s: download failed: %s", source, bbox, exc)

    with psycopg.connect(settings["database_url"]) as conn:
        inserted = db.save_hotspots(conn, deduplicate(collected))
    log.info("Stored %d new hotspots", inserted)
    return inserted


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser(prog="vigia_ingest")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("run-once")
    sub.add_parser("loop")
    boundaries = sub.add_parser("load-boundaries")
    boundaries.add_argument("geojson")
    boundaries.add_argument("--name-field", default="NAMEUNIT")
    boundaries.add_argument("--province-field", default="provincia")
    args = parser.parse_args(argv)

    settings = _settings()

    try:
        get_region(settings["region"])
    except ValueError as exc:
        log.error("%s", exc)
        return 2

    if args.command == "load-boundaries":
        with psycopg.connect(settings["database_url"]) as conn:
            n = db.load_municipalities(conn, args.geojson, args.name_field, args.province_field)
        log.info("Loaded %d municipalities", n)
        return 0

    if not settings["map_key"]:
        log.error("FIRMS_MAP_KEY is not set. Get a free key at https://firms.modaps.eosdis.nasa.gov/api/map_key/")
        return 2

    if args.command == "run-once":
        run_once(settings)
        return 0

    while True:
        try:
            run_once(settings)
        except psycopg.Error as exc:
            log.error("Database error: %s", exc)
        time.sleep(settings["interval"])


if __name__ == "__main__":
    sys.exit(main())
