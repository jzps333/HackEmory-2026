"""Find and decode a QR code in one video frame.

Uses only OpenCV (opencv-python-headless), so no system libraries like zbar are needed.

    from chert.qr_reader import read_qr
    text = read_qr(frame)   # numpy array (RGB, BGR, RGBA or gray) or a PIL image -> str | None

Phone-camera frames are often blurry, dim, small or glary, so we try the frame as-is first and
then a few cleaned-up versions (grayscale, resized, contrast-boosted, thresholded). Every
attempt is cheap (a few ms on a 720p frame), and we stop at the first one that decodes.
"""
from __future__ import annotations

import time
from typing import Any, Iterator, Optional

import cv2
import numpy as np

# Frames bigger than this get shrunk before the cleaned-up attempts (the detector is slow and
# no more accurate on huge images); QR codes smaller than SMALL get blown up.
MAX_SIDE = 1280
SMALL_SIDE = 480

_detector = cv2.QRCodeDetector()
try:  # newer OpenCV ships a second, often more robust, detector
    _aruco_detector: Any = cv2.QRCodeDetectorAruco()
except AttributeError:  # pragma: no cover - depends on the OpenCV build
    _aruco_detector = None


def to_array(frame: Any) -> np.ndarray:
    """Turn a PIL image or numpy array into a uint8 numpy array (gray or 3-channel)."""
    if not isinstance(frame, np.ndarray):
        # PIL image (or anything with the array interface)
        if hasattr(frame, "mode") and getattr(frame, "mode") not in ("L", "RGB"):
            frame = frame.convert("RGB")
        frame = np.asarray(frame)
    arr = frame
    if arr.dtype != np.uint8:
        if arr.dtype.kind == "f" and arr.size and float(arr.max()) <= 1.0:
            arr = arr * 255.0
        arr = np.clip(arr, 0, 255).astype(np.uint8)
    if arr.ndim == 3 and arr.shape[2] == 4:      # RGBA / BGRA -> drop alpha
        arr = arr[:, :, :3]
    if arr.ndim == 3 and arr.shape[2] == 1:
        arr = arr[:, :, 0]
    return np.ascontiguousarray(arr)


def _gray(arr: np.ndarray) -> np.ndarray:
    # Channel order (RGB vs BGR) barely matters for a black-and-white code.
    return arr if arr.ndim == 2 else cv2.cvtColor(arr, cv2.COLOR_BGR2GRAY)


def _resize_to(gray: np.ndarray, side: int) -> np.ndarray:
    h, w = gray.shape[:2]
    scale = side / float(max(h, w))
    interp = cv2.INTER_AREA if scale < 1 else cv2.INTER_CUBIC
    return cv2.resize(gray, (max(1, int(w * scale)), max(1, int(h * scale))), interpolation=interp)


def _variants(arr: np.ndarray) -> Iterator[np.ndarray]:
    """The frame as-is, then progressively more processed versions."""
    yield arr
    gray = _gray(arr)
    yield gray
    side = max(gray.shape[:2])
    if side > MAX_SIDE:
        gray = _resize_to(gray, MAX_SIDE)
        yield gray
    elif side < SMALL_SIDE:
        gray = _resize_to(gray, SMALL_SIDE * 2)
        yield gray
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8)).apply(gray)
    yield clahe
    yield cv2.equalizeHist(gray)
    sharp = cv2.addWeighted(gray, 1.8, cv2.GaussianBlur(gray, (0, 0), 3), -0.8, 0)
    yield sharp
    yield cv2.adaptiveThreshold(cv2.GaussianBlur(gray, (3, 3), 0), 255,
                                cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 5)
    _, otsu = cv2.threshold(clahe, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    yield otsu
    # Upscaled copy as a last try (helps when the code fills only a small part of the frame).
    if max(gray.shape[:2]) <= MAX_SIDE:
        yield cv2.resize(clahe, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    # Light-on-dark codes (inverted) - rare but cheap to check.
    yield cv2.bitwise_not(gray)


def _decode_one(detector: Any, img: np.ndarray) -> Optional[str]:
    try:
        text, points, _ = detector.detectAndDecode(img)
    except cv2.error:
        return None
    if text:
        return text
    if points is None:
        return None
    try:  # found a code but couldn't read it as one; try the multi-code path too
        ok, texts, _, _ = detector.detectAndDecodeMulti(img)
    except (cv2.error, AttributeError):
        return None
    if ok:
        for t in texts:
            if t:
                return t
    return None


def read_qr(frame: Any, time_budget_s: Optional[float] = None) -> Optional[str]:
    """Return the text inside the first QR code found in ``frame``, or None.

    ``time_budget_s`` stops trying more cleaned-up versions once that much time has passed
    (the live video loop uses this so a busy, code-free frame can't stall it).
    """
    if frame is None:
        return None
    try:
        arr = to_array(frame)
    except Exception:
        return None
    if arr.size == 0 or arr.ndim not in (2, 3):
        return None
    detectors = [d for d in (_detector, _aruco_detector) if d is not None]
    deadline = None if time_budget_s is None else time.monotonic() + time_budget_s
    for img in _variants(arr):
        if deadline is not None and time.monotonic() > deadline:
            return None
        for det in detectors:
            text = _decode_one(det, img)
            if text:
                return text.strip() or None
    return None
