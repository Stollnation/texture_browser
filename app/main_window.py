from __future__ import annotations

from datetime import datetime
import os
import re
import shutil
import sys
from pathlib import Path

from PySide6.QtCore import QThreadPool, Qt, QTimer
from PySide6.QtGui import QImageReader
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSplitter,
    QStatusBar,
    QToolBar,
    QVBoxLayout,
    QWidget,
)

from app.associated_browser import AssociatedBrowserDialog
from app.favorites import FavoritesStore
from app.folder_tree import FolderBrowser
from app.models import THUMBNAIL_DIMENSIONS, ThumbnailSize
from app.scanner import ScanWorker
from app.thumbnail_grid import ThumbnailGrid
from app.thumbnailer import ThumbnailWorker
from app.utils import (
    format_type_label,
    is_drive_root,
    open_fbx_in_viewer,
    open_folder_in_explorer,
    open_video_in_vlc,
)
from app.viewer import ViewerWindow


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Texture Browser")
        self.resize(1440, 900)

        self.scan_pool = QThreadPool(self)
        self.scan_pool.setMaxThreadCount(1)
        self.thumbnail_pool = QThreadPool(self)
        self.thumbnail_pool.setMaxThreadCount(4)
        self.settings = FavoritesStore()
        self.current_scan: ScanWorker | None = None
        self.current_root: Path | None = None
        self.items = []
        self._thumb_jobs: set[tuple[int, str, int]] = set()
        self._thumbnail_generation = 0
        self._scan_token = 0
        self._scan_found_count = 0
        self._prefetch_timer = QTimer(self)
        self._prefetch_timer.setSingleShot(True)
        self._prefetch_timer.setInterval(180)
        self._prefetch_timer.timeout.connect(self._request_prefetch_thumbnails)

        self.folder_browser = FolderBrowser()
        self.folder_browser.folderSelected.connect(self.select_folder)
        self.folder_browser.folderOpenRequested.connect(self.open_folder_location)
        self.folder_browser.addFavoriteRequested.connect(self.add_favorite)
        self.folder_browser.removeFavoriteRequested.connect(self.remove_favorite)

        self.search_box = QLineEdit()
        self.search_box.setPlaceholderText("Search, or paste a folder/file path and press Enter...")
        self.search_box.textChanged.connect(self.apply_filter)
        self.search_box.returnPressed.connect(self.browse_to_search_path)
        self.browse_path_button = QPushButton("Browse Path")
        self.browse_path_button.clicked.connect(self.browse_to_search_path)

        self.grid = ThumbnailGrid()
        self.grid.itemActivated.connect(self.open_viewer)
        self.grid.thumbnailRequested.connect(self.request_thumbnail)
        self.grid.visibleRangeChanged.connect(self.request_visible_thumbnails)
        self.grid.populationProgress.connect(self._handle_population_progress)
        self.grid.populationFinished.connect(self._handle_population_finished)
        self.grid.itemSelectionChanged.connect(self.update_selected_info)
        self.grid.filesDropped.connect(self.import_dropped_files)
        self.grid.associatedRequested.connect(self.open_associated_viewer)

        size_bar = QHBoxLayout()
        size_bar.addWidget(QLabel("Thumbnails"))
        self.size_buttons = {}
        for size in ThumbnailSize:
            button = QPushButton(size.value)
            button.setCheckable(True)
            button.clicked.connect(lambda checked=False, chosen=size: self.set_thumbnail_size(chosen))
            self.size_buttons[size] = button
            size_bar.addWidget(button)
        self.fbx_checkbox = QCheckBox("FBX")
        self.fbx_checkbox.toggled.connect(lambda _checked: self.apply_filter(self.search_box.text()))
        size_bar.addSpacing(18)
        size_bar.addWidget(self.fbx_checkbox)
        self.naming_convention_box = QLineEdit()
        self.naming_convention_box.setPlaceholderText("metallic, albedo, roughness, normal")
        self.naming_convention_box.setMinimumWidth(280)
        self.naming_convention_box.textChanged.connect(self.save_naming_convention)
        size_bar.addSpacing(18)
        size_bar.addWidget(QLabel("Naming convention"))
        size_bar.addWidget(self.naming_convention_box, 1)
        size_bar.addStretch(1)

        self.info_label = QLabel("Select an item to see file info.")
        self.info_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.info_label.setWordWrap(True)
        self.info_label.setStyleSheet(
            "QLabel { color: #d7dde5; background: #2f343a; border: 1px solid #4a5058; padding: 6px 8px; }"
        )

        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        search_row = QHBoxLayout()
        search_row.addWidget(self.search_box, 1)
        search_row.addWidget(self.browse_path_button)
        right_layout.addLayout(search_row)
        right_layout.addLayout(size_bar)
        right_layout.addWidget(self.info_label)
        right_layout.addWidget(self.grid, 1)

        splitter = QSplitter()
        splitter.addWidget(self.folder_browser)
        splitter.addWidget(right_panel)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([340, 1100])

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.addWidget(splitter)
        self.setCentralWidget(container)

        toolbar = QToolBar("Main")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)
        choose_root = QPushButton("Choose Root Folder")
        choose_root.clicked.connect(self.choose_root_folder)
        cancel_button = QPushButton("Cancel Scan")
        cancel_button.clicked.connect(self.cancel_scan)
        toolbar.addWidget(choose_root)
        toolbar.addWidget(cancel_button)

        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)

        self.favorites = self.settings.load()
        self.folder_browser.set_favorites(self.favorites)

        stored_size = self.settings.load_thumbnail_size()
        size_choice = ThumbnailSize(stored_size) if stored_size in {size.value for size in ThumbnailSize} else ThumbnailSize.MEDIUM
        self.set_thumbnail_size(size_choice)
        self.naming_convention_box.setText(self.settings.load_naming_convention())

        last_root = self.settings.load_last_root()
        if last_root:
            self.current_root = last_root
            self.folder_browser.set_current_folder(last_root)
            self.status_bar.showMessage(f"Ready. Last folder: {last_root}")

    def choose_root_folder(self) -> None:
        start_dir = str(self.current_root or Path.home())
        folder = QFileDialog.getExistingDirectory(self, "Choose Root Directory", start_dir)
        if folder:
            path = Path(folder)
            self.folder_browser.set_current_folder(path)
            self.select_folder(path)

    def browse_to_search_path(self) -> None:
        path = self._path_from_search_text()
        if path is None:
            self.status_bar.showMessage("Enter an existing folder or file path to browse to it.")
            return

        if path.is_dir():
            self._set_search_text_without_filter("")
            self.folder_browser.set_current_folder(path)
            self.select_folder(path)
            return

        if path.is_file():
            parent = path.parent
            self._set_search_text_without_filter(path.name)
            self.folder_browser.set_current_folder(parent)
            self.select_folder(parent)

    def _path_from_search_text(self) -> Path | None:
        text = self.search_box.text().strip().strip('"').strip("'")
        if not text:
            return None

        path = Path(os.path.expandvars(text)).expanduser()
        if path.exists():
            return path
        return None

    def _set_search_text_without_filter(self, text: str) -> None:
        self.search_box.blockSignals(True)
        self.search_box.setText(text)
        self.search_box.blockSignals(False)

    def select_folder(self, path: Path) -> None:
        if not path.exists():
            return

        if is_drive_root(path):
            self.current_root = path
            self.cancel_scan()
            self._scan_token += 1
            self._prefetch_timer.stop()
            self._reset_thumbnail_queue()
            self.items = []
            self.grid.reset_grid_state()
            self.update_selected_info()
            self.status_bar.showMessage(f"Select a folder inside {path} to scan. Drive roots are skipped.")
            return

        self.current_root = path
        self.settings.save_last_root(path)
        self.cancel_scan()
        self._prefetch_timer.stop()
        self._reset_thumbnail_queue()
        self.items = []

        self.grid.reset_grid_state()
        self.update_selected_info()
        self.status_bar.showMessage(f"Scanning {path}...")
        self._scan_token += 1
        self._scan_found_count = 0
        token = self._scan_token
        worker = ScanWorker(path)
        worker.signals.progress.connect(self.status_bar.showMessage)
        worker.signals.batch.connect(
            lambda items, found_count, scan_token=token: self._handle_scan_batch(scan_token, items, found_count)
        )
        worker.signals.result.connect(
            lambda found_count, scan_token=token: self._handle_scan_result(scan_token, found_count)
        )
        worker.signals.error.connect(lambda message, scan_token=token: self._handle_scan_error(scan_token, message))
        worker.signals.finished.connect(lambda scan_token=token: self._scan_finished(scan_token))
        self.current_scan = worker
        self.scan_pool.start(worker)

    def cancel_scan(self) -> None:
        if self.current_scan is not None:
            self.current_scan.cancel()
            self.current_scan = None

    def _handle_scan_batch(self, scan_token: int, items: list, found_count: int) -> None:
        if scan_token != self._scan_token:
            return
        if not self.items:
            self.grid.reset_grid_state()
        self.items.extend(items)
        self._scan_found_count = found_count
        self.grid.append_items(items)
        self.apply_filter(self.search_box.text())
        self.status_bar.showMessage(f"Scanning... {found_count} items found")

    def _handle_scan_result(self, scan_token: int, found_count: int) -> None:
        if scan_token != self._scan_token:
            return
        self._scan_found_count = found_count
        self.update_selected_info()
        self.status_bar.showMessage(f"Found {self.grid.visible_count()} items")

    def _handle_scan_error(self, scan_token: int, message: str) -> None:
        if scan_token != self._scan_token:
            return
        QMessageBox.warning(self, "Scan Error", message)
        self.status_bar.showMessage("Scan failed")

    def _scan_finished(self, scan_token: int) -> None:
        if scan_token == self._scan_token:
            self.current_scan = None

    def request_thumbnail(self, item) -> None:
        size = THUMBNAIL_DIMENSIONS[self.current_thumbnail_size]
        path_key = str(item.preview_path)
        generation = self._thumbnail_generation
        key = (generation, path_key, size)
        if key in self._thumb_jobs:
            return
        self._thumb_jobs.add(key)
        worker = ThumbnailWorker(item, size, generation)
        worker.signals.ready.connect(self._thumbnail_ready)
        self.thumbnail_pool.start(worker)

    def request_visible_thumbnails(self) -> None:
        self._queue_thumbnail_items(self.grid.visible_items(), prioritize_videos=False)
        self._prefetch_timer.start()

    def _thumbnail_ready(self, generation: int, path_key: str, size: int, pixmap) -> None:
        self._thumb_jobs.discard((generation, path_key, size))
        if generation != self._thumbnail_generation:
            return
        if size != THUMBNAIL_DIMENSIONS[self.current_thumbnail_size]:
            return
        self.grid.set_thumbnail(path_key, pixmap)
        if self.thumbnail_pool.activeThreadCount() < 2:
            self.request_visible_thumbnails()

    def set_thumbnail_size(self, size: ThumbnailSize) -> None:
        self.current_thumbnail_size = size
        self.settings.save_thumbnail_size(size.value)
        for thumb_size, button in self.size_buttons.items():
            button.setChecked(thumb_size == size)
        self._reset_thumbnail_queue()
        self.grid.set_thumbnail_size(THUMBNAIL_DIMENSIONS[size])
        self.request_visible_thumbnails()

    def save_naming_convention(self, text: str) -> None:
        self.settings.save_naming_convention(text)

    def apply_filter(self, text: str) -> None:
        self.grid.apply_filter(text, self.fbx_checkbox.isChecked())
        self.request_visible_thumbnails()
        self.update_selected_info()
        self.status_bar.showMessage(f"Found {self.grid.visible_count()} items")

    def update_selected_info(self) -> None:
        current = self.grid.currentItem()
        if current is None or current.isHidden():
            self.info_label.setText("Select an item to see file info.")
            return

        item = current.data(Qt.UserRole)
        if item is None:
            self.info_label.setText("Select an item to see file info.")
            return

        info_parts = [format_type_label(item)]
        path = item.preview_path

        dimensions = self._image_dimensions_label(path)
        if dimensions:
            info_parts.append(dimensions)

        if item.sequence:
            frame_count = len(item.sequence.frame_paths)
            info_parts.append(f"{frame_count} frames")

        file_size = self._file_size_label(path)
        if file_size:
            info_parts.append(file_size)

        modified = self._modified_label(path)
        if modified:
            info_parts.append(modified)

        self.info_label.setText(f"{item.display_name}    " + "    |    ".join(info_parts))

    def _image_dimensions_label(self, path: Path) -> str:
        reader = QImageReader(str(path))
        size = reader.size()
        if not size.isValid():
            return ""
        return f"{size.width()} x {size.height()} px"

    def _file_size_label(self, path: Path) -> str:
        try:
            size = path.stat().st_size
        except OSError:
            return ""

        units = ["B", "KB", "MB", "GB"]
        value = float(size)
        for unit in units:
            if value < 1024 or unit == units[-1]:
                if unit == "B":
                    return f"{int(value)} {unit}"
                return f"{value:.1f} {unit}"
            value /= 1024
        return ""

    def _modified_label(self, path: Path) -> str:
        try:
            timestamp = path.stat().st_mtime
        except OSError:
            return ""
        modified = datetime.fromtimestamp(timestamp)
        return f"Modified {modified:%Y-%m-%d %H:%M}"

    def add_favorite(self, path: Path) -> None:
        if path not in self.favorites:
            self.favorites.append(path)
            self.settings.save(self.favorites)
            self.folder_browser.set_favorites(self.favorites)

    def remove_favorite(self, path: Path) -> None:
        self.favorites = [favorite for favorite in self.favorites if favorite != path]
        self.settings.save(self.favorites)
        self.folder_browser.set_favorites(self.favorites)

    def import_dropped_files(self, paths: list[Path]) -> None:
        if self.current_root is None or not self.current_root.is_dir() or is_drive_root(self.current_root):
            self.status_bar.showMessage("Select a destination folder before dropping files.")
            return

        copied = 0
        skipped = 0
        for source in paths:
            if not source.is_file():
                skipped += 1
                continue

            destination = self._unique_drop_destination(self.current_root / source.name)
            try:
                if source.resolve() == destination.resolve():
                    skipped += 1
                    continue
                shutil.copy2(source, destination)
                copied += 1
            except OSError:
                skipped += 1

        if copied:
            self.status_bar.showMessage(f"Imported {copied} file(s) into {self.current_root}.")
            self.select_folder(self.current_root)
        elif skipped:
            self.status_bar.showMessage("No files were imported.")

    def _unique_drop_destination(self, destination: Path) -> Path:
        if not destination.exists():
            return destination

        stem = destination.stem
        suffix = destination.suffix
        folder = destination.parent
        index = 1
        while True:
            label = "copy" if index == 1 else f"copy {index}"
            candidate = folder / f"{stem} {label}{suffix}"
            if not candidate.exists():
                return candidate
            index += 1

    def open_folder_location(self, path: Path) -> None:
        open_folder_in_explorer(path)
        self.status_bar.showMessage(f"Opened folder: {path}")

    def open_viewer(self, item) -> None:
        if item.is_video:
            if open_video_in_vlc(item.preview_path):
                self.status_bar.showMessage(f"Opening in VLC: {item.preview_path.name}")
            else:
                QMessageBox.warning(
                    self,
                    "VLC Not Found",
                    "VLC could not be found. Install VLC or add vlc.exe to PATH, then try again.",
                )
            return

        if item.is_model:
            viewer_name = open_fbx_in_viewer(item.preview_path)
            if viewer_name:
                self.status_bar.showMessage(f"Opening FBX in {viewer_name}: {item.preview_path.name}")
            else:
                QMessageBox.warning(
                    self,
                    "FBX Viewer Not Found",
                    "No FBX viewer could be found. Install Blender or set a default app for .fbx files.",
                )
            return

        items = [
            media_item
            for media_item in self.grid.filtered_items()
            if not media_item.is_video and not media_item.is_model
        ]
        current_index = -1
        for index, media_item in enumerate(items):
            if media_item.preview_path == item.preview_path and media_item.display_name == item.display_name:
                current_index = index
                break
        if current_index < 0:
            current_index = 0
        viewer = ViewerWindow(items, current_index, self)
        viewer.exec()

    def open_associated_viewer(self, item) -> None:
        associated_items = self._associated_items_for(item)
        if not associated_items:
            self.status_bar.showMessage("No associated textures found.")
            return

        current_index = 0
        for index, associated_item in enumerate(associated_items):
            if associated_item.preview_path == item.preview_path and associated_item.display_name == item.display_name:
                current_index = index
                break

        self.status_bar.showMessage(f"Showing {len(associated_items)} associated texture(s).")
        browser = AssociatedBrowserDialog(
            associated_items,
            current_index,
            THUMBNAIL_DIMENSIONS[self.current_thumbnail_size],
            self,
        )
        browser.exec()

    def _associated_items_for(self, item) -> list:
        if item.is_video or item.is_model:
            return []

        convention_terms = self._comma_terms(self.naming_convention_box.text())
        search_terms = self._search_words(self.search_box.text())
        source_terms = [
            term
            for term in self._unique_terms(search_terms + convention_terms)
            if term in item.preview_path.stem.lower()
        ]
        if not source_terms and convention_terms:
            source_terms = [term for term in convention_terms if term in item.preview_path.stem.lower()]
        if not source_terms:
            return [item]

        candidates = [
            media_item
            for media_item in self.items
            if media_item.folder == item.folder and not media_item.is_video and not media_item.is_model
        ]

        matches: dict[tuple[Path, str], object] = {}
        for source_term in source_terms:
            variant_terms = self._unique_terms([source_term] + convention_terms)
            selected_key = self._variant_key(item.preview_path.stem, variant_terms)
            for candidate in candidates:
                if candidate.extension != item.extension:
                    continue
                if self._variant_key(candidate.preview_path.stem, variant_terms) == selected_key:
                    matches[(candidate.preview_path, candidate.display_name)] = candidate

        if (item.preview_path, item.display_name) not in matches:
            matches[(item.preview_path, item.display_name)] = item

        def sort_key(media_item) -> tuple[int, str]:
            name = media_item.preview_path.stem.lower()
            term_order = len(convention_terms) + 1
            for index, term in enumerate(convention_terms):
                if term in name:
                    term_order = index + 1
                    break
            if media_item.preview_path == item.preview_path and media_item.display_name == item.display_name:
                term_order = 0
            return (term_order, media_item.display_name.lower())

        return sorted(matches.values(), key=sort_key)

    def _comma_terms(self, text: str) -> list[str]:
        return self._unique_terms(term.strip().lower() for term in text.split(",") if term.strip())

    def _search_words(self, text: str) -> list[str]:
        return self._unique_terms(re.findall(r"[a-z0-9]+", text.lower()))

    def _unique_terms(self, terms) -> list[str]:
        unique = []
        seen = set()
        for term in terms:
            if not term or term in seen:
                continue
            seen.add(term)
            unique.append(term)
        return unique

    def _variant_key(self, stem: str, variant_terms: list[str]) -> str:
        key = stem.lower()
        for term in sorted(variant_terms, key=len, reverse=True):
            key = key.replace(term, "{texture}")
        return re.sub(r"[^a-z0-9{}]+", "_", key).strip("_")

    def _handle_population_progress(self, added_count: int, total_count: int) -> None:
        if self.current_scan is None:
            self.status_bar.showMessage(f"Preparing items... {added_count}/{total_count}")
        if added_count <= self.grid.total_count():
            self.request_visible_thumbnails()

    def _handle_population_finished(self, visible_count: int) -> None:
        self.request_visible_thumbnails()
        if self.current_scan is None:
            self.status_bar.showMessage(f"Found {visible_count} items")

    def _request_prefetch_thumbnails(self) -> None:
        if self.thumbnail_pool.activeThreadCount() >= 3:
            self._prefetch_timer.start()
            return
        self._queue_thumbnail_items(self.grid.prefetch_items(), prioritize_videos=True, limit=40)

    def _reset_thumbnail_queue(self) -> None:
        self._thumbnail_generation += 1
        self._thumb_jobs.clear()
        self.thumbnail_pool.clear()

    def _queue_thumbnail_items(self, items, prioritize_videos: bool, limit: int | None = None) -> None:
        if not items:
            return

        images = [item for item in items if not item.is_video]
        videos = [item for item in items if item.is_video]
        ordered = videos + images if prioritize_videos else images + videos

        if limit is not None:
            ordered = ordered[:limit]

        for item in ordered:
            self.grid.thumbnailRequested.emit(item)


def run() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("Texture Browser")
    app.setOrganizationName("TextureBrowser")
    app.setStyle("Fusion")

    window = MainWindow()
    window.show()
    sys.exit(app.exec())
