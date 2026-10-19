"""Flask application for the Team 2 face-monitoring dashboard."""

from __future__ import annotations

import atexit
import platform
from typing import Any

import cv2
from flask import Flask, Response, jsonify, render_template, request

from config import CAMERA_INDEX, FRAME_HEIGHT, FRAME_WIDTH
from services.camera_service import CameraService
from services.event_logger import EventLogger
from services.face_detector import FaceDetector


def create_app(camera_service: CameraService | None = None) -> Flask:
    """Create the Flask app; injectable services keep API tests hardware-free."""
    app = Flask(__name__)
    events = EventLogger()
    if camera_service is None:
        camera_service = CameraService(
            camera_index=CAMERA_INDEX,
            frame_width=FRAME_WIDTH,
            frame_height=FRAME_HEIGHT,
            detector=FaceDetector(),
            event_logger=events,
        )
    camera = camera_service
    app.extensions["camera_service"] = camera
    app.extensions["event_logger"] = events

    @app.get("/")
    def dashboard() -> str:
        return render_template("index.html")

    @app.get("/video_feed")
    def video_feed() -> Response:
        return Response(
            camera.stream_frames(),
            mimetype="multipart/x-mixed-replace; boundary=frame",
            headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
        )

    @app.get("/api/status")
    def api_status() -> Any:
        return jsonify(
            {
                **camera.get_status(),
                "opencv_version": cv2.__version__,
                "platform": platform.platform(),
                "events": events.get_recent_events(),
            }
        )

    @app.post("/api/settings")
    def api_settings() -> Any:
        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify({"error": "Request body must be a JSON object."}), 400
        mode = data.get("mode")
        if not isinstance(mode, str) or mode not in camera.available_modes:
            return jsonify(
                {
                    "error": "Invalid processing mode.",
                    "allowed_modes": list(camera.available_modes),
                }
            ), 400
        camera.set_processing_mode(mode)
        return jsonify({"message": "Processing mode updated.", "mode": mode})

    @app.post("/api/test-event")
    def api_test_event() -> Any:
        event = events.add_event(
            "test_event_created",
            "Test event created from the dashboard.",
        )
        return jsonify({"message": "Test event created.", "event": event}), 201

    @app.post("/api/camera/restart")
    def api_camera_restart() -> Any:
        camera.request_restart()
        return jsonify({"message": "Camera restart requested."}), 202

    atexit.register(camera.stop)
    return app


app = create_app()


if __name__ == "__main__":
    camera_service = app.extensions["camera_service"]
    camera_service.start()
    print("OpenCV & Face Monitoring - Team 2")
    print("Dashboard: http://127.0.0.1:5000")
    try:
        app.run(
            host="127.0.0.1",
            port=5000,
            debug=False,
            use_reloader=False,
            threaded=True,
        )
    finally:
        camera_service.stop()
