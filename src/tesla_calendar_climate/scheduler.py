"""Run loop: read calendar + vehicle state, decide, execute."""
from __future__ import annotations

import json
import logging
import math
import time
from datetime import datetime
from pathlib import Path

from .calendar_client import CalEvent, CalendarError, fetch_events
from .climate import ClimateDecider, Decision, RearmCop, StartClimate, StopClimate, VehicleClimateState
from .config import Settings
from .tesla_client import TeslaApiError, TeslaClient

log = logging.getLogger("tccal")


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def build_states(client, settings: Settings) -> list[VehicleClimateState]:
    states = []
    for vc in settings.vehicles:
        try:
            data = client.ensure_awake(vc.vin)
        except TeslaApiError as exc:
            log.warning("%s: unreachable: %s", vc.name, exc)
            continue
        climate = data.get("climate_state", {}) or {}
        drive = data.get("drive_state", {}) or {}
        shift = drive.get("shift_state")
        parked = shift in ("P", None)
        at_home = False
        lat, lon = drive.get("latitude"), drive.get("longitude")
        if (settings.home_lat is not None and lat and lon):
            at_home = haversine_m(lat, lon, settings.home_lat, settings.home_lon) <= settings.home_radius_m
        states.append(VehicleClimateState(
            vin=vc.vin,
            name=vc.name,
            inside_temp=climate.get("inside_temp"),
            outside_temp=climate.get("outside_temp"),
            is_climate_on=bool(climate.get("is_climate_on")),
            climate_keeper_mode=str(climate.get("climate_keeper_mode", "off")),
            cop_state=climate.get("cabin_overheat_protection"),
            parked=parked,
            at_home=at_home,
        ))
    return states


def load_decider(settings: Settings) -> ClimateDecider:
    decider = ClimateDecider(settings)
    path = Path(settings.state_file).expanduser()
    if path.exists():
        try:
            decider.from_dict(json.loads(path.read_text()))
        except Exception as exc:
            log.warning("Could not load state file: %s", exc)
    return decider


def save_decider(decider: ClimateDecider, settings: Settings) -> None:
    path = Path(settings.state_file).expanduser()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(decider.to_dict(), indent=2))


def execute(client, settings: Settings, decision: Decision) -> None:
    for action in decision.actions:
        if isinstance(action, StartClimate):
            log.info("CLIMATE ON  %s -> %.1f°C (%s)", action.name, action.temp_c, action.reason)
            if not settings.dry_run:
                try:
                    client.set_temps(action.vin, action.temp_c)
                    client.auto_conditioning_start(action.vin)
                except TeslaApiError as exc:
                    log.warning("climate start failed for %s: %s", action.name, exc)
        elif isinstance(action, StopClimate):
            log.info("CLIMATE OFF %s (%s)", action.name, action.reason)
            if not settings.dry_run:
                try:
                    client.auto_conditioning_stop(action.vin)
                except TeslaApiError as exc:
                    log.warning("climate stop failed for %s: %s", action.name, exc)
        elif isinstance(action, RearmCop):
            log.info("COP RE-ARM  %s (%s)", action.name, action.reason)
            if not settings.dry_run:
                try:
                    client.set_cabin_overheat_protection(action.vin, False)
                    time.sleep(2)
                    client.set_cabin_overheat_protection(action.vin, True)
                except TeslaApiError as exc:
                    log.warning("COP re-arm failed for %s: %s", action.name, exc)
    if decision.note:
        log.info("note: %s", decision.note)


def run_once(client, decider: ClimateDecider, settings: Settings,
             now: datetime | None = None,
             events: list[CalEvent] | None = None) -> Decision:
    """Single sense-decide-act pass. `events` overrides the calendar fetch (tests)."""
    now = now or datetime.now().astimezone()
    if events is None:
        if settings.calendar_ics_url:
            try:
                events = fetch_events(settings.calendar_ics_url, now, settings.lookahead_hours)
            except CalendarError as exc:
                log.warning("%s", exc)
                events = []
        else:
            log.warning("TCC_CALENDAR_ICS_URL not set — calendar features disabled")
            events = []
    states = build_states(client, settings)
    for s in states:
        log.info("%-12s in %.0f°C / out %.0f°C climate=%s parked=%s home=%s",
                 s.name, s.inside_temp or 0, s.outside_temp or 0,
                 "on" if s.is_climate_on else "off", s.parked, s.at_home)
    for e in events[:5]:
        log.info("event: %s at %s", e.summary, e.start.strftime("%a %H:%M"))
    decision = decider.decide(states, events, now)
    execute(client, settings, decision)
    save_decider(decider, settings)
    return decision


def run_loop(settings: Settings) -> None:
    client = TeslaClient(
        client_id=settings.client_id, client_secret=settings.client_secret,
        region=settings.region, redirect_uri=settings.redirect_uri,
        token_file=settings.token_file,
    )
    decider = load_decider(settings)
    mode = "DRY-RUN" if settings.dry_run else "LIVE"
    log.info("Tesla Calendar Climate starting (%s), poll every %ds",
             mode, settings.poll_interval_seconds)
    while True:
        try:
            run_once(client, decider, settings)
        except TeslaApiError as exc:
            log.error("Fleet API error: %s", exc)
        except Exception:
            log.exception("Unexpected error in run loop")
        time.sleep(settings.poll_interval_seconds)
