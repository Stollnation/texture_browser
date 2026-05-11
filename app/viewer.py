from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QEvent, QSize, Qt
from PySide6.QtGui import QImage, QKeySequence, QMouseEvent, QPixmap, QShortcut, QWheelEvent
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from app.models import MediaItem
from app.thumbnailer import build_placeholder, load_media_qimage
from app.utils import format_type_label


class ViewerWindow(QDialog):
    def __init__(self, items: list[MediaItem], current_index: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Texture Browser Viewer")
        self.resize(1100, 760)

        self.items = items
        self.current_index = max(0, min(current_index, len(items) - 1)) if items else 0
        self.sequence_index = 0
        self.original_pixmap = QPixmap()

        self.title_label = QLabel()
        self.info_label = QLabel()
        self.info_label.setStyleSheet("color: #9aa3ad;")

        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setMinimumSize(0, 0)
        self.image_label.setScaledContents(False)

        self.scroll_area = QScrollArea()
        self.scroll_area.setAlignment(Qt.AlignCenter)
        self.scroll_area.setWidgetResizable(False)
        self.scroll_area.setWidget(self.image_label)
        self.scroll_area.viewport().installEventFilter(self)

        self.prev_item_button = QPushButton("Previous")
        self.next_item_button = QPushButton("Next")
        self.prev_item_button.clicked.connect(lambda: self.step_item(-1))
        self.next_item_button.clicked.connect(lambda: self.step_item(1))

        self.prev_frame_button = QPushButton("Prev Frame")
        self.next_frame_button = QPushButton("Next Frame")
        self.prev_frame_button.clicked.connect(lambda: self.step_frame(-1))
        self.next_frame_button.clicked.connect(lambda: self.step_frame(1))

        self.zoom_slider = QSlider(Qt.Horizontal)
        self.zoom_slider.setRange(0, 400)
        self.zoom_slider.setValue(0)
        self.zoom_slider.valueChanged.connect(self._apply_zoom)
        self.zoom_label = QLabel("Fit")
        self.zoom_label.setMinimumWidth(42)

        buttons = QHBoxLayout()
        buttons.addWidget(self.prev_item_button)
        buttons.addWidget(self.next_item_button)
        buttons.addSpacing(16)
        buttons.addWidget(self.prev_frame_button)
        buttons.addWidget(self.next_frame_button)
        buttons.addSpacing(16)
        buttons.addWidget(QLabel("Scale"))
        buttons.addWidget(self.zoom_slider, 1)
        buttons.addWidget(self.zoom_label)
        buttons.addStretch(1)

        layout = QVBoxLayout(self)
        layout.addWidget(self.title_label)
        layout.addWidget(self.info_label)
        layout.addLayout(buttons)
        layout.addWidget(self.scroll_area, 1)

        QShortcut(QKeySequence(Qt.Key_Left), self, activated=lambda: self.step_item(-1))
        QShortcut(QKeySequence(Qt.Key_Right), self, activated=lambda: self.step_item(1))
        QShortcut(QKeySequence(Qt.Key_Up), self, activated=lambda: self.step_frame(-1))
        QShortcut(QKeySequence(Qt.Key_Down), self, activated=lambda: self.step_frame(1))
        QShortcut(QKeySequence(Qt.Key_Escape), self, activated=self.close)
        QShortcut(QKeySequence(Qt.Key_Backspace), self, activated=self.close)

        self.refresh()

    @property
    def item(self) -> MediaItem:
        return self.items[self.current_index]

    def current_path(self) -> Path:
        if self.item.sequence:
            return self.item.sequence.frame_paths[self.sequence_index]
        return self.item.preview_path

    def refresh(self) -> None:
        if not self.items:
            self.close()
            return

        self.setWindowTitle(self.item.display_name)
        self.title_label.setText(self.item.display_name)
        extra = format_type_label(self.item)
        if self.item.sequence:
            current_frame = self.item.sequence.frame_numbers[self.sequence_index]
            extra = f"{extra} | Frame {current_frame}"
        self.info_label.setText(f"{self.current_path()} | {extra}")

        if self.item.is_video:
            image = load_media_qimage(self.item)
            if image is None or image.isNull():
                self._set_pixmap(build_placeholder(self.item.extension, 480, True))
            else:
                self._set_image(image)
        else:
            frame_item = MediaItem(
                display_name=self.item.display_name,
                path=self.current_path(),
                kind=self.item.kind,
                extension=self.item.extension,
                folder=self.item.folder,
                search_text=self.item.search_text,
                sequence=None,
                metadata=self.item.metadata,
            )
            image = load_media_qimage(frame_item)
            if image is None or image.isNull():
                self._set_pixmap(build_placeholder(self.item.extension, 480, False))
            else:
                self._set_image(image)

        self.prev_item_button.setEnabled(self.current_index > 0)
        self.next_item_button.setEnabled(self.current_index < len(self.items) - 1)
        has_sequence = bool(self.item.sequence)
        self.prev_frame_button.setEnabled(has_sequence)
        self.next_frame_button.setEnabled(has_sequence)

    def step_item(self, delta: int) -> None:
        if not self.items:
            return
        new_index = self.current_index + delta
        if new_index < 0 or new_index >= len(self.items):
            return
        self.current_index = new_index
        self.sequence_index = 0
        self.refresh()

    def step_frame(self, delta: int) -> None:
        if not self.item.sequence:
            return
        frame_count = len(self.item.sequence.frame_paths)
        self.sequence_index = (self.sequence_index + delta) % frame_count
        self.refresh()

    def eventFilter(self, watched, event) -> bool:
        if watched is self.scroll_area.viewport() and event.type() == QEvent.Wheel:
            self._zoom_from_wheel(event)
            return True
        return super().eventFilter(watched, event)

    def _set_image(self, image: QImage) -> None:
        pixmap = QPixmap.fromImage(image)
        if pixmap.isNull():
            self._set_pixmap(build_placeholder(self.item.extension, 480, self.item.is_video))
            return
        self._set_pixmap(pixmap)

    def _set_pixmap(self, pixmap: QPixmap) -> None:
        self.original_pixmap = pixmap
        self.zoom_slider.blockSignals(True)
        self.zoom_slider.setValue(0)
        self.zoom_slider.blockSignals(False)
        self._apply_zoom()

    def _apply_zoom(self) -> None:
        if self.original_pixmap.isNull():
            return

        value = self.zoom_slider.value()
        if value == 0:
            viewport_size = self.scroll_area.viewport().size()
            width_scale = viewport_size.width() / max(1, self.original_pixmap.width())
            height_scale = viewport_size.height() / max(1, self.original_pixmap.height())
            scale = min(width_scale, height_scale, 1.0)
            self.zoom_label.setText("Fit")
        else:
            scale = value / 100
            self.zoom_label.setText(f"{value}%")

        scaled_size = QSize(
            max(1, int(self.original_pixmap.width() * scale)),
            max(1, int(self.original_pixmap.height() * scale)),
        )
        pixmap = self.original_pixmap.scaled(scaled_size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.image_label.setPixmap(pixmap)
        self.image_label.setFixedSize(pixmap.size())

    def _fit_zoom_percent(self) -> int:
        if self.original_pixmap.isNull():
            return 100
        viewport_size = self.scroll_area.viewport().size()
        width_scale = viewport_size.width() / max(1, self.original_pixmap.width())
        height_scale = viewport_size.height() / max(1, self.original_pixmap.height())
        return max(10, min(400, int(min(width_scale, height_scale, 1.0) * 100)))

    def _zoom_from_wheel(self, event: QWheelEvent) -> None:
        delta = event.angleDelta().y()
        if delta == 0:
            delta = event.pixelDelta().y()
        if delta == 0:
            return

        current = self.zoom_slider.value()
        if current == 0:
            current = self._fit_zoom_percent()
        step = max(1, round(abs(delta) / 120 * 10))
        value = current + step if delta > 0 else current - step
        self.zoom_slider.setValue(max(10, min(400, value)))
        event.accept()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._apply_zoom()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self.zoom_slider.value() == 0:
            self._apply_zoom()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.BackButton:
            self.close()
            event.accept()
            return
        super().mouseReleaseEvent(event)
