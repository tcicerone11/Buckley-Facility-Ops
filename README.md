# Buckley Facility Weather Operations + Essential Personnel Access

This version restores the original **Facilities Weather** concept as the main dashboard and adds the COtrip commute layer underneath it.

## Primary question: should Buckley change facility operations?

The first and most prominent section is the Buckley facility alert:

* NORMAL
* WATCH
* ACTION
* CLOSE CRITERIA MET

It uses Buckley's exact coordinates, NWS point and zone alerts, NWS forecast data, KBKF current aviation observations and forecast, configurable wind/snow/ice/precipitation thresholds, and nearby wildfire information.

The facility status remains the primary alert system and uses the adaptive monitoring cadence in `facilities.json`.

## Secondary question: can essential personnel get here?

Under the facility alert is the separate access checker:

* NORMAL
* WATCH
* ACTION
* ACCESS CRITICAL

A user can type an address. The page attempts to calculate the driving route to Buckley, checks weather along that route, and compares it with the cached COtrip layers.

COtrip feeds built into the project:

* Incidents
* Road Conditions
* Planned Events
* Weather Stations
* Snow Plows
* Destinations / travel times
* Signs
* Connected Work Zone
* WZDx

The two statuses are independent. Buckley can be NORMAL while an employee route is ACTION or ACCESS CRITICAL.

## One GitHub secret

Only this Actions secret is required:

`COTRIP_API_KEY`

The confirmed COtrip endpoints are built into `cotrip_integration.py`. The key is appended privately by Python and is never embedded in the public HTML.

## Repository files

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

## GitHub Pages

Set repository:

Settings > Pages > Source > GitHub Actions

Then run:

Actions > Buckley Operations Monitor > Run workflow

The workflow generates the HTML and deploys it directly to GitHub Pages.

## Important

This is a development decision-support system. The thresholds and access scoring rules are test rules and are not approved Buckley Space Force Base policy.


## Route lookup fix

The previous browser version used the U.S. Census geocoder. The Census geocoder does not support browser CORS requests, which caused the access checker to stop with a fetch error.

This version uses OpenStreetMap Nominatim only when the user presses the access-check button. It then uses Buckley's stored coordinates directly as the destination, so Buckley itself does not need to be geocoded.

The route process is:

```text
Entered address
    ↓
Nominatim address lookup
    ↓
OSRM driving route to Buckley coordinates
    ↓
NWS weather sampled along route
    +
COtrip hazards intersecting/near route
    ↓
NORMAL / WATCH / ACTION / ACCESS CRITICAL
```

Nominatim usage is user initiated and should remain low volume. Do not add autocomplete or bulk address searches to the public Nominatim service.
