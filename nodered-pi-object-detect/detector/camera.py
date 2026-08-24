"""Camera adapters for USB V4L2 devices and optional Picamera2 devices."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import cv2
import numpy as np


class OpenCVCamera:
    """Read frames from a V4L2 camera using OpenCV."""

    def __init__(self, device: str, width: int, height: int, fps: int) -> None:
        self.device = device
        self.capture = cv2.VideoCapture(device, cv2.CAP_V4L2)
        self.capture.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        self.capture.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
        self.capture.set(cv2.CAP_PROP_FPS, fps)
        self.capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        if not self.capture.isOpened():
            self.close()
            raise RuntimeError(f"Unable to open camera: {device}")

    def read(self) -> np.ndarray | None:
        """Read one BGR frame, or return ``None`` when no frame is ready."""

        ok, frame = self.capture.read()
        return frame if ok else None

    def close(self) -> None:
        """Release the camera device."""

        if getattr(self, "capture", None) is not None:
            self.capture.release()


class ReplayCamera:
    """Replay JPEG/PNG files for deterministic integration tests."""

    def __init__(self, directory: str) -> None:
        self.paths = sorted(
            path
            for path in Path(directory).iterdir()
            if path.suffix.lower() in {".jpg", ".jpeg", ".png"}
        )
        if not self.paths:
            raise RuntimeError(f"No replay images found in {directory}")
        self.index = 0

    def read(self) -> np.ndarray | None:
        """Read the next image and loop at the end."""

        path = self.paths[self.index]
        self.index = (self.index + 1) % len(self.paths)
        frame = cv2.imread(str(path))
        return frame

    def close(self) -> None:
        """Release the replay source."""


def open_camera(config: dict[str, Any]) -> OpenCVCamera | ReplayCamera:
    """Open the configured camera source."""

    if config.get("replay_dir"):
        return ReplayCamera(str(config["replay_dir"]))
    if config.get("type", "usb") != "usb":
        raise RuntimeError(
            "CSI mode requires Picamera2 installation; use camera.type=usb for the current setup."
        )

    devices = [str(config.get("device", "/dev/video0"))]
    devices.extend(str(item) for item in config.get("fallback_devices", []))
    failures: list[str] = []
    for device in devices:
        try:
            return OpenCVCamera(
                device=device,
                width=int(config.get("width", 640)),
                height=int(config.get("height", 480)),
                fps=int(config.get("fps", 15)),
            )
        except RuntimeError as exc:
            failures.append(str(exc))
    raise RuntimeError("; ".join(failures))
