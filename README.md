# Buckley Facility Weather Operations

This is a test decision-support tool for monitoring weather conditions at Buckley Space Force Base and checking whether essential personnel may have weather or roadway problems getting to the installation.

The dashboard is built around two separate questions:

1. **What is happening at Buckley, and does it meet a facility weather threshold?**
2. **Can essential personnel reasonably get to Buckley from a specific starting address?**

Those answers are intentionally kept separate. Conditions at the installation may be normal while an employee's route is affected by snow, ice, an accident, a closure, or another travel hazard.

This is a development tool. The current thresholds are test values and are not approved Buckley Space Force Base policy.

## Facility status

The main dashboard assigns one of four facility levels:

**NORMAL**  
No configured Watch, Action, or Close criteria are currently met.

**WATCH**  
Conditions are beginning to approach a level that may affect operations. Continue monitoring and begin planning.

**ACTION**  
Conditions have reached a configured action threshold or an NWS warning classified at the Action level is active.

**CLOSE CRITERIA MET**  
A configured closure threshold or designated critical NWS warning has been reached. This does not mean the tool is declaring Buckley closed. It means the test criteria for initiating the appropriate closure, restriction, or emergency decision process have been met.

The current criteria can be expanded directly on the dashboard under the Facility Status Guide.

## What the facility monitor checks

The facility assessment currently looks at:

* Wind and wind gusts
* Snow accumulation
* Ice accumulation
* Liquid precipitation
* Thunderstorms
* Visibility and current aviation weather at KBKF
* NWS watches, warnings, and advisories
* Wildfire proximity
* Short-term and seven-day forecast conditions

Buckley is evaluated using its exact configured point:

`39.7017611, -104.7519611`

The NWS forecast zone is derived from that point rather than being manually assigned.

## Weather data flow

The weather portion starts with the NWS `/points` service. Buckley's latitude and longitude are sent to NWS, which returns the Weather Forecast Office, forecast grid, forecast zone, and URLs for the forecast products associated with that exact point.

From there the monitor retrieves the standard forecast, hourly forecast, raw forecast grid data, and active alerts. KBKF aviation observations and terminal forecast information are pulled separately from the Aviation Weather Center.

```text
Buckley latitude / longitude
        |
        v
NWS /points lookup
        |
        +----> NWS 7-day forecast
        +----> NWS hourly forecast
        +----> NWS raw forecast grid data
        +----> NWS forecast zone
        +----> NWS active point and zone alerts
        +----> KBKF METAR + TAF
        +----> Current wildfire incident locations
        |
        v
Threshold and alert evaluation
        |
        v
NORMAL / WATCH / ACTION / CLOSE CRITERIA MET
```

## Public weather and supporting APIs used

The following are the public endpoints currently used by the project. None of these require the private COtrip API key.

### National Weather Service API

Base service:

`https://api.weather.gov`

Official documentation:

`https://www.weather.gov/documentation/services-web-api`

#### Point metadata

```text
https://api.weather.gov/points/{latitude},{longitude}
```

The monitor starts with Buckley's configured latitude and longitude. The response identifies the NWS office, grid point, forecast zone, and URLs for the forecast products that apply to the installation.

The program uses the `forecast`, `forecastHourly`, and `forecastGridData` URLs returned by NWS instead of hard-coding a forecast grid.

#### Seven-day forecast

The URL is supplied by the NWS point response and follows this general form:

```text
https://api.weather.gov/gridpoints/{office}/{gridX},{gridY}/forecast
```

This supplies the forecast periods displayed in the seven-day Buckley outlook.

#### Hourly forecast

```text
https://api.weather.gov/gridpoints/{office}/{gridX},{gridY}/forecast/hourly
```

This supplies hourly forecast periods used for short-term weather evaluation.

#### Raw forecast grid data

```text
https://api.weather.gov/gridpoints/{office}/{gridX},{gridY}
```

This is the underlying digital forecast grid. The monitor uses quantitative grid values for accumulation-related and other threshold calculations.

#### Active alerts for the exact point

```text
https://api.weather.gov/alerts/active?point={latitude},{longitude}
```

This checks for active NWS watches, warnings, and advisories that apply to the exact Buckley point.

#### Active alerts for the derived NWS zone

```text
https://api.weather.gov/alerts/active/zone/{zone}
```

The zone is obtained from the NWS point lookup. Point and zone alerts are merged and de-duplicated before the facility status is evaluated.

The program classifies selected NWS products into Watch, Action, or Close categories. These classifications are stored in `monitor.py`.

### NOAA Aviation Weather Center API

Base service:

`https://aviationweather.gov/api/data`

Official API documentation:

`https://aviationweather.gov/data/api/`

#### KBKF METAR

```text
https://aviationweather.gov/api/data/metar?ids=KBKF&format=json
```

The METAR provides the current aviation observation for KBKF. The monitor uses it as an additional near-facility source for observed conditions such as wind, gusts, and visibility.

#### KBKF TAF

```text
https://aviationweather.gov/api/data/taf?ids=KBKF&format=json
```

The TAF provides the terminal forecast for KBKF. The monitor checks it for short-term signals including thunderstorms, snow, and freezing precipitation.

The NWS point forecast remains the main forecast source. METAR and TAF data add airport-specific observation and short-term forecast context.

### Current wildfire incident data

The monitor queries the current WFIGS/NIFC incident-location ArcGIS service:

```text
https://services3.arcgis.com/T4QMspbfLg3qTGWY/arcgis/rest/services/WFIGS_Incident_Locations_Current/FeatureServer/0/query
```

The query is geographically limited around Buckley. Returned incident coordinates are compared with the installation coordinates and the program calculates the distance to each incident.

Wildfire distance can raise the facility status to Watch or Action under the current test configuration. Wildfire distance by itself does not trigger Close Criteria Met.

## Essential personnel access checker

The second part of the dashboard is the route checker.

A user enters a U.S. starting address. The browser geocodes that address, calculates a driving route to Buckley, samples NWS weather along the route, and compares the route with the roadway information collected by the monitor.

The access result is independent of the facility result:

**NORMAL**  
No significant route hazard was identified by the current checks.

**WATCH**  
Conditions along the route deserve additional attention.

**ACTION**  
A more significant weather or roadway problem is affecting or near the route.

**ACCESS CRITICAL**  
A critical route condition has been identified.

The route checker answers an access question. It does not change the Buckley facility status simply because one employee's route is affected.

## Public services used by the route checker

### OpenStreetMap Nominatim

The test version uses Nominatim to convert the address entered by the user into latitude and longitude coordinates.

`https://nominatim.openstreetmap.org`

The lookup occurs only after the user submits an address. It is not used for autocomplete or bulk geocoding.

### OSRM

The test version uses the public OSRM routing service to calculate the driving route from the geocoded origin to Buckley's stored coordinates.

`https://router.project-osrm.org`

This is being used for development and testing. A production deployment may eventually use a dedicated routing service if stronger availability guarantees or traffic-aware routing are required.

### NWS weather along the route

Weather is sampled at several points along the calculated route.

For each selected route point, the browser uses:

```text
https://api.weather.gov/points/{latitude},{longitude}
```

and:

```text
https://api.weather.gov/alerts/active?point={latitude},{longitude}
```

The point response supplies the hourly forecast URL for that route location. The checker reviews the local hourly forecast and active alerts for conditions that could affect travel, including wintry precipitation, thunderstorms, and significant NWS alert products.

This is why the access result can differ from the facility result. An employee may encounter different weather between the origin and Buckley than is occurring at the installation itself.

## Roadway data

Colorado roadway information is incorporated into the access check through COtrip/CDOT.

The project can evaluate roadway information such as incidents, road conditions, planned events, roadside weather observations, snow-plow locations, travel-time information, highway signs, and work-zone information.

The COtrip API credential is stored in GitHub Actions as:

`COTRIP_API_KEY`

The credential is not written into the generated website or committed to the repository. Specific COtrip request details are intentionally not documented here.

## Threshold configuration

Numerical facility thresholds are stored in:

`facilities.json`

This includes wind, snow, precipitation, ice, thunderstorm, wildfire, and monitoring-interval settings.

The Facility Status Guide on the website is generated from these same configuration values.

For example, changing:

```json
"snow_close_in": 8
```

to:

```json
"snow_close_in": 10
```

changes both the decision threshold and the value displayed in the Close Criteria Met dropdown after the next build. There is not a separate copy of the numerical threshold in the webpage that also needs to be edited.

NWS event classifications are maintained in `monitor.py` through `WATCH_EVENTS`, `ACTION_EVENTS`, and `CLOSE_EVENTS`. The alert names displayed in the Facility Status Guide come from those same sets.

## Monitoring schedule

The GitHub Actions workflow wakes up every five minutes. The facility monitor uses the configured operational level to determine the intended monitoring cadence:

```text
NORMAL    30 minutes
WATCH     15 minutes
ACTION     5 minutes
CLOSE      5 minutes
```

This allows routine conditions to be checked less aggressively while elevated conditions receive more frequent updates.

## GitHub workflow

The project does not require a separate application server.

```text
GitHub Actions starts the monitor
        |
        v
Python retrieves current data
        |
        v
monitor.py evaluates facility conditions
        |
        +----> roadway data is collected for the access tool
        |
        v
Dashboard HTML is generated
        |
        v
GitHub Pages artifact is uploaded
        |
        v
Updated dashboard is deployed
```

The workflow file is:

`.github/workflows/weather-monitor.yml`

It can also be run manually from:

`Actions > Buckley Operations Monitor > Run workflow`

GitHub Pages should be configured as:

`Settings > Pages > Source > GitHub Actions`

## Repository layout

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

`monitor.py` contains the main weather collection, facility decision logic, and generated dashboard.

`facilities.json` contains the facility coordinates and configurable thresholds.

`cotrip_integration.py` handles the roadway-data integration.

`weather-monitor.yml` runs the monitor and deploys the generated site.

## Data sources versus reference links

The dashboard includes links to several additional official situational-awareness resources. A link on the page does not necessarily mean that source is being ingested by the decision engine.

For example, DisasterAWARE is currently a reference link only. It is not an automated input to the facility status.

The current version also does not ingest a dedicated lightning-detection network, USGS stream gauges, or FEMA IPAWS as separate decision-engine feeds.

That distinction is intentional so the dashboard does not imply it is automatically monitoring a source that is only being provided to the user for reference.

## Current limitations

This is a prototype and should be treated as decision support rather than an authoritative closure or travel-safety system.

* Facility thresholds are test values, not approved Buckley policy.
* "Close Criteria Met" does not automatically mean the installation is closed.
* Public APIs can be delayed, unavailable, or incomplete.
* NWS forecasts and alerts should still be reviewed in their original products when making significant operational decisions.
* Public Nominatim and OSRM services are being used for low-volume development testing, not as a production service-level architecture.
* Roadway conditions can change faster than the dashboard refresh cycle.
* Snow-plow proximity is context only and is not treated as proof that a roadway is clear or safe.
* The tool does not currently ingest every possible hazard source.

The purpose of the project is to put the most relevant information in one place, apply a consistent set of configurable screening criteria, and make it easier for a human decision-maker to see when conditions warrant closer review.

## Emergency alert APIs

**NWS Active Alerts**  
`https://api.weather.gov/alerts/active?point={latitude},{longitude}`  
`https://api.weather.gov/alerts/active/zone/{zone}`

The monitor checks active NWS alerts for Buckley's exact coordinates (`39.7017611,-104.7519611`) and its derived NWS forecast zone (`COZ040`). Duplicate point/zone alerts are removed. NWS events are then mapped to the configured WATCH, ACTION, or CLOSE criteria. Alert cards also show severity, urgency, certainty, affected area, timing, description, instructions, sender, and the official alert link when provided.

**OpenFEMA IPAWS Archived Alerts**  
`https://www.fema.gov/api/open/v1/IpawsArchivedAlerts`

IPAWS is displayed as archive/demo data only and does not affect facility status. Returned records are filtered for references to **Aurora, Buckley, Adams County, Arapahoe County, Denver County, or Douglas County**. The public archive is not the live IPAWS All-Hazards Information Feed.
