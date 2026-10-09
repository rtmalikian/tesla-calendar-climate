"""Unit tests for the climate decision logic."""
from datetime import datetime, timedelta

from tesla_calendar_climate.calendar_client import CalEvent
from tesla_calendar_climate.climate import ClimateDecider, RearmCop, StartClimate, StopClimate, VehicleClimateState
from tesla_calendar_climate.config import Settings, VehicleConfig

NOW = datetime.now().astimezone().replace(hour=8, minute=0, second=0, microsecond=0)


def make_settings(**over):
    kw = dict(
        vehicles=[VehicleConfig(name="Model Y", vin="VIN1")],
        target_temp_c=21.0, lead_minutes=20, hot_lead_minutes=30, cold_lead_minutes=30,
        hot_threshold_c=30.0, cold_threshold_c=5.0, lookahead_hours=12,
        overrun_minutes=10, cop_rearm=True, cop_max_park_hours=11.0,
    )
    kw.update(over)
    return Settings(**kw)


def state(**over):
    kw = dict(vin="VIN1", name="Model Y", inside_temp=35.0, outside_temp=36.0,
              is_climate_on=False, climate_keeper_mode="off", cop_state="On",
              parked=True, at_home=True)
    kw.update(over)
    return VehicleClimateState(**kw)


def event(start, summary="Dentist"):
    return CalEvent(uid=f"{summary}@{start.isoformat()}", summary=summary,
                    start=start, end=start + timedelta(hours=1), location="")


def test_precondition_starts_with_hot_lead_time():
    d = ClimateDecider(make_settings())
    ev = event(NOW + timedelta(minutes=25))  # within 30-min hot lead, outside 20-min normal lead
    dec = d.decide([state(outside_temp=36.0)], [ev], NOW)
    starts = [a for a in dec.actions if isinstance(a, StartClimate)]
    assert len(starts) == 1 and starts[0].temp_c == 21.0


def test_no_precondition_too_early():
    d = ClimateDecider(make_settings())
    ev = event(NOW + timedelta(hours=3))
    dec = d.decide([state(outside_temp=36.0)], [ev], NOW)
    assert not [a for a in dec.actions if isinstance(a, StartClimate)]


def test_no_precondition_when_car_not_home():
    d = ClimateDecider(make_settings())
    ev = event(NOW + timedelta(minutes=10))
    dec = d.decide([state(at_home=False, outside_temp=36.0)], [ev], NOW)
    assert not [a for a in dec.actions if isinstance(a, StartClimate)]


def test_no_precondition_when_not_parked():
    d = ClimateDecider(make_settings())
    ev = event(NOW + timedelta(minutes=10))
    dec = d.decide([state(parked=False, outside_temp=36.0)], [ev], NOW)
    assert not [a for a in dec.actions if isinstance(a, StartClimate)]


def test_no_precondition_without_events():
    d = ClimateDecider(make_settings())
    dec = d.decide([state(outside_temp=36.0)], [], NOW)
    assert not [a for a in dec.actions if isinstance(a, StartClimate)]


def test_cold_day_uses_cold_lead_time():
    d = ClimateDecider(make_settings())
    ev = event(NOW + timedelta(minutes=25))  # within 30-min cold lead
    dec = d.decide([state(outside_temp=-2.0, inside_temp=2.0)], [ev], NOW)
    assert any(isinstance(a, StartClimate) for a in dec.actions)


def test_precondition_stops_after_overrun():
    d = ClimateDecider(make_settings())
    ev = event(NOW - timedelta(minutes=30))  # event started 30 min ago
    d.preconditioning["VIN1"] = ev.uid  # we started it earlier
    dec = d.decide([state(is_climate_on=True, outside_temp=36.0)], [ev],
                   NOW)
    stops = [a for a in dec.actions if isinstance(a, StopClimate)]
    assert len(stops) == 1
    assert "VIN1" not in d.preconditioning


def test_cop_rearm_after_11h_in_heat():
    d = ClimateDecider(make_settings())
    d.last_cop_arm["VIN1"] = NOW - timedelta(hours=12)
    dec = d.decide([state(outside_temp=36.0, cop_state="On")], [], NOW)
    rearms = [a for a in dec.actions if isinstance(a, RearmCop)]
    assert len(rearms) == 1


def test_cop_turned_on_when_off_in_heat():
    d = ClimateDecider(make_settings())
    dec = d.decide([state(outside_temp=36.0, cop_state="Off")], [], NOW)
    rearms = [a for a in dec.actions if isinstance(a, RearmCop)]
    assert len(rearms) == 1
    assert "off" in rearms[0].reason.lower()


def test_no_cop_rearm_when_mild():
    d = ClimateDecider(make_settings())
    dec = d.decide([state(outside_temp=22.0, cop_state="On")], [], NOW)
    assert not [a for a in dec.actions if isinstance(a, RearmCop)]


def test_no_cop_rearm_when_disabled():
    d = ClimateDecider(make_settings(cop_rearm=False))
    d.last_cop_arm["VIN1"] = NOW - timedelta(hours=20)
    dec = d.decide([state(outside_temp=36.0, cop_state="On")], [], NOW)
    assert not [a for a in dec.actions if isinstance(a, RearmCop)]
