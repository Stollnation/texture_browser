from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, Signal

from app.models import MediaItem
from app.sequence_detector import build_media_items
from app.utils import is_supported_media


class ScanWorkerSignals(QObject):
    progress = Signal(str)
    batch = Signal(list, int)
    result = Signal(int)
    error = Signal(str)
    finished = Signal()


class ScanWorker(QRunnable):
    def __init__(self, root: Path) -> None:
        super().__init__()
        self.root = root
        self.signals = ScanWorkerSignals()
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        try:
            self.signals.progress.emit(f"Scanning {self.root}...")
            seen = 0
            found = 0
            for dirpath, _dirnames, filenames in os.walk(
                self.root, onerror=lambda err: self.signals.progress.emit(f"Skipping: {err.filename}")
            ):
                if self._cancelled:
                    self.signals.progress.emit("Scan canceled")
                    self.signals.result.emit(found)
                    return
                directory = Path(dirpath)
                paths: list[Path] = []
                for filename in filenames:
                    if self._cancelled:
                        self.signals.progress.emit("Scan canceled")
                        self.signals.result.emit(found)
                        return
                    path = directory / filename
                    seen += 1
                    if seen % 250 == 0:
                        self.signals.progress.emit(f"Scanning... {seen} files checked, {found} items found")
                    if is_supported_media(path):
                        paths.append(path)
                if not paths:
                    continue
                items: list[MediaItem] = build_media_items(paths)
                if items:
                    found += len(items)
                    self.signals.batch.emit(items, found)
            self.signals.result.emit(found)
        except Exception as exc:  # noqa: BLE001
            self.signals.error.emit(str(exc))
        finally:
            self.signals.finished.emit()
