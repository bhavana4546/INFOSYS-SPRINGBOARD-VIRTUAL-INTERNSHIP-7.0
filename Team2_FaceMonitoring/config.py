"""Configuration values for camera and face-detection behaviour."""

import os


CAMERA_INDEX = int(os.getenv("FACE_MONITOR_CAMERA_INDEX", "0"))
FRAME_WIDTH = int(os.getenv("FACE_MONITOR_FRAME_WIDTH", "640"))
FRAME_HEIGHT = int(os.getenv("FACE_MONITOR_FRAME_HEIGHT", "480"))
FACE_SCALE_FACTOR = float(os.getenv("FACE_MONITOR_SCALE_FACTOR", "1.1"))
FACE_MIN_NEIGHBORS = int(os.getenv("FACE_MONITOR_MIN_NEIGHBORS", "5"))
FACE_MIN_SIZE = int(os.getenv("FACE_MONITOR_MIN_SIZE", "30"))
CAMERA_RETRY_SECONDS = 2.0
MAX_RECENT_EVENTS = 100
JPEG_QUALITY = 80
