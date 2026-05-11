from __future__ import annotations

import io
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, Qt, Signal
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen, QPixmap

from app.models import MediaItem
from app.utils import cache_dir, cache_key

try:
    from PIL import Image, ImageOps, ImageSequence
except ImportError:  # pragma: no cover
    Image = None
    ImageOps = None
    ImageSequence = None

try:
    import imageio.v3 as iio
except ImportError:  # pragma: no cover
    iio = None

try:
    from psd_tools import PSDImage
except ImportError:  # pragma: no cover
    PSDImage = None

try:
    import cv2
except ImportError:  # pragma: no cover
    cv2 = None


class ThumbnailWorkerSignals(QObject):
    ready = Signal(int, str, int, QPixmap)
    status = Signal(str)


class ThumbnailWorker(QRunnable):
    def __init__(self, item: MediaItem, size: int, generation: int) -> None:
        super().__init__()
        self.item = item
        self.size = size
        self.generation = generation
        self.signals = ThumbnailWorkerSignals()

    def run(self) -> None:
        pixmap = load_or_create_thumbnail(self.item, self.size, self.signals.status.emit)
        self.signals.ready.emit(self.generation, str(self.item.preview_path), self.size, pixmap)


def load_or_create_thumbnail(item: MediaItem, size: int, status_callback=None) -> QPixmap:
    source_path = item.preview_path
    cache_path = None

    try:
        key = cache_key(source_path)
        cache_path = cache_dir() / f"{key}_{size}.png"
        if cache_path.exists():
            pixmap = QPixmap(str(cache_path))
            if not pixmap.isNull():
                return pixmap
    except OSError:
        cache_path = None

    pixmap = _generate_thumbnail(item, size)
    if cache_path is not None and not pixmap.isNull():
        pixmap.save(str(cache_path), "PNG")
    if status_callback:
        status_callback(f"Generating thumbnails... {item.display_name}")
    return pixmap


def _generate_thumbnail(item: MediaItem, size: int) -> QPixmap:
    image = load_media_qimage(item)
    if image is None or image.isNull():
        return build_placeholder(item.extension or "file", size, item.is_video)

    scaled = image.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    canvas = QPixmap(size, size)
    canvas.fill(QColor("#1e1f22"))

    painter = QPainter(canvas)
    x = (size - scaled.width()) // 2
    y = (size - scaled.height()) // 2
    painter.drawImage(x, y, scaled)
    if item.is_video:
        _draw_video_badge(painter, size)
    elif item.is_sequence:
        _draw_sequence_badge(painter, size)
    painter.end()
    return canvas


def load_media_qimage(item: MediaItem) -> QImage | None:
    path = item.preview_path
    ext = path.suffix.lower()

    try:
        if item.is_video:
            return _load_video_frame(path)
        if ext == ".psd" and PSDImage is not None:
            composite = PSDImage.open(path).composite()
            buffer = io.BytesIO()
            composite.save(buffer, format="PNG")
            image = QImage()
            image.loadFromData(buffer.getvalue(), "PNG")
            return image
        if Image is not None:
            try:
                with Image.open(path) as pil_image:
                    if getattr(pil_image, "is_animated", False) and ImageSequence is not None:
                        pil_image.seek(0)
                    pil_image = ImageOps.exif_transpose(pil_image) if ImageOps else pil_image
                    if pil_image.mode not in ("RGB", "RGBA"):
                        pil_image = pil_image.convert("RGBA")
                    data = pil_image.tobytes("raw", "RGBA")
                    image = QImage(data, pil_image.width, pil_image.height, QImage.Format_RGBA8888)
                    return image.copy()
            except Exception:
                pass
        if iio is not None:
            frame = iio.imread(path)
            if frame.ndim == 2:
                frame = frame[:, :, None]
            if frame.shape[2] == 1:
                frame = frame.repeat(3, axis=2)
            if frame.shape[2] >= 3:
                frame = frame[:, :, :3]
            if frame.dtype != "uint8":
                frame = _normalize_to_uint8(frame)
            height, width, channels = frame.shape
            fmt = QImage.Format_RGB888 if channels == 3 else QImage.Format_RGBA8888
            image = QImage(frame.data, width, height, frame.strides[0], fmt)
            return image.copy()
        image = QImage(str(path))
        return image if not image.isNull() else None
    except Exception:
        return None


def _normalize_to_uint8(frame):
    import numpy as np

    frame = frame.astype("float32")
    max_value = frame.max()
    min_value = frame.min()
    if max_value == min_value:
        return np.zeros_like(frame, dtype="uint8")
    normalized = (frame - min_value) / (max_value - min_value)
    return (normalized * 255).clip(0, 255).astype("uint8")


def _load_video_frame(path: Path) -> QImage | None:
    if cv2 is None:
        image = QImage(str(path))
        return image if not image.isNull() else None

    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        return None
    frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    target_frame = max(0, int(frame_count * 0.1) - 1)
    capture.set(cv2.CAP_PROP_POS_FRAMES, target_frame)
    ok, frame = capture.read()
    capture.release()
    if not ok:
        return None
    frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    height, width, _ = frame.shape
    image = QImage(frame.data, width, height, frame.strides[0], QImage.Format_RGB888)
    return image.copy()


def build_placeholder(label: str, size: int, video: bool = False) -> QPixmap:
    pixmap = QPixmap(size, size)
    pixmap.fill(QColor("#23262b"))
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(QPen(QColor("#4f5b66"), 1))
    painter.drawRoundedRect(4, 4, size - 8, size - 8, 8, 8)
    painter.setPen(QColor("#d9dde3"))
    font = QFont("Segoe UI", max(9, size // 8))
    font.setBold(True)
    painter.setFont(font)
    painter.drawText(pixmap.rect(), Qt.AlignCenter, label.replace(".", "").upper())
    if video:
        _draw_video_badge(painter, size)
    painter.end()
    return pixmap


def _draw_video_badge(painter: QPainter, size: int) -> None:
    badge_width = max(40, size // 2)
    painter.fillRect(size - badge_width - 6, size - 28, badge_width, 22, QColor(0, 0, 0, 170))
    painter.setPen(QColor("#f5f7fa"))
    painter.drawText(size - badge_width - 6, size - 28, badge_width, 22, Qt.AlignCenter, "VIDEO")


def _draw_sequence_badge(painter: QPainter, size: int) -> None:
    badge_width = max(26, size // 3)
    painter.fillRect(6, size - 28, badge_width, 22, QColor(0, 0, 0, 170))
    painter.setPen(QColor("#f5f7fa"))
    painter.drawText(6, size - 28, badge_width, 22, Qt.AlignCenter, "SEQ")
