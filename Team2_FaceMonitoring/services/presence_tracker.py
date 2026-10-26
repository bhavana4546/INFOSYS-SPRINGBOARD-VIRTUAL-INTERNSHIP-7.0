"""Track face presence and threshold-length absence intervals."""

import math
from dataclasses import dataclass
from enum import Enum


class FacePresenceState(str, Enum):
    FACE_PRESENT = "FACE_PRESENT"
    FACE_ABSENT = "FACE_ABSENT"
    DETECTION_UNAVAILABLE = "DETECTION_UNAVAILABLE"


@dataclass(frozen=True)
class PresenceSnapshot:
    state: FacePresenceState
    absence_duration_seconds: float
    prolonged_absence_started: bool


class FacePresenceTracker:
    """Maintain one continuous absence interval using monotonic timestamps."""

    def __init__(self, absence_threshold_seconds: float = 10.0) -> None:
        if not math.isfinite(absence_threshold_seconds) or absence_threshold_seconds < 0:
            raise ValueError(
                "absence_threshold_seconds must be a finite non-negative number"
            )
        self.absence_threshold_seconds = absence_threshold_seconds
        self.state = FacePresenceState.DETECTION_UNAVAILABLE
        self._absence_started_at: float | None = None
        self._absence_alerted = False

    def update(
        self,
        face_present: bool | None,
        timestamp: float,
    ) -> PresenceSnapshot:
        """Update with True/False for a successful detection, or None if unavailable."""
        if face_present is None:
            self.state = FacePresenceState.DETECTION_UNAVAILABLE
            self._absence_started_at = None
            self._absence_alerted = False
            return PresenceSnapshot(self.state, 0.0, False)

        if face_present:
            self.state = FacePresenceState.FACE_PRESENT
            self._absence_started_at = None
            self._absence_alerted = False
            return PresenceSnapshot(self.state, 0.0, False)

        if self.state is not FacePresenceState.FACE_ABSENT:
            self._absence_started_at = timestamp
            self._absence_alerted = False
        self.state = FacePresenceState.FACE_ABSENT
        if self._absence_started_at is None:
            self._absence_started_at = timestamp

        duration = max(0.0, timestamp - self._absence_started_at)
        alert_started = (
            not self._absence_alerted
            and duration >= self.absence_threshold_seconds
        )
        if alert_started:
            self._absence_alerted = True
        return PresenceSnapshot(self.state, duration, alert_started)
