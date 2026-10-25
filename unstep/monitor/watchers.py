"""The four watchers. Thresholds are our own early warnings, not FAA procedures."""

from __future__ import annotations

from dataclasses import dataclass, field

from unstep.cockpit.phraseology import is_restrictive
from unstep.contracts import AnomalyEvent, ApprovedDirective, ReadbackResult

READBACK_WAIT_S = 20.0  # a clearance with no readback after this long is flagged
STUCK_MIC_S = 15.0  # a transmitter keyed this long blocks the frequency
REPEAT_BLOCKED = 2  # the same aircraft stepped on this many times in the window
REPEAT_WINDOW_S = 300.0
CONGESTION_CALLS = 3  # this many stepped-on calls on the frequency in the window
CONGESTION_WINDOW_S = 60.0
RUNWAY_HOLD_S = 90.0  # a runway clearance is treated as open this long


def action(agent: str, key: str, now: int, status: str, text: str, *, station: str | None = None,
           event_id: str | None = None, detail: str | None = None) -> dict:
    """One row for the feed, in the format Rishit's side agreed (R34). `key` is stable per underlying item so a
    flag that clears replaces its own row."""
    return {"type": "agent_action", "id": f"{agent.lower().replace(' ', '-')}-{key}", "ts": now, "agent": agent,
            "kind": "rule", "station": station, "event_id": event_id, "status": status, "text": text,
            "detail": detail, "sponsor": None}


class Watcher:
    name = "Watcher"

    def on_message(self, msg, now: int) -> list[dict]:
        return []

    def on_note(self, kind: str, data: dict, now: int) -> list[dict]:
        return []

    def tick(self, now: int) -> list[dict]:
        return []

    def open_items(self) -> list[dict]:
        """Rows still waiting on someone, for the shift briefing."""
        return []


@dataclass
class ReadbackWatcher(Watcher):
    """Readbacks: a clearance with no readback, and a readback that does not match."""

    name = "Readback watcher"
    wait_ms: int = int(READBACK_WAIT_S * 1000)
    waiting: dict = field(default_factory=dict)  # event_id -> (directive, flagged)

    def on_message(self, msg, now):
        if isinstance(msg, ApprovedDirective):
            self.waiting[msg.event_id] = [msg, False]
        elif isinstance(msg, ReadbackResult) and msg.event_id in self.waiting:
            directive, _ = self.waiting[msg.event_id]
            who = directive.slots.callsign
            if msg.match:
                del self.waiting[msg.event_id]
                return [action(self.name, msg.event_id, now, "done", f"{who} read back \"{directive.instruction_text}\"",
                               station=who, event_id=msg.event_id)]
            self.waiting[msg.event_id][1] = True
            return [action(self.name, msg.event_id, now, "flag",
                           f"{who} read back something different (attempt {msg.attempt}); needs a second look",
                           station=who, event_id=msg.event_id, detail=f"Said: \"{msg.readback_text}\"")]
        return []

    def tick(self, now):
        out = []
        for event_id, (directive, flagged) in self.waiting.items():
            if not flagged and now - directive.approved_at >= self.wait_ms:
                self.waiting[event_id][1] = True
                who = directive.slots.callsign
                out.append(action(self.name, event_id, now, "flag",
                                  f"{who} has not read back \"{directive.instruction_text}\" after "
                                  f"{round(self.wait_ms / 1000)} s", station=who, event_id=event_id))
        return out

    def open_items(self):
        return [{"agent": self.name, "event_id": e, "text": f"{d.slots.callsign}: {d.instruction_text} (no readback yet)"}
                for e, (d, _) in self.waiting.items()]


@dataclass
class RunwayWatcher(Watcher):
    """Landing and takeoff clearances: two aircraft cleared into the same runway while the first is still open.
    Flags only; it never proposes an order."""

    name = "Runway watcher"
    hold_ms: int = int(RUNWAY_HOLD_S * 1000)
    open: dict = field(default_factory=dict)  # runway -> (callsign, action, at, event_id)

    def on_message(self, msg, now):
        if not isinstance(msg, ApprovedDirective) or not msg.slots.runway or is_restrictive(msg.slots.action):
            return []
        if msg.slots.action not in ("cleared to land", "cleared for takeoff", "line up and wait"):
            return []
        runway, who = msg.slots.runway, msg.slots.callsign
        held = self.open.get(runway)
        self.open[runway] = (who, msg.slots.action, now, msg.event_id)
        if held and held[0] != who and now - held[2] < self.hold_ms:
            return [action(self.name, f"{runway}-{msg.event_id}", now, "flag",
                           f"{who} and {held[0]} are both cleared into runway {runway}", station=who,
                           event_id=msg.event_id,
                           detail=f"{held[0]}: {held[1]}; {who}: {msg.slots.action}. Flag only; the controller decides.")]
        return []

    def tick(self, now):
        for runway in [r for r, v in self.open.items() if now - v[2] >= self.hold_ms]:
            del self.open[runway]
        return []

    def open_items(self):
        return [{"agent": self.name, "event_id": v[3], "text": f"runway {r}: {v[0]} {v[1]}"} for r, v in self.open.items()]


@dataclass
class TrackingWatcher(Watcher):
    """Aircraft and microphones: a stuck key, and the same aircraft stepped on again and again."""

    name = "Tracking watcher"
    stuck_ms: int = int(STUCK_MIC_S * 1000)
    keyed: dict = field(default_factory=dict)  # station -> (since, flagged)
    blocked: dict = field(default_factory=dict)  # callsign -> [times]

    def on_note(self, kind, data, now):
        if kind == "key":
            station = data["station"]
            if data.get("down"):
                self.keyed.setdefault(station, [now, False])
            elif station in self.keyed:
                flagged = self.keyed.pop(station)[1]
                if flagged:
                    return [action(self.name, f"mic-{station}", now, "done", f"{station} released the key",
                                   station=station)]
        return []

    def on_message(self, msg, now):
        if not isinstance(msg, AnomalyEvent):
            return []
        times = [t for t in self.blocked.get(msg.callsign, []) if now - t < REPEAT_WINDOW_S * 1000] + [now]
        self.blocked[msg.callsign] = times
        if len(times) >= REPEAT_BLOCKED:
            return [action(self.name, f"blocked-{msg.callsign}", now, "flag",
                           f"{msg.callsign} has been stepped on {len(times)} times in "
                           f"{round(REPEAT_WINDOW_S / 60)} min", station=msg.callsign, event_id=msg.event_id,
                           detail="A repeating pattern can mean a bad radio or a busy shared frequency")]
        return []

    def tick(self, now):
        out = []
        for station, v in self.keyed.items():
            if not v[1] and now - v[0] >= self.stuck_ms:
                v[1] = True
                out.append(action(self.name, f"mic-{station}", now, "flag",
                                  f"{station} has held the key for {round(self.stuck_ms / 1000)} s, "
                                  "which blocks everyone else", station=station))
        return out

    def open_items(self):
        return [{"agent": self.name, "event_id": None, "text": f"{s} is holding the key"}
                for s, v in self.keyed.items() if v[1]]


@dataclass
class FlowWatcher(Watcher):
    """The frequency as a whole: congestion, and what a shift handoff would still have to mention."""

    name = "Flow watcher"
    recent: list = field(default_factory=list)
    congested: bool = False

    def on_message(self, msg, now):
        if isinstance(msg, AnomalyEvent):
            self.recent = [t for t in self.recent if now - t < CONGESTION_WINDOW_S * 1000] + [now]
        return self._check(now)

    def tick(self, now):
        self.recent = [t for t in self.recent if now - t < CONGESTION_WINDOW_S * 1000]
        return self._check(now)

    def _check(self, now):
        busy = len(self.recent) >= CONGESTION_CALLS
        if busy and not self.congested:
            self.congested = True
            return [action(self.name, "congestion", now, "flag",
                           f"{len(self.recent)} stepped-on calls in {round(CONGESTION_WINDOW_S)} s: the frequency is busy",
                           detail="Consider splitting the frequency or slowing the traffic")]
        if not busy and self.congested:
            self.congested = False
            return [action(self.name, "congestion", now, "done", "The frequency has quietened down")]
        return []
