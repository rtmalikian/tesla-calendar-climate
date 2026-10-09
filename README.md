# Tesla Calendar Climate — Automatically Pre-Heat & Pre-Cool Your Tesla Before Calendar Events

**Free, open-source app that reads your calendar and preconditions your Tesla's cabin before appointments — plus keeps Cabin Overheat Protection armed past Tesla's 12-hour cutoff.** Built on the official [Tesla Fleet API](https://developer.tesla.com/docs/fleet-api). Works with Model 3, Model Y, Model S, Model X, and Cybertruck.

## Why?

Tesla's built-in Scheduled Preconditioning only supports **fixed weekly times**, and Smart Preconditioning only learns routines. If your schedule is irregular — dentist at 9, lunch across town at 12:30 — you still walk out to a freezing or baking car. Meanwhile **Cabin Overheat Protection silently shuts off 12 hours after you park**, so cars left at airport lots heat-soak all afternoon and owners never know why.

This app fixes both:

- **Calendar-aware preconditioning** — your Tesla starts heating/cooling itself ahead of every calendar event, with a longer lead time on very hot or very cold days (read from the car's own outside-temp sensor)
- **COP re-arm** — automatically resets Cabin Overheat Protection before Tesla's 12-hour auto-cutoff during long hot parks, and turns COP on if you left it off on a scorcher
- **Home-aware** — only acts while the car is parked at home, so it never preconditions at the office or the mall
- **Free forever** — the only alternatives with automations (Tessie) cost $7–13/month

## How it works

```
36°C day, dentist appointment at 09:00:

06:00  COP re-armed (12h cutoff approaching)
08:30  Climate ON → 21°C (30-min hot-day lead time)
09:00  You walk out to a 25°C cabin instead of 38°C
09:10  Climate hands back off automatically
```

Every few minutes the app:

1. Pulls your upcoming events from your calendar's iCal feed (no OAuth — just a URL)
2. Reads each car's cabin/outside temperature, location, and climate state via the Fleet API
3. Starts preconditioning inside the weather-aware lead window before each event
4. Re-arms Cabin Overheat Protection before the 12-hour cutoff on hot days

## Quickstart

```bash
git clone https://github.com/rtmalikian/tesla-calendar-climate.git
cd tesla-calendar-climate
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 1. Configure (secrets stay local — .env is git-ignored)
cp .env.example .env
nano .env   # Tesla API keys, VINs, calendar iCal URL, home coordinates

# 2. Authorize with your Tesla account (one-time)
tccal auth

# 3. Install the virtual key on each car (one-time)
tccal pairing

# 4. Watch it work on a fake hot day — no API calls, no real cars
tccal simulate

# 5. Single safe pass against your real cars
TCC_DRY_RUN=true tccal run --once

# 6. Run the daemon
tccal run
```

## Tesla developer setup (one-time, ~15 minutes)

**1. Register a developer app** at [developer.tesla.com](https://developer.tesla.com) and request these scopes:

- `vehicle_device_data` — read temperatures, location, climate state
- `vehicle_location` — know when the car is home
- `vehicle_cmds` — climate commands
- `vehicle_charging_cmds` — (reserved for future energy-aware features)

**2. Run `tccal auth`** and sign in with the Tesla account that owns the cars.

**3. Install the app's virtual key** on each car (`tccal pairing` prints the steps): host your public key,
register it via `POST /api/1/partner_accounts`, then approve it at `https://www.tesla.com/_ak/<your-domain>`
from each car's touchscreen.

## Configuration (`.env` reference)

| Variable | Default | What it does |
|---|---|---|
| `TESLA_CLIENT_ID` / `TESLA_CLIENT_SECRET` | — | From developer.tesla.com |
| `TESLA_REGION` | `na` | `na`, `eu`, or `cn` |
| `TCC_VEHICLES` | — | `name=VIN,...` — supports multiple Teslas |
| `TCC_CALENDAR_ICS_URL` | — | Secret iCal URL (Google Calendar → Settings → "Secret address in iCal format") |
| `TCC_HOME_LAT` / `TCC_HOME_LON` | — | Your home coordinates (right-click in Google Maps) |
| `TCC_HOME_RADIUS_M` | `200` | What counts as "home" |
| `TCC_TARGET_TEMP_C` | `21` | Cabin target when preconditioning |
| `TCC_LEAD_MINUTES` | `20` | Preconditioning lead time |
| `TCC_HOT_LEAD_MINUTES` / `TCC_COLD_LEAD_MINUTES` | `30` | Longer lead on extreme days |
| `TCC_HOT_THRESHOLD_C` / `TCC_COLD_THRESHOLD_C` | `30` / `5` | What counts as extreme |
| `TCC_LOOKAHEAD_HOURS` | `12` | How far ahead to watch for events |
| `TCC_OVERRUN_MINUTES` | `10` | Climate stays on this long past event start |
| `TCC_COP_REARM` | `true` | Re-arm Cabin Overheat Protection before the 12h cutoff |
| `TCC_DRY_RUN` | `false` | Log actions without sending commands |

## Try before you connect: `tccal simulate`

No Tesla account needed — simulates a 36°C day with a 9 AM appointment against a virtual car:

```
06:00  False  38.0  Model Y: COP 12h cutoff approaching (last arm never) — re-arming
08:30  True   36.0  Model Y: preconditioning for 'Dentist appointment'
09:15  False  24.8  Model Y: preconditioning done
```

## FAQ

**Does this replace Tesla's Scheduled Departure?**
No — it complements it. Scheduled Departure handles your fixed commute; this handles everything
irregular on your calendar, with weather-aware timing Tesla doesn't offer.

**Will preconditioning drain my battery?**
Preconditioning uses ~2–4% of battery on extreme days. The app only runs while parked at home
(where you're usually plugged in) and stops itself after the event.

**Why does Cabin Overheat Protection stop working?**
Tesla turns COP off 12 hours after you park (and in Low Power Mode). Most owners don't know —
this app re-arms it automatically on hot days so airport-parked cars don't heat-soak.

**Which calendars work?**
Any calendar with an iCal feed URL: Google Calendar, Apple Calendar (via its published URL),
Outlook. Recurring events (daily/weekly) are supported.

**What does it cost to run?**
Tesla's Fleet API is pay-per-use with a $10/month developer credit per account — a
calendar-climate poller fits comfortably inside it, so effectively $0.

**Multiple Teslas?**
Yes — list them all in `TCC_VEHICLES`; each home-parked car is preconditioned independently.

## Development

```bash
PYTHONPATH=src python -m pytest tests/ -q   # 19 tests incl. full-day simulation
```

## License

MIT — see [LICENSE](LICENSE).
