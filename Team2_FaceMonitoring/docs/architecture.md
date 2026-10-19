# System architecture

## Frame and metrics pipeline

**Webcam → Frame acquisition → Preprocessing → Face detection → Bounding boxes → Metrics → Dashboard**

1. **Webcam:** OpenCV opens the configured camera index on the local machine.
2. **Frame acquisition:** `CameraService` captures frames on a dedicated background thread so Flask can continue responding to dashboard and API requests.
3. **Preprocessing:** Frames are converted to grayscale and blurred for the Haar Cascade detector. A separately selected display mode can show normal color, grayscale, Gaussian blur, binary thresholding, or Canny edges.
4. **Face detection:** The bundled OpenCV frontal-face Haar Cascade finds face-like regions. It detects regions only; it does not identify people.
5. **Bounding boxes:** In normal video mode, detected regions are drawn as generic green boxes labelled “Face”. Other display modes show their chosen image transform; detection and face counts still run on the original camera frame.
6. **Metrics:** The service updates face count, smoothed frame rate, frame-processing latency, and camera status. CPU and memory values are reported if `psutil` is available.
7. **Dashboard:** Flask serves the page, MJPEG stream, status JSON, and controls. Browser JavaScript polls status and creates event-log elements using safe DOM text nodes.

## Module responsibilities

- `app.py` creates the Flask app and routes. The `__main__` section starts and stops the camera without Flask's debug reloader.
- `config.py` holds camera and detector settings, with camera/detection overrides available through environment variables.
- `services/camera_service.py` owns camera capture, the worker thread, processing modes, metrics, restart requests, and the MJPEG stream.
- `services/face_detector.py` loads OpenCV's bundled Haar Cascade and performs face detection and generic box drawing.
- `services/event_logger.py` stores up to 100 recent, timestamped events in a lock-protected in-memory queue.
- `templates/index.html` defines dashboard structure and educational project information.
- `static/css/style.css` contains the responsive dark dashboard styling without external assets.
- `static/js/dashboard.js` refreshes status, safely renders event messages, and calls the settings and action APIs.
