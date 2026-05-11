from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings


class FavoritesStore:
    def __init__(self) -> None:
        self.settings = QSettings("TextureBrowser", "TextureBrowser")

    def load(self) -> list[Path]:
        values = self.settings.value("favorites", [], list)
        paths = [Path(value) for value in values]
        return [path for path in paths if path.exists()]

    def save(self, favorites: list[Path]) -> None:
        unique = []
        seen = set()
        for path in favorites:
            resolved = str(path)
            if resolved in seen:
                continue
            seen.add(resolved)
            unique.append(resolved)
        self.settings.setValue("favorites", unique)

    def load_last_root(self) -> Path | None:
        value = self.settings.value("last_root", "", str)
        if not value:
            return None
        path = Path(value)
        return path if path.exists() else None

    def save_last_root(self, path: Path) -> None:
        self.settings.setValue("last_root", str(path))

    def load_thumbnail_size(self) -> str:
        return self.settings.value("thumbnail_size", "Medium", str)

    def save_thumbnail_size(self, value: str) -> None:
        self.settings.setValue("thumbnail_size", value)
