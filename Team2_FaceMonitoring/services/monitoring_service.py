"""Session lifecycle management for the single physical webcam."""

from __future__ import annotations

import re
import logging
from threading import RLock
from typing import Any, Callable

from services.camera_service import CameraService
from services.event_logger import EventLogger
from services.face_detector import FaceDetector

SESSION_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
logger = logging.getLogger(__name__)
INITIAL_METRICS = {
    "face_count": 0,
    "fps": 0.0,
    "latency_ms": 0.0,
    "processing_mode": "normal",
    "system_metrics": {"cpu_percent": None, "memory_percent": None},
}


class MonitoringError(Exception):
    """An expected monitoring failure with its API status and session context."""

    def __init__(
        self,
        message: str,
        status_code: int,
        session_id: str | None,
        status: str = "ERROR",
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.session_id = session_id
        self.status = status

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "status": self.status,
            "message": self.message,
        }


class MonitoringService:
    """Manage session state while ensuring only one session owns the camera."""

    def __init__(
        self,
        camera_factory: Callable[[EventLogger], CameraService] | None = None,
    ) -> None:
        self._camera_factory = camera_factory or self._create_camera
        self._lock = RLock()
        self._sessions: dict[str, dict[str, Any]] = {}
        self._active_session_id: str | None = None

    @staticmethod
    def _create_camera(event_logger: EventLogger) -> CameraService:
        from config import CAMERA_INDEX, FRAME_HEIGHT, FRAME_WIDTH

        return CameraService(
            camera_index=CAMERA_INDEX,
            frame_width=FRAME_WIDTH,
            frame_height=FRAME_HEIGHT,
            detector=FaceDetector(),
            event_logger=event_logger,
        )

    @staticmethod
    def validate_session_id(session_id: Any) -> str:
        if not isinstance(session_id, str) or not SESSION_ID_PATTERN.fullmatch(session_id):
            raise MonitoringError(
                "session_id must be 1-64 characters: start with a letter or number, "
                "then use only letters, numbers, '.', '_' or '-'.",
                400,
                session_id if isinstance(session_id, str) else None,
            )
        return session_id

    def start_monitoring(self, session_id: Any) -> dict[str, Any]:
        session_id = self.validate_session_id(session_id)
        with self._lock:
            record = self._sessions.setdefault(session_id, self._new_record(session_id))
            if self._active_session_id is not None:
                if self._active_session_id == session_id:
                    raise MonitoringError(
                        "Monitoring is already active for this session.",
                        409,
                        session_id,
                        record["status"],
                    )
                raise MonitoringError(
                    f"The webcam is already in use by session {self._active_session_id}.",
                    409,
                    session_id,
                    record["status"],
                )
            record["status"] = "STARTING"
            record["message"] = "Initializing webcam and face detector."
            record["error"] = None
            self._active_session_id = session_id
            event_logger = record["event_logger"]

        camera: CameraService | None = None
        try:
            camera = self._camera_factory(event_logger)
            record["camera"] = camera
            if not camera.start():
                camera_status = camera.get_status()
                message = camera_status.get("camera_error") or "The webcam could not be opened."
                permission_denied = "camera access was denied" in message.lower()
                failure_status = "PERMISSION_DENIED" if permission_denied else "CAMERA_UNAVAILABLE"
                http_status = 403 if permission_denied else 503
                self._finish_failed_start(session_id, failure_status, message, camera)
                raise MonitoringError(message, http_status, session_id, failure_status)
            with self._lock:
                record["status"] = "RUNNING"
                record["message"] = "Monitoring is running."
                record["error"] = None
                event_logger.add_event("monitoring_started", "Monitoring started.")
                return self.get_status(session_id)
        except MonitoringError:
            raise
        except PermissionError as exc:
            message = (
                "Python/OpenCV camera access was denied. Allow camera access for "
                "desktop apps, the terminal, or Python in operating-system privacy "
                "settings; browser-site camera permission does not grant backend "
                f"access. Details: {exc}"
            )
            self._finish_failed_start(session_id, "PERMISSION_DENIED", message, camera)
            raise MonitoringError(message, 403, session_id, "PERMISSION_DENIED") from exc
        except Exception as exc:
            message = f"Could not initialize monitoring: {exc}"
            self._finish_failed_start(session_id, "ERROR", message, camera)
            raise MonitoringError(message, 500, session_id, "ERROR") from exc

    def _finish_failed_start(
        self,
        session_id: str,
        status: str,
        message: str,
        camera: CameraService | None,
    ) -> None:
        if camera is not None:
            try:
                camera.stop()
            except Exception:
                logger.exception("Failed to clean up camera after start failure for %s", session_id)
        with self._lock:
            record = self._sessions[session_id]
            record["camera"] = None
            record["status"] = status
            record["message"] = message
            record["error"] = message
            if self._active_session_id == session_id:
                self._active_session_id = None
            record["event_logger"].add_event("monitoring_start_failed", message)

    def stop_monitoring(self, session_id: Any) -> dict[str, Any]:
        session_id = self.validate_session_id(session_id)
        with self._lock:
            record = self._sessions.setdefault(session_id, self._new_record(session_id))
            if self._active_session_id is not None and self._active_session_id != session_id:
                raise MonitoringError(
                    f"Session {session_id} does not own the webcam; "
                    f"session {self._active_session_id} is active.",
                    409,
                    session_id,
                    record["status"],
                )
            if self._active_session_id is None:
                if record["status"] == "STOPPED":
                    record["message"] = "Monitoring is already stopped."
                    return self.get_status(session_id)
                raise MonitoringError(
                    "This session does not have active monitoring to stop.",
                    409,
                    session_id,
                    record["status"],
                )
            if record["status"] in {"STARTING", "STOPPING"}:
                raise MonitoringError(
                    f"Monitoring is currently {record['status'].lower()}; retry the stop request shortly.",
                    409,
                    session_id,
                    record["status"],
                )
            record["status"] = "STOPPING"
            record["message"] = "Stopping monitoring and releasing the webcam."
            camera = record["camera"]

        stop_error: Exception | None = None
        try:
            if camera is not None:
                camera.stop()
        except Exception as exc:
            stop_error = exc
        finally:
            with self._lock:
                record = self._sessions[session_id]
                record["camera"] = None
                if stop_error is None:
                    self._active_session_id = None
                    record["status"] = "STOPPED"
                    record["message"] = "Monitoring stopped and webcam released."
                    record["error"] = None
                    record["event_logger"].add_event(
                        "monitoring_stopped",
                        "Monitoring stopped and webcam released.",
                    )
                else:
                    self._active_session_id = session_id
                    record["status"] = "ERROR"
                    record["message"] = f"Monitoring stopped with a camera cleanup error: {stop_error}"
                    record["error"] = record["message"]
        if stop_error is not None:
            raise MonitoringError(record["message"], 500, session_id, "ERROR") from stop_error
        return self.get_status(session_id)

    def restart_monitoring(self, session_id: Any) -> dict[str, Any]:
        session_id = self.validate_session_id(session_id)
        with self._lock:
            record = self._sessions.get(session_id)
            if self._active_session_id != session_id and (
                record is None
                or record["status"] not in {"CAMERA_UNAVAILABLE", "PERMISSION_DENIED", "ERROR"}
            ):
                raise MonitoringError(
                    "Only the active session or a session with a camera error can retry its camera.",
                    409,
                    session_id,
                    record["status"] if record else "NOT_STARTED",
                )
            is_active = self._active_session_id == session_id
        if is_active:
            self.stop_monitoring(session_id)
        return self.start_monitoring(session_id)

    def get_status(self, session_id: Any) -> dict[str, Any]:
        session_id = self.validate_session_id(session_id)
        with self._lock:
            record = self._sessions.setdefault(session_id, self._new_record(session_id))
            metrics = dict(INITIAL_METRICS)
            camera = record["camera"]
            if camera is not None:
                camera_status = camera.get_status()
                metrics.update(camera_status)
                metrics.pop("camera_status", None)
                metrics.pop("camera_error", None)
                if record["status"] == "RUNNING" and camera_status["camera_status"] != "online":
                    error = camera_status.get("camera_error") or "Camera processing stopped unexpectedly."
                    record["status"] = (
                        "CAMERA_UNAVAILABLE"
                        if error.lower().startswith("camera frame capture failed")
                        else "ERROR"
                    )
                    record["message"] = error
                    record["error"] = error
                    record["camera"] = None
                    if self._active_session_id == session_id:
                        self._active_session_id = None
            return {
                "session_id": session_id,
                "active_session_id": self._active_session_id,
                "status": record["status"],
                "message": record["message"],
                "error": record["error"],
                **metrics,
                "events": record["event_logger"].get_recent_events(),
            }

    def get_active_status(self) -> dict[str, Any] | None:
        with self._lock:
            session_id = self._active_session_id
        return self.get_status(session_id) if session_id is not None else None

    def get_camera(self, session_id: Any) -> CameraService:
        session_id = self.validate_session_id(session_id)
        with self._lock:
            record = self._sessions.get(session_id)
            if (
                record is None
                or self._active_session_id != session_id
                or record["status"] != "RUNNING"
            ):
                raise MonitoringError(
                    "This session has no active webcam feed.",
                    409,
                    session_id,
                    record["status"] if record else "NOT_STARTED",
                )
            return record["camera"]

    @staticmethod
    def _new_record(session_id: str) -> dict[str, Any]:
        return {
            "session_id": session_id,
            "status": "NOT_STARTED",
            "message": "Monitoring has not started for this session.",
            "error": None,
            "camera": None,
            "event_logger": EventLogger(session_id=session_id),
        }
