"""Flask application for session-based Team 2 face monitoring."""

from __future__ import annotations

import atexit
import platform
from typing import Any

import cv2
from flask import Flask, Response, jsonify, render_template, request

from services.camera_service import CameraService
from services.monitoring_service import MonitoringError, MonitoringService


def create_app(
    camera_service: CameraService | None = None,
    monitoring_service: MonitoringService | None = None,
) -> Flask:
    """Create the Flask app; injectable services keep API tests hardware-free."""
    app = Flask(__name__)
    if monitoring_service is None:
        factory = (lambda _events: camera_service) if camera_service is not None else None
        monitoring_service = MonitoringService(camera_factory=factory)
    monitoring = monitoring_service
    app.extensions["monitoring_service"] = monitoring
    if camera_service is not None:
        app.extensions["camera_service"] = camera_service

    @app.get("/")
    def dashboard() -> str:
        return render_template("index.html")

    @app.get("/video_feed")
    def active_video_feed() -> Any:
        active = monitoring.get_active_status()
        if active is None:
            return jsonify(
                {
                    "session_id": None,
                    "status": "NOT_STARTED",
                    "message": "Start a session before opening the webcam feed.",
                }
            ), 409
        return stream_response(active["session_id"])

    @app.get("/video_feed/<session_id>")
    def video_feed(session_id: str) -> Any:
        try:
            camera = monitoring.get_camera(session_id)
        except MonitoringError as error:
            return jsonify(error.to_dict()), error.status_code
        return Response(
            camera.stream_frames(),
            mimetype="multipart/x-mixed-replace; boundary=frame",
            headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
        )

    def stream_response(session_id: str) -> Any:
        try:
            camera = monitoring.get_camera(session_id)
        except MonitoringError as error:
            return jsonify(error.to_dict()), error.status_code
        return Response(
            camera.stream_frames(),
            mimetype="multipart/x-mixed-replace; boundary=frame",
            headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
        )

    @app.post("/api/monitoring/start")
    def api_monitoring_start() -> Any:
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            error = MonitoringError("Request body must be a JSON object.", 400, None)
            return jsonify(error.to_dict()), error.status_code
        try:
            return jsonify(monitoring.start_monitoring(data.get("session_id"))), 200
        except MonitoringError as error:
            return jsonify(error.to_dict()), error.status_code

    @app.post("/api/monitoring/stop")
    def api_monitoring_stop() -> Any:
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            error = MonitoringError("Request body must be a JSON object.", 400, None)
            return jsonify(error.to_dict()), error.status_code
        try:
            return jsonify(monitoring.stop_monitoring(data.get("session_id"))), 200
        except MonitoringError as error:
            return jsonify(error.to_dict()), error.status_code

    @app.get("/api/monitoring/status/<session_id>")
    def api_monitoring_status(session_id: str) -> Any:
        try:
            return jsonify(
                {
                    **monitoring.get_status(session_id),
                    "opencv_version": cv2.__version__,
                    "platform": platform.platform(),
                }
            )
        except MonitoringError as error:
            return jsonify(error.to_dict()), error.status_code

    @app.get("/api/status")
    def api_status() -> Any:
        session_id = request.args.get("session_id")
        try:
            current = (
                monitoring.get_status(session_id)
                if session_id
                else monitoring.get_active_status()
            )
        except MonitoringError as error:
            return jsonify(error.to_dict()), error.status_code
        return jsonify(
            {
                **(
                    current
                    if current is not None
                    else {
                        "session_id": None,
                        "status": "NOT_STARTED",
                        "message": "No monitoring session is active.",
                        "error": None,
                        "face_count": 0,
                        "fps": 0,
                        "latency_ms": 0,
                        "processing_mode": "normal",
                        "available_modes": list(CameraService.available_modes),
                        "system_metrics": {"cpu_percent": None, "memory_percent": None},
                        "events": [],
                    }
                ),
                "opencv_version": cv2.__version__,
                "platform": platform.platform(),
                "active_session_id": (
                    current["session_id"] if current and current["status"] == "RUNNING" else None
                ),
            }
        )

    @app.post("/api/settings")
    def api_settings() -> Any:
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify({"error": "Request body must be a JSON object."}), 400
        mode = data.get("mode")
        if not isinstance(mode, str) or mode not in CameraService.available_modes:
            return jsonify(
                {
                    "error": "Invalid processing mode.",
                    "allowed_modes": list(CameraService.available_modes),
                }
            ), 400
        try:
            monitoring.get_camera(data.get("session_id")).set_processing_mode(mode)
        except MonitoringError as error:
            return jsonify(error.to_dict()), error.status_code
        return jsonify(
            {
                "session_id": data["session_id"],
                "status": "RUNNING",
                "message": "Processing mode updated.",
                "mode": mode,
            }
        )

    @app.post("/api/test-event")
    def api_test_event() -> Any:
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify({"error": "Request body must be a JSON object."}), 400
        try:
            session_status = monitoring.get_status(data.get("session_id"))
            if session_status["status"] != "RUNNING":
                raise MonitoringError(
                    "Test events can only be added to a running session.",
                    409,
                    session_status["session_id"],
                    session_status["status"],
                )
            camera = monitoring.get_camera(data["session_id"])
            event = camera.event_logger.add_event(
                "test_event_created",
                "Test event created from the dashboard.",
            )
        except MonitoringError as error:
            return jsonify(error.to_dict()), error.status_code
        return jsonify(
            {
                "session_id": data["session_id"],
                "status": "RUNNING",
                "message": "Test event created.",
                "event": event,
            }
        ), 201

    @app.post("/api/camera/restart")
    def api_camera_restart() -> Any:
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify({"error": "Request body must be a JSON object."}), 400
        try:
            result = monitoring.restart_monitoring(data.get("session_id"))
        except MonitoringError as error:
            return jsonify(error.to_dict()), error.status_code
        return jsonify(result), 200

    def stop_active_session() -> None:
        active = monitoring.get_active_status()
        if active is not None:
            try:
                monitoring.stop_monitoring(active["session_id"])
            except MonitoringError:
                app.logger.exception("Failed to stop active monitoring session at shutdown.")

    atexit.register(stop_active_session)
    return app


app = create_app()


if __name__ == "__main__":
    print("OpenCV & Face Monitoring - Team 2")
    print("Dashboard: http://127.0.0.1:5000")
    app.run(
        host="127.0.0.1",
        port=5000,
        debug=False,
        use_reloader=False,
        threaded=True,
    )
