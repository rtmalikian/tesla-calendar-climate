"""Decision logic: when to precondition, when to stop, when to re-arm COP.

Pure logic — no network, `now` injected — so it is fully unit-testable.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .calendar_client import CalEvent


@dataclass
class VehicleClimateState:
    vin: str
    name: str
    inside_temp: float | None
    outside_temp: float | None
    is_climate_on: bool
    climate_keeper_mode: str  # off, Dog, Camp, ...
    cop_state: str | None  # On / Off / None if unknown
    parked: bool
    at_home: bool


@dataclass
class StartClimate:
    vin: str
    name: str
    temp_c: float
    reason: str


@dataclass
class StopClimate:
    vin: str
    name: str
    reason: str


@dataclass
class RearmCop:
    vin: str
    name: str
    reason: str


@dataclass
class Decision:
    actions: list = field(default_factory=list)
    note: str = ""


class ClimateDecider:
    """Decides climate actions for the fleet at a given moment."""

    def __init__(self, settings):
        self.s = settings
        self.preconditioning: dict[str, str] = {}  # vin -> event uid we started for
        self.last_cop_arm: dict[str, datetime] = {}  # vin -> last COP arm time

    # -- helpers ---------------------------------------------------------
    def lead_time(self, outside_temp: float | None) -> timedelta:
        if outside_temp is not None and outside_temp >= self.s.hot_threshold_c:
            return timedelta(minutes=self.s.hot_lead_minutes)
        if outside_temp is not None and outside_temp <= self.s.cold_threshold_c:
            return timedelta(minutes=self.s.cold_lead_minutes)
        return timedelta(minutes=self.s.lead_minutes)

    def _event_by_uid(self, events: list[CalEvent], uid: str) -> CalEvent | None:
        return next((e for e in events if e.uid == uid), None)

    # -- persistence -------------------------------------------------------
    def to_dict(self) -> dict:
        return {
            "preconditioning": self.preconditioning,
            "last_cop_arm": {vin: dt.isoformat() for vin, dt in self.last_cop_arm.items()},
        }

    def from_dict(self, data: dict) -> None:
        self.preconditioning = dict(data.get("preconditioning", {}))
        self.last_cop_arm = {
            vin: datetime.fromisoformat(dt) for vin, dt in data.get("last_cop_arm", {}).items()
        }

    # -- main --------------------------------------------------------------
    def decide(self, states: list[VehicleClimateState],
               events: list[CalEvent], now: datetime) -> Decision:
        actions: list = []
        notes: list[str] = []
        lookahead = timedelta(hours=self.s.lookahead_hours)
        overrun = timedelta(minutes=self.s.overrun_minutes)

        for st in states:
            if not (st.parked and st.at_home):
                # Car left home: drop any session we were tracking for it.
                self.preconditioning.pop(st.vin, None)
                continue

            upcoming = sorted(
                (e for e in events if now < e.start <= now + lookahead),
                key=lambda e: e.start,
            )
            nxt = upcoming[0] if upcoming else None
            lead = self.lead_time(st.outside_temp)

            # --- preconditioning: start ----------------------------------
            if (nxt and not st.is_climate_on
                    and self.preconditioning.get(st.vin) != nxt.uid
                    and nxt.start - lead <= now <= nxt.start + overrun):
                actions.append(StartClimate(
                    st.vin, st.name, self.s.target_temp_c,
                    f"'{nxt.summary}' at {nxt.start.strftime('%H:%M')} "
                    f"(outside {st.outside_temp}°C, lead {lead})",
                ))
                self.preconditioning[st.vin] = nxt.uid
                notes.append(f"{st.name}: preconditioning for '{nxt.summary}'")

            # --- preconditioning: stop after the overrun -------------------
            elif st.vin in self.preconditioning:
                ev = self._event_by_uid(events, self.preconditioning[st.vin])
                if ev is None or now > ev.start + overrun:
                    actions.append(StopClimate(
                        st.vin, st.name,
                        f"preconditioning window ended for '{ev.summary if ev else 'event'}'",
                    ))
                    del self.preconditioning[st.vin]
                    notes.append(f"{st.name}: preconditioning done")

            # --- COP: turn on if off during heat ---------------------------
            if self.s.cop_rearm and st.outside_temp is not None \
                    and st.outside_temp >= self.s.hot_threshold_c:
                last_arm = self.last_cop_arm.get(st.vin)
                arm_due = (last_arm is None
                           or now - last_arm >= timedelta(hours=self.s.cop_max_park_hours))
                cop_off = st.cop_state is not None and st.cop_state.lower() == "off"
                if cop_off or arm_due:
                    why = ("COP was off during heat — turning on"
                           if cop_off else
                           f"COP 12h cutoff approaching (last arm {last_arm.strftime('%H:%M') if last_arm else 'never'}) — re-arming")
                    actions.append(RearmCop(st.vin, st.name, why))
                    self.last_cop_arm[st.vin] = now
                    notes.append(f"{st.name}: {why}")

        return Decision(actions, note="; ".join(notes))
