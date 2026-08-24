"""Capture V4L2 frames and send JPEG packets to the Node-RED camera node."""

from __future__ import annotations

import argparse
import json
import struct
import sys
import time
from pathlib import Path
from typing import Any

import cv2

from .camera import open_camera

PACKET_FRAME = 1
PACKET_STATUS = 2
PACKET_ERROR = 3


def send_packet(packet_type: int, payload: bytes) -> None:
    """Write one length-prefixed packet to stdout."""

    output = sys.stdout.buffer
    output.write(struct.pack(">BI", packet_type, len(payload)))
    output.write(payload)
    output.flush()


def send_json(packet_type: int, payload: dict[str, Any]) -> None:
    """Write a JSON status or error packet."""

    send_packet(packet_type, json.dumps(payload, ensure_ascii=False).encode("utf-8"))


def resolve(root: Path, value: str) -> Path:
    """Resolve a config path relative to the project root."""

    path = Path(value)
    return path if path.is_absolute() else root / path


def run(root: Path, config_path: Path) -> int:
    """Capture and encode frames until the process is terminated."""

    config = json.loads(config_path.read_text(encoding="utf-8"))
    camera_config = config["camera"]
    camera = open_camera(camera_config)
    target_fps = max(1.0, float(camera_config.get("stream_fps", camera_config.get("fps", 15))))
    frame_period = 1.0 / target_fps
    jpeg_quality = max(30, min(95, int(camera_config.get("jpeg_quality", 80))))
    last_emit = 0.0
    last_status = 0.0
    frame_count = 0
    window_started = time.monotonic()
    fps = 0.0
    send_json(
        PACKET_STATUS,
        {"state": "running", "camera": camera_config.get("device", "replay"), "fps": 0.0},
    )

    try:
        while True:
            frame = camera.read()
            now = time.monotonic()
            if frame is None:
                send_json(PACKET_ERROR, {"state": "error", "last_error": "カメラ映像を読み取れません"})
                time.sleep(0.1)
                continue
            if now - last_emit < frame_period:
                continue

            ok, encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, jpeg_quality])
            if not ok:
                send_json(PACKET_ERROR, {"state": "error", "last_error": "JPEG変換に失敗しました"})
                continue
            send_packet(PACKET_FRAME, encoded.tobytes())
            last_emit = now
            frame_count += 1

            if now - window_started >= 1.0:
                fps = frame_count / max(0.001, now - window_started)
                frame_count = 0
                window_started = now
            if now - last_status >= 1.0:
                send_json(
                    PACKET_STATUS,
                    {
                        "state": "running",
                        "camera": camera_config.get("device", "replay"),
                        "fps": round(fps, 2),
                        "frame_bytes": len(encoded),
                    },
                )
                last_status = now
    finally:
        camera.close()
        send_json(PACKET_STATUS, {"state": "stopped"})
    return 0


def main() -> int:
    """Parse arguments and start the camera stream."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--config", type=Path, default=Path("config/detector.json"))
    args = parser.parse_args()
    root = args.root.resolve()
    config_path = args.config if args.config.is_absolute() else root / args.config
    try:
        return run(root, config_path)
    except Exception as exc:  # pylint: disable=broad-except
        send_json(PACKET_ERROR, {"state": "error", "last_error": f"{type(exc).__name__}: {exc}"})
        return 1


if __name__ == "__main__":
    sys.exit(main())
