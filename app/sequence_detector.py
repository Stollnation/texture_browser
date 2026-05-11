from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path

from app.models import MediaItem, MediaKind, SequenceInfo
from app.utils import MODEL_EXTENSIONS, VIDEO_EXTENSIONS

SEQUENCE_PATTERN = re.compile(
    r"^(?P<prefix>.+?)(?P<sep>[._-])(?P<frame>\d{3,6})(?P<suffix>\.[^.]+)$",
    re.IGNORECASE,
)


def _search_text(*parts: str) -> str:
    return " ".join(part.lower() for part in parts if part)


def build_media_items(paths: list[Path]) -> list[MediaItem]:
    grouped: dict[tuple[Path, str, str, str], list[tuple[Path, int, int]]] = defaultdict(list)
    singles: list[Path] = []

    for path in sorted(paths):
        if path.suffix.lower() in VIDEO_EXTENSIONS or path.suffix.lower() in MODEL_EXTENSIONS:
            singles.append(path)
            continue
        match = SEQUENCE_PATTERN.match(path.name)
        if not match:
            singles.append(path)
            continue
        prefix = match.group("prefix")
        separator = match.group("sep")
        frame = match.group("frame")
        suffix = match.group("suffix").lower()
        key = (path.parent, prefix, separator, suffix)
        grouped[key].append((path, int(frame), len(frame)))

    items: list[MediaItem] = []

    for path in singles:
        ext = path.suffix.lower()
        if ext in VIDEO_EXTENSIONS:
            kind = MediaKind.VIDEO
        elif ext in MODEL_EXTENSIONS:
            kind = MediaKind.MODEL
        else:
            kind = MediaKind.IMAGE
        items.append(
            MediaItem(
                display_name=path.name,
                path=path,
                kind=kind,
                extension=ext,
                folder=path.parent,
                search_text=_search_text(path.name, str(path.parent), ext),
            )
        )

    for (folder, prefix, separator, suffix), frames in grouped.items():
        frames.sort(key=lambda value: value[1])
        if len(frames) < 2:
            path = frames[0][0]
            items.append(
                MediaItem(
                    display_name=path.name,
                    path=path,
                    kind=MediaKind.IMAGE,
                    extension=suffix,
                    folder=folder,
                    search_text=_search_text(path.name, str(folder), suffix),
                )
            )
            continue

        frame_paths = [frame[0] for frame in frames]
        frame_numbers = [frame[1] for frame in frames]
        padding = frames[0][2]
        pattern_name = f"{prefix}{separator}{'#' * padding}{suffix}"
        sequence = SequenceInfo(
            pattern_name=pattern_name,
            frame_paths=frame_paths,
            frame_numbers=frame_numbers,
            padding=padding,
        )
        items.append(
            MediaItem(
                display_name=pattern_name,
                path=frame_paths[0],
                kind=MediaKind.SEQUENCE,
                extension=suffix,
                folder=folder,
                search_text=_search_text(pattern_name, str(folder), suffix, prefix),
                sequence=sequence,
                metadata={"frame_range": sequence.frame_range_label},
            )
        )

    items.sort(key=lambda item: (str(item.folder).lower(), item.display_name.lower()))
    return items
