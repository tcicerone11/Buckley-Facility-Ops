import json
import math
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

from cotrip_integration import fetch_cotrip_bundle

ROOT = Path(__file__).resolve().parent
CONFIG_FILE = ROOT / "facilities.json"
DOCS = ROOT / "docs"
STATUS_FILE = DOCS / "status.json"
HTML_FILE = DOCS / "index.html"

NWS = "https://api.weather.gov"
AWC = "https://aviationweather.gov/api/data"
NIFC_INCIDENTS = (
    "https://services3.arcgis.com/T4QMspbfLg3qTGWY/arcgis/rest/services/"
    "WFIGS_Incident_Locations_Current/FeatureServer/0/query"
)

HEADERS = {
    "User-Agent": "BuckleyFacilityOperations/1.0",
    "Accept": "application/geo+json",
}
AWC_HEADERS = {"User-Agent": "BuckleyFacilityOperations/1.0"}

LEVEL = {"normal": 0, "watch": 1, "action": 2, "close": 3}

STATUS_COPY = {
    "normal": {
        "label": "NORMAL",
        "summary": "No configured test threshold currently suggests an operational change.",
        "action": "Continue normal operations and routine monitoring.",
    },
    "watch": {
        "label": "WATCH",
        "summary": "Conditions could affect Buckley operations or employee access.",
        "action": "Monitor conditions and prepare staff, equipment, and access plans.",
    },
    "action": {
        "label": "ACTION",
        "summary": "A significant condition has been reached or is expected.",
        "action": "Take the protective or continuity action defined by the approved facility plan.",
    },
    "close": {
        "label": "CLOSE CRITERIA MET",
        "summary": "A configured closure threshold or critical warning has been reached.",
        "action": "Follow approved closure, restriction, or emergency procedures.",
    },
}

CLOSE_EVENTS = {
    "Tornado Warning",
    "Extreme Wind Warning",
    "Flash Flood Warning",
    "Hurricane Warning",
    "Storm Surge Warning",
    "Tsunami Warning",
}

ACTION_EVENTS = {
    "Severe Thunderstorm Warning",
    "Blizzard Warning",
    "Ice Storm Warning",
    "Winter Storm Warning",
    "High Wind Warning",
    "Flood Warning",
    "Extreme Heat Warning",
    "Excessive Heat Warning",
}

WATCH_EVENTS = {
    "Tornado Watch",
    "Severe Thunderstorm Watch",
    "Winter Storm Watch",
    "High Wind Watch",
    "Flood Watch",
    "Flash Flood Watch",
    "Winter Weather Advisory",
    "Wind Advisory",
    "Heat Advisory",
    "Dense Fog Advisory",
    "Red Flag Warning",
    "Fire Weather Watch",
}


def now_utc():
    return datetime.now(timezone.utc)


def iso(dt):
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_dt(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def load_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def get_json(url, params=None, headers=None, timeout=30):
    r = requests.get(url, params=params, headers=headers or HEADERS, timeout=timeout)
    if r.status_code == 204:
        return []
    r.raise_for_status()
    return r.json()


def c_to_f(v):
    return None if v is None else round((float(v) * 9 / 5) + 32, 1)


def kt_to_mph(v):
    return None if v is None else round(float(v) * 1.15078, 1)


def mps_to_kt(v):
    return None if v is None else round(float(v) * 1.943844, 1)


def kmh_to_kt(v):
    return None if v is None else round(float(v) * 0.539957, 1)


def mm_to_in(v):
    return None if v is None else round(float(v) / 25.4, 3)


def max_level(current, proposed):
    return proposed if LEVEL[proposed] > LEVEL[current] else current


def haversine_miles(lat1, lon1, lat2, lon2):
    radius_miles = 3958.7613
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlon / 2) ** 2
    return radius_miles * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def parse_metar_wind(raw):
    if not raw:
        return None, None
    m = re.search(r"\b(?:\d{3}|VRB)(\d{2,3})(?:G(\d{2,3}))?KT\b", raw)
    if not m:
        return None, None
    return float(m.group(1)), float(m.group(2)) if m.group(2) else None


def parse_metar_visibility(raw):
    if not raw:
        return None
    m = re.search(r"\b(?:(\d+)\s+)?(\d+)/(\d+)SM\b", raw)
    if m:
        whole = float(m.group(1) or 0)
        return round(whole + float(m.group(2)) / float(m.group(3)), 2)
    m = re.search(r"\b(\d+(?:\.\d+)?)SM\b", raw)
    return float(m.group(1)) if m else None


def fetch_metar(icao):
    data = get_json(f"{AWC}/metar", {"ids": icao, "format": "json"}, AWC_HEADERS)
    if not data:
        return None
    row = data[0]
    raw = row.get("rawOb") or row.get("raw_text") or row.get("raw") or ""
    wind, gust = parse_metar_wind(raw)
    if wind is None:
        wind = row.get("wspd") or row.get("windSpeed")
    if gust is None:
        gust = row.get("wgst") or row.get("windGust")
    temp_c = row.get("temp") if row.get("temp") is not None else row.get("tempC")
    wind = float(wind) if wind is not None else None
    gust = float(gust) if gust is not None else None
    return {
        "raw": raw,
        "observed": row.get("reportTime") or row.get("obsTime") or row.get("receiptTime"),
        "wind_kt": wind,
        "wind_mph": kt_to_mph(wind),
        "gust_kt": gust,
        "gust_mph": kt_to_mph(gust),
        "temperature_f": c_to_f(temp_c),
        "visibility_sm": parse_metar_visibility(raw),
        "flight_category": row.get("fltCat") or row.get("flightCategory"),
    }


def fetch_taf(icao):
    data = get_json(f"{AWC}/taf", {"ids": icao, "format": "json"}, AWC_HEADERS)
    if not data:
        return None
    row = data[0]
    raw = row.get("rawTAF") or row.get("raw_text") or row.get("raw") or ""
    upper = raw.upper()
    return {
        "raw": raw,
        "issued": row.get("issueTime") or row.get("issue_time"),
        "valid_from": row.get("validTimeFrom") or row.get("valid_from"),
        "valid_to": row.get("validTimeTo") or row.get("valid_to"),
        "thunder": "TS" in upper,
        "snow": bool(re.search(r"\bSN\b|\bSHSN\b|\bBLSN\b", upper)),
        "freezing_precip": bool(re.search(r"\bFZRA\b|\bFZDZ\b|\bPL\b", upper)),
    }


def nws_point_data(lat, lon):
    point = get_json(f"{NWS}/points/{lat:.4f},{lon:.4f}")
    p = point.get("properties", {})
    hourly = get_json(p["forecastHourly"]) if p.get("forecastHourly") else {"properties": {"periods": []}}
    forecast = get_json(p["forecast"]) if p.get("forecast") else {"properties": {"periods": []}}
    grid = get_json(p["forecastGridData"]) if p.get("forecastGridData") else {"properties": {}}
    return point, hourly, forecast, grid


def value_series(prop, kind, hours=168):
    if not isinstance(prop, dict):
        return []
    out = []
    end = now_utc() + timedelta(hours=hours)
    for item in prop.get("values", []) or []:
        start_text = str(item.get("validTime", "")).split("/", 1)[0]
        dt = parse_dt(start_text)
        if not dt or dt > end:
            continue
        value = item.get("value")
        if value is None:
            continue
        unit = (prop.get("uom") or "").lower()
        value = float(value)

        if kind == "wind":
            if "km_h" in unit or "km/h" in unit:
                value = kmh_to_kt(value)
            elif "m_s" in unit or "m/s" in unit:
                value = mps_to_kt(value)
        elif kind in {"precip", "snow", "ice"}:
            if "mm" in unit:
                value = mm_to_in(value)
            elif "cm" in unit:
                value = round(value / 2.54, 3)

        out.append(value)
    return out


def alert_from_feature(feature, source):
    p = feature.get("properties", {})
    return {
        "event": p.get("event") or "Weather Alert",
        "headline": p.get("headline") or "",
        "severity": p.get("severity") or "Unknown",
        "urgency": p.get("urgency") or "Unknown",
        "expires": p.get("expires"),
        "source": source,
    }


def fetch_point_alerts(lat, lon):
    data = get_json(f"{NWS}/alerts/active", {"point": f"{lat:.4f},{lon:.4f}"})
    if not isinstance(data, dict):
        return []
    return [alert_from_feature(f, "Exact Buckley location") for f in data.get("features", [])]


def fetch_zone_alerts(zone):
    if not zone:
        return []
    data = get_json(f"{NWS}/alerts/active/zone/{zone}")
    if not isinstance(data, dict):
        return []
    return [alert_from_feature(f, f"Broader NWS zone {zone}") for f in data.get("features", [])]


def merge_alerts(*groups):
    seen, merged = set(), []
    for group in groups:
        for item in group:
            key = (item.get("event"), item.get("headline"), item.get("expires"))
            if key in seen:
                continue
            seen.add(key)
            merged.append(item)
    return merged


def fetch_wildfires_near(lat, lon, max_miles=50):
    lat_pad = max_miles / 69.0
    lon_pad = max_miles / max(1.0, 69.0 * math.cos(math.radians(lat)))
    envelope = f"{lon-lon_pad},{lat-lat_pad},{lon+lon_pad},{lat+lat_pad}"

    params = {
        "where": "1=1",
        "geometry": envelope,
        "geometryType": "esriGeometryEnvelope",
        "inSR": "4326",
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": "*",
        "returnGeometry": "true",
        "outSR": "4326",
        "f": "json",
    }
    data = get_json(NIFC_INCIDENTS, params=params, headers=AWC_HEADERS)
    fires = []
    for feature in data.get("features", []) if isinstance(data, dict) else []:
        geom = feature.get("geometry") or {}
        x, y = geom.get("x"), geom.get("y")
        if x is None or y is None:
            continue
        distance = haversine_miles(lat, lon, float(y), float(x))
        if distance > max_miles:
            continue
        a = feature.get("attributes") or {}
        name = a.get("IncidentName") or a.get("IncidentShortDescription") or "Wildland fire"
        acres = (
            a.get("DailyAcres")
            or a.get("CalculatedAcres")
            or a.get("DiscoveryAcres")
            or a.get("IncidentSize")
        )
        fires.append({
            "name": str(name).title(),
            "distance_miles": round(distance, 1),
            "acres": acres,
            "county": a.get("POOCounty"),
            "state": a.get("POOState"),
            "cause": a.get("FireCause"),
        })
    return sorted(fires, key=lambda f: f["distance_miles"])



def cotrip_auth_headers():
    """Build COtrip headers without exposing credentials in generated HTML."""
    key = os.getenv("COTRIP_API_KEY", "").strip()
    headers = {
        "User-Agent": "BuckleyFacilityOperations/1.1",
        "Accept": "application/json, application/geo+json, text/json",
    }
    if key:
        # The exact authentication header can be changed here if CDOT assigns
        # a different scheme when feed access is approved.
        headers["Authorization"] = f"Bearer {key}"
        headers["X-API-Key"] = key
    return headers


def normalize_cotrip_records(data):
    """
    Normalizes several common JSON / GeoJSON feed shapes into a small safe
    structure that can be published to GitHub Pages.

    CDOT controls the actual developer-feed schema. If their assigned feed uses
    different field names, only this adapter needs to be adjusted.
    """
    if isinstance(data, dict):
        if isinstance(data.get("features"), list):
            records = data["features"]
        elif isinstance(data.get("results"), list):
            records = data["results"]
        elif isinstance(data.get("items"), list):
            records = data["items"]
        elif isinstance(data.get("data"), list):
            records = data["data"]
        else:
            records = []
    elif isinstance(data, list):
        records = data
    else:
        records = []

    out = []
    for item in records:
        if not isinstance(item, dict):
            continue

        props = item.get("properties") if isinstance(item.get("properties"), dict) else item
        geom = item.get("geometry") if isinstance(item.get("geometry"), dict) else {}

        lat = props.get("latitude") or props.get("lat")
        lon = props.get("longitude") or props.get("lon") or props.get("lng")

        coords = geom.get("coordinates")
        if (lat is None or lon is None) and isinstance(coords, list) and len(coords) >= 2:
            # Supports simple GeoJSON Point records.
            if isinstance(coords[0], (int, float)) and isinstance(coords[1], (int, float)):
                lon, lat = coords[0], coords[1]

        try:
            lat = float(lat) if lat is not None else None
            lon = float(lon) if lon is not None else None
        except (TypeError, ValueError):
            lat, lon = None, None

        title = (
            props.get("headline")
            or props.get("title")
            or props.get("name")
            or props.get("event")
            or props.get("eventType")
            or props.get("type")
            or "COtrip roadway event"
        )
        description = (
            props.get("description")
            or props.get("details")
            or props.get("comment")
            or props.get("message")
            or ""
        )
        road = (
            props.get("roadName")
            or props.get("route")
            or props.get("road")
            or props.get("highway")
            or ""
        )
        status = props.get("status") or props.get("eventStatus") or ""
        severity = props.get("severity") or props.get("priority") or ""

        searchable = " ".join(
            str(v) for v in (title, description, road, status, severity) if v
        ).lower()

        kind = "road_event"
        if any(k in searchable for k in ("closed", "closure", "road closed")):
            kind = "closure"
        elif any(k in searchable for k in ("crash", "collision", "incident", "accident")):
            kind = "incident"
        elif any(k in searchable for k in ("snow", "ice", "icy", "winter", "slick")):
            kind = "winter"
        elif any(k in searchable for k in ("construction", "work zone", "road work", "roadwork")):
            kind = "construction"
        elif any(k in searchable for k in ("restriction", "chain law", "traction")):
            kind = "restriction"

        out.append({
            "title": str(title),
            "description": str(description),
            "road": str(road),
            "status": str(status),
            "severity": str(severity),
            "kind": kind,
            "latitude": lat,
            "longitude": lon,
        })
    return out


def fetch_cotrip_events(config):
    """
    Pulls the authenticated COtrip developer feed during GitHub Actions.

    This is deliberately server-side (GitHub Actions), not browser-side, so an
    API credential is never exposed on the public GitHub Pages site.
    """
    c = config.get("cotrip", {})
    if not c.get("enabled"):
        return {
            "connected": False,
            "reason": "COtrip developer feed is disabled in facilities.json.",
            "events": [],
        }

    url = os.getenv("COTRIP_API_URL", "").strip()
    key = os.getenv("COTRIP_API_KEY", "").strip()

    if not url or not key:
        return {
            "connected": False,
            "reason": "COtrip feed is enabled, but COTRIP_API_URL or COTRIP_API_KEY is not configured in GitHub Actions secrets.",
            "events": [],
        }

    try:
        response = requests.get(
            url,
            headers=cotrip_auth_headers(),
            timeout=35,
        )
        response.raise_for_status()
        data = response.json()
        events = normalize_cotrip_records(data)

        # Publish only records in a broad Buckley/Denver-metro radius when
        # coordinates are available. Records without coordinates are retained
        # because some feeds attach roadway names but not point coordinates.
        facility = config["facility"]
        flt = float(facility["latitude"])
        fln = float(facility["longitude"])
        radius = float(c.get("regional_radius_miles", 75))

        regional = []
        for event in events:
            lat = event.get("latitude")
            lon = event.get("longitude")
            if lat is None or lon is None:
                regional.append(event)
                continue
            if haversine_miles(flt, fln, lat, lon) <= radius:
                regional.append(event)

        return {
            "connected": True,
            "reason": f"Loaded {len(regional)} regional roadway records from the configured COtrip developer feed.",
            "events": regional,
        }
    except Exception as exc:
        return {
            "connected": False,
            "reason": f"COtrip feed could not be loaded: {exc}",
            "events": [],
        }


def point_to_corridor_distance_miles(point, start, end, samples=20):
    """Approximate distance to the straight origin-to-Buckley corridor."""
    best = None
    for i in range(samples + 1):
        t = i / samples
        lat = start["lat"] + (end["lat"] - start["lat"]) * t
        lon = start["lon"] + (end["lon"] - start["lon"]) * t
        d = haversine_miles(point["lat"], point["lon"], lat, lon)
        best = d if best is None else min(best, d)
    return best



def evaluate(config):
    facility = config["facility"]
    settings = config["settings"]

    lat = float(facility["latitude"])
    lon = float(facility["longitude"])
    icao = facility.get("icao")

    point, hourly, forecast, grid = nws_point_data(lat, lon)
    point_props = point.get("properties", {})
    zone = (point_props.get("forecastZone") or "").split("/")[-1] or None

    metar = fetch_metar(icao)
    taf = fetch_taf(icao)
    alerts = merge_alerts(fetch_point_alerts(lat, lon), fetch_zone_alerts(zone))

    gp = grid.get("properties", {})
    gusts = value_series(gp.get("windGust"), "wind", 24)
    precip = value_series(gp.get("quantitativePrecipitation"), "precip", 168)
    snow = value_series(gp.get("snowfallAmount"), "snow", 168)
    ice = value_series(gp.get("iceAccumulation"), "ice", 168)

    peak_gust = max(gusts) if gusts else None
    if metar and metar.get("gust_kt") is not None:
        peak_gust = max(peak_gust or 0, metar["gust_kt"])

    precip_7d = round(sum(precip), 2)
    snow_7d = round(sum(snow), 2)
    ice_7d = round(sum(ice), 2)

    periods = hourly.get("properties", {}).get("periods", []) or []
    thunder_cutoff = now_utc() + timedelta(hours=settings["thunder_watch_hours"])
    thunder_soon = False
    winter_soon = False

    for period in periods:
        dt = parse_dt(period.get("startTime"))
        if not dt or dt > thunder_cutoff:
            continue
        text = f"{period.get('shortForecast') or ''} {period.get('detailedForecast') or ''}".lower()
        if "thunder" in text:
            thunder_soon = True
        if any(word in text for word in ("snow", "freezing", "sleet", "ice")):
            winter_soon = True

    if taf:
        thunder_soon = thunder_soon or taf.get("thunder", False)
        winter_soon = winter_soon or taf.get("snow", False) or taf.get("freezing_precip", False)

    wildfires = fetch_wildfires_near(
        lat,
        lon,
        max_miles=settings.get("wildfire_watch_miles", 50),
    )

    status = "normal"
    reasons = []

    def add(level, title, detail, action):
        nonlocal status
        status = max_level(status, level)
        reasons.append({
            "level": level,
            "title": title,
            "detail": detail,
            "action": action,
        })

    for alert in alerts:
        event = alert["event"]
        source = alert.get("source", "NWS")
        if event in CLOSE_EVENTS:
            add(
                "close",
                event,
                alert["headline"] or event,
                f"Critical official alert. Follow the installation emergency or closure procedure. Source: {source}.",
            )
        elif event in ACTION_EVENTS:
            add(
                "action",
                event,
                alert["headline"] or event,
                f"Review and implement the approved protective action. Source: {source}.",
            )
        elif event in WATCH_EVENTS:
            add(
                "watch",
                event,
                alert["headline"] or event,
                f"Monitor updates and prepare continuity or access measures. Source: {source}.",
            )

    if peak_gust is not None:
        mph = kt_to_mph(peak_gust)
        if peak_gust >= settings["wind_close_kt"]:
            add("close", "Strong wind threshold reached",
                f"Observed or forecast gusts may reach about {mph:.0f} mph ({peak_gust:.0f} kt).",
                "Follow the approved high-wind closure or restriction procedure.")
        elif peak_gust >= settings["wind_action_kt"]:
            add("action", "Strong winds expected",
                f"Observed or forecast gusts may reach about {mph:.0f} mph ({peak_gust:.0f} kt).",
                "Secure vulnerable assets and review gate, flightline, and outdoor-work restrictions.")
        elif peak_gust >= settings["wind_watch_kt"]:
            add("watch", "Wind may affect operations",
                f"Observed or forecast gusts may reach about {mph:.0f} mph ({peak_gust:.0f} kt).",
                "Monitor wind conditions and prepare for outdoor or access restrictions.")

    if snow_7d >= settings["snow_close_in"]:
        add("close", "Heavy snow test threshold reached",
            f"The 7-day point forecast contains about {snow_7d:.1f} inches of snow.",
            "Follow approved severe-snow continuity and closure procedures.")
    elif snow_7d >= settings["snow_action_in"]:
        add("action", "Significant snow expected",
            f"The 7-day point forecast contains about {snow_7d:.1f} inches of snow.",
            "Prepare snow response, staffing, gate access, and essential-personnel continuity plans.")
    elif snow_7d >= settings["snow_watch_in"]:
        add("watch", "Snow may affect operations",
            f"The 7-day point forecast contains about {snow_7d:.1f} inches of snow.",
            "Monitor forecast changes and begin access and snow-response planning.")

    if ice_7d >= settings.get("ice_action_in", 0.15):
        add("action", "Ice accumulation may affect access",
            f"The 7-day point forecast contains about {ice_7d:.2f} inches of ice accumulation.",
            "Review essential-personnel travel, gate access, walking surfaces, and delayed-reporting plans.")
    elif ice_7d >= settings.get("ice_watch_in", 0.05):
        add("watch", "Ice is possible",
            f"The 7-day point forecast contains about {ice_7d:.2f} inches of ice accumulation.",
            "Monitor road and walking-surface impacts, especially bridges and elevated surfaces.")

    if precip_7d >= settings["precip_action_in"]:
        add("action", "Heavy precipitation outlook",
            f"About {precip_7d:.1f} inches of liquid precipitation is represented in the 7-day outlook.",
            "Review drainage, localized flooding, outdoor work, and access concerns.")
    elif precip_7d >= settings["precip_watch_in"]:
        add("watch", "Wet weather may affect operations",
            f"About {precip_7d:.1f} inches of liquid precipitation is represented in the 7-day outlook.",
            "Monitor drainage, access, and outdoor-work conditions.")

    if thunder_soon:
        add("watch", "Thunderstorms may affect Buckley",
            f"A thunderstorm signal appears in the next {settings['thunder_watch_hours']} hours.",
            "Monitor official warnings and the installation lightning procedure. This tool does not measure live strike distance.")

    if wildfires:
        nearest = wildfires[0]
        if nearest["distance_miles"] <= settings.get("wildfire_action_miles", 20):
            add("action", "Active wildfire nearby",
                f"{nearest['name']} is reported about {nearest['distance_miles']:.0f} miles from Buckley in NIFC data.",
                "Review smoke, access, evacuation, air-quality, and continuity implications with official incident information.")
        else:
            add("watch", "Wildfire activity in the region",
                f"The nearest current NIFC incident is {nearest['name']}, about {nearest['distance_miles']:.0f} miles away.",
                "Monitor fire weather, smoke, and incident movement if conditions worsen.")

    forecast_cards = []
    for p in forecast.get("properties", {}).get("periods", [])[:10]:
        forecast_cards.append({
            "name": p.get("name"),
            "temperature": p.get("temperature"),
            "temperatureUnit": p.get("temperatureUnit"),
            "shortForecast": p.get("shortForecast"),
            "windSpeed": p.get("windSpeed"),
            "windDirection": p.get("windDirection"),
        })

    # This is a planning inference, not a report of fire/EMS staffing.
    strain_score = 0
    strain_reasons = []
    if snow_7d >= 2:
        strain_score += 2
        strain_reasons.append("snow may increase crashes and travel delays")
    if ice_7d >= 0.03 or winter_soon:
        strain_score += 2
        strain_reasons.append("ice or wintry precipitation may increase roadway incidents")
    if peak_gust and kt_to_mph(peak_gust) >= 35:
        strain_score += 1
        strain_reasons.append("strong winds may produce debris, outages, or difficult travel")
    if thunder_soon:
        strain_score += 1
        strain_reasons.append("thunderstorms may create localized high-impact calls")
    if precip_7d >= 2:
        strain_score += 1
        strain_reasons.append("heavy precipitation may increase flooding or crash risk")
    if wildfires and wildfires[0]["distance_miles"] <= 30:
        strain_score += 2
        strain_reasons.append("nearby wildfire activity may increase public-safety workload")

    resource_strain = "LOW"
    if strain_score >= 4:
        resource_strain = "HIGH"
    elif strain_score >= 2:
        resource_strain = "ELEVATED"

    return {
        "name": facility["name"],
        "icao": icao,
        "latitude": lat,
        "longitude": lon,
        "zone": zone,
        "gate_address": facility.get("gate_address"),
        "status": status,
        "status_copy": STATUS_COPY[status],
        "reasons": reasons,
        "metar": metar,
        "taf": taf,
        "alerts": alerts,
        "wildfires": wildfires[:8],
        "resource_strain": {
            "level": resource_strain,
            "reasons": strain_reasons,
            "note": "Planning inference from weather and wildfire signals; not a live fire/EMS staffing or call-volume feed.",
        },
        "metrics": {
            "peak_gust_24h_kt": peak_gust,
            "peak_gust_24h_mph": kt_to_mph(peak_gust),
            "precip_7d_in": precip_7d,
            "snow_7d_in": snow_7d,
            "ice_7d_in": ice_7d,
            "thunder_next_hours": settings["thunder_watch_hours"] if thunder_soon else None,
        },
        "forecast": forecast_cards,
        "checked_at": iso(now_utc()),
    }


def interval_for(status, settings):
    return settings[f"{status}_check_minutes"]


def render_html(payload):
    data_json = json.dumps(payload).replace("</", "<\\/")
    html = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Buckley Facility Operations</title>
<style>
:root{
  --bg:#eef2f5;--card:#fff;--ink:#17212a;--muted:#66727d;--line:#d9e0e5;
  --normal:#237a4b;--watch:#a87400;--action:#c45a00;--close:#aa271d;--blue:#215b87;
}
*{box-sizing:border-box} body{margin:0;font-family:Arial,Helvetica,sans-serif;background:var(--bg);color:var(--ink)}
.wrap{max-width:1180px;margin:auto;padding:24px}.hero{background:#12263a;color:white;padding:24px;border-radius:18px;margin-bottom:18px}
.hero h1{margin:0 0 7px}.muted,.small{color:var(--muted)}.small{font-size:13px}.notice{background:#fff4d7;border:1px solid #e2c36a;padding:14px;border-radius:12px;margin:16px 0}
.legend,.grid,.links{display:grid;grid-template-columns:repeat(auto-fit,minmax(185px,1fr));gap:10px}.legend-card,.metric,.panel{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px}
.legend-card.normal{border-top:5px solid var(--normal)}.legend-card.watch{border-top:5px solid var(--watch)}.legend-card.action{border-top:5px solid var(--action)}.legend-card.close{border-top:5px solid var(--close)}
.facility{background:var(--card);border:1px solid var(--line);border-radius:18px;overflow:hidden;margin:20px 0;box-shadow:0 3px 12px rgba(0,0,0,.06)}
.banner{padding:22px;color:white;display:flex;justify-content:space-between;gap:20px;flex-wrap:wrap}.banner.normal{background:var(--normal)}.banner.watch{background:var(--watch)}.banner.action{background:var(--action)}.banner.close{background:var(--close)}
.level{font-size:30px;font-weight:900;margin:5px 0}.body{padding:22px}.metric strong{display:block;font-size:22px;margin-top:4px}.reason{border-left:5px solid #aaa;padding:12px 14px;background:#fafafa;margin:9px 0;border-radius:7px}.reason.watch{border-color:var(--watch)}.reason.action{border-color:var(--action)}.reason.close{border-color:var(--close)}.do{font-weight:700;display:block;margin-top:7px}
.alert{background:#fff9e8;border:1px solid #ead6a0;padding:11px;border-radius:9px;margin:8px 0}.forecast{display:grid;grid-template-columns:repeat(auto-fit,minmax(145px,1fr));gap:8px}.forecast>div{border:1px solid var(--line);padding:10px;border-radius:9px;background:#fbfcfd}
h2{margin-top:28px}h3{margin-top:25px}.commute{background:#eaf2f8;border:1px solid #b8cfdf;border-radius:16px;padding:20px;margin:22px 0}.commute-form{display:flex;gap:8px;flex-wrap:wrap}.commute-form input{flex:1;min-width:260px;padding:12px;border:1px solid #aab7c2;border-radius:9px}.commute-form button,.button{background:var(--blue);color:white;border:0;border-radius:9px;padding:11px 15px;text-decoration:none;display:inline-block;cursor:pointer}
.button.secondary{background:#546576}.source-link{display:block;background:white;border:1px solid var(--line);border-radius:10px;padding:12px;text-decoration:none;color:var(--ink)}.source-link strong{display:block;color:var(--blue)}
.strain-low{color:var(--normal)}.strain-elevated{color:var(--watch)}.strain-high{color:var(--close)}
details{margin-top:22px;border-top:1px solid var(--line);padding-top:14px}summary{cursor:pointer;font-weight:700}code{display:block;background:#f5f7f8;padding:10px;border-radius:8px;white-space:pre-wrap;word-break:break-word;font-size:12px}
.footer{margin:28px 0;color:var(--muted);font-size:13px;line-height:1.55}
</style>
</head>
<body>
<div class="wrap">
<div class="hero">
  <h1>Buckley Facility Weather Operations</h1>
  <div>Weather alert and closure decision support for Buckley Space Force Base.</div>
</div>

<div class="notice"><strong>TEST SYSTEM.</strong> Thresholds are placeholders for development and are not approved Buckley Space Force Base operating, reporting, restriction, or closure policy.</div>

<h2>Facility Status Guide</h2>
<div class="legend">
  <div class="legend-card normal"><strong>NORMAL</strong><br>Normal facility operations. Continue routine monitoring.</div>
  <div class="legend-card watch"><strong>WATCH</strong><br>Weather could affect facility operations. Monitor and prepare.</div>
  <div class="legend-card action"><strong>ACTION</strong><br>A significant facility weather condition is reached or expected. Take the approved protective action.</div>
  <div class="legend-card close"><strong>CLOSE CRITERIA MET</strong><br>A test closure threshold or critical official warning is reached. Follow approved closure procedures.</div>
</div>

<div id="facility"></div>

<div class="notice" style="background:#e8eef4;border-color:#b8cad8">
<strong>Separate question:</strong> The facility alert above tells you whether Buckley itself may need an operational change. The tool below asks whether essential personnel may have trouble reaching Buckley.
</div>

<div class="commute">
  <h2>Can Essential Personnel Get Here?</h2>
  <p>Enter any U.S. origin address. The tool locates that address, calculates a driving route to Buckley, checks NWS weather along the route, and compares that route with the latest COtrip incidents, road conditions, planned events, roadside weather stations, snow plows, travel times, signs, Connected Work Zone data, and WZDx data.</p>
  <div class="commute-form">
    <input id="origin" aria-label="Commute origin" placeholder="Enter a home, school, or other address">
    <button onclick="checkCommute()">Check access to Buckley</button>
  </div>
  <div class="small" style="margin-top:8px">Default example: __DEFAULT_ORIGIN__. Your last search is stored only in this browser.</div>
  <div id="cotripConnection" class="small" style="margin-top:12px"></div>
  <div id="commuteResult" style="margin-top:16px"></div>
</div>

<h2>Official Access & Situational-Awareness Sources</h2>
<div class="links">
  <a class="source-link" href="https://www.cotrip.org/" target="_blank" rel="noopener"><strong>COtrip / CDOT</strong>Actual Colorado road conditions, closures, construction, and travel information.</a>
  <a class="source-link" href="https://www.weather.gov/bou/winter" target="_blank" rel="noopener"><strong>NWS Probabilistic Winter Planning</strong>Snow and ice ranges and exceedance probabilities for planning.</a>
  <a class="source-link" href="https://www.weather.gov/bou/neco_firedss" target="_blank" rel="noopener"><strong>NWS Fire Weather Decision Support</strong>Point and regional fire-weather planning.</a>
  <a class="source-link" href="https://disasteralert.pdc.org/disasteralert/" target="_blank" rel="noopener"><strong>DisasterAWARE Public</strong>Broader multi-hazard situational awareness.</a>
  <a class="source-link" href="https://www.nifc.gov/nicc/incident-information/national-incident-map" target="_blank" rel="noopener"><strong>NIFC Current Incidents</strong>Authoritative current wildland-fire incident information.</a>
</div>

<div class="small" style="margin-top:14px">Address search uses OpenStreetMap Nominatim. © OpenStreetMap contributors.</div>
<div class="footer">
This dashboard combines exact-point NWS data, the NWS forecast zone derived from Buckley's coordinates, KBKF airport observations/forecast information, and current NIFC wildfire incidents. The access tool attempts to calculate a driving route to Buckley, checks NWS weather along it, and compares it with the latest cached COtrip roadway information. Use COtrip itself for authoritative roadway information. This test version intentionally omits local-specific alert ingestion and focuses on NWS, aviation weather, wildfire, and optional COtrip roadway data.
</div>
</div>

<script>
const DATA=__DATA__;
const e=s=>String(s??'').replace(/[&<>"]/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[m]));
const BUCKLEY={lat:DATA.facility.latitude,lon:DATA.facility.longitude};
const COTRIP=DATA.cotrip||{connected:false,reason:'COtrip feed not configured.',events:[],feeds:{}};
const feedSummary=Object.entries(COTRIP.feeds||{}).map(([k,v])=>`${v.ok?'✓':'○'} ${k.replaceAll('_',' ')}${v.ok&&v.records!=null?' ('+v.records+')':''}`).join(' · ');
document.getElementById('cotripConnection').innerHTML =
  COTRIP.connected
    ? '<strong>COtrip layers:</strong> connected. '+e(COTRIP.reason||'')+'<br>'+e(feedSummary)
    : '<strong>COtrip layers:</strong> not connected. '+e(COTRIP.reason||'The facility alert still works with NWS and KBKF data.')+'<br>'+e(feedSummary);

function renderFacility(r){
  const m=r.metrics||{},met=r.metar||{},taf=r.taf||{},sc=r.status_copy||{};
  const reasons=(r.reasons||[]).length?r.reasons.map(x=>`<div class="reason ${e(x.level)}"><b>${e(x.title)}</b><br>${e(x.detail)}<span class="do">What to do: ${e(x.action)}</span></div>`).join(''):'<p class="muted">No configured test threshold is currently triggered.</p>';
  const alerts=(r.alerts||[]).length?r.alerts.map(a=>`<div class="alert"><b>${e(a.event)}</b><br>${e(a.headline||'Official NWS alert')}<br><span class="small">${e(a.source||'NWS')}</span></div>`).join(''):'<p class="muted">No active official NWS alerts found for the exact Buckley point or its derived forecast zone.</p>';
  const forecast=(r.forecast||[]).map(p=>`<div><b>${e(p.name)}</b><br>${e(p.temperature)}°${e(p.temperatureUnit)}<br>${e(p.shortForecast)}<br><span class="small">${e(p.windSpeed)} ${e(p.windDirection)}</span></div>`).join('');
  const fires=(r.wildfires||[]).length?r.wildfires.map(f=>`<div class="alert"><b>${e(f.name)}</b> · about ${e(f.distance_miles)} mi away${f.acres?` · ${e(f.acres)} acres`:''}</div>`).join(''):'<p class="muted">No current NIFC wildfire incident points found within the configured regional screening radius.</p>';
  const strain=r.resource_strain||{level:'LOW',reasons:[]};
  const strainClass='strain-'+String(strain.level).toLowerCase();

  return `<section class="facility">
    <div class="banner ${e(r.status)}">
      <div><div class="small" style="font-weight:800;letter-spacing:.08em;color:rgba(255,255,255,.9)">FACILITY ALERT</div><div class="small">${e(r.name)} · ${e(r.icao)} · exact point ${e(r.latitude)}, ${e(r.longitude)} · NWS zone ${e(r.zone||'derived')}</div><div class="level">${e(sc.label||r.status)}</div><div>${e(sc.summary||'')}</div></div>
      <div>Next check: ${e(r.next_check_minutes)} min<br><span class="small">Last checked ${e(new Date(r.checked_at).toLocaleString())}</span></div>
    </div>
    <div class="body">
      <h3>What should the facility manager do?</h3><p><strong>${e(sc.action||'Review current conditions and policy.')}</strong></p>
      <h3>Current Buckley Conditions</h3>
      <div class="grid">
        <div class="metric">Temperature<strong>${met.temperature_f==null?'—':e(met.temperature_f)+'°F'}</strong></div>
        <div class="metric">Current wind<strong>${met.wind_mph==null?'—':e(met.wind_mph)+' mph'}</strong></div>
        <div class="metric">Current gust<strong>${met.gust_mph==null?'—':e(met.gust_mph)+' mph'}</strong></div>
        <div class="metric">Visibility<strong>${met.visibility_sm==null?'—':e(met.visibility_sm)+' mi'}</strong></div>
      </div>
      <h3>Planning Outlook</h3>
      <div class="grid">
        <div class="metric">Peak gust, 24h<strong>${m.peak_gust_24h_mph==null?'—':e(Math.round(m.peak_gust_24h_mph))+' mph'}</strong></div>
        <div class="metric">Snow, 7 days<strong>${e(m.snow_7d_in??0)} in</strong></div>
        <div class="metric">Ice, 7 days<strong>${e(m.ice_7d_in??0)} in</strong></div>
        <div class="metric">Precipitation, 7 days<strong>${e(m.precip_7d_in??0)} in</strong></div>
      </div>
      <h3>Why is Buckley at this level?</h3>${reasons}
      <h3>Official Weather Alerts</h3>${alerts}
      <h3>Potential Public-Safety Resource Strain</h3>
      <p><strong class="${strainClass}">${e(strain.level)}</strong></p>
      <p>${(strain.reasons||[]).length?e(strain.reasons.join('; '))+'.':'No major weather-driven strain signal identified by the test rules.'}</p>
      <p class="small">${e(strain.note||'')}</p>
      <h3>Wildfire Proximity Screen</h3>${fires}
      <h3>7 Day Buckley Outlook</h3><div class="forecast">${forecast}</div>
      <details><summary>Technical airport weather details</summary><p class="small">METAR is the coded current KBKF observation. TAF is the coded short-term airport forecast.</p><b>METAR</b><code>${e(met.raw||'Unavailable')}</code><b>TAF</b><code>${e(taf.raw||'Unavailable')}</code></details>
    </div>
  </section>`;
}
document.getElementById('facility').innerHTML=renderFacility(DATA.facility);

const saved=localStorage.getItem('buckleyCommuteOrigin');
document.getElementById('origin').value=saved||DATA.commute.default_origin_address||'';

function commuteLevelName(n){return ['NORMAL','WATCH','ACTION','ACCESS CRITICAL'][n]||'WATCH';}
function levelColor(n){return ['#237a4b','#a87400','#c45a00','#aa271d'][n]||'#a87400';}

async function geocodeAddress(address){
  const url='https://nominatim.openstreetmap.org/search?format=jsonv2&limit=1&countrycodes=us&q='+encodeURIComponent(address);
  const res=await fetch(url,{headers:{'Accept':'application/json'}});
  if(!res.ok) throw new Error('Address lookup service could not be reached.');
  const data=await res.json();
  const hit=Array.isArray(data)?data[0]:null;
  if(!hit) throw new Error('Address could not be located. Try including street, city, state, and ZIP code.');
  return {
    lat:Number(hit.lat),
    lon:Number(hit.lon),
    label:hit.display_name||address
  };
}

function corridorPoints(a,b,count){
  const pts=[];
  for(let i=0;i<count;i++){
    const t=count===1?0:i/(count-1);
    pts.push({lat:a.lat+(b.lat-a.lat)*t,lon:a.lon+(b.lon-a.lon)*t});
  }
  return pts;
}

async function drivingRoute(origin,dest){
  let server=String(DATA.commute.osrm_server||'https://router.project-osrm.org'); if(server.endsWith('/')) server=server.slice(0,-1);
  const url=`${server}/route/v1/driving/${origin.lon},${origin.lat};${dest.lon},${dest.lat}?overview=full&geometries=geojson&steps=true`;
  const res=await fetch(url);
  if(!res.ok) throw new Error('Routing service unavailable');
  const data=await res.json();
  if(data.code!=='Ok'||!data.routes?.length) throw new Error('No driving route returned');
  const r=data.routes[0];
  return {
    points:r.geometry.coordinates.map(c=>({lon:Number(c[0]),lat:Number(c[1])})),
    minutes:r.duration/60,
    miles:r.distance/1609.344
  };
}

function thinRoute(points,max=70){
  if(points.length<=max)return points;
  const step=Math.ceil(points.length/max);
  const out=points.filter((_,i)=>i%step===0);
  if(out[out.length-1]!==points[points.length-1])out.push(points[points.length-1]);
  return out;
}

function itemRouteDistance(event,routePoints){
  const geom=event.geometry||[];
  if(!geom.length)return Infinity;
  const route=thinRoute(routePoints,70);
  let best=Infinity;
  for(const g of geom){
    const p={lon:Number(g[0]),lat:Number(g[1])};
    if(!Number.isFinite(p.lon)||!Number.isFinite(p.lat))continue;
    for(const r of route)best=Math.min(best,browserHaversine(p,r));
  }
  return best;
}

function activeInLookahead(event){
  const now=Date.now();
  const end=now+Number(DATA.commute.lookahead_hours||12)*3600000;
  const start=event.start?Date.parse(event.start):null;
  const finish=event.end?Date.parse(event.end):null;
  if(start&&start>end)return false;
  if(finish&&finish<now)return false;
  return true;
}

async function nwsPointScreen(pt){
  const pointAlertsUrl=`https://api.weather.gov/alerts/active?point=${pt.lat.toFixed(4)},${pt.lon.toFixed(4)}`;
  const [alertsRes,pointRes]=await Promise.all([
    fetch(pointAlertsUrl,{headers:{'Accept':'application/geo+json'}}),
    fetch(`https://api.weather.gov/points/${pt.lat.toFixed(4)},${pt.lon.toFixed(4)}`,{headers:{'Accept':'application/geo+json'}})
  ]);
  if(!alertsRes.ok||!pointRes.ok) throw new Error('NWS commute data could not be loaded.');
  const alerts=await alertsRes.json();
  const point=await pointRes.json();
  const hourlyUrl=point?.properties?.forecastHourly;
  let periods=[];
  if(hourlyUrl){
    const hr=await fetch(hourlyUrl,{headers:{'Accept':'application/geo+json'}});
    if(hr.ok){const h=await hr.json();periods=h?.properties?.periods||[];}
  }
  const lookahead=Number(DATA.commute.lookahead_hours||12);
  const upcoming=periods.slice(0,lookahead);
  let level=0,reasons=[];
  for(const f of alerts.features||[]){
    const event=f?.properties?.event||'Weather alert';
    if(/Tornado Warning|Flash Flood Warning|Extreme Wind Warning/i.test(event)){level=Math.max(level,3);reasons.push(event);}
    else if(/Warning/i.test(event)){level=Math.max(level,2);reasons.push(event);}
    else if(/Watch|Advisory/i.test(event)){level=Math.max(level,1);reasons.push(event);}
  }
  for(const p of upcoming){
    const text=((p.shortForecast||'')+' '+(p.detailedForecast||'')).toLowerCase();
    if(/snow|freezing|sleet|ice/.test(text)){level=Math.max(level,1);reasons.push('wintry precipitation forecast');}
    if(/thunder/.test(text)){level=Math.max(level,1);reasons.push('thunderstorms forecast');}
    const pop=Number(p?.probabilityOfPrecipitation?.value||0);
    if(pop>=70){level=Math.max(level,1);reasons.push('high precipitation probability');}
  }
  return {level,reasons:[...new Set(reasons)].slice(0,5)};
}


function cotripCorridorScreen(routePoints){
  const radius=Number(DATA.commute.cotrip_corridor_radius_miles||2.5);
  const matched=[];
  for(const event of (COTRIP.events||[])){
    if(['planned_event','work_zone'].includes(event.kind)&&!activeInLookahead(event))continue;
    const d=itemRouteDistance(event,routePoints);
    if(d<=radius)matched.push({...event,corridor_distance_miles:d});
  }
  matched.sort((a,b)=>(Number(b.level||0)-Number(a.level||0))||(a.corridor_distance_miles-b.corridor_distance_miles));
  let level=0;
  const reasons=[];
  for(const event of matched){
    if(event.kind==='snow_plow'||event.kind==='travel_time')continue;
    level=Math.max(level,Number(event.level||0));
    if(Number(event.level||0)>0)reasons.push(`${event.feed}: ${event.description||event.title}`);
  }
  return {level,reasons:[...new Set(reasons)].slice(0,8),events:matched.slice(0,14)};
}

function browserHaversine(a,b){
  const R=3958.7613,toRad=x=>x*Math.PI/180;
  const p1=toRad(a.lat),p2=toRad(b.lat);
  const dlat=toRad(b.lat-a.lat),dlon=toRad(b.lon-a.lon);
  const x=Math.sin(dlat/2)**2+Math.cos(p1)*Math.cos(p2)*Math.sin(dlon/2)**2;
  return R*2*Math.atan2(Math.sqrt(x),Math.sqrt(1-x));
}

function browserCorridorDistance(point,start,end){
  let best=Infinity;
  for(let i=0;i<=20;i++){
    const t=i/20;
    const sample={lat:start.lat+(end.lat-start.lat)*t,lon:start.lon+(end.lon-start.lon)*t};
    best=Math.min(best,browserHaversine(point,sample));
  }
  return best;
}

async function checkCommute(){
  const box=document.getElementById('commuteResult');
  const address=document.getElementById('origin').value.trim();
  if(!address){box.innerHTML='<div class="alert">Enter an origin address.</div>';return;}
  box.innerHTML='<div class="panel">Calculating route and checking NWS and COtrip data…</div>';
  try{
    localStorage.setItem('buckleyCommuteOrigin',address);
    const origin=await geocodeAddress(address);
    const dest={
      lat:Number(DATA.facility.latitude),
      lon:Number(DATA.facility.longitude),
      label:DATA.facility.gate_address||DATA.facility.name
    };

    let route,routeMode='calculated driving route';
    try{
      route=await drivingRoute(origin,dest);
    }catch(_){
      route={points:corridorPoints(origin,dest,28),minutes:null,miles:null};
      routeMode='straight-line fallback because the routing service was unavailable';
    }

    const count=Math.max(3,Math.min(7,Number(DATA.commute.weather_sample_points||5)));
    const thinned=thinRoute(route.points,count);
    const sampleIndexes=[];
    for(let i=0;i<count;i++)sampleIndexes.push(Math.round(i*(thinned.length-1)/(count-1)));
    const pts=[...new Set(sampleIndexes.map(i=>thinned[i]))];
    const screens=await Promise.all(pts.map(nwsPointScreen));
    const weatherLevel=Math.max(0,...screens.map(s=>s.level));
    const weatherReasons=[...new Set(screens.flatMap(s=>s.reasons))];

    const road=cotripCorridorScreen(route.points);
    const level=Math.max(weatherLevel,road.level);
    const reasons=[...new Set([...weatherReasons,...road.reasons])];
    const color=levelColor(level);

    const roadItems=road.events.length
      ? `<h4>COtrip information near this route</h4>`+
        road.events.map(x=>`<div class="alert"><b>${e(x.feed||'COtrip')}</b>${x.road?' · '+e(x.road):''}<br><strong>${e(x.title||'')}</strong><br>${e(x.description||x.detail||'')}<br><span class="small">Approx. ${e(x.corridor_distance_miles.toFixed(1))} mi from calculated route${x.updated?' · updated '+e(new Date(x.updated).toLocaleString()):''}</span></div>`).join('')
      : COTRIP.connected
        ? '<p class="small">No matching COtrip record was found near this route.</p>'
        : '<p class="small">COtrip is not connected yet, so this result currently uses NWS route weather only.</p>';

    const routeInfo=route.minutes!=null
      ? `Calculated route is about ${Math.round(route.miles)} miles and ${Math.round(route.minutes)} minutes before incident-delay adjustment.`
      : 'Route distance and time are unavailable in fallback mode.';

    box.innerHTML=`<div class="panel" style="border-left:6px solid ${color}">
      <div class="small">Matched origin: ${e(origin.label)}<br>Destination: ${e(dest.label)}<br>${e(routeMode)}</div>
      <div class="small" style="font-weight:800;letter-spacing:.08em">ACCESS STATUS</div><h3 style="margin:7px 0">Essential personnel: ${e(commuteLevelName(level))}</h3>
      <p><strong>${e(routeInfo)}</strong></p>
      <p>${reasons.length?e(reasons.join('; '))+'.':'No significant NWS route-weather signal or matching COtrip roadway impact was found.'}</p>
      ${roadItems}
      <p><strong>Important:</strong> COtrip primarily covers Colorado state highways. Local-street conditions may still affect the first or last part of the trip.</p>
      <a class="button" href="https://www.cotrip.org/" target="_blank" rel="noopener">Open COtrip</a>
    </div>`;
  }catch(err){
    box.innerHTML=`<div class="alert"><b>Access check unavailable</b><br>${e(err.message)}</div>`;
  }
}

</script>
</body>
</html>"""
    html = html.replace("__DATA__", data_json)
    html = html.replace("__DEFAULT_ORIGIN__", payload["commute"].get("default_origin_address", ""))
    return html


def main(force=False):
    config = load_json(CONFIG_FILE, {})
    settings = config.get("settings", {})
    old = load_json(STATUS_FILE, {})

    previous = old.get("facility")
    current = now_utc()
    due = force or not previous

    if previous and not due:
        interval = interval_for(previous.get("status", "normal"), settings)
        checked = parse_dt(previous.get("checked_at"))
        due = not checked or current >= checked + timedelta(minutes=interval)

    if not due:
        print("Buckley is not due for a weather check yet.")
        return 0

    try:
        result = evaluate(config)
    except Exception as exc:
        if previous:
            result = dict(previous)
            result["data_error"] = str(exc)
        else:
            facility = config.get("facility", {})
            result = {
                "name": facility.get("name", "Buckley Space Force Base"),
                "icao": facility.get("icao", "KBKF"),
                "latitude": facility.get("latitude"),
                "longitude": facility.get("longitude"),
                "status": "watch",
                "status_copy": STATUS_COPY["watch"],
                "reasons": [{
                    "level": "watch",
                    "title": "Weather data temporarily unavailable",
                    "detail": str(exc),
                    "action": "Use official NWS, COtrip, and installation sources until the next successful update.",
                }],
                "metrics": {},
                "alerts": [],
                "wildfires": [],
                "resource_strain": {"level": "UNKNOWN", "reasons": [], "note": "Data unavailable."},
                "metar": None,
                "taf": None,
                "forecast": [],
                "checked_at": iso(current),
            }

    result["next_check_minutes"] = interval_for(result.get("status", "normal"), settings)
    cotrip = fetch_cotrip_bundle(config)
    settings_for_page = dict(settings)
    settings_for_page["cotrip_corridor_radius_miles"] = config.get("commute", {}).get("cotrip_corridor_radius_miles", 2.5)

    payload = {
        "generated_at": iso(current),
        "facility": result,
        "commute": config.get("commute", {}),
        "cotrip": cotrip,
        "settings": settings_for_page,
    }

    DOCS.mkdir(exist_ok=True)
    STATUS_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    HTML_FILE.write_text(render_html(payload), encoding="utf-8")

    print(f"Dashboard updated: Buckley={result.get('status')}")
    return 0


if __name__ == "__main__":
    sys.exit(main(force="--force" in sys.argv))
