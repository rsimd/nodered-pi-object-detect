"""Run object detection on camera frames supplied by Node-RED or a camera."""

from __future__ import annotations

import argparse
import json
import signal
import struct
import sys
import time
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from .camera import open_camera
from .model import YoloOnnxDetector
from .storage import EventStorage
from .tracking import IoUTracker, Track

STOP = False
MAX_FRAME_BYTES = 10 * 1024 * 1024


def emit(kind: str, payload: dict[str, Any]) -> None:
    """Emit one JSON-lines message for the Node-RED custom node."""

    print(json.dumps({"type": kind, "payload": payload}, ensure_ascii=False), flush=True)


def resolve(root: Path, value: str) -> Path:
    """Resolve a config path relative to the project root."""

    path = Path(value)
    return path if path.is_absolute() else root / path


def annotate(frame: Any, tracks: tuple[Track, ...], fps: float, inference_ms: float) -> Any:
    """Draw current tracks and runtime statistics on a preview frame."""

    result = frame.copy()
    for track in tracks:
        x1, y1, x2, y2 = (int(value) for value in track.detection.bbox)
        color = (0, 200, 0) if track.confirmed else (0, 180, 220)
        cv2.rectangle(result, (x1, y1), (x2, y2), color, 2)
        label = f"{track.detection.label} {track.detection.confidence:.2f}"
        cv2.putText(result, label, (x1, max(20, y1 - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2)
    cv2.putText(result, f"FPS {fps:.1f}  infer {inference_ms:.0f} ms", (10, 24), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
    return result


class DetectionPipeline:
    """Hold the model, tracker, and event storage for one process."""

    def __init__(self, root: Path, config: dict[str, Any]) -> None:
        model_config = config["model"]
        runtime_config = config["runtime"]
        model_path = resolve(root, str(model_config["path"]))
        public_dir = resolve(root, str(runtime_config["public_dir"]))
        self.detector = YoloOnnxDetector(str(model_path), model_config)
        self.storage = EventStorage(
            str(public_dir),
            max_events=int(runtime_config.get("retention_count", 500)),
            retention_days=int(runtime_config.get("retention_days", 7)),
        )
        self.tracker = IoUTracker(
            iou_threshold=float(runtime_config.get("track_iou", 0.3)),
            min_hits=int(runtime_config.get("min_track_hits", 3)),
            max_missing_seconds=float(runtime_config.get("max_missing_seconds", 1.5)),
        )
        self.last_detections: list[Any] = []
        self.inference_ms = 0.0

    def process(self, frame: Any, now: float) -> list[dict[str, Any]]:
        """Run inference, update tracks, and save newly confirmed events."""

        started = time.monotonic()
        self.last_detections = self.detector.infer(frame)
        self.inference_ms = (time.monotonic() - started) * 1000.0
        new_tracks = self.tracker.update(self.last_detections, now)
        return [self.storage.save_event(frame, track) for track in new_tracks]

    def write_preview(self, frame: Any, fps: float) -> None:
        """Write the annotated latest frame."""

        self.storage.write_latest(annotate(frame, self.tracker.tracks, fps, self.inference_ms))

    def event_count(self) -> int:
        """Return the current bounded event count."""

        return len(self.storage._load_index())


def create_pipeline(root: Path, config_path: Path) -> tuple[dict[str, Any], DetectionPipeline]:
    """Load configuration and create a detection pipeline."""

    config = json.loads(config_path.read_text(encoding="utf-8"))
    return config, DetectionPipeline(root, config)


def run_camera(root: Path, config_path: Path) -> int:
    """Run the legacy direct-camera mode for command-line compatibility."""

    global STOP
    config, pipeline = create_pipeline(root, config_path)
    camera_config = config["camera"]
    runtime_config = config["runtime"]
    camera = open_camera(camera_config)
    inference_period = 1.0 / max(0.1, float(runtime_config.get("max_inference_fps", 5)))
    last_inference = 0.0
    last_preview = 0.0
    last_status = 0.0
    frame_count = 0
    window_started = time.monotonic()
    fps = 0.0
    last_error = None
    emit("status", {"state": "running", "camera": camera_config.get("device", "replay"), "events_count": 0})

    try:
        while not STOP:
            frame = camera.read()
            now = time.monotonic()
            if frame is None:
                last_error = "Camera frame read failed"
                emit("status", {"state": "error", "last_error": last_error})
                time.sleep(0.1)
                continue
            frame_count += 1
            if now - last_inference >= inference_period:
                for event in pipeline.process(frame, now):
                    emit("event", event)
                last_inference = now
            if now - last_preview >= 0.15:
                pipeline.write_preview(frame, fps)
                last_preview = now
            if now - window_started >= 1.0:
                fps = frame_count / max(0.001, now - window_started)
                frame_count = 0
                window_started = now
            if now - last_status >= 1.0:
                emit(
                    "status",
                    {
                        "state": "running",
                        "camera": camera_config.get("device", "replay"),
                        "fps": round(fps, 2),
                        "inference_ms": round(pipeline.inference_ms, 2),
                        "detections": len(pipeline.last_detections),
                        "tracks": len(pipeline.tracker.tracks),
                        "events_count": pipeline.event_count(),
                        "last_error": last_error,
                    },
                )
                last_status = now
    finally:
        camera.close()
        emit("status", {"state": "stopped"})
    return 0


def read_exact(stream: Any, length: int) -> bytes:
    """Read exactly ``length`` bytes from a binary stream, or EOF."""

    chunks: list[bytes] = []
    remaining = length
    while remaining:
        chunk = stream.read(remaining)
        if not chunk:
            return b""
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def run_frame_stream(root: Path, config_path: Path) -> int:
    """Process length-prefixed JPEG frames arriving on stdin."""

    global STOP
    _config, pipeline = create_pipeline(root, config_path)
    last_status = 0.0
    window_started = time.monotonic()
    frame_count = 0
    fps = 0.0
    emit("status", {"state": "running", "camera": "Node-REDカメラノード", "events_count": pipeline.event_count()})
    emit("ready", {"state": "ready"})

    while not STOP:
        header = read_exact(sys.stdin.buffer, 4)
        if not header:
            break
        frame_length = struct.unpack(">I", header)[0]
        if frame_length == 0 or frame_length > MAX_FRAME_BYTES:
            emit("error", {"state": "error", "last_error": f"入力フレームのサイズが不正です: {frame_length} bytes"})
            emit("ready", {"state": "ready"})
            continue
        encoded = read_exact(sys.stdin.buffer, frame_length)
        if not encoded:
            break
        frame = cv2.imdecode(np.frombuffer(encoded, dtype=np.uint8), cv2.IMREAD_COLOR)
        if frame is None:
            emit("error", {"state": "error", "last_error": "JPEGフレームを読み取れません"})
            emit("ready", {"state": "ready"})
            continue

        now = time.monotonic()
        for event in pipeline.process(frame, now):
            emit("event", event)
        frame_count += 1
        if now - window_started >= 1.0:
            fps = frame_count / max(0.001, now - window_started)
            frame_count = 0
            window_started = now
        pipeline.write_preview(frame, fps)
        if now - last_status >= 1.0:
            emit(
                "status",
                {
                    "state": "running",
                    "camera": "Node-REDカメラノード",
                    "fps": round(fps, 2),
                    "inference_ms": round(pipeline.inference_ms, 2),
                    "detections": len(pipeline.last_detections),
                    "tracks": len(pipeline.tracker.tracks),
                    "events_count": pipeline.event_count(),
                    "last_error": None,
                },
            )
            last_status = now
        emit("ready", {"state": "ready"})

    emit("status", {"state": "stopped"})
    return 0


def main() -> int:
    """Parse arguments and run the selected input mode."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--config", type=Path, default=Path("config/detector.json"))
    parser.add_argument("--input-frames", action="store_true", help="read length-prefixed JPEG frames from stdin")
    args = parser.parse_args()
    root = args.root.resolve()
    config_path = args.config if args.config.is_absolute() else root / args.config

    def stop_handler(_signum: int, _frame: Any) -> None:
        global STOP
        STOP = True

    signal.signal(signal.SIGTERM, stop_handler)
    signal.signal(signal.SIGINT, stop_handler)
    try:
        if args.input_frames:
            return run_frame_stream(root, config_path)
        return run_camera(root, config_path)
    except Exception as exc:  # pylint: disable=broad-except
        emit("error", {"state": "error", "last_error": f"{type(exc).__name__}: {exc}"})
        return 1


if __name__ == "__main__":
    sys.exit(main())
