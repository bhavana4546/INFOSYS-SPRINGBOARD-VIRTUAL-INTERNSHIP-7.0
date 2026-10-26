"""Webcam capture, frame processing, and MJPEG streaming for one session."""

from __future__ import annotations

import logging
import math
import time
from threading import Event, RLock, Thread, current_thread
from typing import Any

import cv2
import numpy as np

from config import (
    ABSENCE_THRESHOLD_SECONDS,
    JPEG_QUALITY,
    TARGET_FPS,
)
from services.event_logger import EventLogger
from services.face_detector import FaceDetector
from services.presence_tracker import (
    FacePresenceState,
    FacePresenceTracker,
    PresenceSnapshot,
)

try:
    import psutil
except ImportError:
    psutil = None

logger = logging.getLogger(__name__)


class CameraService:
    """Own one initialized camera and its frame-processing thread."""

    available_modes = ("normal", "grayscale", "blur", "threshold", "canny")

    def __init__(
        self,
        camera_index: int,
        frame_width: int,
        frame_height: int,
        detector: FaceDetector,
        event_logger: EventLogger,
        source: int | str | None = None,
        target_fps: float = TARGET_FPS,
        absence_threshold_seconds: float = ABSENCE_THRESHOLD_SECONDS,
    ) -> None:
        self.camera_index = camera_index
        self.frame_width = frame_width
        self.frame_height = frame_height
        self.detector = detector
        self.event_logger = event_logger
        self.source = camera_index if source is None else source
        if not math.isfinite(target_fps) or target_fps <= 0:
            raise ValueError("target_fps must be a finite number greater than zero")
        if (
            not math.isfinite(absence_threshold_seconds)
            or absence_threshold_seconds < 0
        ):
            raise ValueError(
                "absence_threshold_seconds must be a finite non-negative number"
            )
        self.target_fps = target_fps
        self._sample_interval = 1.0 / target_fps
        self._next_sample_at = 0.0
        self._presence_tracker = FacePresenceTracker(absence_threshold_seconds)
        self._lock = RLock()
        self._stop_event = Event()
        self._thread: Thread | None = None
        self._capture = None
        self._frame_jpeg: bytes | None = None
        self._mode = "normal"
        self._camera_status = "offline"
        self._camera_error: str | None = None
        self._face_count: int | None = None
        self._fps = 0.0
        self._latency_ms = 0.0
        self._last_frame_at: float | None = None
        self._last_face_state = "none"
        self._face_state = FacePresenceState.DETECTION_UNAVAILABLE.value
        self._absence_duration_seconds = 0.0

    def start(self) -> bool:
        """Initialize the webcam synchronously, then launch frame processing."""
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return self._camera_status == "online"
            capture = self._open_camera()
            if capture is None:
                return False
            self._stop_event.clear()
            self._next_sample_at = 0.0
            self._capture = capture
            self._camera_status = "online"
            self._camera_error = None
            self._thread = Thread(
                target=self._capture_loop,
                args=(capture,),
                name="face-monitor-camera",
                daemon=True,
            )
            try:
                self._thread.start()
            except Exception as exc:
                self._release_camera(capture)
                self._capture = None
                self._camera_status = "offline"
                self._camera_error = f"Could not start camera processing: {exc}"
                raise
        self.event_logger.add_event("camera_connected", "Camera connected.")
        return True

    def stop(self) -> None:
        """Stop frame processing and wait for the worker to release the webcam."""
        self._stop_event.set()
        thread = self._thread
        if thread is not None and thread.is_alive() and thread is not current_thread():
            thread.join(timeout=5)
            if thread.is_alive():
                raise RuntimeError("Camera processing did not stop within five seconds.")
        if thread is None or not thread.is_alive():
            capture = self._capture
            if capture is not None:
                self._release_camera(capture)
                with self._lock:
                    self._capture = None
                    if self._camera_error is None:
                        self._camera_status = "offline"

    def request_restart(self) -> None:
        """Restart is performed by MonitoringService for a specific session."""
        self.stop()

    def set_processing_mode(self, mode: str) -> None:
        if mode not in self.available_modes:
            raise ValueError(f"Unsupported processing mode: {mode}")
        with self._lock:
            if mode == self._mode:
                return
            self._mode = mode
        self.event_logger.add_event(
            "processing_settings_changed",
            f"Processing mode changed to {mode.replace('_', ' ')}.",
        )

    def get_status(self) -> dict[str, Any]:
        system_metrics = {"cpu_percent": None, "memory_percent": None}
        if psutil is not None:
            try:
                system_metrics = {
                    "cpu_percent": round(psutil.cpu_percent(interval=None), 1),
                    "memory_percent": round(psutil.virtual_memory().percent, 1),
                }
            except psutil.Error:
                pass
        with self._lock:
            return {
                "camera_status": self._camera_status,
                "camera_error": self._camera_error,
                "face_count": self._face_count,
                "face_state": self._face_state,
                "absence_duration_seconds": round(self._absence_duration_seconds, 1),
                "absence_threshold_seconds": self._presence_tracker.absence_threshold_seconds,
                "target_fps": self.target_fps,
                "fps": round(self._fps, 1),
                "latency_ms": round(self._latency_ms, 1),
                "processing_mode": self._mode,
                "available_modes": list(self.available_modes),
                "system_metrics": system_metrics,
            }

    def stream_frames(self):
        """Yield processed frames while this session's camera worker is active."""
        while not self._stop_event.is_set():
            with self._lock:
                frame = self._frame_jpeg
            if frame is not None:
                yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + frame + b"\r\n"
            time.sleep(0.05)

    def _capture_loop(self, capture) -> None:
        try:
            while not self._stop_event.is_set():
                delay = self._next_sample_at - time.monotonic()
                if delay > 0 and self._stop_event.wait(delay):
                    break
                ok, frame = capture.read()
                if not ok or frame is None:
                    self._set_presence_unavailable()
                    self._set_camera_error("Camera frame capture failed.")
                    self.event_logger.add_event(
                        "frame_capture_failure",
                        "The camera stopped returning frames.",
                    )
                    break
                if self._frame_is_due(time.monotonic()):
                    self._process_frame(frame)
        except Exception as exc:
            logger.exception("Camera frame processing failed")
            self._set_presence_unavailable()
            self._set_camera_error(f"Camera frame processing failed: {exc}")
            self.event_logger.add_event(
                "frame_capture_failure",
                "Camera frame processing failed; monitoring has stopped.",
            )
        finally:
            try:
                self._release_camera(capture)
            finally:
                with self._lock:
                    self._capture = None
                    self._face_count = None
                    self._face_state = FacePresenceState.DETECTION_UNAVAILABLE.value
                    self._absence_duration_seconds = 0.0
                    self._fps = 0.0
                    self._latency_ms = 0.0
                    self._frame_jpeg = None
                    if self._camera_error is None:
                        self._camera_status = "offline"

    def _open_camera(self):
        capture = None
        try:
            capture = cv2.VideoCapture(self.source)
            if not capture.isOpened():
                self._release_camera(capture)
                source_description = (
                    f"video file {self.source!r}"
                    if not isinstance(self.source, int)
                    else f"camera index {self.source}"
                )
                self._set_camera_error(
                    f"Could not open {source_description}. Check that the source exists "
                    "and is not in use by another application. OpenCV "
                    "cannot reliably distinguish permission denial from unavailability."
                )
                return None
            if isinstance(self.source, int):
                capture.set(cv2.CAP_PROP_FRAME_WIDTH, self.frame_width)
                capture.set(cv2.CAP_PROP_FRAME_HEIGHT, self.frame_height)
            return capture
        except PermissionError as exc:
            if capture is not None:
                self._release_camera(capture)
            self._set_camera_error(
                "Python/OpenCV camera access was denied. Allow camera access for "
                "desktop apps, the terminal, or Python in operating-system privacy "
                "settings; browser-site camera permission does not grant backend "
                f"access. Details: {exc}"
            )
            return None
        except cv2.error as exc:
            if capture is not None:
                self._release_camera(capture)
            source_description = (
                f"video file {self.source!r}"
                if not isinstance(self.source, int)
                else f"camera index {self.source}"
            )
            self._set_camera_error(
                f"Could not initialize {source_description}: {exc}"
            )
            return None
        except Exception:
            if capture is not None:
                self._release_camera(capture)
            raise

    def _release_camera(self, capture) -> None:
        try:
            capture.release()
        except Exception as exc:
            self.event_logger.add_event(
                "camera_release_failure",
                f"Could not release the camera cleanly: {exc}",
            )

    def _process_frame(self, frame) -> None:
        started_at = time.perf_counter()
        if not self._is_valid_frame(frame):
            self._set_presence_unavailable()
            logger.warning("Skipping invalid camera frame")
            return

        detection_available = True
        try:
            faces = self.detector.detect(frame)
        except Exception as exc:
            logger.exception("Face detection failed for a captured frame")
            faces = []
            detection_available = False
        snapshot = self._presence_tracker.update(
            bool(faces) if detection_available else None,
            time.monotonic(),
        )
        self._update_presence(snapshot)
        with self._lock:
            mode = self._mode
        displayed = self._apply_mode(frame, mode)
        if detection_available and mode == "normal":
            displayed = self.detector.draw_faces(displayed, faces)
        state_label = snapshot.state.value.replace("_", " ")
        if snapshot.state is FacePresenceState.FACE_ABSENT:
            state_label += f" ({snapshot.absence_duration_seconds:.1f}s)"
        cv2.putText(
            displayed,
            state_label,
            (12, 28),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.65,
            (54, 220, 130)
            if snapshot.state is FacePresenceState.FACE_PRESENT
            else (60, 170, 255),
            2,
            cv2.LINE_AA,
        )
        encoded, buffer = cv2.imencode(
            ".jpg",
            displayed,
            [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY],
        )
        latency = (time.perf_counter() - started_at) * 1000
        if not encoded:
            raise RuntimeError("OpenCV could not encode the processed frame.")
        now = time.perf_counter()
        with self._lock:
            elapsed = now - self._last_frame_at if self._last_frame_at is not None else 0
            instantaneous_fps = 1 / elapsed if elapsed > 0 else 0
            self._fps = (
                instantaneous_fps
                if self._fps == 0
                else self._fps * 0.8 + instantaneous_fps * 0.2
            )
            self._last_frame_at = now
            self._latency_ms = latency
            self._face_count = len(faces) if detection_available else None
            self._frame_jpeg = buffer.tobytes()
        if detection_available:
            self._log_face_state(len(faces))

    def _frame_is_due(self, timestamp: float) -> bool:
        if timestamp < self._next_sample_at:
            return False
        self._next_sample_at = timestamp + self._sample_interval
        return True

    @staticmethod
    def _is_valid_frame(frame: Any) -> bool:
        return (
            isinstance(frame, np.ndarray)
            and frame.size > 0
            and frame.ndim == 3
            and frame.shape[2] == 3
            and frame.dtype == np.uint8
        )

    def _update_presence(self, snapshot: PresenceSnapshot) -> None:
        previous = self._face_state
        with self._lock:
            self._face_state = snapshot.state.value
            self._absence_duration_seconds = snapshot.absence_duration_seconds
        if snapshot.state.value != previous:
            self.event_logger.add_event(
                "face_presence_state_changed",
                f"Face presence state changed to {snapshot.state.value}.",
            )
        if snapshot.prolonged_absence_started:
            self.event_logger.add_event(
                "prolonged_absence",
                "No face has been detected for at least "
                f"{self._presence_tracker.absence_threshold_seconds:g} seconds.",
            )

    def _set_presence_unavailable(self) -> None:
        snapshot = self._presence_tracker.update(None, time.monotonic())
        self._update_presence(snapshot)
        with self._lock:
            self._face_count = None

    @staticmethod
    def _apply_mode(frame, mode: str):
        if mode == "normal":
            return frame.copy()
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        if mode == "grayscale":
            return cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
        if mode == "blur":
            return cv2.GaussianBlur(frame, (21, 21), 0)
        if mode == "threshold":
            _, binary = cv2.threshold(gray, 127, 255, cv2.THRESH_BINARY)
            return cv2.cvtColor(binary, cv2.COLOR_GRAY2BGR)
        if mode == "canny":
            edges = cv2.Canny(gray, 80, 160)
            return cv2.cvtColor(edges, cv2.COLOR_GRAY2BGR)
        raise ValueError(f"Unsupported processing mode: {mode}")

    def _log_face_state(self, count: int) -> None:
        state = "none" if count == 0 else ("multiple" if count > 1 else "one")
        previous = self._last_face_state
        if state == previous:
            return
        if state == "none" and previous != "none":
            self.event_logger.add_event(
                "face_no_longer_visible",
                "No faces are currently visible.",
            )
        elif state == "multiple":
            self.event_logger.add_event(
                "multiple_faces_detected",
                f"Multiple faces detected ({count}).",
            )
        elif state == "one":
            message = "A face was detected." if previous == "none" else "One face remains visible."
            self.event_logger.add_event("face_detected", message)
        self._last_face_state = state

    def _set_camera_error(self, message: str) -> None:
        with self._lock:
            self._camera_status = "offline"
            self._camera_error = message
        self.event_logger.add_event("camera_unavailable", message)
