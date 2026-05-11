from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QDir, QModelIndex, Qt, Signal
from PySide6.QtWidgets import (
    QFileSystemModel,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QTreeView,
    QVBoxLayout,
    QWidget,
)


class FolderBrowser(QWidget):
    folderSelected = Signal(Path)
    folderOpenRequested = Signal(Path)
    addFavoriteRequested = Signal(Path)
    removeFavoriteRequested = Signal(Path)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._current_folder: Path | None = None

        self.favorites_list = QListWidget()
        self.favorites_list.setMaximumHeight(120)
        self.favorites_list.itemDoubleClicked.connect(self._on_favorite_activated)

        favorites_header = QHBoxLayout()
        favorites_header.addWidget(QLabel("Favorites"))
        self.add_favorite_button = QPushButton("Add")
        self.remove_favorite_button = QPushButton("Remove")
        self.add_favorite_button.clicked.connect(self._emit_add_favorite)
        self.remove_favorite_button.clicked.connect(self._emit_remove_favorite)
        favorites_header.addWidget(self.add_favorite_button)
        favorites_header.addWidget(self.remove_favorite_button)

        self.model = QFileSystemModel(self)
        self.model.setRootPath(QDir.rootPath())
        self.model.setFilter(QDir.AllDirs | QDir.NoDotAndDotDot | QDir.Drives)

        self.tree = QTreeView()
        self.tree.setModel(self.model)
        self.tree.setHeaderHidden(True)
        self.tree.setAnimated(True)
        self.tree.setIndentation(16)
        for column in range(1, 4):
            self.tree.hideColumn(column)
        self.tree.selectionModel().currentChanged.connect(self._on_current_changed)
        self.tree.doubleClicked.connect(self._on_tree_double_clicked)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(favorites_header)
        layout.addWidget(self.favorites_list)
        layout.addWidget(QLabel("Folders"))
        layout.addWidget(self.tree, 1)

    def set_current_folder(self, folder: Path) -> None:
        self._current_folder = folder
        index = self.model.index(str(folder))
        if index.isValid():
            self.tree.setCurrentIndex(index)
            self.tree.scrollTo(index)

    def set_favorites(self, favorites: list[Path]) -> None:
        self.favorites_list.clear()
        for path in favorites:
            item = QListWidgetItem(str(path))
            item.setData(Qt.UserRole, path)
            self.favorites_list.addItem(item)

    def _on_current_changed(self, current: QModelIndex, _previous: QModelIndex) -> None:
        path = Path(self.model.filePath(current))
        if path.exists():
            self._current_folder = path
            self.folderSelected.emit(path)

    def _on_tree_double_clicked(self, index: QModelIndex) -> None:
        path = Path(self.model.filePath(index))
        if path.exists():
            self.folderOpenRequested.emit(path)

    def _on_favorite_activated(self, item: QListWidgetItem) -> None:
        path = item.data(Qt.UserRole)
        if isinstance(path, Path):
            self.set_current_folder(path)
            self.folderSelected.emit(path)

    def _emit_add_favorite(self) -> None:
        if self._current_folder:
            self.addFavoriteRequested.emit(self._current_folder)

    def _emit_remove_favorite(self) -> None:
        item = self.favorites_list.currentItem()
        if item is None:
            return
        path = item.data(Qt.UserRole)
        if isinstance(path, Path):
            self.removeFavoriteRequested.emit(path)
