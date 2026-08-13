# Buckley Facility & Essential Personnel Operations

This is the Buckley-specific test project. It keeps facility closure decisions separate from the ability of essential personnel to reach the installation.

## Integrated layers

The project supports:

* NWS exact-point forecasts and active alerts
* KBKF airport observations and TAF
* NIFC current wildfire incidents
* COtrip Incidents
* COtrip Road Conditions
* COtrip Planned Events
* COtrip Weather Stations
* COtrip Snow Plows
* COtrip Destinations / travel times
* COtrip Signs
* COtrip Connected Work Zone
* COtrip WZDx

The address box uses the U.S. Census geocoder. For testing it uses the public OSRM demo router to calculate a driving route to the Buckley gate. If routing fails, the page falls back to a straight geographic corridor and tells the user.

## Confirmed COtrip endpoints

The code uses these confirmed endpoints:

```text
https://data.cotrip.org/api/v1/incidents
https://data.cotrip.org/api/v1/roadConditions
https://data.cotrip.org/api/v1/plannedEvents
https://data.cotrip.org/api/v1/weatherStations
https://data.cotrip.org/api/v1/snowPlows
https://data.cotrip.org/api/v1/destinations
https://data.cotrip.org/api/v1/signs
https://data.cotrip.org/api/v1/cwz
https://data.cotrip.org/api/v1/wzdx
```

The API key is appended privately by Python as the `apiKey` query parameter.

## Files

```text
.github/
  workflows/
    weather-monitor.yml

docs/
  .nojekyll

cotrip_integration.py
facilities.json
monitor.py
requirements.txt
README.md
```

`docs/index.html` and `docs/status.json` are generated automatically when GitHub Actions runs.

## Only one GitHub secret is required

Create this repository secret:

`COTRIP_API_KEY`

Do not place the key in any public repository file.

## GitHub Pages

Under repository Settings > Pages, set:

`Source: GitHub Actions`

Do not use `Deploy from a branch` for this version.

## First run

1. Upload all project files.
2. Add the `COTRIP_API_KEY` Actions secret.
3. Go to Actions.
4. Open `Buckley Operations Monitor`.
5. Click `Run workflow`.
6. Wait for all steps to turn green.
7. Open Settings > Pages and use the generated site URL.

## Access logic

NORMAL means no meaningful route impact is detected.

WATCH can be triggered by an NWS advisory or watch, wet or slick road conditions, some lane closures, or lower-level roadway impacts.

ACTION can be triggered by an NWS warning, major incident, ramp restriction, alternating traffic, icy or snow-packed road conditions, concerning roadside weather observations, or an active restriction/detour message.

ACCESS CRITICAL can be triggered by a critical NWS route warning or a full road/all-lanes closure intersecting the route.

Snow plow locations are context only. A nearby plow is never treated as proof that a road is safe.

Travel-time records are displayed but are not used for severity until a normal baseline is established.

## Update cadence

GitHub Actions wakes every 5 minutes.

Buckley facility weather still uses adaptive intervals from `facilities.json`:

* NORMAL: 30 minutes
* WATCH: 15 minutes
* ACTION: 5 minutes
* CLOSE: 5 minutes

COtrip is fetched on every workflow run.

## Important

This is a development decision-support tool. The thresholds and access scoring rules are not approved Buckley Space Force Base operating, reporting, access, restriction, or closure policy.
