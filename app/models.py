from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class MediaKind(str, Enum):
    IMAGE = "image"
    VIDEO = "video"
    SEQUENCE = "sequence"
    MODEL = "model"


class ThumbnailSize(str, Enum):
    TINY = "Tiny"
    SMALL = "Small"
    MEDIUM = "Medium"
    LARGE = "Large"


THUMBNAIL_DIMENSIONS = {
    ThumbnailSize.TINY: 72,
    ThumbnailSize.SMALL: 112,
    ThumbnailSize.MEDIUM: 160,
    ThumbnailSize.LARGE: 224,
}


@dataclass(slots=True)
class SequenceInfo:
    pattern_name: str
    frame_paths: list[Path]
    frame_numbers: list[int]
    padding: int

    @property
    def first_frame(self) -> Path:
        return self.frame_paths[0]

    @property
    def frame_range_label(self) -> str:
        if not self.frame_numbers:
            return ""
        return f"{self.frame_numbers[0]}-{self.frame_numbers[-1]}"


@dataclass(slots=True)
class MediaItem:
    display_name: str
    path: Path
    kind: MediaKind
    extension: str
    folder: Path
    search_text: str
    sequence: SequenceInfo | None = None
    metadata: dict[str, str] = field(default_factory=dict)

    @property
    def preview_path(self) -> Path:
        if self.sequence:
            return self.sequence.first_frame
        return self.path

    @property
    def is_video(self) -> bool:
        return self.kind == MediaKind.VIDEO

    @property
    def is_sequence(self) -> bool:
        return self.kind == MediaKind.SEQUENCE

    @property
    def is_model(self) -> bool:
        return self.kind == MediaKind.MODEL
