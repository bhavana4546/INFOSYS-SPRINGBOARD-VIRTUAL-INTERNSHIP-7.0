# Limitations, privacy, and responsible use

## Detection is not recognition

The Haar Cascade finds regions that look like faces. It does not identify, name, track, or verify individuals. A detected box is not proof that a person is present.

## Image and performance constraints

- Dim, uneven, or back lighting and unusual camera angles can reduce detection quality.
- Masks, hands, hair, and other occlusions can hide facial features.
- Small faces and low-resolution or noisy frames may be missed.
- Haar Cascade detection can produce false positives and false negatives. It is a simple Sprint 1 baseline, not a safety-critical classifier.
- Gaussian blur, grayscale, threshold, and Canny modes transform only the displayed image. Detection continues on the captured color frame; boxes are drawn only in normal mode.
- Frame rate and latency depend on camera hardware, resolution, CPU load, and the number of visible faces. The displayed processing latency measures software processing and JPEG encoding, not the full camera-to-screen delay.
- A missing camera or denied camera permission leaves the dashboard available with an offline status; it cannot provide live detections until the camera works.

## Accessibility, privacy, and responsible use

The dashboard is designed with readable contrast, labels, and responsive layout, but the live camera preview is visual and does not provide a complete screen-reader description of the image. The application does not save recordings or transmit frames to external services. Recent event metadata exists only in application memory and disappears on restart.

Use the camera only with appropriate consent and permission. Clearly inform people when monitoring is active, limit access to the local dashboard, and follow applicable college policies and privacy laws. Do not use this prototype to make identity, disciplinary, safety, or other consequential decisions.
