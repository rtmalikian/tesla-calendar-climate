"""Read upcoming events from an ICS calendar feed.

Point TCC_CALENDAR_ICS_URL at your calendar's secret iCal address
(Google Calendar: Settings -> your calendar -> "Secret address in iCal format").
No OAuth, no API keys — just a URL. Supports basic RRULE recurrence
(DAILY / WEEKLY) so recurring standups work too.
"""
from __future__ import annotations

import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from icalendar import Calendar


@dataclass
class CalEvent:
    uid: str
    summary: str
    start: datetime
    end: datetime | None
    location: str


class CalendarError(Exception):
    pass


def _as_local(dt) -> datetime:
    """Normalize an icalendar datetime to an aware local datetime."""
    if isinstance(dt, datetime):
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc).astimezone()
        return dt.astimezone()
    # date (all-day event): treat as midnight local
    return datetime(dt.year, dt.month, dt.day).astimezone()


def _expand_rrule(component, window_start: datetime, window_end: datetime) -> list[datetime]:
    """Expand simple DAILY/WEEKLY RRULEs inside the window. Returns occurrences."""
    rrule = component.get("rrule")
    if not rrule:
        return []
    freq = str(rrule.get("freq", [""])[0]).upper()
    if freq not in ("DAILY", "WEEKLY"):
        return []
    interval = int(rrule.get("interval", [1])[0])
    count = rrule.get("count")
    count = int(count[0]) if count else None
    until = rrule.get("until")
    until = _as_local(until[0]) if until else None

    first = _as_local(component["dtstart"].dt)
    step = timedelta(days=interval) if freq == "DAILY" else timedelta(weeks=interval)
    occurrences = []
    occ, n = first, 0
    while occ <= window_end and (count is None or n < count):
        if until and occ > until:
            break
        if occ >= window_start:
            occurrences.append(occ)
        occ += step
        n += 1
        if n > 500:  # sanity cap
            break
    return occurrences


def parse_ics(data: bytes, window_start: datetime, window_end: datetime) -> list[CalEvent]:
    cal = Calendar.from_ical(data)
    events: list[CalEvent] = []
    for component in cal.walk("VEVENT"):
        if component.get("status", "").upper() == "CANCELLED":
            continue
        dtstart = component.get("dtstart")
        if not dtstart:
            continue
        dtend = component.get("dtend")
        duration = _as_local(dtend.dt) - _as_local(dtstart.dt) if dtend else timedelta(hours=1)
        summary = str(component.get("summary", "Untitled"))
        location = str(component.get("location", ""))
        uid = str(component.get("uid", summary))

        starts = _expand_rrule(component, window_start, window_end)
        if not starts:
            single = _as_local(dtstart.dt)
            starts = [single] if window_start <= single <= window_end else []
        for start in starts:
            events.append(CalEvent(uid=f"{uid}@{start.isoformat()}", summary=summary,
                                   start=start, end=start + duration, location=location))
    events.sort(key=lambda e: e.start)
    return events


def fetch_events(ics_url: str, now: datetime, lookahead_hours: int) -> list[CalEvent]:
    """Download the ICS feed and return events in [now, now+lookahead]."""
    if not ics_url:
        raise CalendarError("TCC_CALENDAR_ICS_URL is not set")
    window_end = now + timedelta(hours=lookahead_hours)
    try:
        req = urllib.request.Request(ics_url, headers={"User-Agent": "tesla-calendar-climate/0.1.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = resp.read()
    except Exception as exc:
        raise CalendarError(f"Could not fetch calendar feed: {exc}") from exc
    try:
        return parse_ics(data, now, window_end)
    except Exception as exc:
        raise CalendarError(f"Could not parse calendar feed: {exc}") from exc
