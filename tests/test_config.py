"""Config parsing tests."""
import pytest

from tesla_calendar_climate.config import ConfigError, load_settings

BASE = {
    "TESLA_CLIENT_ID": "id",
    "TESLA_CLIENT_SECRET": "secret",
    "TCC_VEHICLES": "Daily=VIN1,Second=VIN2",
    "TCC_CALENDAR_ICS_URL": "https://example.com/cal.ics",
    "TCC_HOME_LAT": "34.05",
    "TCC_HOME_LON": "-118.25",
}


def test_vehicle_parsing():
    s = load_settings(dict(BASE))
    assert [(v.name, v.vin) for v in s.vehicles] == [("Daily", "VIN1"), ("Second", "VIN2")]


def test_home_and_climate_defaults():
    s = load_settings(dict(BASE))
    assert s.home_lat == 34.05 and s.home_lon == -118.25
    assert s.home_radius_m == 200.0
    assert s.target_temp_c == 21.0
    assert s.hot_lead_minutes == 30
    assert s.cop_rearm is True


def test_half_home_rejected():
    with pytest.raises(ConfigError):
        load_settings({**BASE, "TCC_HOME_LON": ""})


def test_missing_vehicles_rejected():
    env = dict(BASE)
    del env["TCC_VEHICLES"]
    with pytest.raises(ConfigError):
        load_settings(env)


def test_simulate_needs_no_config():
    s = load_settings({}, require_auth=False)
    assert s.vehicles == []
