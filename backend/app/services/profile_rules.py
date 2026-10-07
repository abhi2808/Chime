"""Body state + type + intent -> target profile (SPEC section 3).

Rules as data, in tables at the top of the file, so tuning Chime's behaviour is editing a
number rather than reading a function. Everything here is pure: no database, no clock, no
network, which is what makes the whole thing unit-testable.

The output is an energy *curve* rather than a single number, because a session has a
shape: a workout climbs and eases off, a wind-down descends. Ranking shapes the running
order to that curve (SPEC section 5).
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Literal

from app.services.body_state import BodyState
from app.services.tagging import AFFINITIES, ENERGY_MAX, ENERGY_MIN

Mood = Literal["wired", "drained", "flat", "steady", "fired_up"]
SessionType = Literal["auto", "workout", "focus", "wind_down", "wake_up"]
Intent = Literal["match", "shift"]

MOODS: tuple[Mood, ...] = ("wired", "drained", "flat", "steady", "fired_up")
SESSION_TYPES: tuple[SessionType, ...] = ("auto", "workout", "focus", "wind_down", "wake_up")
INTENTS: tuple[Intent, ...] = ("match", "shift")

DEFAULT_TYPE: SessionType = "auto"
DEFAULT_INTENT: Intent = "match"


@dataclass(frozen=True, slots=True)
class TypeRule:
    """What a session type wants, before the body has a say."""

    start: float
    end: float
    affinities: Mapping[str, float]
    #: Fraction of the session that comes back down at the end (workout cool-off).
    ease_off: float = 0.0
    #: Ceiling when the mood is drained. SPEC caps a drained workout at 4.
    drained_ceiling: float | None = None


#: SPEC section 3, verbatim where it gives numbers.
TYPE_RULES: dict[str, TypeRule] = {
    "workout": TypeRule(
        start=3,
        end=5,
        affinities={"workout": 1.0, "wake_up": 0.3},
        ease_off=0.10,
        drained_ceiling=4,
    ),
    "focus": TypeRule(start=2, end=3, affinities={"focus": 1.0, "calm": 0.4}),
    "wind_down": TypeRule(start=2, end=1, affinities={"wind_down": 1.0, "calm": 0.9}),
    "wake_up": TypeRule(start=2, end=4, affinities={"wake_up": 1.0, "focus": 0.2}),
}

#: Intent = match: meet the body where it is.
MOOD_SHIFT: dict[str, float] = {
    "wired": -1,
    "drained": -1,
    "flat": +1,
    "fired_up": +1,
    "steady": 0,
}

#: Intent = shift: move to the other pole. ``None`` means there is nowhere to move to.
SHIFT_CURVES: dict[str, tuple[float, float] | None] = {
    "wired": (2, 1),  # same direction as match, steeper
    "drained": (2, 4),  # the case match cannot express: match takes drained *down*
    "flat": (3, 5),
    "fired_up": (4, 2),
    "steady": None,
}

#: Low readiness lowers the ceiling for non-workout sessions.
LOW_READINESS_CEILING = 4.0
#: How far a workout's cool-off descends from its peak.
EASE_OFF_DROP = 1.5
#: A recent workout steers ``auto`` towards cooling down, in minutes.
RECENT_WORKOUT_MINUTES = 60


@dataclass(frozen=True, slots=True)
class TargetProfile:
    """The engine's brief for one session. Stored on ``sessions.target_profile``."""

    type: str
    intent: str
    mood: str | None
    start: float
    end: float
    ceiling: float
    affinities: Mapping[str, float]
    floor: float = ENERGY_MIN
    ease_off: float = 0.0
    #: Plain-language reasons, in the order they were applied. Feeds why_text and the
    #: dev ranking page, and is the only explanation History ever needs.
    notes: tuple[str, ...] = field(default_factory=tuple)

    def curve(self, count: int) -> list[float]:
        """Sample the target energy at each position in the running order."""
        if count <= 0:
            return []
        if count == 1:
            return [self._clamp(self.end)]

        # The cool-off never eats the ramp: two positions always climb.
        tail = min(math.floor(count * self.ease_off), count - 2) if self.ease_off > 0 else 0
        rise = count - tail
        peak = self._clamp(self.end)

        points = [
            self._clamp(self.start + (self.end - self.start) * step / (rise - 1))
            for step in range(rise)
        ]
        if tail:
            cool = self._clamp(peak - EASE_OFF_DROP)
            points += [peak + (cool - peak) * (step + 1) / tail for step in range(tail)]
        return [round(value, 3) for value in points]

    def _clamp(self, value: float) -> float:
        return max(self.floor, min(self.ceiling, value))

    def as_dict(self, positions: int = 25) -> dict[str, object]:
        return {
            "type": self.type,
            "intent": self.intent,
            "mood": self.mood,
            "energy_start": self._clamp(self.start),
            "energy_end": self._clamp(self.end),
            "ceiling": self.ceiling,
            "floor": self.floor,
            "ease_off": self.ease_off,
            "affinities": dict(self.affinities),
            "curve": self.curve(positions),
            "notes": list(self.notes),
        }


def resolve_type(
    requested: str | None, body: BodyState, mood: str | None
) -> tuple[SessionType, str | None]:
    """Turn ``auto`` into a real type, and say why.

    Precedence is deliberate: what the body just did beats what the clock says, and a
    mood of fired_up beats both — except on a low-recovery day, where honouring it would
    be the app talking someone into a session their body is not ready for.
    """
    if requested and requested != "auto":
        if requested not in TYPE_RULES:
            raise ValueError(f"Unknown session type {requested!r}")
        return requested, None  # type: ignore[return-value]

    if mood == "fired_up" and body.readiness != "low":
        return "workout", "You said fired up, so this is a workout mix."
    since = body.minutes_since_last_workout
    if since is not None and since <= RECENT_WORKOUT_MINUTES:
        return "wind_down", "You trained in the last hour, so this comes back down."
    if body.day_part in ("early_morning", "morning"):
        return "wake_up", "It's morning, so this lifts you into the day."
    if body.day_part in ("evening", "late_night"):
        return "wind_down", "It's late, so this winds down."
    return "focus", "Mid-afternoon with nothing else to go on, so this is a focus mix."


def ceiling_for(session_type: str, body: BodyState, mood: str | None) -> tuple[float, str | None]:
    """The highest energy this body should be pushed to, and the reason if capped."""
    rule = TYPE_RULES[session_type]
    if session_type == "workout":
        if mood == "drained" and rule.drained_ceiling is not None:
            return rule.drained_ceiling, "You said drained, so this workout stays off the top."
        return ENERGY_MAX, None
    if body.readiness == "low":
        return (
            LOW_READINESS_CEILING,
            "Recovery is low, so this keeps a lid on how hard it pushes.",
        )
    return ENERGY_MAX, None


def build_profile(
    body: BodyState,
    *,
    mood: str | None = None,
    session_type: str | None = DEFAULT_TYPE,
    intent: str = DEFAULT_INTENT,
) -> TargetProfile:
    """The whole of SPEC section 3, in order: type, curve, mood or intent, ceiling."""
    if mood is not None and mood not in MOODS:
        raise ValueError(f"Unknown mood {mood!r}")
    if intent not in INTENTS:
        raise ValueError(f"Unknown intent {intent!r}")

    resolved, why_type = resolve_type(session_type, body, mood)
    rule = TYPE_RULES[resolved]
    notes: list[str] = [why_type] if why_type else []

    start, end = float(rule.start), float(rule.end)
    ceiling, why_ceiling = ceiling_for(resolved, body, mood)
    shift = SHIFT_CURVES.get(mood or "steady") if intent == "shift" else None

    if intent == "shift" and mood is not None:
        if shift is None:
            notes.append("Steady is already the middle, so there's nowhere to shift to.")
        else:
            start, end = shift
            notes.append(_shift_note(mood, rule, start, end))
    capped = False
    if mood is not None and intent != "shift":
        wanted = MOOD_SHIFT[mood]
        # SPEC: drained lowers the target, except on a workout, where the point is to
        # get going. The ceiling below is what keeps that honest.
        if mood == "drained" and resolved == "workout":
            step = 0.0
            notes.append("You said drained, so this workout starts where you are.")
        else:
            step = _room_for(wanted, start, end, ceiling)
            capped = wanted > 0 and step < wanted
            if step:
                direction = "down" if step < 0 else "up"
                notes.append(
                    f"You said {mood.replace('_', ' ')}, so the whole mix sits {direction}."
                )
        start += step
        end += step

    if why_ceiling and (capped or max(start, end) > ceiling):
        notes.append(why_ceiling)

    return TargetProfile(
        type=resolved,
        intent=intent,
        mood=mood,
        start=start,
        end=end,
        ceiling=ceiling,
        affinities=_affinities(rule),
        ease_off=rule.ease_off,
        notes=tuple(notes),
    )


def _room_for(step: float, start: float, end: float, ceiling: float) -> float:
    """How much of a mood's move there is actually room for.

    The move is clamped, not its endpoints. Lowering a wind-down (2 -> 1) by one would
    put both ends on the floor and flatten the descent that makes it a wind-down; the
    session would lose its shape in the name of honouring the mood. Shifting only as far
    as there is headroom keeps the shape and stays inside 1-5.
    """
    if step < 0:
        return -min(-step, min(start, end) - ENERGY_MIN)
    if step > 0:
        return min(step, ceiling - max(start, end))
    return 0.0


def _shift_note(mood: str, rule: TypeRule, start: float, end: float) -> str:
    """Say what shift is doing, including when it fights the session type."""
    spoken = mood.replace("_", " ")
    if (end - start) * (rule.end - rule.start) < 0:
        # e.g. wind_down (2 -> 1) asked to lift a flat mood (3 -> 5).
        return f"You held for a shift, so this pulls against the {rule_name(rule)} shape."
    return f"You held for a shift, so instead of matching {spoken} this moves you out of it."


def rule_name(rule: TypeRule) -> str:
    for name, candidate in TYPE_RULES.items():
        if candidate is rule:
            return name.replace("_", " ")
    return "session"


def _affinities(rule: TypeRule) -> dict[str, float]:
    """Every dimension present, so a stored profile is comparable across sessions.

    Intent never touches these: SPEC is explicit that shift moves the curve only.
    """
    return {affinity: float(rule.affinities.get(affinity, 0.0)) for affinity in AFFINITIES}
