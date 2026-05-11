from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QThreadPool, QTimer
from PySide6.QtWidgets import QDialog, QLabel, QVBoxLayout, QWidget

from app.models import MediaItem
from app.thumbnail_grid import ThumbnailGrid
from app.thumbnailer import ThumbnailWorker
from app.viewer import ViewerWindow


class AssociatedBrowserDialog(QDialog):
    def __init__(
        self,
        items: list[MediaItem],
        current_index: int,
        thumbnail_size: int,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Associated Textures")
        self.resize(920, 620)

        self.items = items
        self.current_index = max(0, min(current_index, len(items) - 1)) if items else 0
        self.thumbnail_size = thumbnail_size
        self.thumbnail_pool = QThreadPool(self)
        self.thumbnail_pool.setMaxThreadCount(4)
        self._thumb_jobs: set[tuple[str, int]] = set()
        self._selection_applied = False

        self.title_label = QLabel(f"{len(items)} associated texture(s)")
        self.grid = ThumbnailGrid()
        self.grid.set_thumbnail_size(thumbnail_size)
        self.grid.itemActivated.connect(self.open_viewer)
        self.grid.thumbnailRequested.connect(self.request_thumbnail)
        self.grid.visibleRangeChanged.connect(self.request_visible_thumbnails)
        self.grid.populationProgress.connect(lambda *_args: self._select_initial_item())
        self.grid.populationFinished.connect(lambda _count: self._select_initial_item())

        layout = QVBoxLayout(self)
        layout.addWidget(self.title_label)
        layout.addWidget(self.grid, 1)

        self.grid.set_items(items)
        QTimer.singleShot(0, self.request_visible_thumbnails)

    def request_visible_thumbnails(self) -> None:
        for item in self.grid.visible_items():
            self.grid.thumbnailRequested.emit(item)

    def request_thumbnail(self, item: MediaItem) -> None:
        path_key = str(item.preview_path)
        key = (path_key, self.thumbnail_size)
        if key in self._thumb_jobs:
            return
        self._thumb_jobs.add(key)
        worker = ThumbnailWorker(item, self.thumbnail_size, 0)
        worker.signals.ready.connect(self._thumbnail_ready)
        self.thumbnail_pool.start(worker)

    def _thumbnail_ready(self, generation: int, path_key: str, size: int, pixmap) -> None:
        self._thumb_jobs.discard((path_key, size))
        if size != self.thumbnail_size:
            return
        self.grid.set_thumbnail(path_key, pixmap)
        if self.thumbnail_pool.activeThreadCount() < 2:
            self.request_visible_thumbnails()

    def open_viewer(self, item: MediaItem) -> None:
        items = self.grid.filtered_items()
        current_index = 0
        for index, media_item in enumerate(items):
            if media_item.preview_path == item.preview_path and media_item.display_name == item.display_name:
                current_index = index
                break
        viewer = ViewerWindow(items, current_index, self)
        viewer.exec()

    def _select_initial_item(self) -> None:
        if self._selection_applied:
            return
        if self.current_index >= self.grid.count():
            return

        item = self.grid.item(self.current_index)
        if item is None:
            return

        self.grid.setCurrentItem(item)
        self.grid.scrollToItem(item)
        self._selection_applied = True
