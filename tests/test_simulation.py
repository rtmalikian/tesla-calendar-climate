"""End-to-end test: fake fleet + fake calendar over virtual time.

Core invariants: climate must start within the lead window before the
event, the cabin must be near target temp at event time, and nothing
happens when the car isn't home.
"""
from datetime import datetime, timedelta

from tesla_calendar_climate.climate import ClimateDecider
from tesla_calendar_climate.config import Settings, VehicleConfig
from tesla_calendar_climate.simulator import FakeEvent, FakeVehicle, run_simulation


def make_settings(**over):
    kw = dict(
        vehicles=[VehicleConfig(name="Model Y", vin="VIN1")],
        home_lat=34.05, home_lon=-118.25, home_radius_m=500.0,
        target_temp_c=21.0, lead_minutes=20, hot_lead_minutes=30, cold_lead_minutes=30,
        hot_threshold_c=30.0, cold_threshold_c=5.0, lookahead_hours=12,
        overrun_minutes=10, cop_rearm=True, cop_max_park_hours=11.0,
    )
    kw.update(over)
    return Settings(**kw)


def test_climate_starts_before_event_on_hot_day():
    start = datetime.now().astimezone().replace(hour=6, minute=0, second=0, microsecond=0)
    vehicles = [FakeVehicle(vin="VIN1", name="Model Y", inside_temp=38.0, outside_temp=36.0)]
    events = [FakeEvent(uid="e1", summary="Dentist", start=start + timedelta(hours=3))]
    settings = make_settings()
    report = run_simulation(vehicles, events, ClimateDecider(settings), settings, start, hours=6.0)

    starts = [c for c in report["commands"] if c[0] == "auto_conditioning_start"]
    assert len(starts) == 1, f"expected exactly one climate start, got {report['commands']}"
    # started within the 30-min hot lead window (08:30–09:00)?
    started_at = next(t["time"] for t in report["timeline"]
                      if any(a[0] == "StartClimate" for a in t["actions"]))
    assert started_at >= "08:30", f"climate started too early: {started_at}"
    # cabin cooled toward target by event time
    assert report["final_inside"]["Model Y"] < 30.0


def test_no_action_when_car_away_from_home():
    start = datetime.now().astimezone().replace(hour=6, minute=0, second=0, microsecond=0)
    vehicles = [FakeVehicle(vin="VIN1", name="Model Y", inside_temp=38.0,
                            outside_temp=36.0, at_home=False)]
    events = [FakeEvent(uid="e1", summary="Dentist", start=start + timedelta(hours=3))]
    settings = make_settings()
    report = run_simulation(vehicles, events, ClimateDecider(settings), settings, start, hours=6.0)
    assert not [c for c in report["commands"] if c[0] == "auto_conditioning_start"]


def test_cop_rearm_fires_on_long_hot_park():
    start = datetime.now().astimezone().replace(hour=6, minute=0, second=0, microsecond=0)
    vehicles = [FakeVehicle(vin="VIN1", name="Model Y", inside_temp=38.0, outside_temp=36.0)]
    settings = make_settings(cop_max_park_hours=0.2)  # re-arm quickly for the test
    decider = ClimateDecider(settings)
    report = run_simulation(vehicles, [], decider, settings, start, hours=2.0)
    rearms = [c for c in report["commands"] if c[0] == "set_cabin_overheat_protection"]
    assert rearms, "expected COP re-arm commands on a long hot park"
