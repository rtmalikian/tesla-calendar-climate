"""Fake fleet + fake calendar for testing and demos. No API calls, no real cars."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta


@dataclass
class FakeVehicle:
    vin: str
    name: str
    inside_temp: float = 35.0
    outside_temp: float = 36.0
    climate_on: bool = False
    keeper_mode: str = "off"
    cop_state: str = "On"
    parked: bool = True
    at_home: bool = True
    target_temp: float = 21.0

    def tick(self, minutes: float) -> None:
        # Cabin drifts toward outside temp when climate is off, toward target when on.
        goal = self.target_temp if self.climate_on else self.outside_temp
        rate = 0.25 if self.climate_on else 0.03  # °C per minute
        diff = goal - self.inside_temp
        step = max(-rate * minutes, min(rate * minutes, diff))
        self.inside_temp += step


@dataclass
class FakeEvent:
    uid: str
    summary: str
    start: datetime
    location: str = ""


class FakeTeslaClient:
    """Stand-in for TeslaClient with the methods the scheduler uses."""

    def __init__(self, vehicles: list[FakeVehicle]):
        self.vehicles = {v.vin: v for v in vehicles}
        self.command_log: list[tuple[str, str]] = []

    def ensure_awake(self, vin: str) -> dict:
        v = self.vehicles[vin]
        # Home is configured at 34.05, -118.25 in tests/demo; away = far away.
        lat, lon = (34.05, -118.25) if v.at_home else (36.5, -121.9)
        return {
            "state": "online",
            "climate_state": {
                "inside_temp": v.inside_temp,
                "outside_temp": v.outside_temp,
                "is_climate_on": v.climate_on,
                "climate_keeper_mode": v.keeper_mode,
                "cabin_overheat_protection": v.cop_state,
            },
            "drive_state": {
                "shift_state": "P" if v.parked else "D",
                "latitude": lat, "longitude": lon,
            },
        }

    def set_temps(self, vin: str, temp_c: float) -> dict:
        self.vehicles[vin].target_temp = temp_c
        self.command_log.append(("set_temps", vin))
        return {"result": True}

    def auto_conditioning_start(self, vin: str) -> dict:
        self.vehicles[vin].climate_on = True
        self.command_log.append(("auto_conditioning_start", vin))
        return {"result": True}

    def auto_conditioning_stop(self, vin: str) -> dict:
        self.vehicles[vin].climate_on = False
        self.command_log.append(("auto_conditioning_stop", vin))
        return {"result": True}

    def set_cabin_overheat_protection(self, vin: str, on: bool) -> dict:
        self.vehicles[vin].cop_state = "On" if on else "Off"
        self.command_log.append(("set_cabin_overheat_protection", vin))
        return {"result": True}

    def tick(self, minutes: float) -> None:
        for v in self.vehicles.values():
            v.tick(minutes)


def run_simulation(vehicles: list[FakeVehicle], events: list[FakeEvent],
                   decider, settings, start: datetime,
                   hours: float = 12.0, tick_minutes: float = 5.0) -> dict:
    """Drive the real scheduler against the fake fleet over virtual time."""
    from .calendar_client import CalEvent
    from .scheduler import run_once

    client = FakeTeslaClient(vehicles)
    cal_events = [CalEvent(uid=e.uid, summary=e.summary, start=e.start,
                           end=e.start + timedelta(hours=1), location=e.location)
                  for e in events]
    now = start
    end = start + timedelta(hours=hours)
    timeline: list[dict] = []
    while now < end:
        decision = run_once(client, decider, settings, now=now, events=cal_events)
        timeline.append({
            "time": now.strftime("%H:%M"),
            "climate": {v.name: v.climate_on for v in vehicles},
            "inside": {v.name: round(v.inside_temp, 1) for v in vehicles},
            "note": decision.note,
            "actions": [(type(a).__name__, a.name) for a in decision.actions],
        })
        client.tick(tick_minutes)
        now += timedelta(minutes=tick_minutes)
    return {"timeline": timeline, "commands": client.command_log,
            "final_inside": {v.name: round(v.inside_temp, 1) for v in vehicles}}
