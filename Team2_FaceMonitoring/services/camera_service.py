"""Background webcam capture, frame processing, and MJPEG streaming."""

from __future__ import annotations

import time
from threading import Event, Lock, Thread, current_thread
from typing import Any

import cv2
import numpy as np

from config import CAMERA_RETRY_SECONDS, JPEG_QUALITY
from services.event_logger import EventLogger
from services.face_detector import FaceDetector

try:
    import psutil
except ImportError:
    psutil = None


class CameraService:
    """Own one camera-capture thread and expose its latest processed frame."""

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
        self._lock = Lock()
        self._stop_event = Event()
        self._restart_event = Event()
        self._thread: Thread | None = None
        self._frame_jpeg: bytes | None = None
        self._mode = "normal"
        self._camera_status = "starting"
        self._camera_error: str | None = None
        self._face_count = 0
        self._fps = 0.0
        self._latency_ms = 0.0
        self._last_frame_at: float | None = None
        self._last_face_state = "none"
        self._last_capture_failure_logged = False

    def start(self) -> None:
        """Start the worker once; this method is safe to call repeatedly."""
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop_event.clear()
            self._thread = Thread(
                target=self._capture_loop,
                name="face-monitor-camera",
                daemon=True,
            )
            self._thread.start()

    def stop(self) -> None:
        """Stop the worker and wait for the camera handle to be released."""
        self._stop_event.set()
        self._restart_event.set()
        thread = self._thread
        if thread is not None and thread.is_alive() and thread is not current_thread():
            thread.join(timeout=5)

    def request_restart(self) -> None:
        """Request a safe camera reopen by the owning worker thread."""
        self._restart_event.set()

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
        """Yield the latest JPEG repeatedly for Flask's MJPEG response."""
        while not self._stop_event.is_set():
            with self._lock:
                frame = self._frame_jpeg
            if frame is None:
                frame = self._offline_frame()
            yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + frame + b"\r\n"
            time.sleep(0.05)

    def _capture_loop(self) -> None:
        capture = None
        while not self._stop_event.is_set():
            if self._restart_event.is_set():
                self._restart_event.clear()
                if capture is not None:
                    capture.release()
                    capture = None
                self._set_camera_status("restarting", None)

            if capture is None:
                capture = self._open_camera()
                if capture is None:
                    self._stop_event.wait(CAMERA_RETRY_SECONDS)
                    continue
                self._set_camera_status("online", None)
                self._last_capture_failure_logged = False

            ok, frame = capture.read()
            if not ok or frame is None:
                self._handle_capture_failure()
                capture.release()
                capture = None
                self._stop_event.wait(CAMERA_RETRY_SECONDS)
                continue

            try:
                self._process_frame(frame)
            except (cv2.error, RuntimeError) as exc:
                self._set_camera_status("offline", f"Frame processing failed: {exc}")
                if not self._last_capture_failure_logged:
                    self.event_logger.add_event(
                        "frame_capture_failure",
                        "A captured frame could not be processed.",
                    )
                    self._last_capture_failure_logged = True
                capture.release()
                capture = None
                self._stop_event.wait(CAMERA_RETRY_SECONDS)

        if capture is not None:
            capture.release()
        self._set_camera_status("offline", None)

    def _open_camera(self):
        try:
            capture = cv2.VideoCapture(self.camera_index)
        except cv2.error as exc:
            self._set_camera_status(
                "offline",
                f"Could not initialize camera index {self.camera_index}: {exc}",
            )
            return None
        if not capture.isOpened():
            capture.release()
            self._set_camera_status(
                "offline",
                f"Could not open camera index {self.camera_index}. Check camera permissions and connection.",
            )
            return None
        capture.set(cv2.CAP_PROP_FRAME_WIDTH, self.frame_width)
        capture.set(cv2.CAP_PROP_FRAME_HEIGHT, self.frame_height)
        return capture

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
        elif state == "one" and previous == "none":
            self.event_logger.add_event("face_detected", "A face was detected.")
        elif state == "one" and previous == "multiple":
            self.event_logger.add_event(
                "face_detected",
                "One face remains visible.",
            )
        self._last_face_state = state

    def _handle_capture_failure(self) -> None:
        self._set_camera_status("offline", "Camera frame capture failed.")
        if not self._last_capture_failure_logged:
            self.event_logger.add_event(
                "frame_capture_failure",
                "The camera stopped returning frames.",
            )
            self._last_capture_failure_logged = True

    def _set_camera_status(self, status: str, error: str | None) -> None:
        with self._lock:
            previous = self._camera_status
            self._camera_status = status
            self._camera_error = error
        if status == "online" and previous != "online":
            self.event_logger.add_event("camera_connected", "Camera connected.")
        elif status == "offline" and previous != "offline":
            self.event_logger.add_event(
                "camera_unavailable",
                error or "Camera unavailable.",
            )

    @staticmethod
    def _offline_frame() -> bytes:
        image = np.zeros((360, 640, 3), dtype="uint8")
        cv2.putText(
            image,
            "Camera unavailable",
            (150, 175),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.9,
            (185, 190, 200),
            2,
            cv2.LINE_AA,
        )
        ok, encoded = cv2.imencode(".jpg", image)
        if not ok:
            raise RuntimeError("Could not encode the offline camera placeholder.")
        return encoded.tobytes()
