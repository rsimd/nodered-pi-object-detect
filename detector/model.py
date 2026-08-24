"""YOLO ONNX preprocessing, inference, and postprocessing."""

from __future__ import annotations

from typing import Any

import cv2
import numpy as np
import onnxruntime as ort

from .tracking import Detection

COCO_LABELS = (
    "person", "bicycle", "car", "motorcycle", "airplane", "bus", "train", "truck", "boat", "traffic light",
    "fire hydrant", "stop sign", "parking meter", "bench", "bird", "cat", "dog", "horse", "sheep", "cow",
    "elephant", "bear", "zebra", "giraffe", "backpack", "umbrella", "handbag", "tie", "suitcase", "frisbee",
    "skis", "snowboard", "sports ball", "kite", "baseball bat", "baseball glove", "skateboard", "surfboard", "tennis racket", "bottle",
    "wine glass", "cup", "fork", "knife", "spoon", "bowl", "banana", "apple", "sandwich", "orange",
    "broccoli", "carrot", "hot dog", "pizza", "donut", "cake", "chair", "couch", "potted plant", "bed",
    "dining table", "toilet", "tv", "laptop", "mouse", "remote", "keyboard", "cell phone", "microwave", "oven",
    "toaster", "sink", "refrigerator", "book", "clock", "vase", "scissors", "teddy bear", "hair drier", "toothbrush",
)


class YoloOnnxDetector:
    """Run a YOLO detection ONNX model on CPU."""

    def __init__(self, path: str, config: dict[str, Any]) -> None:
        providers = ["CPUExecutionProvider"]
        self.session = ort.InferenceSession(path, providers=providers)
        self.input_name = self.session.get_inputs()[0].name
        configured_size = config.get("input_size", 640)
        self.input_size = int(configured_size)
        self.confidence = float(config.get("confidence", 0.4))
        self.nms_iou = float(config.get("nms_iou", 0.45))
        class_filter = config.get("classes")
        self.class_filter = set(int(value) for value in class_filter) if class_filter else None

    def infer(self, frame: np.ndarray) -> list[Detection]:
        """Return detections in the original frame coordinates."""

        height, width = frame.shape[:2]
        image, ratio, pad = self._letterbox(frame, self.input_size)
        blob = image.astype(np.float32) / 255.0
        blob = np.transpose(blob, (2, 0, 1))[None, ...]
        outputs = self.session.run(None, {self.input_name: blob})
        rows = self._prediction_rows(outputs)

        boxes: list[list[int]] = []
        scores: list[float] = []
        detections: list[Detection] = []
        for row in rows:
            if row.size < 6:
                continue
            if row.size == 6:
                x1, y1, x2, y2, confidence, class_value = row[:6]
                class_id = int(class_value)
                score = float(confidence)
            else:
                x_center, y_center, box_width, box_height = row[:4]
                class_scores = row[4:]
                if row.size == len(COCO_LABELS) + 5:
                    class_scores = row[5:] * row[4]
                class_id = int(np.argmax(class_scores))
                score = float(class_scores[class_id])
                x1 = x_center - box_width / 2.0
                y1 = y_center - box_height / 2.0
                x2 = x_center + box_width / 2.0
                y2 = y_center + box_height / 2.0
            if score < self.confidence or class_id not in range(len(COCO_LABELS)):
                continue
            if self.class_filter is not None and class_id not in self.class_filter:
                continue
            x1 = (float(x1) - pad[0]) / ratio
            y1 = (float(y1) - pad[1]) / ratio
            x2 = (float(x2) - pad[0]) / ratio
            y2 = (float(y2) - pad[1]) / ratio
            x1 = max(0.0, min(float(width - 1), x1))
            y1 = max(0.0, min(float(height - 1), y1))
            x2 = max(0.0, min(float(width - 1), x2))
            y2 = max(0.0, min(float(height - 1), y2))
            if x2 <= x1 or y2 <= y1:
                continue
            boxes.append([int(x1), int(y1), int(x2 - x1), int(y2 - y1)])
            scores.append(score)
            detections.append(
                Detection(
                    label=COCO_LABELS[class_id],
                    class_id=class_id,
                    confidence=score,
                    bbox=(x1, y1, x2, y2),
                )
            )

        if not boxes:
            return []
        selected = cv2.dnn.NMSBoxes(boxes, scores, self.confidence, self.nms_iou)
        indices = [int(index) for index in np.asarray(selected).reshape(-1)]
        return [detections[index] for index in indices]

    @staticmethod
    def _letterbox(frame: np.ndarray, size: int) -> tuple[np.ndarray, float, tuple[float, float]]:
        height, width = frame.shape[:2]
        ratio = min(size / width, size / height)
        resized_width = max(1, int(round(width * ratio)))
        resized_height = max(1, int(round(height * ratio)))
        resized = cv2.resize(frame, (resized_width, resized_height), interpolation=cv2.INTER_LINEAR)
        pad_x = (size - resized_width) / 2.0
        pad_y = (size - resized_height) / 2.0
        left = int(round(pad_x - 0.1))
        right = int(round(pad_x + 0.1))
        top = int(round(pad_y - 0.1))
        bottom = int(round(pad_y + 0.1))
        padded = cv2.copyMakeBorder(resized, top, bottom, left, right, cv2.BORDER_CONSTANT, value=(114, 114, 114))
        return padded, ratio, (pad_x, pad_y)

    @staticmethod
    def _prediction_rows(outputs: list[np.ndarray]) -> np.ndarray:
        """Normalize common YOLO raw/NMS output layouts to rows."""

        for output in outputs:
            array = np.asarray(output)
            array = np.squeeze(array)
            if array.ndim == 1:
                array = array[None, :]
            if array.ndim != 2:
                continue
            if array.shape[1] in {6, 84, 85}:
                return array
            if array.shape[0] in {6, 84, 85}:
                return array.T
            if array.shape[1] < array.shape[0]:
                return array
        raise RuntimeError("Unsupported YOLO ONNX output shape")
