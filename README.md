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


## Facility Status Guide dropdowns stay synchronized with the decision engine

The NORMAL, WATCH, ACTION, and CLOSE CRITERIA MET boxes on the website are expandable and show the criteria currently used by the facility alert engine.

The numerical descriptions in those dropdowns are generated from the **same `settings` values in `facilities.json` that Python uses to make the facility-status decision**. They are not a second hard-coded set of thresholds in the HTML.

This means the website automatically stays synchronized with configuration changes. For example, if:

```json
"snow_close_in": 8
```

is later changed to:

```json
"snow_close_in": 10
```

the CLOSE CRITERIA MET dropdown will automatically display 10 inches the next time the dashboard is generated. There is no separate HTML threshold that also needs to be edited.

The NWS event names shown in the WATCH, ACTION, and CLOSE dropdowns are likewise generated from the same `WATCH_EVENTS`, `ACTION_EVENTS`, and `CLOSE_EVENTS` classifications used by `monitor.py`.

For future policy changes, edit numerical thresholds in `facilities.json`. If the official classification of an NWS alert should change, edit the corresponding event set in `monitor.py`.
