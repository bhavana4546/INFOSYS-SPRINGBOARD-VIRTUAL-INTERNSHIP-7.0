"""Face-only detection using OpenCV's bundled Haar Cascade model."""

import cv2

from config import FACE_MIN_NEIGHBORS, FACE_MIN_SIZE, FACE_SCALE_FACTOR


class FaceDetector:
    """Detect faces, but never attempt to identify who a person is."""

    def __init__(self) -> None:
        cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        try:
            self._classifier = cv2.CascadeClassifier(cascade_path)
        except (AttributeError, cv2.error) as exc:
            raise RuntimeError(
                "This OpenCV installation cannot load Haar Cascade models. "
                "Install the compatible opencv-python package from requirements.txt."
            ) from exc
        if self._classifier.empty():
            raise RuntimeError(
                f"Could not load the OpenCV Haar Cascade model: {cascade_path}"
            )

    def detect(self, frame):
        """Return face rectangles after grayscale conversion and blur."""
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (5, 5), 0)
        faces = self._classifier.detectMultiScale(
            gray,
            scaleFactor=FACE_SCALE_FACTOR,
            minNeighbors=FACE_MIN_NEIGHBORS,
            minSize=(FACE_MIN_SIZE, FACE_MIN_SIZE),
        )
        return list(faces)

    @staticmethod
    def draw_faces(frame, faces):
        """Draw a rectangle and a generic face label on a copy of the frame."""
        result = frame.copy()
        for x, y, width, height in faces:
            cv2.rectangle(result, (x, y), (x + width, y + height), (54, 220, 130), 2)
            cv2.putText(
                result,
                "Face",
                (x, max(y - 8, 18)),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (54, 220, 130),
                2,
                cv2.LINE_AA,
            )
        return result
