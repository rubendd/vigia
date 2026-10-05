"""NASA FIRMS client: download, parse and normalise active-fire detections for Spanish regions.

FIRMS (Fire Information for Resource Management System) publishes near-real-time
hotspots from the VIIRS and MODIS instruments. The area API returns CSV:
https://firms.modaps.eosdis.nasa.gov/api/area/
"""

from __future__ import annotations

import csv
import hashlib
import io
from dataclasses import dataclass
from datetime import datetime, timezone

import requests

FIRMS_BASE_URL = "https://firms.modaps.eosdis.nasa.gov/api/area/csv"

BBox = tuple[float, float, float, float]  # (west, south, east, north)

# Bounding box of Andalucía, slightly padded.
ANDALUCIA_BBOX: BBox = (-7.55, 35.90, -1.60, 38.75)

# A region is one or more boxes: a single box covering both the Peninsula and the
# Canary Islands would download most of the Atlantic and Morocco.
REGIONS: dict[str, list[BBox]] = {
    "andalucia": [ANDALUCIA_BBOX],
    "espana": [
        (-9.50, 35.10, 4.50, 43.90),    # Peninsula, Balearic Islands, Ceuta and Melilla
        (-18.30, 27.50, -13.30, 29.50),  # Canary Islands
    ],
}


def get_region(name: str) -> list[BBox]:
    key = (name or "").strip().lower()
    if key not in REGIONS:
        raise ValueError(f"Unknown region {name!r}. Use one of {sorted(REGIONS)}.")
    return REGIONS[key]

SUPPORTED_SOURCES = {
    "VIIRS_SNPP_NRT",
    "VIIRS_NOAA20_NRT",
    "VIIRS_NOAA21_NRT",
    "MODIS_NRT",
}

CONFIDENCE_ORDER = {"low": 0, "nominal": 1, "high": 2}


class FirmsError(RuntimeError):
    """Raised when FIRMS returns an error instead of CSV data."""


@dataclass(frozen=True)
class Hotspot:
    id: str
    source: str
    satellite: str
    latitude: float
    longitude: float
    acquired_at: datetime
    brightness: float | None
    frp: float | None
    confidence: str
    daynight: str


def build_url(map_key: str, source: str, bbox=ANDALUCIA_BBOX, days: int = 1) -> str:
    if not map_key:
        raise ValueError("A FIRMS MAP_KEY is required (free at firms.modaps.eosdis.nasa.gov/api/map_key/).")
    if source not in SUPPORTED_SOURCES:
        raise ValueError(f"Unsupported source {source!r}. Use one of {sorted(SUPPORTED_SOURCES)}.")
    if not 1 <= days <= 10:
        raise ValueError("days must be between 1 and 10.")
    west, south, east, north = bbox
    area = f"{west},{south},{east},{north}"
    return f"{FIRMS_BASE_URL}/{map_key}/{source}/{area}/{days}"


def normalise_confidence(raw: str) -> str:
    """Map VIIRS letters (l/n/h) and MODIS percentages (0-100) to low/nominal/high."""
    value = (raw or "").strip().lower()
    letters = {"l": "low", "n": "nominal", "h": "high", "low": "low", "nominal": "nominal", "high": "high"}
    if value in letters:
        return letters[value]
    try:
        pct = float(value)
    except ValueError:
        return "low"
    if pct < 30:
        return "low"
    if pct < 80:
        return "nominal"
    return "high"


def _parse_time(acq_date: str, acq_time: str) -> datetime:
    hhmm = acq_time.strip().zfill(4)
    return datetime.strptime(f"{acq_date.strip()} {hhmm}", "%Y-%m-%d %H%M").replace(tzinfo=timezone.utc)


def _to_float(value: str | None) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except ValueError:
        return None


def hotspot_id(source: str, lat: float, lon: float, acquired_at: datetime) -> str:
    """Deterministic id so re-downloading the same detection never duplicates it."""
    key = f"{source}|{lat:.5f}|{lon:.5f}|{acquired_at.isoformat()}"
    return hashlib.sha1(key.encode()).hexdigest()[:20]


def parse_csv(text: str, source: str) -> list[Hotspot]:
    stripped = text.lstrip()
    if not stripped.lower().startswith("latitude"):
        # FIRMS answers errors (bad key, quota) as plain text with HTTP 200.
        raise FirmsError(stripped[:200] or "Empty response from FIRMS")

    hotspots: list[Hotspot] = []
    for row in csv.DictReader(io.StringIO(stripped)):
        try:
            lat = float(row["latitude"])
            lon = float(row["longitude"])
            acquired = _parse_time(row["acq_date"], row["acq_time"])
        except (KeyError, ValueError):
            continue  # skip malformed rows rather than failing the whole batch
        brightness = _to_float(row.get("bright_ti4") or row.get("brightness"))
        hotspots.append(
            Hotspot(
                id=hotspot_id(source, lat, lon, acquired),
                source=source,
                satellite=(row.get("satellite") or "").strip(),
                latitude=lat,
                longitude=lon,
                acquired_at=acquired,
                brightness=brightness,
                frp=_to_float(row.get("frp")),
                confidence=normalise_confidence(row.get("confidence", "")),
                daynight=(row.get("daynight") or "").strip().upper()[:1],
            )
        )
    return hotspots


def within_bbox(h: Hotspot, bbox=ANDALUCIA_BBOX) -> bool:
    west, south, east, north = bbox
    return west <= h.longitude <= east and south <= h.latitude <= north


def deduplicate(hotspots: list[Hotspot]) -> list[Hotspot]:
    seen: dict[str, Hotspot] = {}
    for h in hotspots:
        seen.setdefault(h.id, h)
    return list(seen.values())


def fetch(map_key: str, source: str, days: int = 1, bbox=ANDALUCIA_BBOX, timeout: int = 60) -> list[Hotspot]:
    url = build_url(map_key, source, bbox, days)
    response = requests.get(url, timeout=timeout)
    response.raise_for_status()
    return [h for h in parse_csv(response.text, source) if within_bbox(h, bbox)]
