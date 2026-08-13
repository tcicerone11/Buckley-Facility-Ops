import json
import math
import os
import re
from datetime import datetime, timezone
from urllib.parse import urlparse, parse_qsl, urlencode, urlunparse

import requests

UA = "BuckleyFacilityOperations/3.0"
HEADERS = {"User-Agent": UA, "Accept": "application/json, application/geo+json"}

FEED_KEYS = [
    "incidents",
    "road_conditions",
    "planned_events",
    "weather_stations",
    "snow_plows",
    "destinations",
    "signs",
    "connected_work_zone",
    "wzdx",
]

COTRIP_BASE = "https://data.cotrip.org/api/v1"

COTRIP_ENDPOINTS = {
    "incidents": f"{COTRIP_BASE}/incidents",
    "road_conditions": f"{COTRIP_BASE}/roadConditions",
    "planned_events": f"{COTRIP_BASE}/plannedEvents",
    "weather_stations": f"{COTRIP_BASE}/weatherStations",
    "snow_plows": f"{COTRIP_BASE}/snowPlows",
    "destinations": f"{COTRIP_BASE}/destinations",
    "signs": f"{COTRIP_BASE}/signs",
    "connected_work_zone": f"{COTRIP_BASE}/cwz",
    "wzdx": f"{COTRIP_BASE}/wzdx",
}


def haversine_miles(lat1, lon1, lat2, lon2):
    r = 3958.7613
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlon / 2) ** 2
    return r * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def flatten_geometry(geometry):
    if not isinstance(geometry, dict):
        return []
    coords = geometry.get("coordinates")
    if coords is None:
        x, y = geometry.get("x"), geometry.get("y")
        if x is not None and y is not None:
            return [[float(x), float(y)]]
        return []

    out = []

    def walk(obj):
        if (
            isinstance(obj, list)
            and len(obj) >= 2
            and isinstance(obj[0], (int, float))
            and isinstance(obj[1], (int, float))
        ):
            lon, lat = float(obj[0]), float(obj[1])
            if -180 <= lon <= 180 and -90 <= lat <= 90 and not (lon == 0 and lat == 0):
                out.append([lon, lat])
            return
        if isinstance(obj, list):
            for child in obj:
                walk(child)

    walk(coords)
    if len(out) > 80:
        step = max(1, math.ceil(len(out) / 80))
        out = out[::step]
    return out[:80]


def near_facility(geometry, facility, radius):
    pts = flatten_geometry(geometry)
    if not pts:
        return True
    lat = float(facility["latitude"])
    lon = float(facility["longitude"])
    return any(haversine_miles(lat, lon, p[1], p[0]) <= radius for p in pts)


def features(data):
    if isinstance(data, dict):
        for key in ("features", "items", "results", "data"):
            if isinstance(data.get(key), list):
                return data[key]
    return data if isinstance(data, list) else []


def endpoint_map():
    return dict(COTRIP_ENDPOINTS)


def with_query(url, extra):
    parts = urlparse(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query.update(extra)
    return urlunparse(parts._replace(query=urlencode(query)))


def cotrip_get(url):
    key = os.getenv("COTRIP_API_KEY", "").strip()
    if not key:
        raise RuntimeError("COTRIP_API_KEY is not configured.")

    response = requests.get(
        with_query(url, {"apiKey": key}),
        headers=HEADERS,
        timeout=45,
    )
    response.raise_for_status()
    return response.json()


def lane_summary(lane_impacts):
    count = 0
    closed_types = []
    for li in lane_impacts if isinstance(lane_impacts, list) else []:
        try:
            count += int(float(li.get("laneClosures") or 0))
        except (TypeError, ValueError):
            pass
        closed_types.extend(li.get("closedLaneTypes") or [])
    return count, closed_types


def incident_items(data, facility, radius):
    out = []
    for f in features(data):
        if not isinstance(f, dict):
            continue
        geom = f.get("geometry") or {}
        if not near_facility(geom, facility, radius):
            continue
        p = f.get("properties") or {}
        count, closed = lane_summary(p.get("laneImpacts") or [])
        text = " ".join(str(v) for v in [
            p.get("travelerInformationMessage"), p.get("type"), p.get("severity"),
            p.get("status"), " ".join(map(str, closed))
        ] if v).lower()
        level = 0
        if re.search(r"road(?:way)? closed|all lanes closed|full closure", text):
            level = 3
        elif str(p.get("severity", "")).lower() in {"major", "critical", "severe"} or count > 0 or p.get("hasRampRestriction"):
            level = 2
        elif str(p.get("severity", "")).lower() in {"minor", "moderate"}:
            level = 1
        out.append({
            "feed": "Incidents", "kind": "incident", "level": level,
            "id": p.get("id"), "road": p.get("routeName") or "",
            "direction": p.get("direction") or "", "title": p.get("type") or "Traffic incident",
            "description": p.get("travelerInformationMessage") or "",
            "status": p.get("status") or "", "severity": p.get("severity") or "",
            "start": p.get("startTime"), "end": p.get("clearTime"),
            "updated": p.get("lastUpdated"), "geometry": flatten_geometry(geom),
        })
    return out


def road_condition_items(data, facility, radius):
    out = []
    for f in features(data):
        geom = f.get("geometry") or {}
        if not near_facility(geom, facility, radius):
            continue
        p = f.get("properties") or {}
        cc = p.get("currentConditions") or []
        operator = next((x for x in cc if str(x.get("sourceType", "")).upper() == "OPERATOR"), None)
        forecast = next((x for x in cc if str(x.get("sourceType", "")).upper() == "NDFD"), None)
        selected = operator or (cc[0] if cc else {})
        condition = str(selected.get("conditionDescription") or "")
        extra = str((forecast or {}).get("additionalData") or selected.get("additionalData") or "")
        text = (condition + " " + extra).lower()
        level = 0
        if re.search(r"closed|impassable", text):
            level = 3
        elif re.search(r"icy|ice|snow packed|snowpacked|slush|traction|chains", text):
            level = 2
        elif re.search(r"wet|slick|snow|frost", text):
            level = 1
        out.append({
            "feed": "Road Conditions", "kind": "road_condition", "level": level,
            "id": p.get("id"), "road": p.get("routeName") or "",
            "title": p.get("name") or p.get("nameId") or p.get("routeName") or "Road condition segment",
            "description": condition, "detail": extra,
            "updated": selected.get("updateTime") or (forecast or {}).get("updateTime"),
            "geometry": flatten_geometry(geom),
        })
    return out


def planned_items(data, facility, radius):
    out = []
    for f in features(data):
        geom = f.get("geometry") or {}
        if not near_facility(geom, facility, radius):
            continue
        p = f.get("properties") or {}
        count, closed = lane_summary(p.get("laneImpacts") or [])
        msg = str(p.get("travelerInformationMessage") or "")
        text = (msg + " " + " ".join(map(str, closed))).lower()
        level = 0
        if re.search(r"road closed|full closure|all lanes closed", text):
            level = 3
        elif count > 0 or p.get("hasRampRestriction") or re.search(r"ramp closed|alternating traffic|detour", text):
            level = 2
        elif msg:
            level = 1
        out.append({
            "feed": "Planned Events", "kind": "planned_event", "level": level,
            "id": p.get("id"), "road": p.get("routeName") or "",
            "direction": p.get("direction") or "", "title": p.get("type") or p.get("name") or "Planned roadway event",
            "description": msg, "start": p.get("startTime"), "end": p.get("clearTime"),
            "schedule": p.get("schedule") or [], "updated": p.get("lastUpdated"),
            "geometry": flatten_geometry(geom),
        })
    return out


def weather_station_items(data, facility, radius):
    useful = {
        "temperature", "road surface temperature", "road surface black ice",
        "road surface friction index", "precipitation situation", "precipitation rate",
        "precipitation accumulation 1hr", "visibility", "average wind speed", "gust wind speed",
    }
    out = []
    for f in features(data):
        geom = f.get("geometry") or {}
        if not near_facility(geom, facility, radius):
            continue
        p = f.get("properties") or {}
        if str(p.get("communicationStatus", "")).lower() not in {"", "operational"}:
            continue
        readings = {}
        for s in p.get("sensors") or []:
            st = str(s.get("type") or "").lower()
            if st in useful:
                readings[st] = s.get("currentReading")
        level = 0
        black = str(readings.get("road surface black ice", "")).lower()
        precip = str(readings.get("precipitation situation", "")).lower()
        try:
            surf = float(readings.get("road surface temperature"))
        except (TypeError, ValueError):
            surf = None
        try:
            friction = float(readings.get("road surface friction index"))
        except (TypeError, ValueError):
            friction = None
        if black in {"yes", "true", "detected", "present"}:
            level = 2
        if friction is not None and friction < 0.35:
            level = max(level, 2)
        elif friction is not None and friction < 0.50:
            level = max(level, 1)
        if surf is not None and surf <= 1.0 and precip and "no precipitation" not in precip:
            level = max(level, 2)
        elif surf is not None and surf <= 2.0:
            level = max(level, 1)
        detail = " · ".join(f"{k}: {v}" for k, v in readings.items())
        out.append({
            "feed": "Weather Stations", "kind": "weather_station", "level": level,
            "id": p.get("id"), "road": p.get("routeName") or "",
            "direction": p.get("direction") or "", "title": p.get("publicName") or p.get("name") or "Roadside weather station",
            "description": detail, "updated": p.get("lastUpdated"),
            "geometry": flatten_geometry(geom),
        })
    return out


def snow_plow_items(data, facility, radius):
    out = []
    for f in features(data):
        if not isinstance(f, dict):
            continue
        avl = f.get("avl_location")
        if not isinstance(avl, dict):
            continue
        vehicle = avl.get("vehicle") or {}
        if "snow plow" not in (str(vehicle.get("type", "")) + " " + str(vehicle.get("sub_type", ""))).lower():
            continue
        pos = avl.get("position") or {}
        try:
            lat, lon = float(pos["latitude"]), float(pos["longitude"])
        except (KeyError, ValueError, TypeError):
            continue
        if haversine_miles(float(facility["latitude"]), float(facility["longitude"]), lat, lon) > radius:
            continue
        source = avl.get("source") or {}
        updated = None
        try:
            updated = datetime.fromtimestamp(float(source.get("collection_timestamp")), timezone.utc).isoformat()
        except (TypeError, ValueError, OSError):
            pass
        status = avl.get("current_status") or {}
        out.append({
            "feed": "Snow Plows", "kind": "snow_plow", "level": 0,
            "id": vehicle.get("id"), "road": "", "title": "CDOT snow plow",
            "description": f"{status.get('state','')} {status.get('info','')} · speed {pos.get('speed','—')}",
            "updated": updated, "geometry": [[lon, lat]],
        })
    return out


def destination_items(data, facility, radius):
    out = []
    for f in features(data):
        geom = f.get("geometry") or {}
        if not near_facility(geom, facility, radius):
            continue
        p = f.get("properties") or {}
        try:
            minutes = round(float(p.get("travelTime")) / 60.0, 1)
        except (TypeError, ValueError):
            minutes = None
        out.append({
            "feed": "Destinations", "kind": "travel_time", "level": 0,
            "id": p.get("id"), "road": "",
            "title": p.get("name") or "Travel-time segment",
            "description": f"Current published travel time: {minutes} min" if minutes is not None else "Current travel time unavailable",
            "updated": p.get("lastUpdated"), "geometry": flatten_geometry(geom),
        })
    return out


def sign_items(data, facility, radius):
    out = []
    for f in features(data):
        geom = f.get("geometry") or {}
        if not near_facility(geom, facility, radius):
            continue
        p = f.get("properties") or {}
        if str(p.get("displayStatus", "")).lower() != "on":
            continue
        if str(p.get("communicationStatus", "")).lower() not in {"", "operational"}:
            continue
        msg = re.sub(r"\s+", " ", str(p.get("messageText") or "")).strip()
        text = msg.lower()
        level = 0
        if re.search(r"road closed|closed ahead|closure in effect", text):
            level = 3
        elif re.search(r"closure|detour|restriction|chain|traction|lane closed|lanes closed", text):
            level = 2
        elif msg:
            level = 1
        out.append({
            "feed": "Signs", "kind": "sign", "level": level,
            "id": p.get("id"), "road": p.get("routeName") or "",
            "direction": p.get("direction") or "", "title": p.get("publicName") or p.get("name") or "Electronic sign",
            "description": msg, "updated": p.get("lastUpdated"), "geometry": flatten_geometry(geom),
        })
    return out


def wzdx_items(data, facility, radius, feed_name):
    out = []
    for f in features(data):
        geom = f.get("geometry") or {}
        if not near_facility(geom, facility, radius):
            continue
        p = f.get("properties") or {}
        core = p.get("core_details") or {}
        lanes = p.get("lanes") or []
        impact = str(p.get("vehicle_impact") or "").lower()
        lane_text = " ".join(f"{x.get('type','')} {x.get('status','')}" for x in lanes if isinstance(x, dict)).lower()
        desc = str(core.get("description") or "")
        text = f"{impact} {lane_text} {desc}".lower()
        level = 0
        if impact == "all-lanes-closed" or re.search(r"road closed|all lanes closed", text):
            level = 3
        elif impact == "alternating-one-way":
            level = 2
        elif impact == "some-lanes-closed":
            level = 1
        if re.search(r"exit-ramp.*closed|ramp.*closed|detour", text):
            level = max(level, 2)
        out.append({
            "feed": feed_name, "kind": "work_zone", "level": level,
            "id": f.get("id") or core.get("name"), "road": ", ".join(core.get("road_names") or []),
            "direction": core.get("direction") or "", "title": core.get("name") or "Work zone",
            "description": desc, "start": p.get("start_date"), "end": p.get("end_date"),
            "updated": core.get("update_date"), "geometry": flatten_geometry(geom),
        })
    return out


def dedupe(items):
    seen = set()
    out = []
    for item in items:
        key = (item.get("kind"), item.get("id"), item.get("road"), item.get("start"), item.get("end"))
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def fetch_cotrip_bundle(config):
    c = config.get("cotrip", {})
    if not c.get("enabled", False):
        return {"connected": False, "reason": "COtrip is disabled in facilities.json.", "events": [], "feeds": {}}

    endpoints = endpoint_map()
    if not os.getenv("COTRIP_API_KEY", "").strip():
        return {"connected": False, "reason": "COTRIP_API_KEY is not configured.", "events": [], "feeds": {}}

    facility = config["facility"]
    radius = float(config.get("commute", {}).get("regional_publish_radius_miles", c.get("regional_radius_miles", 100)))

    parsers = {
        "incidents": incident_items,
        "road_conditions": road_condition_items,
        "planned_events": planned_items,
        "weather_stations": weather_station_items,
        "snow_plows": snow_plow_items,
        "destinations": destination_items,
        "signs": sign_items,
    }

    events = []
    statuses = {}
    for key in FEED_KEYS:
        url = endpoints.get(key)
        if not url:
            statuses[key] = {"ok": False, "message": "URL not configured"}
            continue
        try:
            data = cotrip_get(url)
            if key == "connected_work_zone":
                rows = wzdx_items(data, facility, radius, "Connected Work Zone")
            elif key == "wzdx":
                rows = wzdx_items(data, facility, radius, "WZDx")
            else:
                rows = parsers[key](data, facility, radius)
            events.extend(rows)
            statuses[key] = {"ok": True, "records": len(rows)}
        except Exception as exc:
            statuses[key] = {"ok": False, "message": str(exc)[:220]}

    events = dedupe(events)
    good = sum(1 for v in statuses.values() if v.get("ok"))
    configured = sum(1 for key in FEED_KEYS if endpoints.get(key))
    return {
        "connected": good > 0,
        "reason": f"Loaded {good} of {configured or len(FEED_KEYS)} configured COtrip feeds.",
        "events": events,
        "feeds": statuses,
        "connected_feeds": good,
        "configured_feeds": configured,
    }
