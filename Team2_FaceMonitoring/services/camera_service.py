"""Webcam capture, frame processing, and MJPEG streaming for one session."""

from __future__ import annotations

import time
from threading import Event, RLock, Thread, current_thread
from typing import Any

import cv2
import numpy as np

from config import JPEG_QUALITY
from services.event_logger import EventLogger
from services.face_detector import FaceDetector

try:
    import psutil
except ImportError:
    psutil = None


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
    ) -> None:
        self.camera_index = camera_index
        self.frame_width = frame_width
        self.frame_height = frame_height
        self.detector = detector
        self.event_logger = event_logger
        self._lock = RLock()
        self._stop_event = Event()
        self._thread: Thread | None = None
        self._capture = None
        self._frame_jpeg: bytes | None = None
        self._mode = "normal"
        self._camera_status = "offline"
        self._camera_error: str | None = None
        self._face_count = 0
        self._fps = 0.0
        self._latency_ms = 0.0
        self._last_frame_at: float | None = None
        self._last_face_state = "none"

    def start(self) -> bool:
        """Initialize the webcam synchronously, then launch frame processing."""
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return self._camera_status == "online"
            capture = self._open_camera()
            if capture is None:
                return False
            self._stop_event.clear()
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
                ok, frame = capture.read()
                if not ok or frame is None:
                    self._set_camera_error("Camera frame capture failed.")
                    self.event_logger.add_event(
                        "frame_capture_failure",
                        "The camera stopped returning frames.",
                    )
                    break
                self._process_frame(frame)
        except Exception as exc:
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
                    self._face_count = 0
                    self._fps = 0.0
                    self._latency_ms = 0.0
                    self._frame_jpeg = None
                    if self._camera_error is None:
                        self._camera_status = "offline"

    def _open_camera(self):
        capture = None
        try:
            capture = cv2.VideoCapture(self.camera_index)
            if not capture.isOpened():
                self._release_camera(capture)
                self._set_camera_error(
                    f"Could not open camera index {self.camera_index}. Check that the "
                    "webcam is connected and not in use by another application. OpenCV "
                    "cannot reliably distinguish permission denial from unavailability."
                )
                return None
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
            self._set_camera_error(
                f"Could not initialize camera index {self.camera_index}: {exc}"
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
        faces = self.detector.detect(frame)
        with self._lock:
            mode = self._mode
        displayed = self._apply_mode(frame, mode)
        if mode == "normal":
            displayed = self.detector.draw_faces(displayed, faces)
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
            self._face_count = len(faces)
            self._frame_jpeg = buffer.tobytes()
        self._log_face_state(len(faces))

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
