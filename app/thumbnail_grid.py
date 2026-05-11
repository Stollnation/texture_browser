from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QEvent, QMimeData, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QWidget,
)

from app.models import MediaItem
from app.thumbnailer import build_placeholder
from app.utils import format_type_label, open_in_explorer


class ThumbnailGrid(QListWidget):
    itemActivated = Signal(MediaItem)
    thumbnailRequested = Signal(MediaItem)
    visibleRangeChanged = Signal()
    populationFinished = Signal(int)
    populationProgress = Signal(int, int)
    filesDropped = Signal(list)
    associatedRequested = Signal(MediaItem)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._items: list[MediaItem] = []
        self._item_map: dict[Path, QListWidgetItem] = {}
        self._thumb_size = 160
        self._loaded_paths: set[Path] = set()
        self._prefetch_chunk_size = 100
        self._populate_batch_size = 250
        self._pending_items: list[MediaItem] = []
        self._added_count = 0
        self._filter_query = ""
        self._filter_terms: list[str] = []
        self._fbx_only = False
        self._visible_count = 0
        self._visible_timer = QTimer(self)
        self._visible_timer.setSingleShot(True)
        self._visible_timer.setInterval(60)
        self._visible_timer.timeout.connect(self._emit_visible_range_changed)
        self._populate_timer = QTimer(self)
        self._populate_timer.setSingleShot(True)
        self._populate_timer.setInterval(0)
        self._populate_timer.timeout.connect(self._populate_next_batch)

        self.setViewMode(QListWidget.IconMode)
        self.setResizeMode(QListWidget.Adjust)
        self.setMovement(QListWidget.Static)
        self.setSpacing(12)
        self.setUniformItemSizes(True)
        self.setWordWrap(True)
        self.setAcceptDrops(True)
        self.setDragEnabled(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.DragDrop)
        self.setDefaultDropAction(Qt.CopyAction)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.itemDoubleClicked.connect(self._on_item_double_clicked)
        self.customContextMenuRequested.connect(self._show_context_menu)
        self.verticalScrollBar().valueChanged.connect(self.schedule_visible_refresh)
        self.horizontalScrollBar().valueChanged.connect(self.schedule_visible_refresh)
        self.viewport().installEventFilter(self)
        self._apply_size()

    def set_thumbnail_size(self, size: int) -> None:
        self._thumb_size = size
        self._loaded_paths.clear()
        self._apply_size()
        for row in range(self.count()):
            item = self.item(row)
            media_item = item.data(Qt.UserRole)
            placeholder = build_placeholder(media_item.extension or "file", self._thumb_size, media_item.is_video)
            item.setIcon(QIcon(placeholder))
        self.schedule_visible_refresh()

    def set_items(self, items: list[MediaItem]) -> None:
        self.reset_grid_state()
        self._items = items
        self._pending_items = list(items)
        self._added_count = 0
        self._visible_count = 0
        self._populate_timer.start()

    def append_items(self, items: list[MediaItem]) -> None:
        if not items:
            return
        self._items.extend(items)
        self._pending_items.extend(items)
        if not self._populate_timer.isActive():
            self._populate_timer.start()

    def reset_grid_state(self) -> None:
        self._populate_timer.stop()
        self._visible_timer.stop()
        self.clear()
        self._items = []
        self._item_map.clear()
        self._loaded_paths.clear()
        self._pending_items = []
        self._added_count = 0
        self._visible_count = 0

    def apply_filter(self, text: str, fbx_only: bool = False) -> None:
        query = text.strip().lower()
        self._filter_query = query
        self._filter_terms = [term.strip() for term in query.split(",") if term.strip()]
        self._fbx_only = fbx_only
        visible_count = 0
        for row in range(self.count()):
            item = self.item(row)
            media_item = item.data(Qt.UserRole)
            hidden = self._is_hidden_by_filter(media_item)
            item.setHidden(hidden)
            if not hidden:
                visible_count += 1
        self._visible_count = visible_count
        self.schedule_visible_refresh()

    def set_thumbnail(self, path_key: str, pixmap) -> None:
        path = Path(path_key)
        item = self._item_map.get(path)
        if item is None:
            return
        item.setIcon(QIcon(pixmap))
        self._loaded_paths.add(path)

    def visible_items(self) -> list[MediaItem]:
        if self.count() == 0:
            return []

        return self._collect_unloaded_visible_items()

    def prefetch_items(self) -> list[MediaItem]:
        if self.count() == 0:
            return []

        visible_rows = self._visible_row_indexes()
        if not visible_rows:
            return []
        bottom_row = visible_rows[-1]
        next_start = bottom_row + 1
        next_end = min(self.count() - 1, bottom_row + self._prefetch_chunk_size)
        if next_start <= next_end:
            return self._collect_unloaded_items(next_start, next_end)
        return []

    def _apply_size(self) -> None:
        self.setIconSize(QSize(self._thumb_size, self._thumb_size))
        self.setGridSize(QSize(self._thumb_size + 56, self._thumb_size + 62))

    def schedule_visible_refresh(self) -> None:
        self._visible_timer.start()

    def visible_count(self) -> int:
        return self._visible_count

    def total_count(self) -> int:
        return len(self._items)

    def filtered_items(self) -> list[MediaItem]:
        items: list[MediaItem] = []
        for row in range(self.count()):
            item = self.item(row)
            if item.isHidden():
                continue
            items.append(item.data(Qt.UserRole))
        return items

    def index_of_item(self, target: MediaItem) -> int:
        filtered = self.filtered_items()
        for index, item in enumerate(filtered):
            if item.preview_path == target.preview_path and item.display_name == target.display_name:
                return index
        return -1

    def mimeData(self, items: list[QListWidgetItem]) -> QMimeData:
        mime_data = QMimeData()
        paths: list[Path] = []
        seen: set[Path] = set()
        for item in items:
            media_item = item.data(Qt.UserRole)
            if media_item is None:
                continue
            item_paths = media_item.sequence.frame_paths if media_item.sequence else [media_item.preview_path]
            for path in item_paths:
                resolved = path.resolve()
                if resolved in seen:
                    continue
                seen.add(resolved)
                paths.append(resolved)
        mime_data.setUrls([QUrl.fromLocalFile(str(path)) for path in paths])
        return mime_data

    def supportedDropActions(self):
        return Qt.CopyAction

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            return
        super().dragMoveEvent(event)

    def dropEvent(self, event) -> None:
        if not event.mimeData().hasUrls():
            super().dropEvent(event)
            return

        paths = [Path(url.toLocalFile()) for url in event.mimeData().urls() if url.isLocalFile()]
        if paths:
            self.filesDropped.emit(paths)
            event.acceptProposedAction()
            return
        super().dropEvent(event)

    def eventFilter(self, watched, event) -> bool:
        if watched is self.viewport() and event.type() in {QEvent.Resize, QEvent.Paint, QEvent.Wheel}:
            self.schedule_visible_refresh()
        return super().eventFilter(watched, event)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.schedule_visible_refresh()

    def _on_item_double_clicked(self, item: QListWidgetItem) -> None:
        media_item = item.data(Qt.UserRole)
        self.itemActivated.emit(media_item)

    def _show_context_menu(self, position) -> None:
        item = self.itemAt(position)
        if item is None:
            return
        media_item = item.data(Qt.UserRole)

        menu = QMenu(self)
        associated_action = QAction("Select associated", self)
        open_action = QAction("Open file location", self)
        copy_file_action = QAction("Copy file path", self)
        copy_folder_action = QAction("Copy folder path", self)

        associated_action.triggered.connect(lambda: self.associatedRequested.emit(media_item))
        open_action.triggered.connect(lambda: open_in_explorer(media_item.preview_path))
        copy_file_action.triggered.connect(
            lambda: QApplication.clipboard().setText(str(media_item.preview_path))
        )
        copy_folder_action.triggered.connect(
            lambda: QApplication.clipboard().setText(str(media_item.folder))
        )

        menu.addAction(associated_action)
        menu.addSeparator()
        menu.addAction(open_action)
        menu.addAction(copy_file_action)
        menu.addAction(copy_folder_action)
        menu.exec(self.mapToGlobal(position))

    def _emit_visible_range_changed(self) -> None:
        self.visibleRangeChanged.emit()

    def _populate_next_batch(self) -> None:
        if not self._pending_items:
            self.populationFinished.emit(self._visible_count)
            self.schedule_visible_refresh()
            return

        batch = self._pending_items[: self._populate_batch_size]
        del self._pending_items[: self._populate_batch_size]

        for media_item in batch:
            widget_item = QListWidgetItem()
            widget_item.setText(f"{media_item.display_name}\n{format_type_label(media_item)}")
            widget_item.setData(Qt.UserRole, media_item)
            placeholder = build_placeholder(media_item.extension or "file", self._thumb_size, media_item.is_video)
            widget_item.setIcon(QIcon(placeholder))
            hidden = self._is_hidden_by_filter(media_item)
            self.addItem(widget_item)
            widget_item.setHidden(hidden)
            if not hidden:
                self._visible_count += 1
            self._item_map[media_item.preview_path] = widget_item

        self._added_count += len(batch)
        self.populationProgress.emit(self._added_count, len(self._items))
        self._populate_timer.start()

    def _visible_row_indexes(self) -> list[int]:
        viewport_rect = self.viewport().rect()
        rows: list[int] = []
        for row in range(self.count()):
            item = self.item(row)
            if item.isHidden():
                continue
            item_rect = self.visualItemRect(item)
            if item_rect.isValid() and item_rect.intersects(viewport_rect):
                rows.append(row)
        return rows

    def _collect_unloaded_visible_items(self) -> list[MediaItem]:
        items: list[MediaItem] = []
        for row in self._visible_row_indexes():
            item = self.item(row)
            media_item = item.data(Qt.UserRole)
            if media_item.preview_path in self._loaded_paths:
                continue
            items.append(media_item)
        return items

    def _collect_unloaded_items(self, start_row: int, end_row: int) -> list[MediaItem]:
        items: list[MediaItem] = []
        for row in range(start_row, end_row + 1):
            item = self.item(row)
            if item.isHidden():
                continue
            media_item = item.data(Qt.UserRole)
            if media_item.preview_path in self._loaded_paths:
                continue
            items.append(media_item)
        return items

    def _is_hidden_by_filter(self, media_item: MediaItem) -> bool:
        missing_required_term = any(term not in media_item.search_text for term in self._filter_terms)
        return missing_required_term or (self._fbx_only and media_item.extension != ".fbx")
